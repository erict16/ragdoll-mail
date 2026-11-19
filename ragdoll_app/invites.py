"""Meeting invites: reading the calendar part of a mail and answering it."""

import json
import os
import re
import secrets
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import ragdoll as R
from .common import fail, open_path, person
from .message import index_raw


# ------------------------------------------------------------------ meeting invites (iCalendar)

WIN_ZONES = {   # the names Outlook writes -> the names browsers know
    "China Standard Time": "Asia/Shanghai", "Singapore Standard Time": "Asia/Singapore",
    "Taipei Standard Time": "Asia/Taipei", "Tokyo Standard Time": "Asia/Tokyo", "Korea Standard Time": "Asia/Seoul",
    "India Standard Time": "Asia/Kolkata", "SE Asia Standard Time": "Asia/Bangkok",
    "Arabian Standard Time": "Asia/Dubai", "Arab Standard Time": "Asia/Riyadh", "Turkey Standard Time": "Europe/Istanbul",
    "Russian Standard Time": "Europe/Moscow", "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin", "Romance Standard Time": "Europe/Paris",
    "Central Europe Standard Time": "Europe/Budapest", "Central European Standard Time": "Europe/Warsaw",
    "E. Europe Standard Time": "Europe/Chisinau", "FLE Standard Time": "Europe/Kiev",
    "Eastern Standard Time": "America/New_York", "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver", "Pacific Standard Time": "America/Los_Angeles",
    "E. South America Standard Time": "America/Sao_Paulo", "AUS Eastern Standard Time": "Australia/Sydney",
    "New Zealand Standard Time": "Pacific/Auckland", "South Africa Standard Time": "Africa/Johannesburg",
    "Egypt Standard Time": "Africa/Cairo", "UTC": "UTC", "Greenwich Standard Time": "UTC",
}


def ics_lines(text):
    """Content lines of an iCalendar text as (NAME, {PARAM: value}, value, raw line); long lines are joined."""
    for raw in re.sub(r"\r?\n[ \t]", "", text or "").splitlines():
        quoted, cut = False, -1
        for k, ch in enumerate(raw):
            if ch == '"':
                quoted = not quoted
            elif ch == ":" and not quoted:
                cut = k
                break
        if cut < 1:
            continue
        head = re.findall(r'(?:[^;"]|"[^"]*")+', raw[:cut])
        params = {}
        for x in head[1:]:
            k, _, v = x.partition("=")
            params[k.upper()] = v.strip('"')
        yield head[0].upper(), params, raw[cut + 1:], raw


def ics_text(v):
    return re.sub(r"\\([\\;,nN])", lambda mo: "\n" if mo.group(1) in "nN" else mo.group(1), v or "").strip()


def ics_time(params, value, offsets):
    """A DTSTART/DTEND for the page: the wall clock, and the zone it is in (the page knows the zones)."""
    mo = re.fullmatch(r"(\d{4})(\d\d)(\d\d)(?:T(\d\d)(\d\d)(\d\d)?(Z)?)?", value.strip())
    if not mo:
        return None
    y, m, d, h, mi, _, z = mo.groups()
    out = {"wall": [int(y), int(m), int(d), int(h or 0), int(mi or 0)], "day": h is None}
    if z:
        out["tz"] = "UTC"
    elif h is not None and params.get("TZID"):
        tzid = params["TZID"]
        out["tz"] = WIN_ZONES.get(tzid, tzid)
        if tzid in offsets:
            out["offset"] = offsets[tzid]           # minutes east of UTC, when the page does not know the zone
    return out


