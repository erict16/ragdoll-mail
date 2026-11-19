"""Looking for a newer version of the app and installing it."""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import ragdoll as R
from .common import __version__, fail, FROZEN
from .desktop import relaunch


RELEASES_API = "https://api.github.com/repos/erict16/ragdoll-mail/releases/latest"


RELEASES_PAGE = "https://github.com/erict16/ragdoll-mail/releases/latest"


UPDATE_CHECK_EVERY = 6 * 3600


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


def release_asset(assets):
    """The file of a GitHub release that this computer installs, or None."""
    want = {"win32": (".exe", ".msi"), "darwin": (".dmg", ".pkg", ".zip")}.get(sys.platform, (".appimage", ".deb"))
    for ext in want:
        for x in assets or []:
            url = x.get("browser_download_url") or ""
            if (x.get("name") or "").lower().endswith(ext) and url.startswith("https://"):
                return url
    return None


def release_notes(body):
    """A release's text as short plain lines: its list items when it has a list, else its first lines."""
    lines = [x.strip() for x in (body or "").splitlines() if x.strip()]
    items = [x for x in lines if re.match(r"[-*+] ", x)] or [x for x in lines if not x.startswith("#")]
    out = []
    for x in items[:12]:
        x = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", re.sub(r"^[-*+] +", "", x))
        out.append(re.sub(r"[*_`]+", "", x)[:200])
    return out


class Updates:
    """The update check and install. (Part of Backend.)"""

    def update_loop(self):
        """Look for a newer version at the start and then through the day (the app may stay open for days)."""
        while not self.stopping.is_set():
            was = self.update
            self.check_update()
            if self.update != was:
                self.poke()
            self.stopping.wait(3600)

    def check_update(self):
        try:
            if self.update and self.update.get("ready"):
                return                                  # already installed; it waits for a restart
            if FROZEN:
                if time.time() - self.update_checked < UPDATE_CHECK_EVERY:
                    return
                self.update_checked = time.time()
                req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "ragdoll-mail",
                                                                    "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=15) as f:
                    d = json.load(f)
                v = (d.get("tag_name") or "").lstrip("v")
                if version_tuple(v) > version_tuple(__version__):
                    self.update = {"version": v, "id": v, "kind": "download", "url": d.get("html_url") or RELEASES_PAGE,
                                   "download": release_asset(d.get("assets")), "notes": release_notes(d.get("body"))}
            elif os.path.isdir(os.path.join(R.APP_DIR, ".git")):
                R.maybe_check_later()                   # it keeps its own six-hour pace
                latest = R.update_state().get("latest") or {}
                code, head, _ = R.git(R.APP_DIR, "rev-parse", "HEAD", timeout=10)
                if latest.get("behind") and not latest.get("ahead") and code == 0 and head == latest.get("head"):
                    self.update = {"version": latest.get("version"), "id": latest.get("sha"), "kind": "source",
                                   "notes": [str(x)[:200] for x in (latest.get("notes") or [])[:12]]}
                else:
                    self.update = None
        except Exception:
            pass

    def shown_update(self):
        u = self.update
        if u and not u.get("ready") and u.get("id") and self.prefs().get("skip_update") == u["id"]:
            return None                                 # the user said: not this version
        return u

    def api_update(self, a):
        """skip: do not offer this version again. install: update a source clone in place. restart: reopen the app."""
        u, do = self.update, a.get("do")
        if do == "restart":
            relaunch()
            return {}
        if not u:
            fail("There is no update now.")
        if do == "skip":
            self.save_prefs({"skip_update": u.get("id")})
            return {}
        if do != "install" or u.get("kind") != "source" or self.demo:
            fail("This version can't update itself. Download the new one instead.")
        if not self.update_lock.acquire(blocking=False):
            fail("The update is already running.")
        try:
            r = R.do_update(R.APP_DIR)
        finally:
            self.update_lock.release()
        if r["state"] == "updated":
            self.update = dict(u, ready=True, version=r.get("version") or u.get("version"))
        elif r["state"] == "current":
            self.update = None
        else:
            fail("Not updated: %s" % r.get("reason", r["state"]))
        return {"state": r["state"], "update": self.update}
