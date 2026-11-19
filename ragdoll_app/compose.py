"""Writing mail: new, reply, forward, drafts, attachments, and sending."""

import contextlib
import hashlib
import json
import os
import re
import secrets
import time

import ragdoll as R
from .common import ApiError, fail, people_in, people_json, person
from .message import cid_map, data_images, file_parts, index_raw, page_html


def app_problems(msg, reply):
    """ragdoll's pre-send check, worded for the app (no CLI flags; no table-layout rules)."""
    out = []
    for p in R.check_message(msg, reply, blanks_ok=False, required_cc=True, attach_ok=False):
        if "table" in p or "no quoted history" in p or "signature" in p:
            continue
        out.append(re.split(r";\s*(?=.*--)", p)[0])
    return out


class Compose:
    """Drafts and sending. (Part of Backend.)"""

    # ---- compose

    def signature(self):
        s = R.CFG.signature
        if not s:
            return ""
        p = os.path.expanduser(s)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return f.read()
        return R.text_to_html(s) if "\n" in s or "/" not in s else ""

    def upload_dir(self):
        d = os.path.join(R.CFG.home, "uploads", secrets.token_hex(6))
        os.makedirs(d, exist_ok=True)
        return d

    def keep_file(self, name, data):
        path = os.path.join(self.upload_dir(), R.safe_name(name))
        with open(path, "wb") as f:
            f.write(data)
        return {"path": path, "name": os.path.basename(path), "size": len(data)}

    def api_compose(self, a):
        mode = a.get("mode") or "new"
        out = {"mode": mode, "orig": None, "replace": None, "to": [], "cc": [], "bcc": [], "subject": "",
               "html": "", "atts": [], "quote": "", "signature": self.signature(), "use_signature": True}
        if mode in ("reply", "replyall", "forward"):
            orig = R.to_msg(self.raw(a["id"]))
            out["orig"] = a["id"]
            q = R.quote_block(orig)
            out["quote"] = page_html(q, cid_map(orig))
            if mode == "forward":
                out["subject"] = R.forward_subject(R.hdr(orig, "Subject"))
                out["atts"] = [self.keep_file(R.fname(p) or "attachment", R.part_bytes(p)) for p in file_parts(orig)]
            else:
                to, cc = R.reply_recipients(orig, mode == "replyall", R.CFG.user)
                out["to"] = [person(n, x) for n, x in to]
                out["cc"] = [person(n, x) for n, x in cc]
                out["subject"] = R.reply_subject(R.hdr(orig, "Subject"))
        elif mode == "outbox":
            x = next((y for y in self.outbox_list() if "outbox:" + y["key"] == a.get("id") and y.get("args")), None)
            if not x:
                fail("This mail is no longer waiting.")
            out.update({k: v for k, v in x["args"].items() if v is not None})
            out["mode"] = x["args"].get("mode") or "new"
            out["signature"] = self.signature()
            out["atts"] = [y for y in x["args"].get("atts") or [] if isinstance(y, dict) and os.path.isfile(y.get("path", ""))]
            if out.get("orig"):
                with contextlib.suppress(ApiError, SystemExit, Exception):
                    orig = R.to_msg(self.raw(out["orig"]))
                    out["quote"] = page_html(R.quote_block(orig), cid_map(orig))
            self.outbox_drop(key=x["key"])
            return out
        elif mode == "draft":
            out["replace"] = a["id"]
            msg = R.to_msg(self.raw(a["id"]))
            state = self.compose_state(R.hdr(msg, "Message-ID"))
            if state:
                out.update(state)
                out["replace"] = a["id"]
                out["signature"] = self.signature()
                if state.get("orig"):
                    with contextlib.suppress(ApiError, SystemExit, Exception):
                        orig = R.to_msg(self.raw(state["orig"]))
                        out["quote"] = page_html(R.quote_block(orig), cid_map(orig))
                out["atts"] = [x for x in state.get("atts", []) if os.path.isfile(x["path"])]
                return out
            plain, html = R.bodies(msg)
            out.update({"to": people_json(R.hdr(msg, "To")), "cc": people_json(R.hdr(msg, "Cc")),
                        "bcc": people_json(R.hdr(msg, "Bcc")), "subject": R.hdr(msg, "Subject"),
                        "html": page_html(html, cid_map(msg)) if html.strip() else R.text_to_html(plain),
                        "use_signature": False, "irt": R.hdr(msg, "In-Reply-To").strip(),
                        "refs": R.hdr(msg, "References").strip(), "fwd": R.hdr(msg, R.FWD_HEADER).strip(),
                        "atts": [self.keep_file(R.fname(p) or "attachment", R.part_bytes(p))
                                 for p in file_parts(msg)]})
            return out
        if mode != "draft":
            have = {x["addr"] for x in out["to"] + out["cc"]}
            for x in R.CFG.require_cc or []:
                if x.lower() not in have and x.lower() != R.CFG.user:
                    out["cc"].append(person("", x.lower()))
        return out

    def state_path(self, mid):
        return os.path.join(R.CFG.home, "compose", hashlib.sha1((mid or "").strip().encode()).hexdigest() + ".json")

    def drop_state(self, i):
        f, u = self.parse(i)
        for r in self.q("select msgid from msgs where folder=? and uid=?", (f, u)):
            with contextlib.suppress(OSError):
                os.remove(self.state_path(r["msgid"]))

    def compose_state(self, mid):
        with contextlib.suppress(OSError, ValueError):
            with open(self.state_path(mid), encoding="utf-8") as f:
                return json.load(f)
        return None

    def build(self, a):
        mode = a.get("mode") or "new"
        orig = None
        if a.get("orig"):
            orig = R.to_msg(self.raw(a["orig"]))
        to, cc, bcc = people_in(a.get("to")), people_in(a.get("cc")), people_in(a.get("bcc"))
        to, cc = R.clean_recipients(to, cc, set())
        subject = (a.get("subject") or "").strip()
        atts = []
        root = os.path.realpath(os.path.join(R.CFG.home, "uploads"))
        for x in a.get("atts") or []:
            p = os.path.realpath(x["path"])
            if not p.startswith(root + os.sep) or not os.path.isfile(p):
                fail("An attachment is missing: %s" % x.get("name", ""))
            atts.append(p)
        body, images = data_images(a.get("html") or "")
        sig = self.signature() if a.get("use_signature", True) else ""
        msg = R.build_message(body, to, cc, subject, orig, "reply" if mode in ("reply", "replyall") else None,
                              bcc, atts, sig)
        if mode == "draft" and not orig and a.get("irt"):
            msg["In-Reply-To"] = a["irt"]
            msg["References"] = a.get("refs") or a["irt"]
        if mode == "forward" and orig is not None and R.hdr(orig, "Message-ID").strip():
            msg[R.FWD_HEADER] = R.hdr(orig, "Message-ID").strip()
        elif mode == "draft" and not orig and a.get("fwd"):
            msg[R.FWD_HEADER] = a["fwd"]
        if images:
            holder = msg.get_body(("related",)) or msg.get_body(("html",))
            for cid, data, mt, st in images:
                holder.add_related(data, mt, st, cid="<%s>" % cid)
                holder = msg.get_body(("related",)) or holder
        return msg

    def save(self, a):
        """Save the compose as a draft (replacing the one it came from). Returns (id, msg)."""
        msg = self.build(a)
        if self.fake_offline:
            raise R.NotConnected("offline")
        raw = msg.as_bytes(policy=R.OUT_POLICY)
        drafts = R.CFG.folders["drafts"]
        old = a.get("replace")
        if old:
            f, u = self.parse(old)
            if f != drafts:
                old = None
            else:
                with self.schedlock:
                    self.sched_drop(old)
                self.drop_state(old)
        if self.demo:
            uid = self.demo_insert(drafts, raw, int(time.time()), 1, 0)
            if old:
                self.demo_delete(old)
        else:
            def go(m):
                uid = R.append_draft(m, raw)
                uidv = R.select(m, drafts)
                if old:
                    with contextlib.suppress(Exception):
                        R.delete_uid(m, *self.parse(old))
                return uid, uidv
            uid, uidv = self.imap(go)
            with self.dblock:
                if old:
                    self.db_delete(old)
                if uid:
                    index_raw(self.c, drafts, uidv, uid, raw, int(time.time()), 1, 0)
        state = {k: a.get(k) for k in ("mode", "orig", "to", "cc", "bcc", "subject", "html", "atts",
                                       "use_signature", "irt", "refs", "fwd")}
        with contextlib.suppress(OSError):
            os.makedirs(os.path.join(R.CFG.home, "compose"), exist_ok=True)
            with open(self.state_path(R.hdr(msg, "Message-ID")), "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
        self.bump()
        return R.make_id(drafts, uid) if uid else None, msg

    def api_save_draft(self, a):
        i, _ = self.save(a)
        return {"id": i}

    def api_prepare_send(self, a):
        """Check the mail, save it as a draft. The page sends it (api_send) after the undo pause."""
        msg = self.build(a)
        problems = [] if a.get("force") else app_problems(msg, a.get("mode") in ("reply", "replyall"))
        if problems:
            return {"problems": problems}
        try:
            i, _ = self.save(a)
        except (Exception, SystemExit) as e:        # noqa: BLE001
            if isinstance(e, ApiError) or not R.not_connected(e):
                raise
            keep = {k: a.get(k) for k in ("mode", "orig", "to", "cc", "bcc", "subject", "html", "atts",
                                          "use_signature", "irt", "refs", "fwd", "replace")}
            then = a.get("at") if isinstance(a.get("at"), (int, float)) else None
            x = self.outbox_add({"args": keep, "then": then} if then else {"args": keep})
            return {"queued": True, "id": "outbox:" + x["key"], "problems": []}
        if not i:
            fail("The draft was saved but the server did not say where. Open Drafts and send it from there.")
        return {"id": i, "problems": []}

    def api_send(self, a):
        with self.schedlock:
            self.sched_drop(a["id"])
            return self.send_now(a)

    def send_now(self, a, queue=True):
        """Send the draft. queue: when the servers cannot be reached, keep it in the outbox and say so."""
        try:
            if self.fake_offline:
                raise R.NotConnected("offline")
            r = self.send_draft_now(a)
        except R.NotConnected:
            if not queue:
                raise
            self.outbox_add({"id": a["id"]})
            return {"queued": True}
        self.outbox_drop(i=a["id"])
        return r

    def send_draft_now(self, a):
        folder, uid = self.parse(a["id"])
        if folder != R.CFG.folders["drafts"]:
            fail("Only drafts can be sent.")
        self.drop_state(a["id"])
        if self.demo:
            raw = self.demo_raw.get((folder, uid))
            if raw is None:
                fail("The draft is gone.")
            msg = R.to_msg(raw)
            self.demo_delete(a["id"])
            del msg["Bcc"]
            self.demo_insert(R.CFG.folders["sent"], msg.as_bytes(policy=R.OUT_POLICY), int(time.time()), 1, 0)
            fwd = R.forward_source(msg)
            irt = R.hdr(msg, "In-Reply-To").strip()
            if fwd:
                self.exec("update msgs set forwarded=1 where msgid=?", (fwd,))
            elif irt:
                self.exec("update msgs set answered=1 where msgid=?", (irt,))
            self.bump()
            return {"sent": True, "problems_after_sending": []}
        r = R.send_draft(folder, uid)
        with self.dblock:
            self.db_delete(a["id"])
        self.bump()
        self.wake.set()
        return r

    def api_delete_draft(self, a):
        folder, uid = self.parse(a["id"])
        if folder != R.CFG.folders["drafts"]:
            fail("Only drafts can be deleted this way.")
        with self.schedlock:
            self.sched_drop(a["id"])
        self.drop_state(a["id"])
        if self.demo:
            self.demo_delete(a["id"])
        else:
            self.imap(lambda m: R.delete_uid(m, folder, uid))
            with self.dblock:
                self.db_delete(a["id"])
        self.bump()
        return {}

    def upload(self, name, data):
        return self.keep_file(name or "file", data)