def ics_parse(text):
    """The first event of an iCalendar text, or None."""
    method, ev, stack, zones, zone, offsets = "", None, [], [], None, {}
    for name, params, value, raw in ics_lines(text):
        if name == "BEGIN":
            stack.append(value.upper())
            if value.upper() == "VTIMEZONE":
                zone = {"lines": [], "id": "", "std": None}
            elif value.upper() == "VEVENT" and ev is None:
                ev = {"attendees": [], "keep": []}
        if zone is not None:
            zone["lines"].append(raw)
            if name == "TZID":
                zone["id"] = value
            elif name == "TZOFFSETTO" and "STANDARD" in stack:
                mo = re.fullmatch(r"([+-])(\d\d)(\d\d)(\d\d)?", value.strip())
                if mo:
                    zone["std"] = (1 if mo.group(1) == "+" else -1) * (int(mo.group(2)) * 60 + int(mo.group(3)))
        if name == "END":
            if value.upper() == "VTIMEZONE" and zone is not None:
                zones.append("\r\n".join(zone["lines"]))
                if zone["std"] is not None:
                    offsets[zone["id"]] = zone["std"]
                zone = None
            if stack:
                stack.pop()
            if value.upper() == "VEVENT" and ev is not None and "done" not in ev:
                ev["done"] = True
            continue
        if name == "METHOD" and stack == ["VCALENDAR"]:
            method = value.strip().upper()
        if ev is None or "done" in ev or stack[-1:] != ["VEVENT"]:
            continue
        if name in ("UID", "SUMMARY", "LOCATION", "DESCRIPTION", "STATUS"):
            ev[name.lower()] = ics_text(value)
        elif name == "SEQUENCE":
            ev["sequence"] = int(value) if value.strip().isdigit() else 0
        elif name in ("DTSTART", "DTEND"):
            ev[name.lower()] = (params, value)
            ev["keep"].append(raw)
        elif name in ("RECURRENCE-ID",):
            ev["keep"].append(raw)
        elif name == "RRULE":
            ev["repeats"] = True
        elif name in ("ORGANIZER", "ATTENDEE"):
            who = {"name": ics_text(params.get("CN", "")), "addr": re.sub(r"(?i)^mailto:", "", value.strip()).lower(),
                   "status": params.get("PARTSTAT", "NEEDS-ACTION").upper()}
            if name == "ORGANIZER":
                ev["organizer"] = who
                ev["organizer_line"] = raw
            else:
                ev["attendees"].append(who)
    if not ev or not ev.get("uid"):
        return None
    for k in ("dtstart", "dtend"):
        if k in ev:
            ev[k[2:]] = ics_time(ev[k][0], ev[k][1], offsets)
            del ev[k]
    used = {p.get("TZID") for n, p, _, _ in ics_lines("\n".join(ev["keep"]))}
    ev["zones"] = [z for z in zones if any(("TZID:%s" % u) in z for u in used if u)]
    ev["method"] = method or "PUBLISH"
    return ev


def find_invite(msg):
    """(event, the mail part it is in) for a mail that carries a meeting invite, else (None, None)."""
    for p in R.leaf_parts(msg):
        ct = p.get_content_type()
        if ct != "text/calendar" and not (p.get_filename() or "").lower().endswith(".ics"):
            continue
        try:
            data = p.get_payload(decode=True) or b""
            text = data.decode(p.get_content_charset() or "utf-8", "replace")
            ev = ics_parse(text)
        except Exception:       # noqa: BLE001 - a broken invite is just a mail without one
            ev = None
        if ev:
            return ev, p
    return None, None


