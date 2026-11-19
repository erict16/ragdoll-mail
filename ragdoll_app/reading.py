"""Lists, search, conversations, one mail, attachments, and marking or moving mail."""

import contextlib
import os
import re
import secrets
import threading
import time
import webbrowser
from types import SimpleNamespace

import ragdoll as R
from .common import ApiError, fail, ids_in, int_in, open_path, people_json, person, text_in
from .desktop import window_do, window_theme
from .invites import find_invite
from .message import cid_map, file_parts, has_remote, page_html, part_info, plain_html


def downloads_dir():
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    return d if os.path.isdir(d) else os.path.expanduser("~")


class Reading:
    """Lists, search, reading, marking, moving. (Part of Backend.)"""

    # ---- api: lists and reading

    def api_list(self, a):
        key = a.get("folder") or "inbox"
        if key == "scheduled":
            return {"rows": self.scheduled_rows(), "more": False}
        if key == "snoozed":
            return {"rows": self.snoozed_rows(), "more": False}
        limit = max(1, min(int_in(a, "limit", 100), 500))
        offset = max(0, min(int_in(a, "offset", 0), 10 ** 7))
        if key == "flagged":
            fs = self.flag_folders()
            rows = self.q("select * from msgs where flagged=1 and folder in (%s) order by ts desc, uid desc limit ? offset ?"
                          % ",".join("?" * len(fs)), (*fs, limit, offset)) if fs else []
            return {"rows": [self.row_json(r) for r in rows], "more": len(rows) == limit}
        folder = self.folder_of(key) or key
        top, skip = [], []
        if key == "inbox":
            # snoozed mail is out of the list; mail that came back sits on top until it is read
            wait, woke = self.snooze_state()
            skip = [r["uid"] for _, r in wait + woke]
            if offset == 0:
                top = [dict(self.row_json(r), woke=True) for _, r in woke]
            else:
                offset = max(0, offset - len(woke))
        rows = self.q("select * from msgs where folder=? %s order by ts desc, uid desc limit ? offset ?"
                      % ("and uid not in (%s)" % ",".join("?" * len(skip)) if skip else ""),
                      (folder, *skip, limit, offset))
        out = top + [self.row_json(r) for r in rows]
        if key == "drafts":
            sched = {x["id"]: x for x in self.sched_list()}
            for r in out:
                if r["id"] in sched:
                    r["sched"] = sched[r["id"]]["at"]
                    r["sched_error"] = sched[r["id"]].get("error")
        return {"rows": out, "more": len(rows) == limit}

    def api_search(self, a):
        text = text_in(a, "q").strip()[:500]
        limit = max(1, min(int_in(a, "limit", 100), 2000))
        offset = max(0, min(int_in(a, "offset", 0), 10 ** 7))
        ns = SimpleNamespace(limit=limit + 1, offset=offset, folder=None, from_=None, to=None, since=None, until=None,
                             unread=False, att=False)
        words = []
        for w in re.findall(r'(\w+:"[^"]*"|"[^"]*"|\S+)', text):
            k, _, v = w.partition(":")
            v = v.strip('"')
            if v and k.lower() in ("from", "to", "in", "folder"):
                setattr(ns, {"from": "from_", "to": "to", "in": "folder", "folder": "folder"}[k.lower()], v)
            elif w.lower() in ("is:unread", "has:attachment", "has:file"):
                ns.unread = ns.unread or w.lower() == "is:unread"
                ns.att = ns.att or w.lower() != "is:unread"
            else:
                words.append(w.strip('"'))
        if not words and not any((ns.folder, ns.from_, ns.to, ns.unread, ns.att)):
            return {"rows": [], "more": False, "next": 0}
        with self.dblock:
            rows = R.search_rows(self.c, words, ns)
        more, rows = len(rows) > limit, rows[:limit]
        skip = set() if ns.folder else {R.CFG.folders.get("junk")}     # Junk shows only when asked for (in:junk)
        return {"rows": [self.row_json(r) for r in rows if r["folder"] not in skip], "more": more,
                "next": offset + len(rows)}

    def api_thread(self, a):
        r = self.row(a["id"])
        with self.dblock:
            rows = R.thread_rows(self.c, r)
        skip = {R.CFG.folders.get("trash"), R.CFG.folders.get("junk"), R.CFG.folders.get("drafts")} - {r["folder"]}
        rows = [x for x in rows if x["folder"] not in skip or x["id"] == r["id"]]
        return {"subject": r["subject"] or "", "rows": [self.row_json(x) for x in rows], "id": a["id"]}

    def api_message(self, a):
        i = a["id"]
        msg = R.to_msg(self.raw(i))
        plain, html = R.bodies(msg)
        cids = cid_map(msg)
        body = page_html(html, cids) if html.strip() else plain_html(plain)
        f = R.addrs(R.hdr(msg, "From"))
        n, ad = f[0] if f else ("", "")
        try:
            ts = int(R.parsedate_to_datetime(R.hdr(msg, "Date")).timestamp())
        except Exception:
            ts = 0
        out = {"id": i, "from": person(n, ad), "to": people_json(R.hdr(msg, "To")),
               "cc": people_json(R.hdr(msg, "Cc")), "bcc": people_json(R.hdr(msg, "Bcc")),
               "subject": R.hdr(msg, "Subject"), "ts": ts, "html": body, "plain": not html.strip(),
               "remote": has_remote(body), "atts": [part_info(k, p) for k, p in enumerate(file_parts(msg))],
               "big": R.big_attachment_lines(R.html_to_text(html) or plain)}
        ev, _ = find_invite(msg)
        if ev:
            out["invite"] = self.invite_json(ev)
        if a.get("mark", True):
            with contextlib.suppress(ApiError):
                r = self.row(i)
                if not r["seen"]:
                    self.set_flag([i], "seen", True)
        return out

    def set_flag(self, ids, flag, on):
        col, imap_flag = {"seen": ("seen", "\\Seen"), "flagged": ("flagged", "\\Flagged")}[flag]
        by = {}
        for i in ids:
            f, u = self.parse(i)
            by.setdefault(f, []).append(u)
        if not self.demo:
            def go(m):
                for f, uids in by.items():
                    R.select(m, f, readonly=False)
                    m.uid("STORE", ",".join(map(str, uids)), "+FLAGS.SILENT" if on else "-FLAGS.SILENT",
                          "(%s)" % imap_flag)
            self.imap(go)
        with self.dblock:
            for f, uids in by.items():
                self.c.execute("update msgs set %s=? where folder=? and uid in (%s)" % (col, ",".join("?" * len(uids))),
                               [int(on), f, *uids])
            self.c.commit()
        self.bump()

    def api_mark(self, a):
        self.set_flag(ids_in(a), a.get("flag", "seen"), bool(a.get("on", True)))
        return {}

    def api_move(self, a):
        """Move mails to archive, trash or inbox (dest is the folder key)."""
        dest_key = a["to"]
        if dest_key not in ("archive", "trash", "inbox", "junk") and not str(dest_key).startswith("f:"):
            fail("can't move to %s" % dest_key)
        dest = self.folder_of(dest_key) or ("Archive" if dest_key == "archive" else None)
        if not dest:
            fail("No %s folder is set." % dest_key)
        by = {}
        for i in ids_in(a):
            f, u = self.parse(i)
            if f != dest:
                by.setdefault(f, []).append(u)
                # a moved draft is no longer the one that was scheduled
                self.sched_drop(i)
        if self.demo:
            for f, uids in by.items():
                for u in uids:
                    r = self.q("select * from msgs where folder=? and uid=?", (f, u))
                    raw = self.demo_raw.pop((f, u), None)
                    if r and raw:
                        self.demo_insert(dest, raw, r[0]["ts"], r[0]["seen"], r[0]["answered"], r[0]["flagged"])
        else:
            def go(m):
                if dest not in self.folders(m):
                    typ, data = m.create(R.q(dest))
                    if typ != "OK":
                        fail("Could not make the %s folder: %s" % (dest, data))
                    self.server_folders = None
                    if dest not in R.CFG.sync_folders and dest_key == "archive":
                        R.CFG.folders["archive"] = dest
                for f, uids in by.items():
                    R.move_uids(m, f, sorted(set(uids)), dest)
            self.imap(go)
        with self.dblock:
            for f, uids in by.items():
                for u in uids:
                    for r in self.c.execute("select id from msgs where folder=? and uid=?", (f, u)).fetchall():
                        self.c.execute("delete from msgs where id=?", (r["id"],))
                        self.c.execute("delete from fts where rowid=?", (r["id"],))
            self.c.commit()
        self.bump()
        if not self.demo:
            self.wake.set()
        return {"moved": sum(len(x) for x in by.values())}

    def api_attachment(self, a):
        msg = R.to_msg(self.raw(a["id"]))
        parts = file_parts(msg)
        k = int(a["i"])
        if not 0 <= k < len(parts):
            fail("That attachment is not in the mail any more.")
        p = parts[k]
        name = R.safe_name(R.fname(p) or "attachment")
        if a.get("action") == "save":
            path = R.unique_path(downloads_dir(), name, set())
            n = 2
            while os.path.exists(path):
                stem, ext = os.path.splitext(name)
                path = os.path.join(downloads_dir(), "%s (%d)%s" % (stem, n, ext))
                n += 1
        else:
            d = os.path.join(R.CFG.home, "open", secrets.token_hex(4))
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, name)
        with open(path, "wb") as f:
            f.write(R.part_bytes(p))
        self.made.add(path)
        if a.get("action") != "save":
            open_path(path)
        return {"path": path, "name": os.path.basename(path)}

    def api_reveal(self, a):
        if a.get("path") not in self.made:
            fail("unknown file")
        open_path(a["path"], reveal=True)
        return {}

    def api_open_url(self, a):
        u = a.get("url") or ""
        if not re.match(r"(?i)(https?|mailto):", u):
            fail("can't open that link")
        webbrowser.open(u)
        return {}

    def api_window(self, a):
        """The window buttons the page draws on Windows: state, min, max, close, drag (move), top (resize from the top edge)."""
        if a.get("do") not in ("state", "min", "max", "close", "drag", "top"):
            fail("bad request")
        return window_do(a["do"])

    def api_window_theme(self, a):
        window_theme(bool(a.get("dark")), a.get("bg"), a.get("text"))
        return {}

    def load_contacts(self):
        """Everyone in the newest 6000 mails, people written to counting three times."""
        seen = {}
        sent = R.CFG.folders.get("sent")
        for r in self.q("select folder, frm, to_, cc from msgs order by ts desc limit 6000"):
            weight = 3 if r["folder"] == sent else 1
            for n, ad in R.addrs(r["frm"]) + R.addrs(r["to_"]) + R.addrs(r["cc"]):
                if ad == R.CFG.user or re.search(r"no-?reply|mailer-daemon|notification", ad):
                    continue
                e = seen.setdefault(ad, [0, ""])
                e[0] += weight
                if n and "�" not in n and not e[1]:
                    e[1] = n
        self.contacts = (time.time(), seen)

    def api_contacts(self, a):
        q = text_in(a, "q").strip().lower()
        if not self.contacts[0]:
            self.load_contacts()
        elif time.time() - self.contacts[0] > 300:
            # show what is known and read the address book again behind the scenes
            self.contacts = (time.time(), self.contacts[1])
            threading.Thread(target=self.load_contacts, daemon=True).start()
        hits = [(v[0], ad, v[1]) for ad, v in self.contacts[1].items()
                if not q or q in ad or q in v[1].lower()]
        hits.sort(key=lambda x: (-x[0], x[1]))
        return [person(n, ad) for _, ad, n in hits[:8]]

    def db_delete(self, i):
        f, u = self.parse(i)
        for r in self.c.execute("select id from msgs where folder=? and uid=?", (f, u)).fetchall():
            self.c.execute("delete from msgs where id=?", (r["id"],))
            self.c.execute("delete from fts where rowid=?", (r["id"],))
        self.c.commit()
