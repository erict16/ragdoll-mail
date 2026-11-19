"""Mail that leaves later: scheduled send, and the outbox for mail written while offline."""

import contextlib
import json
import os
import secrets
import time

import ragdoll as R
from .common import ApiError, fail, friendly, person, snippet
from .message import page_html


class SendLater:
    """Scheduled send and the offline outbox. (Part of Backend.)"""

    # ---- scheduled send
    # A scheduled mail is a saved draft plus an entry in scheduled.json. The app sends it when it is
    # due, while the app is running (the next start sends anything that came due while it was closed).

    def sched_path(self):
        return os.path.join(R.CFG.home, "scheduled.json")

    def sched_list(self):
        with self.schedlock:
            try:
                with open(self.sched_path(), encoding="utf-8") as f:
                    d = json.load(f)
                return [x for x in d if isinstance(x, dict) and x.get("id") and isinstance(x.get("at"), (int, float))]
            except (OSError, ValueError):
                return []

    def sched_save(self, items):
        with self.schedlock:
            os.makedirs(R.CFG.home, exist_ok=True)
            tmp = self.sched_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False)
            os.replace(tmp, self.sched_path())

    def sched_drop(self, i):
        with self.schedlock:
            items = self.sched_list()
            keep = [x for x in items if x["id"] != i]
            if len(keep) != len(items):
                self.sched_save(keep)
                self.bump()
                return True
            return False

    def api_schedule(self, a):
        """Send the saved draft a["id"] at a["at"] (Unix seconds)."""
        i = a["id"]
        folder, uid = self.parse(i)
        if folder != R.CFG.folders["drafts"]:
            fail("Only drafts can be scheduled.")
        try:
            at = int(a["at"])
        except (KeyError, TypeError, ValueError, OverflowError):
            fail("Pick a time to send.")
        if at < time.time() - 60:
            fail("That time has already passed.")
        if at > time.time() + 5 * 366 * 86400:
            fail("Pick a time within the next five years.")
        with self.schedlock:
            self.row(i)
            items = [x for x in self.sched_list() if x["id"] != i]
            items.append({"id": i, "at": at})
            self.sched_save(items)
        self.bump()
        self.sched_wake.set()
        return {"id": i, "at": at}

    def api_unschedule(self, a):
        """Keep the mail as a draft and do not send it."""
        self.sched_drop(a["id"])
        self.outbox_drop(i=a["id"])
        return {}

    def scheduled_rows(self):
        out = []
        for x in sorted(self.sched_list(), key=lambda x: x["at"]):
            try:
                r = self.row_json(self.row(x["id"]))
            except ApiError:
                continue
            r["sched"] = x["at"]
            r["sched_error"] = x.get("error")
            out.append(r)
        return self.outbox_rows() + out

    def sched_loop(self):
        while not self.stopping.is_set():
            self.sched_wake.wait(15)
            self.sched_wake.clear()
            if self.stopping.is_set():
                break
            with contextlib.suppress(Exception):
                self.send_due()
            with contextlib.suppress(Exception):
                self.wake_due()
            with contextlib.suppress(Exception):
                if time.time() - self.outbox_tried >= 60 and self.outbox_list():
                    self.flush_outbox()

    def send_due(self, now=None):
        """Send every scheduled mail that is due. A failure stays in the list with its reason and is not
        tried again by itself: a send that failed half way could otherwise go out twice."""
        now = time.time() if now is None else now
        sent = 0
        with self.schedlock:
            for x in self.sched_list():
                if x["at"] > now or x.get("error"):
                    continue
                try:
                    self.send_now({"id": x["id"]}, queue=False)
                    self.sched_drop(x["id"])
                    sent += 1
                except R.NotConnected:
                    continue                                    # no connection now: the next pass tries again
                except Exception as e:       # noqa: BLE001 - every reason is shown to the person
                    msg = str(e) if isinstance(e, ApiError) else friendly(e)
                    items = self.sched_list()
                    for y in items:
                        if y["id"] == x["id"]:
                            y["error"] = msg
                    self.sched_save(items)
                    self.bump()
        return sent

    # ---- outbox: mail that could not leave because the servers were out of reach
    # An entry is {"key", "at", and "id" (a draft saved on the server) or "args" (the compose, when even the
    # draft could not be saved)}. It is tried again when the connection is back. Only a failure from before
    # the mail was handed over is tried again; any other failure stays, with its reason, for the person.

    def outbox_path(self):
        return os.path.join(R.CFG.home, "outbox.json")

    def outbox_list(self):
        with self.schedlock:
            try:
                with open(self.outbox_path(), encoding="utf-8") as f:
                    d = json.load(f)
                return [x for x in d if isinstance(x, dict) and x.get("key") and (x.get("id") or x.get("args"))]
            except (OSError, ValueError):
                return []

    def outbox_save(self, items):
        with self.schedlock:
            os.makedirs(R.CFG.home, exist_ok=True)
            tmp = self.outbox_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False)
            os.replace(tmp, self.outbox_path())
        self.bump()

    def outbox_add(self, entry):
        with self.schedlock:
            items = self.outbox_list()
            if entry.get("id"):
                for x in items:
                    if x.get("id") == entry["id"]:
                        return x
            entry = dict(entry, key=secrets.token_hex(6), at=int(time.time()))
            self.outbox_save(items + [entry])
        return entry

    def outbox_drop(self, key=None, i=None):
        with self.schedlock:
            items = self.outbox_list()
            keep = [x for x in items if not ((key and x["key"] == key) or (i and x.get("id") == i))]
            if len(keep) != len(items):
                self.outbox_save(keep)
                return True
        return False

    def outbox_set(self, key, **patch):
        with self.schedlock:
            items = self.outbox_list()
            for x in items:
                if x["key"] == key:
                    x.update(patch)
                    for k in [k for k, v in x.items() if v is None]:
                        del x[k]
            self.outbox_save(items)

    def flush_outbox(self, again=False):
        """Send what waits. Stops at the first mail that still cannot connect. again: also the failed ones."""
        sent = 0
        self.outbox_tried = time.time()
        with self.schedlock:
            for x in self.outbox_list():
                if x.get("error") and not again:
                    continue
                try:
                    if x.get("args") is not None:               # first the draft, now that the server answers
                        i, _ = self.save(x["args"])
                        if not i:
                            raise ApiError("The draft was saved but the server did not say where. Send it from Drafts.")
                        then = x.get("then") or 0
                        if then > time.time():
                            self.sched_save([y for y in self.sched_list() if y["id"] != i] + [{"id": i, "at": then}])
                            self.outbox_drop(key=x["key"])
                            continue
                        self.outbox_set(x["key"], id=i, args=None, error=None)
                        x = dict(x, id=i)
                    self.send_now({"id": x["id"]}, queue=False)
                    self.outbox_drop(key=x["key"])
                    sent += 1
                except (Exception, SystemExit) as e:    # noqa: BLE001 - every reason is shown to the person
                    if R.not_connected(e):
                        break                                   # still no connection: try all of it later
                    self.outbox_set(x["key"], error=str(e) if isinstance(e, (ApiError, SystemExit)) else friendly(e))
        if sent:
            self.wake.set()
        return sent

    def outbox_rows(self):
        out = []
        for x in self.outbox_list():
            if x.get("args") is not None:
                a = x["args"]
                r = {"id": "outbox:" + x["key"], "folder": "drafts", "ts": x["at"],
                     "from": person(R.CFG.name, R.CFG.user), "to": a.get("to") or [], "cc": a.get("cc") or [],
                     "subject": a.get("subject") or "", "snippet": snippet(R.html_to_text(a.get("html") or "")),
                     "unread": False, "flagged": False, "answered": False, "forwarded": False,
                     "atts": [y.get("name") for y in a.get("atts") or [] if isinstance(y, dict)]}
            else:
                try:
                    r = self.row_json(self.row(x["id"]))
                except ApiError:
                    continue
            r.update(sched=x.get("then") or x["at"], waiting=True, sched_error=x.get("error"))
            out.append(r)
        return out

    def api_outbox(self, a):
        """retry: try the waiting mail now. message: the text of a mail that waits without a draft."""
        if a.get("do") == "message":
            x = next((y for y in self.outbox_list() if "outbox:" + y["key"] == a.get("id") and y.get("args")), None)
            if not x:
                fail("This mail is no longer waiting.")
            args = x["args"]
            html = page_html(args.get("html") or "", {})
            return {"id": a["id"], "from": person(R.CFG.name, R.CFG.user), "to": args.get("to") or [],
                    "cc": args.get("cc") or [], "bcc": args.get("bcc") or [], "subject": args.get("subject") or "",
                    "ts": x["at"], "html": html, "plain": False, "remote": False, "big": [],
                    "atts": []}
        sent = self.flush_outbox(again=True)
        return {"sent": sent, "waiting": len(self.outbox_list())}
