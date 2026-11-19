"""What the page needs to draw itself: start-up data, folder counts, live status, saved preferences."""

import json
import contextlib
import os
import re
import sys
import time

import ragdoll as R
from .common import __version__, configured, int_in


LANGS = ("system", "en", "zh-Hans", "zh-Hant", "ja", "ko", "es", "fr", "de")


UNDO_SECONDS = (0, 5, 10, 20, 30)


FONTS = ("system", "arial", "helvetica", "georgia", "times", "verdana", "courier", "yahei", "pingfang", "simsun")


FONT_SIZES = (12, 13, 14, 16, 18)


TEXT_SIZES = (12, 13, 14, 15, 16, 18, 20)


class Status:
    """Start-up data, counts, status, preferences. (Part of Backend.)"""

    # ---- api: app state

    def api_boot(self, a):
        return {"configured": configured() or self.demo, "demo": self.demo, "user": R.CFG.user,
                "name": R.CFG.name, "version": __version__, "platform": sys.platform,
                "folders": self.folder_counts(), "theme": self.prefs().get("theme", "system"),
                "prefs": self.prefs()}

    def flag_folders(self):
        """Folders whose flagged mail shows in the Flagged list (not Trash or Junk)."""
        return [R.CFG.folders[k] for k in ("inbox", "sent", "archive", "drafts") if R.CFG.folders.get(k)]

    def index_state(self):
        """Changes whenever the index does, whoever wrote to it (this app, its sync, the command line)."""
        with self.dblock:
            return self.c.execute("pragma data_version").fetchone()[0], self.c.total_changes

    def mail_counts(self):
        """{folder: (mails, unread)} and the same for starred mail, read again only after the index changed."""
        fs = self.flag_folders()
        with self.dblock:
            key = (self.index_state(), tuple(fs))
            if self.counts[0] != key:
                per = {r[0]: (r[1], r[2]) for r in self.c.execute(
                    "select folder, count(*), coalesce(sum(seen=0),0) from msgs group by folder")}
                star = self.c.execute(
                    "select count(*), coalesce(sum(seen=0),0) from msgs where flagged=1 and folder in (%s)"
                    % ",".join("?" * len(fs)), fs).fetchone() if fs else (0, 0)
                self.counts = (key, (per, tuple(star)))
            return self.counts[1]

    def folder_counts(self):
        out = []
        per, star = self.mail_counts()
        count = lambda f: dict(zip(("n", "u"), per.get(f, (0, 0))))     # noqa: E731
        for k in ("inbox", "flagged", "drafts", "scheduled", "sent", "archive", "trash", "junk"):
            if k == "flagged":
                if star[0]:
                    out.append({"key": k, "total": star[0], "unread": star[1]})
                continue
            if k == "scheduled":
                n = len(self.scheduled_rows())
                if n:
                    out.append({"key": k, "total": n, "unread": 0})
                n = len(self.snooze_state()[0])
                if n:
                    out.append({"key": "snoozed", "total": n, "unread": 0})
                continue
            f = R.CFG.folders.get(k)
            if not f:
                continue
            r = count(f)
            if k == "junk" and not r["n"] and f not in {n for n, _ in self.listed}:
                continue
            out.append({"key": k, "total": r["n"], "unread": r["u"]})
        for name, delim in self.extra_folders():
            r = count(name)
            parts = name.split(delim) if delim else [name]
            out.append({"key": "f:" + name, "name": parts[-1], "depth": min(len(parts) - 1, 4), "custom": True,
                        "total": r["n"], "unread": r["u"]})
        return out

    def api_status(self, a):
        req, self.open_req = self.open_req, None
        return {"rev": self.rev, "tick": self.tick, "syncing": self.sync["running"], "error": self.sync["error"],
                "last": self.sync["last"], "folders": self.folder_counts(), "update": self.shown_update(),
                "open": req}

    def api_wait(self, a):
        """The status, as soon as something changed after the caller's tick; after 25 s at the latest.
        The page keeps one such call open, so it shows new mail at once and never has to ask in a loop."""
        most = a.get("max")
        end = time.time() + (min(25, max(0, most)) if isinstance(most, (int, float)) else 25)
        seen = self.index_state()[0]
        while not self.stopping.is_set():
            with self.cond:
                if self.tick != a.get("tick"):
                    break
                left = end - time.time()
                if left <= 0:
                    break
                self.cond.wait(min(left, 2))
            if self.index_state()[0] != seen:           # another program wrote to the index
                break
        return self.api_status(a)

    def api_sync(self, a):
        if not self.demo:
            self.start_sync()
        return {}

    def prefs(self):
        try:
            with open(os.path.join(R.CFG.home, "app.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def api_prefs(self, a):
        p = self.prefs()
        p.update({k: v for k, v in a.items() if k in ("theme", "list_width", "sidebar")})
        if a.get("lang") in LANGS:
            p["lang"] = a["lang"]
        if isinstance(a.get("tz"), str) and re.fullmatch(r"system|[A-Za-z][A-Za-z0-9_+\-/]{0,63}", a["tz"]):
            p["tz"] = a["tz"]
        if a.get("undo") in UNDO_SECONDS:
            p["undo"] = a["undo"]
        if a.get("font") in FONTS:
            p["font"] = a["font"]
        if a.get("font_size") in FONT_SIZES:
            p["font_size"] = a["font_size"]
        if a.get("text_size") in TEXT_SIZES:
            p["text_size"] = a["text_size"]
        for k in ("fmt_bar", "notify", "badge"):
            if isinstance(a.get(k), bool):
                p[k] = a[k]
        if "side_width" in a:                  # 0 = back to the usual width
            w = a["side_width"]
            p["side_width"] = w if isinstance(w, int) and 180 <= w <= 360 else 0
        out = self.save_prefs(p)
        if "badge" in a:
            with contextlib.suppress(Exception):
                self.badge()
        return out

    def save_prefs(self, patch):
        """Write app.json with these keys changed (the caller has checked the values)."""
        with self.preflock:
            p = self.prefs()
            p.update(patch)
            os.makedirs(R.CFG.home, exist_ok=True)
            tmp = os.path.join(R.CFG.home, "app.json.%d.tmp" % os.getpid())
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(p, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(R.CFG.home, "app.json"))
        return p
