"""Snooze: a mail leaves the Inbox until a time, then comes back on top, unread."""

import contextlib
import json
import os
import time

import ragdoll as R
from . import desktop
from .common import ApiError, fail, ids_in
from .desktop import window_focused


class Snooze:
    """Snoozed mail. (Part of Backend.)"""

    # ---- snooze: a mail leaves the Inbox list until a time; then it is back on top, unread
    # snoozed.json holds {"id", "until"} and, once the time has come, "woke". Nothing moves on the server.

    def snooze_path(self):
        return os.path.join(R.CFG.home, "snoozed.json")

    def snooze_list(self):
        with self.schedlock:
            try:
                with open(self.snooze_path(), encoding="utf-8") as f:
                    d = json.load(f)
                return [x for x in d if isinstance(x, dict) and x.get("id") and isinstance(x.get("until"), (int, float))]
            except (OSError, ValueError):
                return []

    def snooze_save(self, items):
        with self.schedlock:
            os.makedirs(R.CFG.home, exist_ok=True)
            tmp = self.snooze_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items, f)
            os.replace(tmp, self.snooze_path())
        self.bump()

    def api_snooze(self, a):
        """Hide these Inbox mails until a["until"] (Unix seconds). until 0: back in the Inbox now."""
        ids = ids_in(a)
        try:
            until = int(a.get("until") or 0)
        except (TypeError, ValueError, OverflowError):
            fail("Pick a time.")
        with self.schedlock:
            items = [x for x in self.snooze_list() if x["id"] not in ids]
            if until:
                if until < time.time() + 30:
                    fail("Pick a time in the future.")
                if until > time.time() + 5 * 366 * 86400:
                    fail("Pick a time within the next five years.")
                inbox = R.CFG.folders.get("inbox") or "INBOX"
                for i in ids:
                    if self.row(i)["folder"] != inbox:
                        fail("Only mail in the Inbox can be snoozed.")
                items += [{"id": i, "until": until} for i in ids]
            self.snooze_save(items)
        self.sched_wake.set()
        return {"snoozed": len(ids) if until else 0}

    def snooze_state(self):
        """(rows that wait, rows that came back and are still unread, newest wake first), stale entries dropped."""
        items, wait, woke, keep = self.snooze_list(), [], [], []
        for x in items:
            try:
                r = self.row(x["id"])
            except ApiError:
                continue                                # moved or deleted meanwhile
            if x.get("woke"):
                if r["seen"]:
                    continue                            # read again: an ordinary mail from here on
                woke.append((x, r))
            else:
                wait.append((x, r))
            keep.append(x)
        if len(keep) != len(items):
            with self.schedlock:
                have = {x["id"] for x in keep}
                self.snooze_save([x for x in self.snooze_list() if x["id"] in have])
        woke.sort(key=lambda p: -p[0]["woke"])
        wait.sort(key=lambda p: p[0]["until"])
        return wait, woke

    def snoozed_rows(self):
        out = []
        for x, r in self.snooze_state()[0]:
            j = self.row_json(r)
            j["snooze"] = x["until"]
            out.append(j)
        return out

    def wake_due(self, now=None):
        """Bring back every snoozed mail whose time has come: unread, on top of the Inbox, with a notification."""
        now = time.time() if now is None else now
        with self.schedlock:
            items = self.snooze_list()
            due = [x for x in items if not x.get("woke") and x["until"] <= now]
            if not due:
                return 0
            for x in due:
                x["woke"] = int(now)
            self.snooze_save(items)
        ids = [x["id"] for x in due]
        try:
            self.set_flag(ids, "seen", False)
        except (Exception, SystemExit):     # noqa: BLE001 - no connection: unread here, the server hears later
            for i in ids:
                with contextlib.suppress(Exception):
                    f, u = self.parse(i)
                    self.exec("update msgs set seen=0 where folder=? and uid=?", (f, u))
            self.bump()
        with contextlib.suppress(Exception):
            if self.prefs().get("notify") is not False and not window_focused():
                r = self.row(ids[0])
                n, a = (R.addrs(r["frm"]) or [("", "")])[0]
                title = (n or a or "ragdoll-mail") + (" +%d" % (len(ids) - 1) if len(ids) > 1 else "")
                desktop.desktop_notify(title, r["subject"] or "", lambda: self.open_from_note(ids[0]))
        return len(due)
