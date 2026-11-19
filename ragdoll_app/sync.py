"""Keeping the index up to date with the mail server, and telling the desktop about new mail."""

import contextlib
import imaplib
import socket
import ssl
import sys
import threading
import time
import traceback

import ragdoll as R
from . import desktop
from .common import configured, friendly
from .desktop import window_focused, window_front


class Sync:
    """The background sync and new-mail notifications. (Part of Backend.)"""

    def start_sync(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.sync_loop, daemon=True)
            self.thread.start()
        self.wake.set()

    def sync_loop(self):
        c, m = None, None
        while not self.stopping.is_set():
            self.wake.wait(60)
            self.wake.clear()
            if self.stopping.is_set():
                break
            if not configured():
                continue
            self.sync["running"] = True
            self.poke()
            before = None
            try:
                c = c or R.db()
                before = self.fingerprint(c)
                with R.file_lock("headers", wait=False) as got:
                    if got:
                        for attempt in (0, 1):
                            try:
                                if m is None:
                                    m = R.imap()
                                    with contextlib.suppress(Exception):
                                        m.sock.settimeout(120)
                                self.note_folders(m, c)
                                for f in self.sync_folders():
                                    R.sync_headers(m, c, f)
                                    if self.fingerprint(c) != before:
                                        self.bump()
                                        before = self.fingerprint(c)
                                break
                            except (imaplib.IMAP4.abort, ssl.SSLError, ConnectionError, socket.timeout):
                                with contextlib.suppress(Exception):
                                    m.logout()
                                m = None
                                if attempt:
                                    raise
                        c.execute("insert or replace into meta values('last_sync', ?)", (str(int(time.time())),))
                        c.commit()
                        try:
                            self.notify_new(c)
                        except Exception:       # noqa: BLE001 - a notification must never stop the sync
                            traceback.print_exc(file=sys.stderr)
                self.sync["error"] = None
                self.sync["last"] = int(time.time())
                if self.outbox_tried and self.outbox_list():
                    self.outbox_tried = 0
                    self.sched_wake.set()
                with R.file_lock("bodies", wait=False) as got:
                    if got:
                        R.sync_bodies(c, self.sync_folders(), limit=200, workers=2, quiet=True)
                        if c.execute("select 1 from msgs where has_body=0 limit 1").fetchone():
                            threading.Timer(3, self.wake.set).start()     # keep going until all are in
            except BaseException as e:          # noqa: B036 - die() raises SystemExit
                self.sync["error"] = friendly(e)
                with contextlib.suppress(Exception):
                    m.logout()
                m = None
            finally:
                self.sync["running"] = False
                if c is not None and self.fingerprint(c) != before:
                    self.bump()
                else:
                    self.poke()
        if m is not None:
            with contextlib.suppress(Exception):
                m.logout()

    def notify_new(self, c):
        """Tell the desktop about unread mail that came into the Inbox since the last pass.
        The first pass only marks where the Inbox stands, so opening the app never pops up old mail."""
        inbox = R.CFG.folders.get("inbox") or "INBOX"
        top = c.execute("select coalesce(max(id),0) from msgs where folder=?", (inbox,)).fetchone()[0]
        mark, self.note_mark = self.note_mark, top
        if mark is None or top <= mark or self.prefs().get("notify") is False:
            return None
        rows = c.execute("select uid, frm, subject from msgs where folder=? and id>? and seen=0 and ts>? "
                         "order by ts desc", (inbox, mark, int(time.time()) - 2 * 86400)).fetchall()
        rows = [r for r in rows if all(a != R.CFG.user for _, a in R.addrs(r["frm"]))]
        if not rows or window_focused():
            return None
        n, a = (R.addrs(rows[0]["frm"]) or [("", "")])[0]
        title = (n or a or "ragdoll-mail") + (" +%d" % (len(rows) - 1) if len(rows) > 1 else "")
        i = R.make_id(inbox, rows[0]["uid"])
        desktop.desktop_notify(title, rows[0]["subject"] or "", lambda: self.open_from_note(i))
        return i

    def open_from_note(self, i):
        """A click on the notification: bring the window up; the page opens the mail at its next status call."""
        self.open_req = i
        self.bump()
        window_front()

    @staticmethod
    def fingerprint(c):
        return tuple(c.execute("select count(*), coalesce(max(id),0), coalesce(sum(seen),0), "
                               "coalesce(sum(has_body),0), coalesce(sum(answered),0), coalesce(sum(flagged),0), coalesce(sum(forwarded),0) "
                               "from msgs").fetchone())
