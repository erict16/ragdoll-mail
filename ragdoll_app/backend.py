"""Backend: one object behind the page. Each feature lives in its own file as a class that Backend
inherits; this file keeps what they all share (the index, the mail server connection, the raw-mail cache).

To add a feature: write a class with its api_<name> methods in a new file and add it to the list below.
The page reaches every api_<name> method as  api("<name>", {...})."""

import contextlib
import hashlib
import imaplib
import os
import smtplib
import socket
import ssl
import sys
import threading
import time
import traceback

import ragdoll as R
from .common import ApiError, fail, friendly, people_json, person, snippet
from .compose import Compose
from .demo import Demo
from .desktop import set_badge
from .folders import Folders
from .invites import Invites
from .reading import Reading
from .sendlater import SendLater
from .settings import Settings
from .snooze import Snooze
from .status import Status
from .sync import Sync
from .templates import Templates
from .updates import Updates


class Backend(Folders, Sync, Updates, Status, Reading, Compose, SendLater, Invites, Snooze, Templates, Settings, Demo):
    def __init__(self, demo=False):
        self.demo = demo
        self.lock = threading.RLock()           # the action IMAP connection
        self.dblock = threading.RLock()         # the request db connection
        self.m = None
        self.m_used = 0
        self.rev = 1                            # goes up when the mail on show may have changed
        self.tick = 1                           # goes up when anything the page shows changed
        self.cond = threading.Condition()       # api_wait sleeps on it until a tick
        self.counts = (None, None)              # (what the index looked like, counts per folder)
        self.sync = {"running": False, "error": None, "last": None}
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.contacts = (0, {})
        self.update = None
        self.update_checked = 0
        self.update_lock = threading.Lock()
        self.preflock = threading.RLock()       # app.json
        self.server_folders = None
        self.made = set()                       # files the app wrote (only these may be revealed)
        self.demo_raw = {}
        self.thread = None
        self.schedlock = threading.RLock()      # the scheduled-send list (scheduled.json)
        self.sched_wake = threading.Event()
        self.outbox_tried = 0
        self.fake_offline = False               # tests: behave as if the servers were out of reach
        self.note_mark = None                   # newest Inbox row the desktop was told about
        self.open_req = None                    # a mail whose desktop notification was clicked
        self.listed = []                        # the server's folders, [(name, delimiter)]
        if demo:
            self.make_demo()
        self.c = R.db()
        self.listed = self.listed or self.load_listed()
        self.marks_seen = self.marks_state()    # what the lists showed when another program last wrote
        if not demo:
            threading.Thread(target=self.housekeeping, daemon=True).start()
            threading.Thread(target=self.update_loop, daemon=True).start()
            self.start_sync()
        threading.Thread(target=self.sched_loop, daemon=True).start()
        with contextlib.suppress(Exception):
            self.badge()

    # ---- plumbing

    def call(self, name, args):
        fn = getattr(self, "api_" + name, None)
        if fn is None:
            return 404, {"ok": False, "error": "unknown call %s" % name}
        if args is not None and not isinstance(args, dict):
            return 400, {"ok": False, "error": "bad request"}
        try:
            return 200, {"ok": True, "data": fn(args or {})}
        except ApiError as e:
            return 200, {"ok": False, "error": str(e)}
        except SystemExit as e:
            return 200, {"ok": False, "error": friendly(e)}
        except (imaplib.IMAP4.error, smtplib.SMTPException, OSError, LookupError) as e:
            return 200, {"ok": False, "error": friendly(e)}
        except Exception as e:      # noqa: BLE001 - a bug must not take the page down with it
            traceback.print_exc(file=sys.stderr)
            return 500, {"ok": False, "error": "Something went wrong (%s)" % type(e).__name__}

    def q(self, sql, params=()):
        with self.dblock:
            return self.c.execute(sql, params).fetchall()

    def exec(self, sql, params=()):
        with self.dblock:
            self.c.execute(sql, params)
            self.c.commit()

    def imap(self, fn):
        """Run fn(m) on the kept connection; reconnect once when it dropped."""
        if self.demo:
            fail("not in the demo")
        with self.lock:
            for attempt in (0, 1):
                try:
                    if self.m is None:
                        self.m = R.imap()
                        with contextlib.suppress(Exception):
                            self.m.sock.settimeout(90)
                    elif time.time() - self.m_used > 60:
                        self.m.noop()
                    r = fn(self.m)
                    self.m_used = time.time()
                    return r
                except (imaplib.IMAP4.abort, ssl.SSLError, ConnectionError, socket.timeout, BrokenPipeError):
                    self.drop()
                    if attempt:
                        raise

    def drop(self):
        m, self.m = self.m, None
        if m is not None:
            with contextlib.suppress(Exception):
                m.logout()

    def bump(self):
        """The mail on show may have changed: the page loads its list again."""
        with self.cond:
            self.rev += 1
            self.tick += 1
            self.cond.notify_all()
        with contextlib.suppress(Exception):
            self.badge()

    def poke(self):
        """Something beside the mail changed (sync started or ended, an update was found)."""
        with self.cond:
            self.tick += 1
            self.cond.notify_all()

    def housekeeping(self):
        """Slow start-up work that nothing waits for."""
        with contextlib.suppress(Exception):
            self.prune_cache()
        if not self.stopping.wait(3):
            with contextlib.suppress(Exception):
                self.load_contacts()            # so the first address typed gets its suggestions at once

    def badge(self):
        """The unread Inbox count on the app's icon. Off unless turned on in Settings, Notifications."""
        if self.prefs().get("badge") is not True:
            return set_badge(0)
        inbox = R.CFG.folders.get("inbox") or "INBOX"
        set_badge(self.q("select coalesce(sum(seen=0),0) u from msgs where folder=?", (inbox,))[0]["u"])

    def row(self, i):
        folder, uid = self.parse(i)
        r = self.q("select * from msgs where folder=? and uid=?", (folder, uid))
        if not r:
            fail("This mail is no longer here. It may have been moved or deleted.")
        return r[0]

    @staticmethod
    def parse(i):
        try:
            return R.parse_id(i)
        except SystemExit:
            fail("bad mail id %r" % i)

    def row_json(self, r):
        f = R.addrs(r["frm"])
        n, a = f[0] if f else ("", "")
        return {"id": R.make_id(r["folder"], r["uid"]), "folder": R.CFG.short(r["folder"]), "ts": r["ts"],
                "from": person(n, a), "to": people_json(r["to_"]), "cc": people_json(r["cc"]),
                "subject": r["subject"] or "", "snippet": snippet(r["body"]), "unread": not r["seen"],
                "flagged": bool(r["flagged"]), "answered": bool(r["answered"]), "forwarded": bool(r["forwarded"]),
                "atts": [x for x in (r["atts"] or "").split(" | ") if x]}

    # ---- raw mail, with a disk cache

    def cache_path(self, r):
        key = hashlib.sha1(("%s|%s|%s" % (r["folder"], r["uidv"], r["uid"])).encode()).hexdigest()
        return os.path.join(R.CFG.home, "cache", key[:2], key + ".eml")

    def raw(self, i):
        folder, uid = self.parse(i)
        if self.demo:
            if (folder, uid) not in self.demo_raw:
                fail("This mail is no longer here.")
            return self.demo_raw[(folder, uid)]
        r = self.row(i)
        path = self.cache_path(r)
        with contextlib.suppress(OSError):
            with open(path, "rb") as f:
                return f.read()
        raw = self.imap(lambda m: R.fetch_raw(m, folder, uid))
        with contextlib.suppress(OSError):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".%d.tmp" % os.getpid()
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, path)
        return raw

    def prune_cache(self, days=90):
        root = os.path.join(R.CFG.home, "cache")
        cut = time.time() - days * 86400
        for d, _, files in os.walk(root):
            for n in files:
                p = os.path.join(d, n)
                with contextlib.suppress(OSError):
                    if os.path.getatime(p) < cut:
                        os.remove(p)

    def close(self):
        self.stopping.set()
        self.poke()
        self.wake.set()
        self.sched_wake.set()
        self.drop()