def ics_fold(line):
    """One content line, folded so no line is longer than 75 bytes."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode()) > (75 if not out else 74):
            out.append(cur)
            cur = ""
        cur += ch
    out.append(cur)
    return "\r\n ".join(out)


def ics_reply(ev, answer, name, addr):
    """The iCalendar REPLY that tells the organizer: accepted, tentative or declined."""
    esc = lambda s: re.sub(r"([\\;,])", r"\\\1", s or "").replace("\n", "\\n")     # noqa: E731
    cn = (';CN="%s"' % name.replace('"', "")) if name else ""
    lines = ["BEGIN:VCALENDAR", "PRODID:-//ragdoll-mail//EN", "VERSION:2.0", "METHOD:REPLY"]
    for z in ev.get("zones") or []:
        lines += z.split("\r\n")
    lines += ["BEGIN:VEVENT", "UID:" + ev["uid"], "SEQUENCE:%d" % ev.get("sequence", 0),
              "DTSTAMP:" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())]
    lines += ev.get("keep") or []
    if ev.get("organizer_line"):
        lines.append(ev["organizer_line"])
    lines += ["ATTENDEE;PARTSTAT=%s%s:mailto:%s" % (answer, cn, addr), "SUMMARY:" + esc(ev.get("summary")),
              "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(ics_fold(x) for x in lines) + "\r\n"


class Invites:
    """Meeting invites. (Part of Backend.)"""

    # ---- meeting invites

    def answers_path(self):
        return os.path.join(R.CFG.home, "invites.json")

    def answers(self):
        try:
            with open(self.answers_path(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def invite_json(self, ev):
        me = R.CFG.user
        mine = next((x["status"] for x in ev["attendees"] if x["addr"] == me), None)
        said = self.answers().get(ev["uid"])
        if said and said.get("sequence", 0) >= ev.get("sequence", 0):
            mine = said["answer"]
        org = ev.get("organizer") or {}
        cancelled = ev["method"] == "CANCEL" or (ev.get("status") or "").upper() == "CANCELLED"
        out = {"method": ev["method"], "summary": ev.get("summary") or "", "location": ev.get("location") or "",
               "start": ev.get("start"), "end": ev.get("end"), "repeats": bool(ev.get("repeats")),
               "organizer": person(org.get("name", ""), org.get("addr", "")) if org.get("addr") else None,
               "attendees": [dict(person(x["name"], x["addr"]), status=x["status"]) for x in ev["attendees"][:60]],
               "mine": mine, "cancelled": cancelled,
               "can_answer": bool(ev["method"] == "REQUEST" and not cancelled and org.get("addr")
                                  and org.get("addr") != me)}
        return out

    def api_invite(self, a):
        """answer: tell the organizer accepted / tentative / declined. open: hand the invite to the calendar app."""
        msg = R.to_msg(self.raw(a["id"]))
        ev, part = find_invite(msg)
        if not ev:
            fail("This mail has no meeting invite.")
        if a.get("do") == "open":
            d = os.path.join(R.CFG.home, "open", secrets.token_hex(4))
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, R.safe_name((ev.get("summary") or "invite")[:60]) + ".ics")
            with open(path, "wb") as f:
                f.write(part.get_payload(decode=True) or b"")
            self.made.add(path)
            if not self.demo:
                open_path(path)
            return {"path": path}
        answer = {"accepted": "ACCEPTED", "tentative": "TENTATIVE", "declined": "DECLINED"}.get(a.get("answer"))
        org = (ev.get("organizer") or {}).get("addr")
        if not answer or ev["method"] != "REQUEST" or not org:
            fail("This invite can't be answered.")
        word = {"ACCEPTED": "Accepted", "TENTATIVE": "Tentative", "DECLINED": "Declined"}[answer]
        out = EmailMessage(policy=R.OUT_POLICY)
        out["From"] = formataddr((R.CFG.name, R.CFG.user))
        out["To"] = formataddr(((ev.get("organizer") or {}).get("name") or "", org))
        out["Subject"] = "%s: %s" % (word, ev.get("summary") or "")
        out["Date"] = formatdate(localtime=True)
        out["Message-ID"] = make_msgid(domain=(R.CFG.user.split("@")[-1] or None))
        mid = R.hdr(msg, "Message-ID").strip()
        if mid:
            out["In-Reply-To"] = mid
            out["References"] = mid
        out.set_content("%s %s: %s\n" % (R.CFG.name or R.CFG.user, {"ACCEPTED": "has accepted", "TENTATIVE":
                        "has tentatively accepted", "DECLINED": "has declined"}[answer], ev.get("summary") or ""))
        out.add_alternative(ics_reply(ev, answer, R.CFG.name, R.CFG.user), subtype="calendar",
                            params={"method": "REPLY"})
        raw = out.as_bytes(policy=R.OUT_POLICY)
        drafts = R.CFG.folders["drafts"]
        if self.demo:
            uid = self.demo_insert(drafts, raw, int(time.time()), 1, 0)
        else:
            def go(m):
                return R.append_draft(m, raw), R.select(m, drafts)
            uid, uidv = self.imap(go)
            if not uid:
                fail("The reply was saved in Drafts but the server did not say where. Send it from there.")
            with self.dblock:
                index_raw(self.c, drafts, uidv, uid, raw, int(time.time()), 1, 0)
        r = self.send_now({"id": R.make_id(drafts, uid)})
        said = self.answers()
        said[ev["uid"]] = {"answer": answer, "sequence": ev.get("sequence", 0), "at": int(time.time())}
        os.makedirs(R.CFG.home, exist_ok=True)
        with open(self.answers_path(), "w", encoding="utf-8") as f:
            json.dump(said, f)
        self.bump()
        return {"mine": answer, "queued": bool(r.get("queued")), "to": org}
