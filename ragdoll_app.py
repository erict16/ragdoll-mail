#!/usr/bin/env python3
"""ragdoll-mail desktop app: a window over ragdoll's mailbox and search index.

    ragdoll app                 open the app (pywebview window, else the default browser)
    python ragdoll_app.py --demo --browser
                                a made-up mailbox in the browser, no account needed

The page (app/) talks to a small HTTP server on 127.0.0.1. The server answers only requests
that carry this run's random token, and only for the 127.0.0.1 host name (no DNS rebinding).
"""
import argparse
import atexit
import base64
import contextlib
import datetime as dt
import hashlib
import html as htmlmod
import imaplib
import json
import locale
import collections
import queue
import mimetypes
import os
import re
import secrets
import shutil
import signal
import smtplib
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

for _s in ("stdout", "stderr"):          # a windowed (PyInstaller) build has no console
    if getattr(sys, _s) is None:
        setattr(sys, _s, open(os.devnull, "w", encoding="utf-8"))

import ragdoll as R  # noqa: E402

__version__ = R.__version__
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(getattr(sys, "_MEIPASS", HERE), "app")
FROZEN = bool(getattr(sys, "frozen", False))
RELEASES_API = "https://api.github.com/repos/erict16/ragdoll-mail/releases/latest"
APP_NAME = "Ragdoll Mail"   # what people see: window title, Dock, menu bar; the repo and files keep ragdoll-mail
RELEASES_PAGE = "https://github.com/erict16/ragdoll-mail/releases/latest"
FOLDER_KEYS = ("inbox", "drafts", "sent", "archive", "trash", "junk")
LIST_KEYS = FOLDER_KEYS + ("flagged", "scheduled")      # the names the app's own lists go by
VIEW_FLAGS = ("\\noselect", "\\nonexistent", "\\all", "\\flagged", "\\important")   # not a folder to show
FOLDER_NAMES = {
    "sent": ("sent messages", "sent", "sent items", "sent mail", "[gmail]/sent mail", "已发送", "已发送邮件"),
    "drafts": ("drafts", "draft", "[gmail]/drafts", "草稿箱", "草稿"),
    "trash": ("deleted messages", "trash", "deleted items", "deleted", "[gmail]/trash", "已删除", "已删除邮件"),
    "junk": ("junk", "spam", "junk e-mail", "junk email", "[gmail]/spam", "垃圾邮件", "垃圾箱"),
    "archive": ("archive", "archives", "归档"),
}
PROVIDERS = {       # domain -> (imap host, smtp host[, smtp port]); IMAP on 993, SMTP on 465 unless given
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "qq.com": ("imap.qq.com", "smtp.qq.com"),
    "foxmail.com": ("imap.qq.com", "smtp.qq.com"),
    "163.com": ("imap.163.com", "smtp.163.com"),
    "126.com": ("imap.126.com", "smtp.126.com"),
    "yeah.net": ("imap.yeah.net", "smtp.yeah.net"),
    "sina.com": ("imap.sina.com", "smtp.sina.com"),
    "aliyun.com": ("imap.aliyun.com", "smtp.aliyun.com"),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com"),
    "fastmail.com": ("imap.fastmail.com", "smtp.fastmail.com"),
    "zoho.com": ("imap.zoho.com", "smtp.zoho.com"),
    "gmx.com": ("imap.gmx.com", "mail.gmx.com"),
    "yandex.com": ("imap.yandex.com", "smtp.yandex.com"),
    "icloud.com": ("imap.mail.me.com", "smtp.mail.me.com", 587),
    "me.com": ("imap.mail.me.com", "smtp.mail.me.com", 587),
    "mac.com": ("imap.mail.me.com", "smtp.mail.me.com", 587),
}


class ApiError(Exception):
    pass


def fail(msg):
    raise ApiError(msg)


LANGS = ("system", "en", "zh-Hans", "zh-Hant", "ja", "ko", "es", "fr", "de")
UNDO_SECONDS = (0, 5, 10, 20, 30)
FONTS = ("system", "arial", "helvetica", "georgia", "times", "verdana", "courier", "yahei", "pingfang", "simsun")
FONT_SIZES = (12, 13, 14, 16, 18)
TEXT_SIZES = (12, 13, 14, 15, 16, 18, 20)


def friendly(e):
    """A sentence a person can act on, for an exception from IMAP, SMTP or ragdoll."""
    s = str(e.code if isinstance(e, SystemExit) else e) or e.__class__.__name__
    low = s.lower()
    if isinstance(e, (smtplib.SMTPAuthenticationError,)) or (
            isinstance(e, imaplib.IMAP4.error) and re.search(r"login|auth|password|credentials|invalid", low)):
        return "Sign-in failed. Check the email address and password in Settings."
    if "is not set and no password is saved" in s:
        return "No password saved. Add it in Settings."
    if "no account configured" in s:
        return "No account yet. Add one in Settings."
    if isinstance(e, socket.gaierror):
        return "Can't find the mail server. Check the server name and the internet connection."
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "The mail server did not answer in time."
    if isinstance(e, ssl.SSLError):
        return "Secure connection failed (%s). Check the server name and port." % s
    if isinstance(e, ConnectionRefusedError):
        return "The mail server refused the connection. Check the port."
    if isinstance(e, OSError) and not isinstance(e, FileNotFoundError):
        return "Can't reach the mail server (%s)." % s
    if isinstance(e, imaplib.IMAP4.error):
        return "The mail server said: %s" % s
    return s


def config_path():
    return R.move_old_setup(R.env("CONFIG"))[0]


def cut(m):
    """Shut a connection's socket from another thread: a read that waits on it ends at once, and
    whoever waited gets an error and connects again (#40, #56)."""
    sock = getattr(m, "sock", None)
    if sock is not None:
        with contextlib.suppress(Exception):
            sock.shutdown(socket.SHUT_RDWR)


IDLE_CHECK = 60     # seconds a kept connection may sit unused before it is asked whether it is still there


def still_there(m, used, timeout):
    """After sleep or a network change a kept connection is dead, and its first command would wait
    out the whole timeout: past IDLE_CHECK a NOOP with a short wait says whether it lives (#56)."""
    if time.time() - used <= IDLE_CHECK:
        return True
    try:
        m.sock.settimeout(6)
        m.noop()
        return True
    except Exception:           # noqa: BLE001 - whatever it is, the connection is not usable
        return False
    finally:
        with contextlib.suppress(Exception):
            m.sock.settimeout(timeout)


def configured():
    return bool(R.CFG.user and R.CFG.imap.get("host") and R.CFG.smtp.get("host"))


def person(n, a):
    return {"name": n or "", "addr": a}


def people_json(v):
    return [person(n, a) for n, a in R.addrs(v)]


def people_in(lst):
    """[{name, addr}] or ["a@b"] from the page -> [(name, addr)], checked."""
    out = []
    for x in lst or []:
        n, a = (x.get("name", ""), x.get("addr", "")) if isinstance(x, dict) else ("", x)
        a = (a or "").strip().lower()
        if not a:
            continue
        if not re.fullmatch(r"[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+", a):
            fail("Not an email address: %s" % a)
        out.append(((n or "").strip(), a))
    return out


def snippet(body):
    return re.sub(r"\s+", " ", R.new_text(body or ""))[:180]


def open_path(path, reveal=False):
    if sys.platform == "darwin":
        # waits only until macOS has handed the file to an app, so a file no app opens says so
        try:
            r = subprocess.run(["open", "-R", path] if reveal else ["open", path], capture_output=True, timeout=20)
        except subprocess.TimeoutExpired:
            return              # the app is still starting: it opens the file when it is up
        if r.returncode:
            fail("The Mac could not open %s: %s" % (os.path.basename(path),
                 r.stderr.decode("utf-8", "replace").strip() or "no app opens this kind of file."))
    elif sys.platform == "win32":
        if reveal:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            try:
                os.startfile(path)                              # noqa: S606
            except OSError as e:
                fail("Windows could not open %s: %s" % (os.path.basename(path), e.strerror or e))
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) if reveal else path])


def downloads_dir():
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


# ------------------------------------------------------------------ mail -> page

STYLE_RE = re.compile(r"(?is)<style\b[^>]*>.*?</style>")


def data_uri(ctype, data):
    return "data:%s;base64,%s" % (ctype, base64.b64encode(data).decode())


def cid_map(msg):
    out = {}
    for p in msg.walk():
        if p.is_multipart() or not p.get("Content-ID"):
            continue
        ctype = R.image_type(p)
        if not ctype:
            continue
        data = p.get_payload(decode=True) or b""
        if data and len(data) <= 8 * 1024 * 1024:   # no data: a file the light mail left on the server
            out[p.get("Content-ID").strip().strip("<>")] = data_uri(ctype, data)
    return out


def page_html(html, cids):
    """A mail's HTML made ready for the sandboxed frame: its styles kept, the document wrapper,
    scripts, refreshes, base and form targets removed, cid: images inlined."""
    styles = "".join(STYLE_RE.findall(re.search(r"(?is)<head\b.*?</head>", html).group(0))) \
        if re.search(r"(?is)<head\b.*?</head>", html) else ""
    html = re.sub(r"(?is)<head\b.*?</head>", "", html)
    html = re.sub(r"(?is)^.*?<body[^>]*>|</body>.*$", "", html)
    html = re.sub(r"(?is)<!doctype[^>]*>|</?html\b[^>]*>|<base\b[^>]*>|<title\b.*?</title>", "", html)
    html = re.sub(r"(?is)<(script|iframe|object|embed|frameset|applet)\b.*?(</\1>|$)", "", html)
    html = re.sub(r"(?is)<meta\b[^>]*>|<link\b[^>]*>", "", html)
    html = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html)
    html = re.sub(r"(?i)(href|src)\s*=\s*([\"']?)\s*javascript:[^\"'>\s]*", r"\1=\2#", html)

    def cid(mo):
        return cids.get(urllib.parse.unquote(mo.group(2)), "data:,") if mo.group(2) else mo.group(0)
    html = re.sub(r"(?i)cid:(<?)([^\"'\s>)]+)", lambda mo: cids.get(urllib.parse.unquote(mo.group(2)).strip("<>"),
                                                                  "data:,"), html)
    return styles + html


LINK_RE = re.compile(r"(https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]}])|([\w.+-]+@[\w-]+(?:\.[\w-]+)+)")


def linkify(escaped):
    def one(mo):
        if mo.group(1):
            u = htmlmod.unescape(mo.group(1))
            return '<a href="%s">%s</a>' % (htmlmod.escape(u), mo.group(1))
        return '<a href="mailto:%s">%s</a>' % (mo.group(2), mo.group(2))
    return LINK_RE.sub(one, escaped)


def plain_html(text):
    text = (text or "").replace("\r\n", "\n").strip("\n")
    mo = R.QUOTE_RE.search(text)
    if not mo:
        mo = re.search(r"(?m)^(>.*\n?){2,}\Z", text)
    main, quoted = (text[:mo.start()], text[mo.start():]) if mo and mo.start() > 0 else (text, "")
    out = '<div class="rd-plain">%s</div>' % linkify(htmlmod.escape(main.rstrip()))
    if quoted.strip():
        out += '<div class="rd-plain rd-quote">%s</div>' % linkify(htmlmod.escape(quoted.strip()))
    return out


def has_remote(html):
    return bool(re.search(r"(?i)<img\b[^>]*\ssrc\s*=\s*[\"']?\s*(https?:)?//|url\(\s*[\"']?\s*(https?:)?//|"
                          r"\sbackground\s*=\s*[\"']?\s*https?:", html))


def file_parts(msg):
    """The mail's files (not the images shown in the body), in a fixed order."""
    out = []
    for p in R.attachments(msg, inline=True):
        if R.is_inline(p):
            continue
        out.append(p)
    return out


def left_out(p, light):
    """The IMAP section of a file the light mail left on the server, else None. Only a mail from our
    own light cache can say so: the same header in a mail somebody sent means nothing."""
    if not light or p.is_multipart() or (p.get_payload() or "").strip():
        return None
    sec = str(p["X-Ragdoll-Part"] or "").strip()
    return sec if R.SECTION_RE.fullmatch(sec) else None


def part_info(k, p, light=False):
    name = R.fname(p) or "attachment"
    try:
        size = int(p["X-Ragdoll-Size"]) if left_out(p, light) and p["X-Ragdoll-Size"] else len(R.part_bytes(p))
    except Exception:
        size = 0
    return {"i": k, "name": name, "size": size, "type": mimetypes.guess_type(name)[0] or p.get_content_type()}



def list_unsub(msg):
    """The mail's own way out of a mailing list (List-Unsubscribe, RFC 2369; one click per RFC 8058):
    {"url", "mailto", "one_click"}, or None for a mail that has none."""
    h = R.hdr(msg, "List-Unsubscribe") or ""
    links = re.findall(r"<\s*([^>\s]+)\s*>", h)
    url = next((u for u in links if re.match(r"(?i)https://", u)), None) or \
        next((u for u in links if re.match(r"(?i)http://", u)), None)
    mailto = next((u for u in links if re.match(r"(?i)mailto:[^@\s]+@", u)), None)
    if not url and not mailto:
        return None
    one = bool(url and url.lower().startswith("https://")
               and re.search(r"(?i)List-Unsubscribe\s*=\s*One-Click", R.hdr(msg, "List-Unsubscribe-Post") or ""))
    return {"url": url, "mailto": mailto, "one_click": one}


# Outlook names Windows time zones, not IANA ones
WIN_TZ = {"China Standard Time": "Asia/Shanghai", "Singapore Standard Time": "Asia/Singapore",
          "Taipei Standard Time": "Asia/Taipei", "Tokyo Standard Time": "Asia/Tokyo", "Korea Standard Time": "Asia/Seoul",
          "India Standard Time": "Asia/Kolkata", "SE Asia Standard Time": "Asia/Bangkok",
          "W. Australia Standard Time": "Australia/Perth", "AUS Eastern Standard Time": "Australia/Sydney",
          "GMT Standard Time": "Europe/London", "W. Europe Standard Time": "Europe/Berlin",
          "Romance Standard Time": "Europe/Paris", "Central Europe Standard Time": "Europe/Budapest",
          "Russian Standard Time": "Europe/Moscow", "Arabian Standard Time": "Asia/Dubai",
          "Eastern Standard Time": "America/New_York", "Central Standard Time": "America/Chicago",
          "Mountain Standard Time": "America/Denver", "Pacific Standard Time": "America/Los_Angeles",
          "UTC": "UTC", "Coordinated Universal Time": "UTC"}


def ics_time(value, params):
    """An iCalendar date or date-time -> (unix time, all day)."""
    v = value.strip()
    if re.fullmatch(r"\d{8}", v):           # a whole day: midnight where the reader is
        d = dt.datetime.strptime(v, "%Y%m%d")
        return int(d.timestamp()), True
    m = re.fullmatch(r"(\d{8}T\d{4})(\d{2})?(Z?)", v)
    if not m:
        return None, False
    d = dt.datetime.strptime(m.group(1) + (m.group(2) or "00"), "%Y%m%dT%H%M%S")
    if m.group(3):
        return int(d.replace(tzinfo=dt.timezone.utc).timestamp()), False
    tz = None
    name = (params.get("TZID") or "").strip('"')
    if name:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(WIN_TZ.get(name, name))
        except Exception:
            tz = None
    return int(d.replace(tzinfo=tz).timestamp() if tz else d.timestamp()), False


def ics_part(msg):
    """The mail's calendar part (an invitation), or None."""
    for p in msg.walk():
        if p.is_multipart():
            continue
        if p.get_content_type() == "text/calendar" or (R.fname(p) or "").lower().endswith(".ics"):
            return p
    return None


def invite_of(msg):
    """What a meeting invitation says: {"title", "start", "end", "all_day", "where", "organizer", "method"}, or None."""
    p = ics_part(msg)
    if p is None:
        return None
    try:
        text = R.part_bytes(p).decode("utf-8", "replace")
    except Exception:
        return None
    text = re.sub(r"\r?\n[ \t]", "", text)               # unfold
    method = (re.search(r"(?mi)^METHOD:(.*)$", text) or [None, ""])[1].strip().upper()
    ev = re.search(r"(?s)BEGIN:VEVENT(.*?)END:VEVENT", text)
    if not ev:
        return None
    props = {}
    for line in ev.group(1).splitlines():
        m = re.match(r"([A-Za-z-]+)((?:;[^:]*)?):(.*)", line)
        if not m or m.group(1).upper() in props:
            continue
        params = dict(re.findall(r';([A-Za-z-]+)=("[^"]*"|[^;]*)', m.group(2)))
        props[m.group(1).upper()] = (m.group(3), {k.upper(): v for k, v in params.items()})
    unesc = lambda v: re.sub(r"\\([,;\\])", r"\1", v.replace("\\n", "\n").replace("\\N", "\n")).strip()
    start, all_day = ics_time(*props["DTSTART"]) if "DTSTART" in props else (None, False)
    if start is None:
        return None
    end = ics_time(*props["DTEND"])[0] if "DTEND" in props else None
    org = props.get("ORGANIZER")
    organizer = ""
    if org:
        organizer = org[1].get("CN", "").strip('"') or re.sub(r"(?i)^mailto:", "", org[0])
    return {"title": unesc(props.get("SUMMARY", ("", {}))[0]), "start": start, "end": end, "all_day": all_day,
            "where": unesc(props.get("LOCATION", ("", {}))[0]), "organizer": organizer,
            "method": method, "cancelled": method == "CANCEL" or props.get("STATUS", ("", {}))[0].upper() == "CANCELLED"}

def data_images(html):
    """Pasted data: images in the editor -> (html with cid: links, [(cid, bytes, maintype, subtype)])."""
    found = []

    def one(mo):
        ctype, b64 = mo.group(2), mo.group(3)
        try:
            data = base64.b64decode(b64)
        except ValueError:
            return mo.group(0)
        cid = make_msgid(domain="ragdoll")[1:-1]
        found.append((cid, data, *ctype.split("/", 1)))
        return '%ssrc="cid:%s"' % (mo.group(1), cid)
    html = re.sub(r'(?i)(<img\b[^>]*?)src="data:(image/[\w.+-]+);base64,([A-Za-z0-9+/=\s]+)"', one, html or "")
    return html, found


# ------------------------------------------------------------------ demo mailbox

def png_bytes(rows, w, h):
    """A PNG from its rows of RGB bytes."""
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(b"\x00" + bytes(r) for r in rows), 9)) + chunk(b"IEND", b""))


def demo_png(rgb, w=240, h=120):
    return png_bytes([bytes(rgb) * w] * h, w, h)


def demo_photo(w=720, h=450):
    """The picture in the demo mailbox: two switch cabinets in front of a wall. Drawn here, so the
    demo needs no picture file."""
    floor = h * 3 // 4
    rows = []
    for y in range(h):
        if y < floor:
            k = y / floor
            c = (226 - 22 * k, 229 - 21 * k, 231 - 20 * k)
        else:
            k = (y - floor) / (h - floor)
            c = (150 - 30 * k, 151 - 30 * k, 149 - 30 * k)
        rows.append(bytearray(bytes(int(v) for v in c) * w))

    def box(x0, y0, x1, y1, rgb):
        px = bytes(rgb) * (x1 - x0)
        for y in range(y0, y1):
            rows[y][x0 * 3:x1 * 3] = px

    top, foot = h * 14 // 100, floor + h * 6 // 100
    cw, gap = w * 30 // 100, w * 5 // 100
    left = (w - cw * 2 - gap) // 2
    for k, base in enumerate(((104, 126, 136), (113, 135, 145))):
        x0, x1 = left + k * (cw + gap), left + k * (cw + gap) + cw
        dark, light = tuple(v - 26 for v in base), tuple(v + 22 for v in base)
        box(x0 + 8, foot, x1 + 14, foot + 9, (104, 105, 103))                   # its shadow on the floor
        box(x0, top, x1, foot, base)
        box(x0, top, x1, top + 16, dark)                                        # the top rail
        box(x0, foot - 14, x1, foot, dark)                                      # the plinth
        box(x0, top, x0 + 3, foot, light)                                       # light from the left
        mid = (x0 + x1) // 2
        box(mid - 1, top + 16, mid + 1, foot - 14, dark)                        # the gap between the two doors
        box(mid + 10, top + 150, mid + 15, top + 196, (52, 60, 66))             # the handle
        box(x0 + 22, top + 34, x0 + 96, top + 58, (232, 235, 236))              # the name plate
        box(x0 + 28, top + 43, x0 + 78, top + 46, (150, 158, 163))
        for j, lamp in enumerate(((74, 176, 112), (226, 172, 64))):
            box(mid + 30 + j * 24, top + 38, mid + 44 + j * 24, top + 52, lamp)
        for j in range(6):                                                      # the vent slots
            box(x0 + 24, foot - 86 + j * 10, mid - 22, foot - 82 + j * 10, dark)
    return png_bytes(rows, w, h)


def demo_size(name, low, high):
    """A size in bytes for a demo file, the same each time for one name."""
    return (low + sum(name.encode("utf-8")) * 37 % (high - low)) * 1024


def demo_pdf(title, size=0):
    text = "BT /F1 18 Tf 72 720 Td (%s) Tj ET" % title.replace("(", "").replace(")", "")
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            "<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text),
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    if size:                # a comment line, so the file has the size of a real one
        out += "%" + " " * max(0, size - 700) + "\n"
    for k, o in enumerate(objs, 1):
        offs.append(len(out))
        out += "%d 0 obj\n%s\nendobj\n" % (k, o)
    xref = len(out)
    out += "xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + "".join("%010d 00000 n \n" % x for x in offs)
    out += "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out.encode()


ME = ("Alex Morgan", "you@example.com")
DEMO_FLAGGED = ("Quote for PO-1234", "PO-1234 报价")
DEMO_INLINE = ("Re: Site visit photos", "回复：现场照片")     # mails with a photo in the text
DEMO_LISTS = ("noreply@github.com", "news@acme-industrial.com", "offers@example.net", "noreply@gitee.com",
              "news@acme-industrial.cn")                    # mailing lists: they carry List-Unsubscribe
DEMO = [
    # (folder, minutes ago, from, to, cc, subject, body, attachments, seen, thread key, reply-to key)
    ("inbox", 14, ("Jane Doe", "jane.doe@acme-industrial.com"), [ME], [("Tom Becker", "tom.becker@acme-industrial.com")],
     "Quote for PO-1234",
     "Hi Alex,\n\nThanks for the quick turnaround. I've attached the signed quote for PO-1234 and the updated "
     "delivery schedule.\n\nCould you confirm the ship date for the first batch? Our site team would like to plan "
     "the installation for the week of the 8th.\n\nBest regards,\nJane Doe\nProcurement Manager, Acme Industrial"
     "\n\nOn Monday, Alex Morgan <you@example.com> wrote:\n> Hi Jane,\n>\n> Please find our quote for PO-1234 "
     "attached. Lead time is 6 weeks from order.\n>\n> Best regards,\n> Alex",
     [("Quote_PO-1234_signed.pdf", "pdf"), ("Delivery_schedule.xlsx", "bin")], False, "po", "po1"),
    ("inbox", 52, ("Li Ming", "li.ming@example.cn"), [ME], [],
     "Beijing ABC project: drawings to confirm",
     "Hi Alex,\n\nAttached are the latest drawings for the Beijing ABC project. Please confirm the dimensions and "
     "the wiring by Friday, and call me if anything is unclear.\n\nThanks,\nLi Ming",
     [("ABC_assembly_drawing_rev3.pdf", "pdf")], False, None, None),
    ("inbox", 130, ("GitHub", "noreply@github.com"), [ME], [],
     "[ragdoll-mail] Release v0.5.0 published",
     "A new release is out.\n\nragdoll-mail v0.5.0: the desktop app.\n\nView it on GitHub: "
     "https://github.com/", [], True, None, None),
    ("inbox", 60 * 5, ("Sara Kim", "sara.kim@northwind.io"), [ME], [],
     "Lunch on Thursday?",
     "Hey Alex,\n\nAre you around on Thursday? There's a new ramen place near the office I've been meaning to try.\n\n"
     "Sara", [], False, "lunch", None),
    ("inbox", 60 * 9, ("Daniel Ruiz", "d.ruiz@contoso.com"), [ME], [],
     "Re: Site visit photos",
     "Photos from yesterday's visit are below. The cabinet on the left needs a new door seal.\n\nDaniel",
     [], True, None, None),
    ("inbox", 60 * 26, ("Northwind Billing", "billing@northwind.io"), [ME], [],
     "Your invoice INV-0006 is ready",
     "Hello,\n\nYour invoice INV-0006 for November is attached. The amount will be charged on the 30th.\n\n"
     "Northwind Billing", [("INV-0006.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 30, ("Tom Becker", "tom.becker@acme-industrial.com"), [ME], [],
     "Packing list for the November shipment",
     "Hi Alex,\n\nPlease find the packing list attached. Gross weight is 1,240 kg across 3 crates.\n\nTom",
     [("Packing_list_Nov.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 50, ("Priya Natarajan", "priya@fabrikam.com"), [ME], [("Jane Doe", "jane.doe@acme-industrial.com")],
     "Meeting notes — Q4 planning",
     "Hi all,\n\nNotes from today:\n\n1. Q4 targets confirmed.\n2. New supplier onboarding starts in December.\n"
     "3. Next review on the 2nd.\n\nPriya", [], True, None, None),
    ("inbox", 60 * 75, ("Sara Kim", "sara.kim@northwind.io"), [ME], [],
     "Slides for Friday",
     "Here are the slides for Friday's review. Feedback welcome before Thursday noon.",
     [("Friday_review.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 100, ("Hannah Weber", "h.weber@example.de"), [ME], [],
     "Certificate of origin",
     "Dear Alex,\n\nCould you send the certificate of origin for order 4471? Customs is asking for it.\n\n"
     "Kind regards,\nHannah Weber", [], True, None, None),
    ("inbox", 60 * 140, ("Emily Wang", "emily.wang@example.com"), [ME], [],
     "Product training next Wednesday",
     "Hi all,\n\nThe product training is next Wednesday at 2 pm in the meeting room on the third floor. "
     "Please be on time.\n\nEmily", [("invite.ics", "ics")], True, None, None),
    ("inbox", 60 * 200, ("Marco Rossi", "marco.rossi@example.it"), [ME], [],
     "Spare parts list",
     "Ciao Alex,\n\nAttached is the list of spare parts we need for next year.\n\nMarco",
     [("spare_parts_2027.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 260, ("Jane Doe", "jane.doe@acme-industrial.com"), [ME], [],
     "Welcome to the Acme supplier portal",
     "Hi Alex,\n\nYour supplier portal account is ready. You can upload invoices and certificates there.\n\nJane",
     [], True, None, None),
    ("sent", 60 * 28, ME, [("Jane Doe", "jane.doe@acme-industrial.com")], [],
     "Quote for PO-1234",
     "Hi Jane,\n\nPlease find our quote for PO-1234 attached. Lead time is 6 weeks from order.\n\n"
     "Best regards,\nAlex", [("Quote_PO-1234.pdf", "pdf")], True, "po", "po0"),
    ("sent", 60 * 4, ME, [("Sara Kim", "sara.kim@northwind.io")], [],
     "Re: Lunch on Thursday?", "Sounds great, 12:30 works for me.\n\nAlex", [], True, "lunch", None),
    ("sent", 60 * 98, ME, [("Hannah Weber", "h.weber@example.de")], [],
     "Re: Certificate of origin", "Dear Hannah,\n\nThe certificate is attached.\n\nBest regards,\nAlex",
     [("CO_order_4471.pdf", "pdf")], True, None, None),
    ("drafts", 40, ME, [("Li Ming", "li.ming@example.cn")], [],
     "Re: Beijing ABC project: drawings to confirm",
     "Hi Li Ming,\n\nThanks for the drawings. The dimensions are fine. We will confirm the wiring tomorrow.\n\nAlex",
     [], True, None, None),
    ("archive", 60 * 24 * 12, ("Acme Industrial", "news@acme-industrial.com"), [ME], [],
     "Acme Industrial newsletter — October", "Our October news: new plant, new products, and a new website.",
     [], True, None, None),
    ("archive", 60 * 24 * 20, ("Tom Becker", "tom.becker@acme-industrial.com"), [ME], [],
     "Shipping marks", "Hi Alex, please use the attached shipping marks on every crate.\n\nTom",
     [("shipping_marks.pdf", "pdf")], True, None, None),
    ("trash", 60 * 24 * 3, ("Deals Daily", "offers@example.net"), [ME], [],
     "50% off everything this weekend", "Don't miss out!", [], True, None, None),
    ("junk", 60 * 5, ("Prize Centre", "winner@example.net"), [ME], [],
     "You have won a gift card", "Click the link to claim your prize today.", [], False, None, None),
    ("junk", 60 * 30, ("SEO Experts", "hello@example.org"), [ME], [],
     "Get your website to page one", "We can bring you 10,000 visitors a month.", [], True, None, None),
    ("Projects", 60 * 24 * 6, ("Maria Santos", "maria.santos@example.com.br"), [ME], [],
     "Project list for next year", "Hi Alex,\n\nThe list of next year's projects is attached.\n\nMaria",
     [("projects_2027.pdf", "pdf")], True, None, None),
    ("Projects/Acme", 60 * 24 * 8, ("Tom Becker", "tom.becker@acme-industrial.com"), [ME], [],
     "Acme plant 2: kick-off notes", "Hi Alex, the notes from the kick-off meeting are below.\n\nTom",
     [], True, None, None),
    ("Projects/Acme", 60 * 24 * 9, ("Tom Becker", "tom.becker@acme-industrial.com"), [ME], [],
     "Acme plant 2: site layout", "Hi Alex, here is the site layout.\n\nTom",
     [("site_layout.pdf", "pdf")], False, None, None),
]
DEMO_FOLDERS = [("Projects", ""), ("Projects/Acme", "")]

# The same mailbox in Chinese, for a Chinese screen: no English mail in it, as a Chinese user's box would be
ME_ZH = ("林晓", "you@example.com")
ZW = ("张伟", "zhang.wei@acme-industrial.cn")
ZL = ("赵磊", "zhao.lei@acme-industrial.cn")
SJ = ("孙佳", "sun.jia@northwind.cn")
WJ = ("吴静", "wu.jing@example.com")
LM = ("李明", "li.ming@example.cn")
DEMO_ZH = [
    ("inbox", 14, ZW, [ME_ZH], [ZL],
     "PO-1234 报价",
     "林工你好，\n\n谢谢你们这么快回复。签好字的 PO-1234 报价单和更新后的交货计划都在附件里。\n\n"
     "麻烦确认一下第一批的发货日期，我们现场想把安装排在 8 号那一周。\n\n祝好\n张伟\n采购经理，艾克美工业"
     "\n\n周一，林晓 <you@example.com> 写道：\n> 张经理你好，\n>\n> 附件是 PO-1234 的报价，交期为下单后 6 周。"
     "\n>\n> 祝好\n> 林晓",
     [("PO-1234_报价单_已签字.pdf", "pdf"), ("交货计划.xlsx", "bin")], False, "po", "po1"),
    ("inbox", 52, LM, [ME_ZH], [],
     "北京ABC项目 — 图纸确认",
     "林工你好，\n\n附件是北京ABC项目的最新图纸，请在周五前确认尺寸和接线方式。如有问题请随时联系我。\n\n谢谢！\n李明",
     [("ABC项目_总装图_rev3.pdf", "pdf")], False, None, None),
    ("inbox", 130, ("Gitee", "noreply@gitee.com"), [ME_ZH], [],
     "[ragdoll-mail] 新版本 v0.5.0 已发布",
     "新版本已发布。\n\nragdoll-mail v0.5.0：桌面版。\n\n在 Gitee 上查看：https://gitee.com/", [], True, None, None),
    ("inbox", 60 * 5, SJ, [ME_ZH], [],
     "周四一起吃午饭？",
     "林晓，\n\n周四有空吗？公司附近新开了一家拉面店，一直想去试试。\n\n孙佳", [], False, "lunch", None),
    ("inbox", 60 * 9, ("刘洋", "liu.yang@contoso.cn"), [ME_ZH], [],
     "回复：现场照片",
     "昨天现场的照片在下面。左边那台柜子的门密封条要换新的。\n\n刘洋", [], True, None, None),
    ("inbox", 60 * 26, ("北风云", "billing@northwind.cn"), [ME_ZH], [],
     "11 月账单 INV-0006 已出",
     "你好，\n\n你 11 月的账单 INV-0006 在附件里，将于 30 号扣款。\n\n北风云", [("INV-0006.pdf", "pdf")],
     True, None, None),
    ("inbox", 60 * 30, ZL, [ME_ZH], [],
     "11 月发货的装箱单",
     "林工，\n\n装箱单在附件里。一共 3 箱，毛重 1,240 公斤。\n\n赵磊", [("装箱单_11月.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 50, ("周敏", "zhou.min@fabrikam.cn"), [ME_ZH], [ZW],
     "会议纪要 — 第四季度计划",
     "各位好，\n\n今天的纪要：\n\n1. 第四季度目标已确认。\n2. 新供应商 12 月开始接入。\n3. 下次评审在 2 号。\n\n周敏",
     [], True, None, None),
    ("inbox", 60 * 75, SJ, [ME_ZH], [],
     "周五评审的幻灯片",
     "周五评审用的幻灯片在附件里，周四中午前有意见请告诉我。", [("周五评审.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 100, WJ, [ME_ZH], [],
     "原产地证",
     "林工你好，\n\n订单 4471 的原产地证能发我一份吗？海关在要。\n\n谢谢\n吴静", [], True, None, None),
    ("inbox", 60 * 140, ("王芳", "wang.fang@example.cn"), [ME_ZH], [],
     "下周培训安排",
     "各位好，\n\n下周三下午两点在三楼会议室进行产品培训，请准时参加。\n\n王芳", [("invite.ics", "ics")], True, None, None),
    ("inbox", 60 * 200, ("陈刚", "chen.gang@example.com"), [ME_ZH], [],
     "备件清单",
     "林工，\n\n附件是明年需要的备件清单。\n\n陈刚", [("备件清单_2027.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 260, ZW, [ME_ZH], [],
     "欢迎使用艾克美供应商平台",
     "林工，\n\n你的供应商平台账号已经开好了，发票和证书都可以在上面上传。\n\n张伟", [], True, None, None),
    ("sent", 60 * 28, ME_ZH, [ZW], [],
     "PO-1234 报价",
     "张经理你好，\n\n附件是 PO-1234 的报价，交期为下单后 6 周。\n\n祝好\n林晓", [("PO-1234_报价单.pdf", "pdf")],
     True, "po", "po0"),
    ("sent", 60 * 4, ME_ZH, [SJ], [],
     "回复：周四一起吃午饭？", "好呀，12:30 可以。\n\n林晓", [], True, "lunch", None),
    ("sent", 60 * 98, ME_ZH, [WJ], [],
     "回复：原产地证", "吴静你好，\n\n原产地证在附件里。\n\n祝好\n林晓", [("原产地证_订单4471.pdf", "pdf")], True, None, None),
    ("drafts", 40, ME_ZH, [LM], [],
     "回复：北京ABC项目 — 图纸确认", "李明你好，\n\n图纸已收到，尺寸没有问题。接线方式我们明天确认后回复。\n\n林晓",
     [], True, None, None),
    ("archive", 60 * 24 * 12, ("艾克美工业", "news@acme-industrial.cn"), [ME_ZH], [],
     "艾克美工业 10 月简讯", "10 月动态：新工厂、新产品，还有新网站。", [], True, None, None),
    ("archive", 60 * 24 * 20, ZL, [ME_ZH], [],
     "唛头", "林工，每个箱子上都请贴附件里的唛头。\n\n赵磊", [("唛头.pdf", "pdf")], True, None, None),
    ("trash", 60 * 24 * 3, ("每日优惠", "offers@example.net"), [ME_ZH], [],
     "本周末全场五折", "千万别错过！", [], True, None, None),
    ("junk", 60 * 5, ("中奖中心", "winner@example.net"), [ME_ZH], [],
     "恭喜你获得一张购物卡", "点击链接，今天就能领取。", [], False, None, None),
    ("junk", 60 * 30, ("网站优化专家", "hello@example.org"), [ME_ZH], [],
     "让你的网站排到第一页", "每月给你带来一万访客。", [], True, None, None),
    ("项目", 60 * 24 * 6, ("马丽", "ma.li@example.com"), [ME_ZH], [],
     "明年的项目清单", "林工，\n\n明年的项目清单在附件里。\n\n马丽", [("项目清单_2027.pdf", "pdf")], True, None, None),
    ("项目/艾克美", 60 * 24 * 8, ZL, [ME_ZH], [],
     "艾克美二厂：启动会纪要", "林工，启动会的纪要在下面。\n\n赵磊", [], True, None, None),
    ("项目/艾克美", 60 * 24 * 9, ZL, [ME_ZH], [],
     "艾克美二厂：现场布置图", "林工，这是现场布置图。\n\n赵磊", [("现场布置图.pdf", "pdf")], False, None, None),
]
DEMO_SETS = {
    "en": {"me": ME, "mail": DEMO, "folders": DEMO_FOLDERS,
           "signature": "Alex Morgan<br>Sales Engineer · Example Co.<br>+1 555 0100",
           "event": ("Product training", "Meeting room, 3rd floor", "Emily Wang", "emily.wang@example.com")},
    "zh": {"me": ME_ZH, "mail": DEMO_ZH, "folders": [("项目", ""), ("项目/艾克美", "")],
           "signature": "林晓<br>销售工程师 · 示例科技<br>021 5555 0100",
           "event": ("产品培训", "三楼会议室", "王芳", "wang.fang@example.cn")},
}


def demo_lang(want=None):
    """The demo mailbox's language: the one asked for, else Chinese on a Chinese system, else English."""
    if want in DEMO_SETS:
        return want
    names = [os.environ.get(k, "") for k in ("LC_ALL", "LC_MESSAGES", "LANG")]
    if sys.platform == "darwin":
        with contextlib.suppress(Exception):
            names.append(subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True,
                                        text=True, timeout=2).stdout)
    elif os.name == "nt":
        with contextlib.suppress(Exception):
            import ctypes
            names.append(locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), ""))
    first = next((n for n in names if n.strip()), "")
    return "zh" if re.search(r"\bzh", first.replace('"', " ").replace("(", " ")) else "en"


def demo_ics(name, ts, event=DEMO_SETS["en"]["event"]):
    """An invitation for a Wednesday at 14:00 local time still to come, as the mail promises."""
    d = dt.datetime.now() + dt.timedelta(days=1)
    d = (d + dt.timedelta(days=(2 - d.weekday()) % 7 or 7)).replace(hour=14, minute=0, second=0, microsecond=0)
    u = d.astimezone(dt.timezone.utc)
    f = "%Y%m%dT%H%M%SZ"
    title, place, who, addr = event
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Ragdoll Mail demo//EN\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\n"
            "UID:training@demo\r\nDTSTAMP:%s\r\nDTSTART:%s\r\nDTEND:%s\r\nSUMMARY:%s\r\n"
            "LOCATION:%s\r\nORGANIZER;CN=%s:mailto:%s\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
            % (u.strftime(f), u.strftime(f), (u + dt.timedelta(hours=1)).strftime(f), title, place, who, addr))


def demo_message(folder, ts, frm, to, cc, subject, body, atts, mid, irt, refs, inline=False,
                 event=DEMO_SETS["en"]["event"]):
    msg = EmailMessage()
    msg["From"] = formataddr(frm)
    msg["To"] = ", ".join(formataddr(x) for x in to)
    if cc:
        msg["Cc"] = ", ".join(formataddr(x) for x in cc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(ts, localtime=True)
    msg["Message-ID"] = mid
    if irt:
        msg["In-Reply-To"] = irt
        msg["References"] = refs
    if frm[1] in DEMO_LISTS:
        msg["List-Unsubscribe"] = "<https://example.com/unsubscribe/demo>, <mailto:unsubscribe@example.com?subject=unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(body)
    html = R.text_to_html(body)
    if inline:
        html += '<div><br></div><div><img src="cid:photo1@demo" width="480" height="300" alt="site photo"></div>'
    # Chinese mail from Windows names 宋体, as real mail from China often does
    font = "宋体,SimSun" if re.search(r"[\u4e00-\u9fff]", body) else "Helvetica,Arial,sans-serif"
    msg.add_alternative('<div style="font-family:%s;font-size:14px">%s</div>' % (font, html), subtype="html")
    if inline:
        msg.get_body(("html",)).add_related(demo_photo(), "image", "png", cid="<photo1@demo>")
    for name, kind in atts:
        if kind == "ics":
            msg.add_attachment(demo_ics(name, ts, event), subtype="calendar", filename=name, params={"method": "REQUEST"})
        elif kind == "pdf":
            msg.add_attachment(demo_pdf(name, demo_size(name, 90, 460)), "application", "pdf", filename=name)
        else:
            msg.add_attachment(b"PK\x03\x04 demo".ljust(demo_size(name, 24, 60), b"\x00"), "application",
                               "octet-stream", filename=name)
    return msg.as_bytes(policy=R.OUT_POLICY)


# ------------------------------------------------------------------ backend

class Backend:
    def __init__(self, demo=False, demo_lang="en"):
        self.demo = demo
        self.demo_set = DEMO_SETS[demo_lang if demo_lang in DEMO_SETS else "en"]
        self.lock = threading.RLock()           # the action IMAP connection
        self.dlock = threading.RLock()          # the download connection: big mails and files (#55)
        self.dm = None
        self.dm_used = 0
        self.dblock = threading.RLock()         # the request db connection
        self.m = None
        self.m_used = 0
        self.rev = 1
        self.sync = {"running": False, "error": None, "last": None}
        self.sync_m = None                      # the sync's own connection
        self.pre_m = None                       # the head start's own connection
        self.pass_at = None                     # when the sync pass under way began (time.monotonic)
        self.pass_cut = False                   # the watchdog has cut that pass's connection
        self.sync_used = self.pre_used = 0      # when those connections last answered
        self.clock = None                       # (time.time(), time.monotonic()) at the watchdog's last look
        self.woke_at = None                     # when the computer last woke from sleep
        self.body_m = None                      # the body download's own connection (#57)
        self.body_used = 0
        self.body_thread = None
        self.body_wake = threading.Event()
        self.bodies = None                      # {"done": n, "left": n} while mail text is downloading
        self.active_at = 0                      # when the user last did something that is not a poll
        self.watch_thread = None
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.contacts = (0, {})
        self.update = None
        self.server_folders = None
        self.found = list(self.demo_set["folders"]) if demo else []     # [(folder on the server, its flags)]
        self.extra_at = 0                       # when Junk and the other folders were last synced
        self.extra_now = False
        self.folder_status = {}                 # folder -> its STATUS when it was last synced (#39)
        self.news = []                          # new mail the page has yet to hear about
        self.news_n = 0
        self.asks = []                          # hand-offs from ragdoll (open this mail, a draft is ready)
        self.asks_n = 0
        self.news_mark = None
        self.moved_in = {}                      # message-id -> when the app itself put it in the inbox
        self.focus_at = 0                       # when the page last said its window is in front
        self.web_notice_at = 0                  # when a page that shows the browser's own notices last asked
        self.made = set()                       # files the app wrote (only these may be revealed)
        self.demo_raw = {}
        self.thread = None
        self.schedlock = threading.RLock()      # the scheduled-send list (scheduled.json)
        self.data_v = None                      # the index as last seen: changes when the sync or the CLI writes
        self.counts = None                      # (what they were counted from, the folder counts)
        self.pre = collections.deque()          # mail to bring in before it is opened: (folder, uidv, uid, size)
        self.pre_wake = threading.Event()
        self.pre_thread = None
        self.pre_now = None         # the mail the head start is fetching right now
        self.fg = 0                 # mails being fetched because somebody opened them
        self.built = collections.OrderedDict()  # id -> the opened mail as the page gets it
        self.sched_wake = threading.Event()
        self.flag_q = queue.Queue()             # flag changes for the server, in the order they were made
        self.flag_thread = None
        self.marks = {}                         # (folder, uid, column) -> [value, how many on their way, when the last arrived]
        self.marklock = threading.Lock()
        self.badge_n = None                     # the unread count the Dock icon shows
        if demo:
            self.make_demo()                    # opens self.c on the demo's own index
        else:
            self.c = R.db()
        self.data_v = self.c.execute("pragma data_version").fetchone()[0]
        if not demo:
            with contextlib.suppress(Exception):
                r = self.q("select v from meta where k='folders'")
                self.found = [tuple(x) for x in json.loads(r[0]["v"])] if r else []
            self.prune_cache()
            threading.Thread(target=self.check_update, daemon=True).start()
            self.start_sync()
        threading.Thread(target=self.sched_loop, daemon=True).start()
        if not demo:
            threading.Thread(target=self.asks_loop, daemon=True).start()

    # ---- plumbing

    def call(self, name, args):
        fn = getattr(self, "api_" + name, None)
        if fn is None:
            return 404, {"ok": False, "error": "unknown call %s" % name}
        if args is not None and not isinstance(args, dict):
            return 400, {"ok": False, "error": "bad request"}
        if name not in self.PASSIVE:
            self.active_at = time.time()        # the body download makes way (#57)
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

    # calls the page makes by itself, not because the user did something
    PASSIVE = frozenset(("status", "list", "boot", "prefs", "notice_state", "cli_state", "window_theme",
                         "settings", "senders", "contacts"))

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
                        # after sleep or a network change the old connection is dead and a NOOP on it
                        # would wait out the whole 90 s timeout: ask briefly, else reconnect
                        with contextlib.suppress(Exception):
                            self.m.sock.settimeout(6)
                        self.m.noop()
                        with contextlib.suppress(Exception):
                            self.m.sock.settimeout(90)
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
                m.sock.settimeout(3)            # a dead connection would keep LOGOUT waiting its whole timeout
            with contextlib.suppress(Exception):
                m.logout()

    DOWNLOAD_IDLE = 120     # seconds the download connection stays open with nothing to fetch

    def download(self, fn):
        """Run fn(m) on a second kept connection, for a big mail or file. That may take minutes, and
        opening other mail, marks and moves go on meanwhile on the first one (#55)."""
        if self.demo:
            fail("not in the demo")
        with self.dlock:
            for attempt in (0, 1):
                try:
                    if self.dm is not None and not still_there(self.dm, self.dm_used, 90):
                        self.drop_download()
                    if self.dm is None:
                        self.dm = R.imap()
                        with contextlib.suppress(Exception):
                            self.dm.sock.settimeout(90)
                    r = fn(self.dm)
                    self.dm_used = time.time()
                    return r
                except (imaplib.IMAP4.abort, ssl.SSLError, ConnectionError, socket.timeout, BrokenPipeError):
                    self.drop_download()
                    if attempt:
                        raise

    def drop_download(self):
        m, self.dm = self.dm, None
        R.quit_imap(m, quick=True)

    def bump(self):
        self.rev += 1

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
        return R.cache_path(r["folder"], r["uidv"], r["uid"])

    def raw(self, i):
        folder, uid = self.parse(i)
        if self.demo:
            if (folder, uid) not in self.demo_raw:
                fail("This mail is no longer here.")
            return self.demo_raw[(folder, uid)]
        r = self.row(i)
        path = self.cache_path(r)
        raw = R.cache_get(path)
        if raw:
            return raw
        k = (r["folder"], r["uidv"], r["uid"])
        self.fg += 1                            # the mail somebody is waiting for goes first
        try:
            end = time.time() + 30
            while self.pre_now == k and time.time() < end:      # already on its way: do not fetch it twice
                time.sleep(0.05)
            raw = R.cache_get(path)
            if not raw:
                # a big one may take minutes: on its own connection, so other mail opens meanwhile
                go = self.download if (r["size"] or 0) > R.LIGHT_MIN else self.imap
                raw = go(lambda m: R.fetch_raw(m, folder, uid))
                R.cache_put(path, raw)
        finally:
            self.fg -= 1
        return raw

    def view_raw(self, i):
        return self.view(i)[0]

    def view(self, i):
        """What showing the mail needs, and whether it is the light one: the whole mail, or for a big
        one the mail without its big files (R.fetch_light); those are fetched one by one when opened."""
        if self.demo:
            return self.raw(i), False
        r = self.row(i)
        if (r["size"] or 0) <= R.LIGHT_MIN or os.path.exists(self.cache_path(r)):
            return self.raw(i), False
        lp = R.light_path(r["folder"], r["uidv"], r["uid"])
        raw = R.cache_get(lp)
        if raw:
            return raw, True
        k = (r["folder"], r["uidv"], r["uid"])
        light = False
        self.fg += 1
        try:
            end = time.time() + 30
            while self.pre_now == k and time.time() < end:
                time.sleep(0.05)
            raw = R.cache_get(lp)
            light = bool(raw)
            raw = raw or R.cache_get(self.cache_path(r))
            if not raw:
                raw = self.imap(lambda m: R.fetch_light(m, r["folder"], r["uid"]))
                if raw:
                    light = True
                    R.cache_put(lp, raw)
        finally:
            self.fg -= 1
        return (raw, light) if raw else (self.raw(i), False)

    # ---- mail brought in ahead of time, so opening it does not wait for the server

    PRE_MAX = 3 * 1024 * 1024       # a bigger mail is fetched when it is opened

    def prefetch(self, rows):
        if self.demo or not rows:
            return
        for r in reversed(rows):                # the first of them ends up first in line
            k = (r["folder"], r["uidv"], r["uid"])
            item = k + (r["size"] or 0,)            # a big one is brought in light (R.fetch_light)
            if item not in self.pre and not os.path.exists(R.cache_path(*k)) and not os.path.exists(R.light_path(*k)):
                self.pre.appendleft(item)
        while len(self.pre) > 150:
            self.pre.pop()
        if self.pre_thread is None or not self.pre_thread.is_alive():
            self.pre_thread = threading.Thread(target=self.prefetch_loop, daemon=True)
            self.pre_thread.start()
        self.pre_wake.set()

    def prefetch_loop(self):
        while not self.stopping.is_set():
            try:
                k = self.pre.popleft()
            except IndexError:
                self.pre_wake.clear()
                if not self.pre_wake.wait(90) and self.pre_m is not None:    # idle: let the connection go
                    m, self.pre_m = self.pre_m, None
                    R.quit_imap(m, quick=True)
                continue
            k, size = k[:3], k[3]
            path = R.cache_path(*k)
            if os.path.exists(path) or os.path.exists(R.light_path(*k)):
                continue
            while self.fg > 0 and not self.stopping.is_set():   # a mail is being opened: stay out of its way
                time.sleep(0.1)
            try:
                if self.pre_m is not None and not still_there(self.pre_m, self.pre_used, 60):
                    m, self.pre_m = self.pre_m, None
                    R.quit_imap(m, quick=True)
                if self.pre_m is None:
                    self.pre_m = R.imap()
                    with contextlib.suppress(Exception):
                        self.pre_m.sock.settimeout(60)
                m = self.pre_m
                self.pre_now = k
                raw = R.fetch_light(m, k[0], k[2]) if size > R.LIGHT_MIN else None
                if raw:
                    R.cache_put(R.light_path(*k), raw)
                elif size <= self.PRE_MAX:
                    R.cache_put(path, R.fetch_raw(m, k[0], k[2]))
                self.pre_used = time.time()
            except SystemExit:
                pass                            # moved or deleted since
            except Exception:                   # noqa: BLE001 - only a head start; opening the mail fetches it
                self.pre_now = None
                m, self.pre_m = self.pre_m, None
                R.quit_imap(m, quick=True)
                self.pre.clear()
                time.sleep(5)
            finally:
                self.pre_now = None
        m, self.pre_m = self.pre_m, None
        R.quit_imap(m, quick=True)

    def prune_cache(self, days=90):
        root = os.path.join(R.CFG.home, "cache")
        cut = time.time() - days * 86400
        for d, _, files in os.walk(root):
            gone = set()
            for n in files:
                p = os.path.join(d, n)
                with contextlib.suppress(OSError):
                    if os.path.getatime(p) < cut:
                        os.remove(p)
                        gone.add(n)
            for n in files:         # a file fetched by itself (R.part_path) goes when its light mail goes
                if ".part" in n and n not in gone and not os.path.exists(
                        os.path.join(d, n.split(".part")[0] + ".light.eml")):
                    with contextlib.suppress(OSError):
                        os.remove(os.path.join(d, n))

    # ---- sync

    def sync_folders(self):
        fs = list(R.CFG.sync_folders)
        for k in ("archive", "trash"):
            f = R.CFG.folders.get(k)
            if f and f not in fs:
                fs.append(f)
        return fs

    def others(self):
        """[(folder, label, depth)]: the server's own folders besides the standard ones."""
        return folder_tree(self.found, set(R.CFG.folders.values()))

    def extra_folders(self):
        """Junk and the other folders: shown in the app, synced less often than the rest."""
        have = set(self.sync_folders())
        j = R.CFG.folders.get("junk")
        return [f for f in ([j] if j else []) + [n for n, _, _ in self.others()] if f not in have]

    def note_folders(self, m, c):
        found = list_folders(m)
        self.server_folders = [n for n, _ in found]
        if found != self.found:
            self.found = found
            c.execute("insert or replace into meta values('folders', ?)", (json.dumps(found),))
            c.commit()
            self.bump()
        if drop_gone_folders(c, self.server_folders):
            self.bump()

    def note_new(self, c):
        """Unread inbox mail that came in since the last pass becomes news. The first pass only sets the mark."""
        inbox = R.CFG.folders.get("inbox") or "INBOX"
        top = c.execute("select coalesce(max(id),0) from msgs where folder=?", (inbox,)).fetchone()[0]
        mark, self.news_mark = self.news_mark, top
        now = time.time()
        self.moved_in = {k: v for k, v in self.moved_in.items() if now - v < 900}
        if mark is None or top <= mark:
            return
        rows = [r for r in c.execute("select * from msgs where folder=? and id>? and seen=0 and ts>? order by id",
                                     (inbox, mark, now - 86400)).fetchall() if r["msgid"] not in self.moved_in]
        if not rows:
            return
        fresh = []
        for r in rows:
            self.news_n += 1
            j = self.row_json(r)
            fresh.append({"n": self.news_n, "at": int(now), "id": j["id"], "from": j["from"], "subject": j["subject"]})
        self.news = (self.news + fresh)[-20:]
        self.bump()
        if (not self.demo and self.prefs().get("notify", True) and now - self.focus_at > 12
                and now - self.web_notice_at > 150):        # an open page shows its own notice
            who = []
            for x in fresh:
                n = x["from"]["name"] or x["from"]["addr"]
                if n not in who:
                    who.append(n)
            title = ", ".join(who[:3]) + (" +%d" % (len(who) - 3) if len(who) > 3 else "")
            body = " · ".join(x["subject"] or "" for x in fresh[:3])
            threading.Thread(target=system_notice, args=(title, body[:200]), daemon=True).start()

    def start_sync(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.sync_loop, daemon=True)
            self.thread.start()
        if self.watch_thread is None or not self.watch_thread.is_alive():
            self.watch_thread = threading.Thread(target=self.watch_loop, daemon=True)
            self.watch_thread.start()
        self.wake.set()

    # ---- the watchdog: a pass that hangs is cut off, so the sync never waits for good (#40)

    SYNC_STUCK = 300    # seconds a sync pass may take before its connection is cut and made again
    WATCH_EVERY = 2     # seconds between the watchdog's looks
    WAKE_GAP = 20       # seconds the clock may jump between two looks before it counts as a wake from sleep

    def watch_loop(self):
        while not self.stopping.wait(self.WATCH_EVERY):
            try:
                self.watch_tick()
            except Exception:           # noqa: BLE001 - the watchdog must live on
                traceback.print_exc(file=sys.stderr)

    def watch_tick(self, mono=None, wall=None):
        mono = time.monotonic() if mono is None else mono
        wall = time.time() if wall is None else wall
        last, self.clock = self.clock, (wall, mono)
        if last is not None:
            # macOS stops the monotonic clock in sleep, so the wall clock runs ahead of it; Windows
            # keeps both running, so only the long gap between two looks shows it
            dw, dm = wall - last[0], mono - last[1]
            if dw - dm > self.WAKE_GAP or dm > self.WATCH_EVERY + self.WAKE_GAP:
                self.woke()
        if self.pass_at is not None and not self.pass_cut and mono - self.pass_at > self.SYNC_STUCK:
            # a read that waits on a connection that died while it waited: end it, so the pass
            # connects again (or fails and says so) instead of hanging for good
            self.pass_cut = True
            print("a sync pass took over %d s: its connection was cut" % self.SYNC_STUCK, file=sys.stderr)
            cut(self.sync_m)
        if self.dm is not None and time.time() - self.dm_used > self.DOWNLOAD_IDLE and self.dlock.acquire(blocking=False):
            try:
                self.drop_download()            # nothing to download for a while: let it go
            finally:
                self.dlock.release()

    def woke(self):
        """The computer woke (or the app was stopped a long while): every kept connection is dead.
        Cut them all, so nobody waits out a timeout on one, and look for new mail now (#56)."""
        self.woke_at = time.time()
        print("woke from sleep: connecting again", file=sys.stderr)
        for m in (self.m, self.dm, self.sync_m, self.pre_m, self.body_m):
            cut(m)
        self.wake.set()

    EXTRA_EVERY = 300   # seconds between full syncs of Junk and the owner's folders; in between, only changed ones

    def sync_pass(self, m, c):
        """One look at the server: the folder list, then the sync folders, then each of the owner's
        folders (and Junk) whose STATUS changed since it was last synced (#39), or all of them now and then."""
        self.note_folders(m, c)
        todo = self.sync_folders()
        extras = self.extra_folders()
        if self.server_folders:
            extras = [f for f in extras if f in self.server_folders]
        full = self.extra_now or time.time() - self.extra_at > self.EXTRA_EVERY
        self.extra_now = False
        now = {}
        for f in extras:
            now[f] = folder_status(m, f)
            if full or now[f] is None or now[f] != self.folder_status.get(f):
                todo.append(f)
        for f in todo:
            try:
                R.sync_headers(m, c, f, held=self.held)
            except LookupError:
                if f in self.sync_folders():
                    raise
                continue        # one of the owner's folders, renamed or deleted a moment ago
            if f in now:
                self.folder_status[f] = now[f]
            if f == (R.CFG.folders.get("inbox") or "INBOX"):
                self.note_new(c)
        if full:
            self.extra_at = time.time()

    def sync_loop(self):
        c = None
        while not self.stopping.is_set():
            self.wake.wait(60)
            self.wake.clear()
            if self.stopping.is_set():
                break
            if not configured():
                continue
            self.sync["running"] = True
            self.pass_at, self.pass_cut = time.monotonic(), False
            try:
                c = c or R.db()
                with R.file_lock("headers", wait=False) as got:
                    if got:
                        for attempt in (0, 1):
                            try:
                                if self.sync_m is not None and not still_there(self.sync_m, self.sync_used, 120):
                                    m, self.sync_m = self.sync_m, None
                                    R.quit_imap(m, quick=True)
                                if self.sync_m is None:
                                    self.sync_m = R.imap()
                                    with contextlib.suppress(Exception):
                                        self.sync_m.sock.settimeout(120)
                                self.sync_pass(self.sync_m, c)
                                self.sync_used = time.time()
                                break
                            except (imaplib.IMAP4.abort, ssl.SSLError, OSError):
                                m, self.sync_m = self.sync_m, None
                                R.quit_imap(m, quick=True)
                                if attempt:
                                    raise
                        c.execute("insert or replace into meta values('last_sync', ?)", (str(int(time.time())),))
                        c.commit()
                self.sync["error"] = None
                self.sync["last"] = int(time.time())
                self.start_bodies()
            except BaseException as e:          # noqa: B036 - die() raises SystemExit
                self.sync["error"] = friendly(e)
                m, self.sync_m = self.sync_m, None
                R.quit_imap(m, quick=True)
            finally:
                self.sync["running"] = False
                self.pass_at = None
            with contextlib.suppress(Exception):
                self.folder_counts()            # the Dock count follows new mail with the window in the back too
        m, self.sync_m = self.sync_m, None
        R.quit_imap(m, quick=True)
        if c is not None:
            c.close()

    # ---- the text of mail that has only its headers: one worker, its own connection (#57)

    BODY_ROUND = 400        # rows taken per round, newest first
    BODY_PAUSE = 0.2        # seconds between two FETCH commands: the server serves a whole company
    BODY_QUIET = 2          # seconds after the user's last action before the download goes on
    BODY_IDLE = 300         # seconds with nothing to download before its connection is let go

    def body_folders(self):
        """The folders whose mail text is fetched: only ones the server still has (#48)."""
        fs = self.sync_folders() + self.extra_folders()
        there = self.server_folders
        return [f for f in fs if f in there] if there else fs

    def start_bodies(self):
        if self.demo:
            return
        if self.body_thread is None or not self.body_thread.is_alive():
            self.body_thread = threading.Thread(target=self.bodies_loop, daemon=True)
            self.body_thread.start()
        self.body_wake.set()

    def bodies_loop(self):
        c = None
        while not self.stopping.is_set():
            if not self.body_wake.wait(self.BODY_IDLE):
                m, self.body_m = self.body_m, None
                R.quit_imap(m, quick=True)
                continue
            self.body_wake.clear()
            if self.stopping.is_set() or not configured():
                continue
            try:
                c = c or R.db()
                with R.file_lock("bodies", wait=False) as got:
                    if got:                     # else the ragdoll command is at it
                        self.fetch_bodies_now(c)
            except BaseException as e:          # noqa: B036 - R.imap() dies with SystemExit; the next pass tries again
                print("mail text download stopped: %s" % friendly(e), file=sys.stderr)
                m, self.body_m = self.body_m, None
                R.quit_imap(m, quick=True)
            finally:
                self.bodies = None
        m, self.body_m = self.body_m, None
        R.quit_imap(m, quick=True)
        if c is not None:
            c.close()

    def quiet_wait(self):
        """Wait while somebody opens a mail or has just done something: they go first."""
        while not self.stopping.is_set() and (self.fg > 0 or time.time() - self.active_at < self.BODY_QUIET):
            self.stopping.wait(0.2)

    def body_fetch(self, folder, uids):
        for attempt in (0, 1):
            try:
                if self.body_m is not None and not still_there(self.body_m, self.body_used, 90):
                    m, self.body_m = self.body_m, None
                    R.quit_imap(m, quick=True)
                if self.body_m is None:
                    self.body_m = R.imap()
                    with contextlib.suppress(Exception):
                        self.body_m.sock.settimeout(90)
                got = R.fetch_bodies_on(self.body_m, folder, uids)
                self.body_used = time.time()
                return got
            except (imaplib.IMAP4.abort, ssl.SSLError, OSError):
                m, self.body_m = self.body_m, None
                R.quit_imap(m, quick=True)
                if attempt:
                    raise

    def fetch_bodies_now(self, c):
        """Newest first, many mails per command, one SELECT per folder, at a polite pace, making way
        for the user; no folder or flag work in between (that was a whole sync per 50 mails)."""
        folders = self.body_folders()
        if not folders:
            return
        marks = ",".join("?" * len(folders))
        count = "select count(*) from msgs where has_body=0 and folder in (%s)" % marks
        left = c.execute(count, folders).fetchone()[0]
        skip = set()                    # asked this time and not given: tried again on a later pass
        self.bodies = {"done": 0, "left": left}
        while left > len(skip) and not self.stopping.is_set():
            rows = c.execute("select folder, uid from msgs where has_body=0 and folder in (%s) order by ts desc "
                             "limit ?" % marks, folders + [self.BODY_ROUND + len(skip)]).fetchall()
            rows = [r for r in rows if (r["folder"], r["uid"]) not in skip][:self.BODY_ROUND]
            if not rows:
                break
            by = {}
            for r in rows:
                by.setdefault(r["folder"], []).append(r["uid"])
            for f, uids in by.items():
                for k in range(0, len(uids), R.BODY_BATCH):
                    part = uids[k:k + R.BODY_BATCH]
                    self.quiet_wait()
                    if self.stopping.is_set():
                        return
                    try:
                        got = self.body_fetch(f, part)
                    except LookupError:     # the folder went (renamed or deleted elsewhere): not again this time
                        skip.update((f, u) for u in uids)
                        break
                    R.store_bodies(c, f, got)
                    skip.update((f, u) for u in part if u not in got)
                    self.bodies = {"done": self.bodies["done"] + len(got), "left": max(0, left - len(got))}
                    left = self.bodies["left"]
                    self.stopping.wait(self.BODY_PAUSE)
            left = c.execute(count, folders).fetchone()[0]

    def look(self):
        """The index was written by someone else (the sync, the CLI in a terminal): the page loads its list again."""
        with self.dblock:
            v = self.c.execute("pragma data_version").fetchone()[0]
        if v != self.data_v:
            self.data_v = v
            self.bump()

    def check_update(self):
        try:
            if FROZEN:
                req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "ragdoll-mail",
                                                                    "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=15) as f:
                    d = json.load(f)
                v = (d.get("tag_name") or "").lstrip("v")
                if version_tuple(v) > version_tuple(__version__):
                    self.update = {"version": v, "url": d.get("html_url") or RELEASES_PAGE}
            elif os.path.isdir(os.path.join(R.APP_DIR, ".git")):
                R.maybe_check_later()
                latest = R.update_waiting()
                if latest:
                    self.update = {"version": latest.get("version"), "command": "ragdoll update"}
        except Exception:
            pass

    # ---- api: app state

    def api_boot(self, a):
        return {"configured": configured() or self.demo, "demo": self.demo, "user": R.CFG.user,
                "name": R.CFG.name, "version": __version__, "platform": sys.platform,
                "folders": self.folder_counts(), "theme": self.prefs().get("theme", "system"),
                "prefs": self.prefs(), "news": self.news, "asks": self.asks,
                "window": WINDOW.w is not None}

    def flag_folders(self):
        """Folders whose flagged mail shows in the Flagged list (not Trash or Junk)."""
        return ([R.CFG.folders[k] for k in ("inbox", "sent", "archive", "drafts") if R.CFG.folders.get(k)]
                + [n for n, _, _ in self.others()])

    def folder_counts(self):
        with self.dblock:
            key = (self.c.execute("pragma data_version").fetchone()[0], self.c.total_changes,
                   repr(self.found), repr(sorted(R.CFG.folders.items())))
        try:
            key += (os.path.getmtime(self.sched_path()),)
        except OSError:
            pass
        if self.counts and self.counts[0] == key:
            return self.counts[1]
        out = self.count_folders()
        self.counts = (key, out)
        n = next((x["unread"] for x in out if x["key"] == "inbox"), 0)
        if n != self.badge_n and dock_badge(n):
            self.badge_n = n
        return out

    def count_folders(self):
        out = []
        for k in ("inbox", "flagged", "drafts", "scheduled", "sent", "archive", "junk", "trash"):
            if k == "flagged":
                fs = self.flag_folders()
                if fs:
                    r = self.q("select count(*) n, coalesce(sum(seen=0),0) u from msgs where flagged=1 and folder in (%s)"
                               % ",".join("?" * len(fs)), fs)[0]
                    if r["n"]:
                        out.append({"key": k, "total": r["n"], "unread": r["u"]})
                continue
            if k == "scheduled":
                n = len(self.scheduled_rows())
                if n:
                    out.append({"key": k, "total": n, "unread": 0})
                continue
            f = R.CFG.folders.get(k)
            if not f:
                continue
            r = self.q("select count(*) n, coalesce(sum(seen=0),0) u from msgs where folder=?", (f,))[0]
            out.append({"key": k, "total": r["n"], "unread": r["u"]})
        n = {r["folder"]: r for r in self.q("select folder, count(*) n, coalesce(sum(seen=0),0) u from msgs group by folder")}
        for f, label, depth in self.others():
            out.append({"key": f, "label": label, "depth": depth, "other": True,
                        "total": n[f]["n"] if f in n else 0, "unread": n[f]["u"] if f in n else 0})
        return out

    def api_status(self, a):
        self.look()
        if a.get("focus"):
            self.focus_at = time.time()
        if a.get("web_notice"):
            self.web_notice_at = time.time()
        return {"rev": self.rev, "syncing": self.sync["running"], "error": self.sync["error"],
                "last": self.sync["last"], "folders": self.folder_counts(), "update": self.update,
                "news": self.news, "asks": self.asks, "bodies": self.bodies}

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
        p.update({k: v for k, v in a.items() if k in ("theme", "sidebar")})
        # widths in pixels (the page puts them in its style): whole numbers in a sane range; 0 is the default width
        lw, sw = a.get("list_width"), a.get("side_width")
        if type(lw) is int and 200 <= lw <= 1200:
            p["list_width"] = lw
        if type(sw) is int and (sw == 0 or 140 <= sw <= 400):
            p["side_width"] = sw
        if isinstance(a.get("side_hidden"), bool):
            p["side_hidden"] = a["side_hidden"]
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
        if isinstance(a.get("fmt_bar"), bool):
            p["fmt_bar"] = a["fmt_bar"]
        if isinstance(a.get("notify"), bool):
            p["notify"] = a["notify"]
        f = a.get("folded")
        if isinstance(f, list) and len(f) <= 500 and all(isinstance(x, str) and 0 < len(x) <= 500 for x in f):
            p["folded"] = f
        os.makedirs(R.CFG.home, exist_ok=True)
        with open(os.path.join(R.CFG.home, "app.json"), "w", encoding="utf-8") as f:
            json.dump(p, f)
        return p

    # ---- api: lists and reading

    LIST = ("id, folder, uidv, uid, msgid, ts, frm, to_, cc, subject, atts, substr(body, 1, 3000) body, "
            "seen, flagged, answered, forwarded, size")

    def api_list(self, a):
        key = a.get("folder") or "inbox"
        if key == "scheduled":
            return {"rows": self.scheduled_rows(), "more": False}
        limit = max(1, min(int_in(a, "limit", 100), 500))
        offset = max(0, min(int_in(a, "offset", 0), 10 ** 7))
        more, params = self.list_filter(a, key)
        if key == "flagged":
            fs = self.flag_folders()
            rows = self.q("select %s from msgs where flagged=1 and folder in (%s)%s order by ts desc, uid desc limit ? offset ?"
                          % (self.LIST, ",".join("?" * len(fs)), more), (*fs, *params, limit, offset)) if fs else []
            if not offset:
                self.prefetch(rows[:20])
            return {"rows": [self.row_json(r) for r in rows], "more": len(rows) == limit}
        folder = R.CFG.folders.get(key, key)
        if not self.demo and folder in self.extra_folders() and time.time() - self.extra_at > 60 and not self.extra_now:
            self.extra_now = True               # an opened Junk or other folder is brought up to date at once
            self.wake.set()
        rows = self.q("select %s from msgs where folder=?%s order by ts desc, uid desc limit ? offset ?" % (self.LIST, more),
                      (folder, *params, limit, offset))
        if not offset and key != "drafts":
            self.prefetch(rows[:20])
        out = [self.row_json(r) for r in rows]
        if key == "drafts":
            sched = {x["id"]: x for x in self.sched_list()}
            for r in out:
                if r["id"] in sched:
                    r["sched"] = sched[r["id"]]["at"]
                    r["sched_error"] = sched[r["id"]].get("error")
        return {"rows": out, "more": len(rows) == limit}

    @staticmethod
    def list_filter(a, key):
        """(" and ..." , params) for the list's filter: unread, starred, with a file, one person."""
        where, params = [], []
        if a.get("unread"):
            where.append("seen=0")
        if a.get("starred"):
            where.append("flagged=1")
        if a.get("att"):
            where.append("atts!=''")
        who = text_in(a, "from").strip()
        if who:
            pat = R.like_arg(who)
            if key in ("sent", "drafts"):       # in these the other person is who it went to
                where.append("(to_ like ? escape '\\' or cc like ? escape '\\')")
                params += [pat, pat]
            else:
                where.append("frm like ? escape '\\'")
                params.append(pat)
        return "".join(" and " + w for w in where), params

    def api_senders(self, a):
        """The people most often seen in the newest mail of a list, for its filter."""
        key = a.get("folder") or "inbox"
        if key == "scheduled":
            return {"people": []}
        fs = self.flag_folders() if key == "flagged" else [R.CFG.folders.get(key, key)]
        rows = self.q("select frm, to_ from msgs where folder in (%s)%s order by ts desc, uid desc limit 300"
                      % (",".join("?" * len(fs)), " and flagged=1" if key == "flagged" else ""), fs) if fs else []
        me = (R.CFG.user or "").lower()
        count, names = {}, {}
        for r in rows:
            for n, ad in (R.addrs(r["to_"]) if key in ("sent", "drafts") else R.addrs(r["frm"])[:1]):
                k = (ad or "").lower()
                if k and k != me:
                    count[k] = count.get(k, 0) + 1
                    names[k] = names.get(k) or n
        top = sorted(count, key=lambda k: -count[k])[:6]
        return {"people": [person(names[k], k) for k in top]}

    def api_demo_mail(self, a):
        """In the demo only: one new mail comes in, the way a sync would bring it."""
        if not self.demo:
            fail("only in the demo")
        with self.dblock:
            if self.news_mark is None:
                self.note_new(self.c)
            ts = int(time.time())
            zh = self.demo_set["me"] == ME_ZH
            frm, subj, body = ((("何敏", "he.min@example.cn"), "订单 4502 的交货日期",
                                "林工你好，\n\n订单 4502 的交货日期能确认一下吗？\n\n何敏") if zh else
                               (("Sofia Rossi", "sofia.rossi@example.it"), "Delivery date for order 4502",
                                "Hi Alex,\n\nCan you confirm the delivery date for order 4502?\n\nSofia"))
            raw = demo_message("inbox", ts, frm, [self.demo_set["me"]], [], subj, body,
                               [], make_msgid(domain="example.com"), None, None)
            self.demo_insert(R.CFG.folders["inbox"], raw, ts, 0, 0)
            self.note_new(self.c)
        return {}

    def api_demo_ask(self, a):
        """In the demo only: what an agent's `ragdoll draft --reply` and `ragdoll open` do, for the tour video:
        a reply draft is saved and the app is asked to open it."""
        if not self.demo:
            fail("only in the demo")
        c = self.api_compose({"mode": "reply", "id": a["id"]})
        i, _ = self.save(dict(c, html=text_in(a, "html")))
        self.asks_n += 1
        self.asks.append({"n": self.asks_n, "kind": "open", "id": i, "subject": c["subject"], "at": int(time.time())})
        self.bump()
        return {"id": i}

    def api_search(self, a):
        text = text_in(a, "q").strip()[:500]
        ns = SimpleNamespace(limit=200, folder=None, from_=None, to=None, since=None, until=None,
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
            return {"rows": []}
        with self.dblock:
            rows = R.search_rows(self.c, words, ns)
        skip = {R.CFG.folders.get("junk")}
        rows = [r for r in rows if r["folder"] not in skip]
        self.prefetch(rows[:10])
        return {"rows": [self.row_json(r) for r in rows]}

    def api_thread(self, a):
        r = self.row(a["id"])
        with self.dblock:
            rows = R.thread_rows(self.c, r)
        skip = {R.CFG.folders.get("trash"), R.CFG.folders.get("junk"), R.CFG.folders.get("drafts")} - {r["folder"]}
        rows = [x for x in rows if x["folder"] not in skip or x["id"] == r["id"]]
        if not self.demo:       # the mails just below the opened one, then the rest of its thread
            self.prefetch(rows[-6:][::-1])
            self.prefetch(self.q("select folder, uidv, uid, size from msgs where folder=? and ts<=? "
                                 "order by ts desc, uid desc limit 8", (r["folder"], r["ts"])))
        return {"subject": r["subject"] or "", "rows": [self.row_json(x) for x in rows], "id": a["id"]}

    def api_message(self, a):
        i = a["id"]
        send = back = None
        if a.get("mark", True):         # read the moment it is opened, not once a big mail is in
            with contextlib.suppress(ApiError):
                if not self.row(i)["seen"]:
                    send, back = self.set_flag([i], "seen", True, wait=False, later=True)
        try:
            with self.dblock:
                out = None if self.demo else self.built.get(i)
                if out is not None:
                    self.built.move_to_end(i)
            if out is None:
                out = self.build_message(i)
                if not self.demo and len(out["html"]) < 1500000:
                    with self.dblock:
                        self.built[i] = out
                        while len(self.built) > 40:
                            self.built.popitem(last=False)
        except BaseException:
            if back:
                back()                  # a mail that did not open was not read
            raise
        if send:
            send()                      # the server hears it in the background, now that the mail is open
        return out

    def build_message(self, i):
        raw, light = self.view(i)
        msg = R.to_msg(raw)
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
               "remote": has_remote(body), "atts": [part_info(k, p, light) for k, p in enumerate(file_parts(msg))],
               "big": R.big_attachment_lines(R.html_to_text(html) or plain),
               "unsub": list_unsub(msg), "invite": invite_of(msg)}
        return out

    def set_flag(self, ids, flag, on, wait=True, later=False):
        """wait: the server has it before this returns (an error is raised); else the index changes now,
        the server hears it in the background and the index is put back if the server says no.
        later (not with wait): the index changes now and (send, back) comes back: send() tells the
        server, back() puts the index back. For a mark that depends on what happens next."""
        by = {}
        for i in ids:
            f, u = self.parse(i)
            by.setdefault(f, []).append(u)
        return self.flag_by(by, flag, on, wait, later)

    def flag_by(self, by, flag, on, wait=True, later=False):
        """set_flag for {folder: [uid, ...]}."""
        col, imap_flag = {"seen": ("seen", "\\Seen"), "flagged": ("flagged", "\\Flagged")}[flag]

        def db(val):
            with self.dblock:
                for f, uids in by.items():
                    for k in range(0, len(uids), 500):      # a whole folder at once: under SQLite's limit
                        part = uids[k:k + 500]
                        self.c.execute("update msgs set %s=? where folder=? and uid in (%s)"
                                       % (col, ",".join("?" * len(part))), [int(val), f, *part])
                self.c.commit()
            self.bump()
        if self.demo:
            db(on)
            return (lambda: None, lambda: db(not on)) if later else None

        def go(m):
            for f, uids in by.items():
                R.use(m, f, write=True)
                for k in range(0, len(uids), 200):
                    typ, data = m.uid("STORE", ",".join(map(str, uids[k:k + 200])),
                                      "+FLAGS.SILENT" if on else "-FLAGS.SILENT", "(%s)" % imap_flag)
                    if typ != "OK":
                        raise imaplib.IMAP4.error("the server refused: %s" % (data,))

        def end(e):                     # called once, when the server has it (e is None) or will not
            self.settle(by, col, e is None)
            if wait and e is None:
                db(on)
            elif not wait and e is not None:
                print("a mark did not reach the server: %s" % friendly(e), file=sys.stderr)
                db(not on)
        done = {"ev": threading.Event()} if wait else None

        def send():
            self.flag_q.put((go, done, end))
            if self.flag_thread is None or not self.flag_thread.is_alive():
                self.flag_thread = threading.Thread(target=self.flag_loop, daemon=True)
                self.flag_thread.start()

        def back():
            self.settle(by, col, False)
            db(not on)
        self.hold(by, col, on)          # a sync that asks the server meanwhile must not put the old value back
        if not wait:
            db(on)
            if later:
                return send, back
            return send()
        send()
        if not done["ev"].wait(self.MARK_WAIT):
            # still behind other marks: it is skipped. Already with the server: the index follows if it lands.
            done["gone"] = True
            raise TimeoutError("the mark took too long")
        if done.get("err"):
            raise done["err"]

    MARK_WAIT = 60      # seconds an asked-for mark may take before whoever waits is told it failed
    MARK_TIMEOUT = 20   # seconds the server may take to answer a mark: the connection is shared with opening mail
    MARK_PAUSE = 2      # seconds before a failed mark is tried once more
    QUIT_WAIT = 4       # seconds quitting waits for the marks still on their way

    # ---- marks on their way to the server

    def hold(self, by, col, val):
        with self.marklock:
            for f, uids in by.items():
                for u in uids:
                    e = self.marks.get((f, u, col))
                    self.marks[(f, u, col)] = [int(val), (e[1] if e else 0) + 1, 0]

    def settle(self, by, col, ok):
        """The server has the mark (ok), or it was given up: a sync may then set the flag again."""
        now = time.time()
        with self.marklock:
            for f, uids in by.items():
                for u in uids:
                    e = self.marks.get((f, u, col))
                    if not e:
                        continue
                    e[1] -= 1
                    if e[1] <= 0 and ok:
                        e[2] = now
                    elif e[1] <= 0:
                        del self.marks[(f, u, col)]

    def held(self, folder, since):
        """{uid: {column: value}} for R.sync_headers: the flags changed here that the server may not
        have had yet when the sync asked it at `since`."""
        out, now = {}, time.time()
        with self.marklock:
            for (f, u, col), e in list(self.marks.items()):
                if e[1] <= 0 and now - e[2] > 300:
                    del self.marks[(f, u, col)]             # long with the server: nothing to keep
                elif f == folder and (e[1] > 0 or e[2] >= since - 2):
                    out.setdefault(u, {})[col] = e[0]
        return out

    def flag_try(self, go):
        """One mark sent to the server; when that fails, once more on a new connection."""
        def run(m):
            with contextlib.suppress(Exception):
                m.sock.settimeout(self.MARK_TIMEOUT)    # opening a mail waits for this connection
            try:
                return go(m)
            finally:
                with contextlib.suppress(Exception):
                    m.sock.settimeout(90)
        try:
            return self.imap(run)
        except (ApiError, LookupError):
            raise                       # the server answered: asking again changes nothing
        except BaseException:           # noqa: B036 - R.imap() dies with SystemExit
            self.drop()
            self.stopping.wait(self.MARK_PAUSE)     # a network that just dropped is often back in a moment
            return self.imap(run)

    def flag_end(self, job, err):
        go, done, end = job
        try:
            end(err)
        except Exception:               # noqa: BLE001 - the loop must live on
            traceback.print_exc(file=sys.stderr)
        finally:
            if done is not None:
                done["err"] = err
                done["ev"].set()
            self.flag_q.task_done()

    def flag_loop(self):
        while not self.stopping.is_set():
            try:
                job = self.flag_q.get(timeout=60)
            except queue.Empty:
                continue
            if job[1] is not None and job[1].get("gone"):
                self.flag_end(job, TimeoutError("nobody waits for it any more"))
                continue
            err = None
            try:
                self.flag_try(job[0])
            except BaseException as e:  # noqa: B036 - handed to whoever waits, or undone in the index
                err = e
            self.flag_end(job, err)
            if err is not None and self.m is None:
                # the server cannot be reached: each mark waiting behind this one would wait that out
                # again, and whoever opens a mail waits with them. They fail now.
                while True:
                    try:
                        job = self.flag_q.get_nowait()
                    except queue.Empty:
                        break
                    self.flag_end(job, err)

    def api_mark(self, a):
        self.set_flag(ids_in(a), a.get("flag", "seen"), bool(a.get("on", True)))
        return {}

    def api_notice_on(self, a):
        """Notices were just switched on: show one, so the owner sees them work (and macOS asks, once,
        whether the app may show them). Only the app's own window: a browser page shows its own."""
        if self.demo or WINDOW.w is None:
            return {"ok": False}
        threading.Thread(target=system_notice, args=(APP_NAME, text_in(a, "body")[:200]), daemon=True).start()
        return {"ok": True}

    def api_notice_state(self, a):
        """Whether macOS lets the app show notices, for the line in Settings."""
        return {"state": "" if self.demo or WINDOW.w is None else mac_notice_state()}

    def api_notice_settings(self, a):
        """Open the system's page where the owner allows notices. The switch itself is theirs."""
        if self.demo or WINDOW.w is None or sys.platform != "darwin":
            return {"ok": False}
        mac_notice_page()
        return {"ok": True}

    def api_mark_all_read(self, a):
        """Every unread mail of a list becomes read: the index now, the server in the background.
        {"folder": the list's key, as for api_list} -> {"count": how many were unread}."""
        key = text_in(a, "folder") or "inbox"
        if key == "scheduled":
            return {"count": 0}
        fs = self.flag_folders() if key == "flagged" else [R.CFG.folders.get(key, key)]
        rows = self.q("select folder, uid from msgs where seen=0%s and folder in (%s)"
                      % (" and flagged=1" if key == "flagged" else "", ",".join("?" * len(fs))), fs) if fs else []
        by = {}
        for r in rows:
            by.setdefault(r["folder"], []).append(r["uid"])
        if by:
            self.flag_by(by, "seen", True, wait=False)
        return {"count": len(rows)}

    def api_move(self, a):
        """Move mails to archive, trash, inbox or junk (dest is the folder key), or to one of the other folders."""
        dest_key = a.get("to")
        other = isinstance(dest_key, str) and dest_key in [n for n, _, _ in self.others()]
        if not other and dest_key not in ("archive", "trash", "inbox", "junk"):
            fail("can't move to %s" % dest_key)
        dest = dest_key if other else R.CFG.folders.get(dest_key) or ("Archive" if dest_key == "archive" else None)
        if not dest:
            fail("No %s folder is set." % dest_key)
        by = {}
        for i in ids_in(a):
            f, u = self.parse(i)
            if f != dest:
                by.setdefault(f, []).append(u)
                # a moved draft is no longer the one that was scheduled
                self.sched_drop(i)
                if dest_key == "inbox":         # mail the owner put back is not new mail
                    for r in self.q("select msgid from msgs where folder=? and uid=?", (f, u)):
                        self.moved_in[r["msgid"]] = time.time()
        if self.demo:
            for f, uids in by.items():
                for u in uids:
                    r = self.q("select * from msgs where folder=? and uid=?", (f, u))
                    raw = self.demo_raw.pop((f, u), None)
                    if r and raw:
                        self.demo_insert(dest, raw, r[0]["ts"], r[0]["seen"], r[0]["answered"], r[0]["flagged"])
        else:
            def go(m):
                if other:
                    self.server_folders = None
                    if dest not in self.folders(m):
                        fail("The folder %s is no longer on the server." % dest)
                elif dest not in self.folders(m):
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
            if (set(by) | {dest}) - set(self.sync_folders()):
                self.extra_now = True
            self.wake.set()
        return {"moved": sum(len(x) for x in by.values())}

    def folders(self, m):
        if self.server_folders is None:
            self.server_folders = [n for n, _ in list_folders(m)]
        return self.server_folders

    # ---- the owner's own folders: make, rename, delete (only an empty one)

    def own_folder(self, a):
        key = a.get("key")
        for n, label, _ in self.others():
            if n == key:
                return n, label
        fail("The folder %s is no longer on the server." % key)

    def own_parent(self, sep):
        """Where a new folder goes: beside the ones already there (some servers keep them all under one fixed folder)."""
        tops = [n for n, _, d in self.others() if d == 0]
        if tops:
            parents = {n.rpartition(sep)[0] for n in tops}
            return parents.pop() if len(parents) == 1 else ""
        holders = [n for n, flags in self.found if "\\noselect" in flags.split() and n.strip(sep)]
        return holders[0] if len(holders) == 1 else ""

    def refresh_folders(self, m):
        found = list_folders(m)
        self.server_folders = [n for n, _ in found]
        self.found = found
        self.exec("insert or replace into meta values('folders', ?)", (json.dumps(found),))

    def free_name(self, name, label):
        if name.lower() in [n.lower() for n, _ in self.found] or name.upper() == "INBOX":
            fail("There is already a folder called %s." % label)

    def rename_rows(self, old, new, sep):
        """The mail already listed follows its folder to the new name (the folders inside it too)."""
        with self.dblock:
            names = {r[0] for r in self.c.execute("select folder from msgs union select folder from state").fetchall()}
            for f in names:
                if f == old or f.startswith(old + sep):
                    to = new + f[len(old):]
                    self.c.execute("delete from state where folder=?", (to,))
                    self.c.execute("update msgs set folder=? where folder=?", (to, f))
                    self.c.execute("update state set folder=? where folder=?", (to, f))
            self.c.commit()

    def api_folder_new(self, a):
        label = folder_label(a.get("name"))
        if self.demo:
            base = self.own_parent("/")
            name = base + "/" + label if base else label
            self.free_name(name, label)
            self.found.append((name, ""))
        else:
            def go(m):
                sep = folder_sep(m)
                if sep in label:
                    fail("A folder name can't have %s in it." % sep)
                self.refresh_folders(m)
                base = self.own_parent(sep)
                name = base + sep + label if base else label
                self.free_name(name, label)
                typ, data = m.create(R.q(name))
                if typ != "OK":
                    fail("The mail server said: %s" % said(data))
                with contextlib.suppress(Exception):
                    m.subscribe(R.q(name))
                self.refresh_folders(m)
                return name
            name = self.imap(go)
        self.bump()
        return {"key": name}

    def api_folder_rename(self, a):
        key, old = self.own_folder(a)
        label = folder_label(a.get("name"))
        name = key[:len(key) - len(old)] + label
        if name == key:
            return {"key": key}
        if self.demo:
            self.free_name(name, label)
            self.found = [(name + n[len(key):], f) if n == key or n.startswith(key + "/") else (n, f) for n, f in self.found]
            for (f, u) in list(self.demo_raw):
                if f == key or f.startswith(key + "/"):
                    self.demo_raw[(name + f[len(key):], u)] = self.demo_raw.pop((f, u))
            self.rename_rows(key, name, "/")
        else:
            def go(m):
                sep = folder_sep(m)
                if sep in label:
                    fail("A folder name can't have %s in it." % sep)
                self.refresh_folders(m)
                self.own_folder(a)
                self.free_name(name, label)
                R.select(m, R.CFG.folders.get("inbox") or "INBOX", readonly=True)
                typ, data = m.rename(R.q(key), R.q(name))
                if typ != "OK":
                    fail("The mail server said: %s" % said(data))
                with contextlib.suppress(Exception):
                    m.unsubscribe(R.q(key))
                    m.subscribe(R.q(name))
                self.rename_rows(key, name, sep)
                self.refresh_folders(m)
            self.imap(go)
            self.extra_now = True
            self.wake.set()
        self.bump()
        return {"key": name}

    def api_folder_delete(self, a):
        """Only a folder with no mail and no folders inside goes; mail is never deleted this way."""
        key, label = self.own_folder(a)
        if self.demo:
            if any(n.startswith(key + "/") for n, _ in self.found):
                fail("%s has folders inside it. Delete those first." % label)
            if self.q("select 1 from msgs where folder=? limit 1", (key,)):
                fail("%s still has mail in it. Move the mail out first." % label)
            self.found = [(n, f) for n, f in self.found if n != key]
        else:
            def go(m):
                sep = folder_sep(m)
                self.refresh_folders(m)
                self.own_folder(a)
                if any(n.startswith(key + sep) for n, _ in self.found):
                    fail("%s has folders inside it. Delete those first." % label)
                typ, data = m.status(R.q(key), "(MESSAGES)")
                mo = re.search(rb"MESSAGES\s+(\d+)", b" ".join(x for x in data or [] if isinstance(x, bytes)))
                if typ != "OK" or not mo:
                    fail("The mail server said: %s" % said(data))
                if int(mo.group(1)):
                    fail("%s still has mail in it. Move the mail out first." % label)
                R.select(m, R.CFG.folders.get("inbox") or "INBOX", readonly=True)
                with contextlib.suppress(Exception):
                    m.unsubscribe(R.q(key))
                typ, data = m.delete(R.q(key))
                if typ != "OK":
                    fail("The mail server said: %s" % said(data))
                self.refresh_folders(m)
            self.imap(go)
        with self.dblock:
            for r in self.c.execute("select id from msgs where folder=?", (key,)).fetchall():
                self.c.execute("delete from fts where rowid=?", (r["id"],))
            self.c.execute("delete from msgs where folder=?", (key,))
            self.c.execute("delete from state where folder=?", (key,))
            self.c.commit()
        self.bump()
        return {}

    def files_of(self, i):
        """(the mail's files, whether the mail is the light one)."""
        raw, light = self.view(i)
        return file_parts(R.to_msg(raw)), light

    def whole_part(self, i, p, light):
        """The file with its data. A big one the light mail left on the server is fetched by itself,
        once: it is kept beside the light mail (R.part_path) for the next open or save."""
        sec = left_out(p, light)
        if not sec:
            return p
        r = self.row(i)
        path = R.part_path(r["folder"], r["uidv"], r["uid"], sec)
        raw = R.cache_get(path)
        if not raw:
            raw = self.download(lambda m: R.fetch_part_raw(m, r["folder"], r["uid"], sec))
            R.cache_put(path, raw)
        return R.to_msg(raw)

    def write_part(self, p, save):
        """The file written to Downloads under a name that is free there (save), or to a folder of
        its own to open it from. Returns its path. Opening the same file again opens the copy made the
        first time: a second copy of the same name would not open in Excel ("a workbook with the same
        name is already open"), and changes made in the first copy stay."""
        name = R.safe_name(R.fname(p) or "attachment")
        data = R.part_bytes(p)
        if not os.path.splitext(name)[1] and p.get_content_type() != "application/octet-stream":
            name += mimetypes.guess_extension(p.get_content_type()) or ""     # so the Mac knows which app
        if save:
            path = R.unique_path(downloads_dir(), name, set())
            n = 2
            while os.path.exists(path):
                stem, ext = os.path.splitext(name)
                path = os.path.join(downloads_dir(), "%s (%d)%s" % (stem, n, ext))
                n += 1
        else:
            d = os.path.join(R.CFG.home, "open", hashlib.sha256(name.encode() + b"\0" + data).hexdigest()[:12])
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, name)
            if os.path.exists(path):
                self.made.add(path)
                return path
        tmp = path + ".part"
        with open(tmp, "wb") as f:      # the app that opens it never sees half a file
            f.write(data)
        os.replace(tmp, path)
        self.made.add(path)
        return path

    def api_attachment(self, a):
        parts, light = self.files_of(a["id"])
        k = int(a["i"])
        name = a.get("name")
        # the page may show the light mail's list and this the whole mail's (or the other way): the name decides
        if name and not (0 <= k < len(parts) and (R.fname(parts[k]) or "attachment") == name):
            k = next((j for j, p in enumerate(parts) if (R.fname(p) or "attachment") == name), -1)
        if not 0 <= k < len(parts):
            fail("That attachment is not in the mail any more.")
        save = a.get("action") == "save"
        path = self.write_part(self.whole_part(a["id"], parts[k], light), save)
        if a.get("action") == "drag":
            # the file under its own name in the app's open folder; Finder copies it where it is dropped
            return {"path": path, "name": os.path.basename(path), "dragging": drag_out(path)}
        if not save:
            open_path(path)
        return {"path": path, "name": os.path.basename(path)}

    def api_unsubscribe(self, a):
        """Leave the mailing list the mail came from. One click (RFC 8058): the app asks the list itself.
        Else the list's page opens in the browser, or the page writes the mail the list asks for."""
        u = list_unsub(R.to_msg(self.view(a["id"])[0]))
        if not u:
            fail("This mail has no way to unsubscribe.")
        if u["one_click"]:
            if not self.demo:
                req = urllib.request.Request(u["url"], data=b"List-Unsubscribe=One-Click", method="POST",
                                             headers={"Content-Type": "application/x-www-form-urlencoded",
                                                      "User-Agent": APP_NAME})
                try:
                    with urllib.request.urlopen(req, timeout=15) as r:
                        r.read(4096)
                except Exception as e:
                    fail("The list did not answer: %s" % (getattr(e, "reason", None) or e))
            return {"done": True}
        if u["url"]:
            webbrowser.open(u["url"])
            return {"opened": True}
        to, _, query = u["mailto"][7:].partition("?")
        subj = urllib.parse.parse_qs(query).get("subject", ["unsubscribe"])[0]
        return {"mailto": urllib.parse.unquote(to), "subject": subj}

    def api_open_invite(self, a):
        """The invitation's .ics, opened by the system: Calendar on a Mac, Outlook on Windows."""
        p = ics_part(R.to_msg(self.view(a["id"])[0]))
        if p is None:
            fail("This mail has no invitation.")
        data = R.part_bytes(p)
        d = os.path.join(R.CFG.home, "open", hashlib.sha256(data).hexdigest()[:12])
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, R.safe_name(R.fname(p) or "invite.ics"))
        if not path.lower().endswith(".ics"):
            path += ".ics"
        with open(path, "wb") as f:
            f.write(data)
        self.made.add(path)
        if not self.demo:
            open_path(path)
        return {"path": path}

    def api_save_all(self, a):
        """Every file of the mail into Downloads, the way api_attachment's "save" does one.
        {"id": the mail} -> {"count": files saved, "path": the last one (the folder when none), "folder": Downloads}."""
        parts, light = self.files_of(a["id"])
        folder = downloads_dir()
        path = None
        for p in parts:
            path = self.write_part(self.whole_part(a["id"], p, light), True)
        if path is None:
            self.made.add(folder)       # so the page may show the folder
        return {"count": len(parts), "path": path or folder, "folder": folder}

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

    def api_window_theme(self, a):
        window_theme(bool(a.get("dark")), a.get("bg"), a.get("text"))
        return {}

    def api_contacts(self, a):
        q = text_in(a, "q").strip().lower()
        if time.time() - self.contacts[0] > 300:
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
        hits = [(v[0], ad, v[1]) for ad, v in self.contacts[1].items()
                if not q or q in ad or q in v[1].lower()]
        hits.sort(key=lambda x: (-x[0], x[1]))
        return [person(n, ad) for _, ad, n in hits[:8]]

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
        i, _ = self.save(a)
        if not i:
            fail("The draft was saved but the server did not say where. Open Drafts and send it from there.")
        return {"id": i, "problems": []}

    def api_send(self, a):
        with self.schedlock:
            self.sched_drop(a["id"])
            return self.send_now(a)

    def send_now(self, a):
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
        return out

    def sched_loop(self):
        while not self.stopping.is_set():
            self.sched_wake.wait(15)
            self.sched_wake.clear()
            if self.stopping.is_set():
                break
            with contextlib.suppress(Exception):
                self.send_due()

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
                    self.send_now({"id": x["id"]})
                    self.sched_drop(x["id"])
                    sent += 1
                except Exception as e:       # noqa: BLE001 - every reason is shown to the person
                    msg = str(e) if isinstance(e, ApiError) else friendly(e)
                    items = self.sched_list()
                    for y in items:
                        if y["id"] == x["id"]:
                            y["error"] = msg
                    self.sched_save(items)
                    self.bump()
        return sent

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

    def db_delete(self, i):
        f, u = self.parse(i)
        for r in self.c.execute("select id from msgs where folder=? and uid=?", (f, u)).fetchall():
            self.c.execute("delete from msgs where id=?", (r["id"],))
            self.c.execute("delete from fts where rowid=?", (r["id"],))
        self.c.commit()

    def upload(self, name, data):
        return self.keep_file(name or "file", data)

    # ---- hand-offs from ragdoll in a terminal or an agent (ragdoll open, a new draft)

    def asks_loop(self):
        while not self.stopping.is_set():
            with contextlib.suppress(Exception):
                self.take_asks()
            self.stopping.wait(1)

    def take_asks(self):
        got = R.take_asks()
        if not got:
            return
        for x in got:
            self.asks_n += 1
            self.asks.append({"n": self.asks_n, "kind": x.get("kind") or "open", "id": x["id"],
                              "subject": x.get("subject") or "", "at": x.get("at") or int(time.time())})
        self.asks = self.asks[-20:]
        self.look()
        self.bump()
        if any(x.get("kind") == "open" for x in got):
            bring_front()
        poke_page()

    # ---- the ragdoll command

    def api_cli_state(self, a):
        launcher = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ragdoll-mail", "bin", "ragdoll.cmd") \
            if sys.platform == "win32" else os.path.expanduser("~/.local/bin/ragdoll")
        return {"installed": os.path.exists(launcher), "launcher": launcher}

    def api_install_cli(self, a):
        if self.demo:
            fail("Not in the demo.")
        try:
            r = R.install_cli()
        except OSError as e:
            fail(str(e))
        return r

    # ---- settings and setup

    def api_settings(self, a):
        return {"name": R.CFG.name, "user": R.CFG.user, "imap_host": R.CFG.imap.get("host", ""),
                "imap_port": R.CFG.imap.get("port", 993), "smtp_host": R.CFG.smtp.get("host", ""),
                "smtp_port": R.CFG.smtp.get("port", 465),
                "signature": self.signature(), "has_password": self.has_password(),
                "password_env": R.CFG.password_env if not self.demo and (
                    os.environ.get(R.CFG.password_env) or R._SHELL_ENV.get(R.CFG.password_env)) else "",
                "folders": dict(R.CFG.folders), "config": config_path(), "demo": self.demo}

    def has_password(self):
        if self.demo:
            return True
        return bool(R.find_password())

    def api_guess_servers(self, a):
        dom = (a.get("user") or "").rpartition("@")[2].lower()
        if dom in PROVIDERS:
            i, s, *port = PROVIDERS[dom]
            return {"imap_host": i, "smtp_host": s, "smtp_port": (port or [465])[0]}
        # a company domain: who receives its mail says whose servers it uses (Exmail, Google, ...)
        found = None if self.demo or not dom else R.servers_from_mx(dom)
        return found or {"imap_host": "imap." + dom if dom else "", "smtp_host": "smtp." + dom if dom else "",
                         "smtp_port": 465}

    def api_test(self, a):
        """Sign in to IMAP and SMTP with these settings; find the special folders."""
        user = text_in(a, "user").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", user):
            fail("Enter a full email address.")
        pw = a.get("password") or (os.environ.get(R.CFG.password_env) if user == R.CFG.user else None) \
            or R.keychain_get(user)
        if not pw:
            fail("Enter the password.")
        if self.demo:
            return {"folders": dict(R.CFG.folders)}
        ihost, iport = text_in(a, "imap_host").strip(), int_in(a, "imap_port", 993)
        shost, sport = text_in(a, "smtp_host").strip(), int_in(a, "smtp_port", 465)
        try:
            m = imaplib.IMAP4_SSL(ihost, iport, timeout=20)
        except Exception as e:
            fail("Incoming server: " + friendly(e))
        try:
            try:
                m.login(user, pw)
            except imaplib.IMAP4.error as e:
                fail("Incoming server: sign-in failed (%s). Some providers need an app password." % e)
            found = detect_folders(list_folders(m))
        finally:
            with contextlib.suppress(Exception):
                m.logout()
        try:
            s = R.smtp_open(shost, sport, 20)
            try:
                s.login(user, pw)
            finally:
                with contextlib.suppress(Exception):
                    s.quit()
        except smtplib.SMTPAuthenticationError as e:
            fail("Outgoing server: sign-in failed (%s)." % e.smtp_error.decode(errors="replace")[:200])
        except Exception as e:
            fail("Outgoing server: " + friendly(e))
        return {"folders": found}

    def api_save_settings(self, a):
        if self.demo:
            fail("Settings can't be changed in the demo.")
        path = config_path()
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            raw = {}
        except ValueError:
            fail("The settings file %s is broken; fix or remove it first." % path)
        user = (a.get("user") or R.CFG.user or "").strip().lower()
        if a.get("account", True):
            raw["user"] = user
            raw["name"] = (a.get("name") or "").strip()
            raw["imap"] = {"host": (a.get("imap_host") or "").strip(), "port": int(a.get("imap_port") or 993)}
            raw["smtp"] = {"host": (a.get("smtp_host") or "").strip(), "port": int(a.get("smtp_port") or 465)}
        if a.get("folders"):
            fs = dict(raw.get("folders") or {})
            fs.update({k: v for k, v in a["folders"].items() if k in FOLDER_KEYS and v})
            raw["folders"] = fs
            raw["sync_folders"] = [fs.get("inbox", "INBOX"), fs.get("sent", R.CFG.folders["sent"]),
                                   fs.get("drafts", R.CFG.folders["drafts"])]
        if "signature" in a:
            sig = a["signature"] or ""
            cur = os.path.expanduser(R.CFG.signature or "")
            mine = os.path.join(os.path.dirname(path), "signature.html")
            target = cur if cur and os.path.realpath(cur) == os.path.realpath(mine) else mine
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(sig)
            raw["signature"] = target if sig.strip() else ""
        if a.get("password"):
            try:
                R.keychain_set(user, a["password"])
            except OSError as e:
                fail("Could not save the password in the system keychain: %s" % e)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
        old_home = R.CFG.home
        R.CFG = R.load_config(path)
        if R.CFG.home != old_home:
            with self.dblock:
                self.c = R.db()
        self.drop()
        self.server_folders = None
        self.contacts = (0, {})
        self.sync["error"] = None
        self.start_sync()
        self.bump()
        return self.api_boot({})

    # ---- demo

    def make_demo(self):
        home = tempfile.mkdtemp(prefix="ragdoll-demo-")
        self.demo_uids = {}
        atexit.register(shutil.rmtree, home, True)
        d = json.loads(json.dumps(R.DEFAULTS))
        ds = self.demo_set
        me = ds["me"]
        d.update({"user": me[1], "name": me[0], "data_dir": home, "imap": {"host": "demo", "port": 993},
                  "smtp": {"host": "demo", "port": 465}})
        sig = os.path.join(home, "signature.html")
        with open(sig, "w", encoding="utf-8") as f:
            f.write('<div style="color:#6b6b6b;font-size:13px">%s</div>' % ds["signature"])
        d["signature"] = sig
        R.CFG = R.Cfg(d)
        self.c = R.db()
        now = int(time.time())
        mids = {}
        for k, (fk, ago, frm, to, cc, subj, body, atts, seen, thread, key) in enumerate(ds["mail"]):
            ts = now - ago * 60
            mid = "<demo-%d@example.com>" % k
            irt = refs = None
            if thread and thread in mids:
                irt = mids[thread]
                refs = irt
            if thread:
                mids[thread] = mid
            raw = demo_message(fk, ts, frm, to, cc, subj, body, atts, mid, irt, refs,
                               inline=subj in DEMO_INLINE, event=ds["event"])
            self.demo_insert(R.CFG.folders.get(fk, fk), raw, ts, int(seen), int(fk == "inbox" and thread == "lunch"),
                             int(subj in DEMO_FLAGGED))
        self.demo_order_threads()

    def demo_order_threads(self):
        # the demo list is made oldest-thread-first above; nothing else to do, kept for clarity
        return

    def demo_insert(self, folder, raw, ts, seen, answered, flagged=0):
        with self.dblock:
            r = self.c.execute("select coalesce(max(uid),0)+1 from msgs where folder=?", (folder,)).fetchone()
            uid = max(r[0], self.demo_uids.get(folder, 0) + 1)
            self.demo_uids[folder] = uid
            index_raw(self.c, folder, 1, uid, raw, ts, seen, answered, flagged)
        self.demo_raw[(folder, uid)] = raw
        return uid

    def demo_delete(self, i):
        f, u = self.parse(i)
        self.demo_raw.pop((f, u), None)
        with self.dblock:
            self.db_delete(i)

    def close(self):
        # marks made a moment ago are still on their way to the server: a few seconds for them, never more
        end = time.time() + self.QUIT_WAIT
        while (self.flag_q.unfinished_tasks and self.flag_thread is not None and self.flag_thread.is_alive()
               and time.time() < end):
            time.sleep(0.05)
        self.stopping.set()
        self.wake.set()
        self.sched_wake.set()
        self.pre_wake.set()
        self.body_wake.set()
        self.drop()
        for m in (self.dm, self.sync_m, self.pre_m, self.body_m):
            cut(m)


def ids_in(a):
    ids = a.get("ids")
    if isinstance(ids, str):
        ids = [ids]
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        fail("bad request")
    return ids


def text_in(a, k):
    v = a.get(k)
    return v if isinstance(v, str) else ""


def int_in(a, k, default):
    try:
        return int(a.get(k) or default)
    except (TypeError, ValueError, OverflowError):
        return default


def app_problems(msg, reply):
    """ragdoll's pre-send check, worded for the app (no CLI flags; no table-layout rules)."""
    out = []
    for p in R.check_message(msg, reply, blanks_ok=False, required_cc=False, attach_ok=False):
        if "table" in p or "no quoted history" in p or "signature" in p:
            continue
        out.append(re.split(r";\s*(?=.*--)", p)[0])
    return out


def index_raw(c, folder, uidv, uid, raw, ts, seen, answered, flagged=0):
    msg = R.to_msg(raw)
    names = [R.fname(p) or "" for p in file_parts(msg)]
    body = R.body_text(msg)[:R.CFG.body_chars]
    c.execute("insert or ignore into state values(?,?)", (folder, uidv))
    cur = c.execute(
        "insert or ignore into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,"
        "answered,size,has_body,fwd) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
        (folder, uidv, uid, R.hdr(msg, "Message-ID").strip(), R.hdr(msg, "In-Reply-To").strip(),
         R.hdr(msg, "References"), ts, R.hdr(msg, "From"), R.hdr(msg, "To"), R.hdr(msg, "Cc"),
         R.hdr(msg, "Subject"), " | ".join(names), body, seen, int(flagged), answered, len(raw),
         R.forward_source(msg)))
    if cur.rowcount:
        c.execute("insert into fts(rowid,subject,frm,to_,atts,body) values(?,?,?,?,?,?)",
                  (cur.lastrowid, R.hdr(msg, "Subject"), R.hdr(msg, "From"),
                   R.hdr(msg, "To") + " " + R.hdr(msg, "Cc"), " | ".join(names), body))
    c.commit()


STATUS_RE = re.compile(rb"\b(MESSAGES|UIDNEXT|UNSEEN|UIDVALIDITY) (\d+)")


def folder_status(m, folder):
    """(messages, uidnext, unseen, uidvalidity) from STATUS: cheap, and it changes when mail comes,
    goes or is read elsewhere. None when the server does not say: the folder is then synced."""
    try:
        typ, data = m.status(R.q(folder), "(MESSAGES UIDNEXT UNSEEN UIDVALIDITY)")
    except (imaplib.IMAP4.abort, OSError):
        raise                                   # the connection: the pass connects again
    except Exception:                           # noqa: BLE001 - a server without STATUS for it
        return None
    if typ != "OK":
        return None
    got = dict(STATUS_RE.findall(b" ".join(x for x in data if isinstance(x, bytes))))
    if not got:
        return None
    return tuple(int(got.get(k, -1)) for k in (b"MESSAGES", b"UIDNEXT", b"UNSEEN", b"UIDVALIDITY"))


def drop_gone_folders(c, names):
    """Mail of folders the server no longer has (renamed or deleted in webmail or on the phone) leaves
    the index, so it shows in no search and keeps no sync busy (#48). Returns how many rows went.
    Only after a LIST that has the inbox: a failed or empty answer removes nothing."""
    if not names or not any(n.upper() == "INBOX" for n in names):
        return 0
    have = set(names)
    gone = [r[0] for r in c.execute("select folder from msgs union select folder from state").fetchall()
            if r[0] not in have and r[0].upper() != "INBOX"]
    n = 0
    for f in gone:
        ids = [r[0] for r in c.execute("select id from msgs where folder=?", (f,)).fetchall()]
        for i in ids:
            c.execute("delete from fts where rowid=?", (i,))
        c.execute("delete from msgs where folder=?", (f,))
        c.execute("delete from state where folder=?", (f,))
        n += len(ids)
    if gone:
        c.commit()
    return n


def folder_label(v):
    """A folder name the owner typed, tidied; refuses what no server takes."""
    name = " ".join(v.split()) if isinstance(v, str) else ""
    if not name:
        fail("Give the folder a name.")
    if len(name) > 60:
        fail("That folder name is too long.")
    for ch in '/\\."%*':
        if ch in name:
            fail("A folder name can't have %s in it." % ch)
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        fail("A folder name can't have %s in it." % "control characters")
    return name


def folder_sep(m):
    """The character the server puts between a folder and the folders inside it."""
    with contextlib.suppress(Exception):
        typ, data = m.list('""', '""')
        for line in data or []:
            mo = re.match(rb'\([^)]*\)\s+"(\\?.)"', line if isinstance(line, bytes) else b"")
            if mo:
                return mo.group(1).decode()[-1]
    return "/"


def said(data):
    return b" ".join(x for x in data or [] if isinstance(x, bytes)).decode("utf-8", "replace")


def list_folders(m):
    """[(name, lowercased flags)] from LIST."""
    typ, data = m.list()
    out = []
    for line in data or []:
        if isinstance(line, tuple):
            line = line[0] + b'"' + line[1].replace(b'"', b'\\"') + b'"'
        if not line:
            continue
        mo = re.match(rb'\(([^)]*)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+(.+)$', line)
        if not mo:
            continue
        name = mo.group(2).strip()
        if name.startswith(b'"') and name.endswith(b'"'):
            name = re.sub(rb"\\(.)", rb"\1", name[1:-1])
        out.append((R.mutf7_decode(name.decode("utf-8", "replace")), mo.group(1).decode().lower()))
    return out


def folder_tree(found, taken):
    """[(folder, label, depth)] for the server folders that hold mail and are not in `taken`, parents first."""
    every = [n for n, _ in found]
    names = [n for n, flags in found if n not in taken and n.upper() != "INBOX" and n.lower() not in LIST_KEYS
             and not any(x in flags.split() for x in VIEW_FLAGS)]

    def parent(n, among):
        return max((p for p in among if p != n and n.startswith(p) and n[len(p):len(p) + 1] in ("/", ".")
                    and n[len(p) + 1:]), key=len, default=None)
    kids = {}
    for n in names:
        kids.setdefault(parent(n, names), []).append(n)
    out = []

    def walk(p, depth):
        for n in sorted(kids.get(p, []), key=str.lower):
            above = parent(n, every)
            out.append((n, n[len(above) + 1:] if above else n, depth))
            walk(n, depth + 1)
    walk(None, 0)
    return out


def mac_notice(title, body):
    """A notice sent by the app itself, so it carries the app's icon and a click on it brings the
    app to the front (one sent through osascript shows Script Editor's icon). True when it was
    handed to macOS. Only the built app: run from the source, "the app" is Python.

    The app needs no certificate for this: an ad-hoc signed build is asked like any other (seen on
    macOS 26), as long as it runs from a normal place such as /Applications. macOS asks the owner
    once. If the answer was no, or the question was closed without an answer, macOS keeps "not
    allowed" and refuses with "Notifications are not allowed for this application"; the notice then
    goes out through osascript, and Settings shows how to allow them (mac_notice_state)."""
    if not getattr(sys, "frozen", False):
        return False
    try:
        import UserNotifications as UN
        center = UN.UNUserNotificationCenter.currentNotificationCenter()
        if center is None:
            return False
        with MAC_NOTICES.lock:
            if MAC_NOTICES.delegate is None:
                MAC_NOTICES.delegate = mac_notice_delegate(UN)
                center.setDelegate_(MAC_NOTICES.delegate)

        def show():
            c = UN.UNMutableNotificationContent.alloc().init()
            c.setTitle_(title or APP_NAME)
            c.setBody_(body)
            req = UN.UNNotificationRequest.requestWithIdentifier_content_trigger_(secrets.token_hex(8), c, None)
            center.addNotificationRequest_withCompletionHandler_(req, lambda err: None)

        def answered(ok, err):
            # macOS asks the owner once; later calls come straight back with that answer
            with contextlib.suppress(Exception):
                if ok:
                    show()
                elif err is not None:       # not allowed in System Settings
                    osa_notice(title, body)

        center.requestAuthorizationWithOptions_completionHandler_(
            UN.UNAuthorizationOptionAlert | UN.UNAuthorizationOptionSound, answered)
        return True
    except Exception:       # noqa: BLE001 - the old way still works
        return False


MAC_NOTICES = SimpleNamespace(delegate=None, lock=threading.Lock())
MAC_NOTICE_PAGE = "x-apple.systempreferences:com.apple.Notifications-Settings.extension"


def mac_notice_state():
    """What macOS has for this app's notices: "on", "off" (the owner said no, or closed the question),
    "ask" (not asked yet), or "" when it cannot be told (not the built Mac app)."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return ""
    try:
        import UserNotifications as UN
        center = UN.UNUserNotificationCenter.currentNotificationCenter()
        if center is None:
            return ""
        got, box = threading.Event(), []

        def answer(settings):
            with contextlib.suppress(Exception):
                box.append(int(settings.authorizationStatus()))
            got.set()

        center.getNotificationSettingsWithCompletionHandler_(answer)
        if not got.wait(3) or not box:
            return ""
        return {0: "ask", 1: "off"}.get(box[0], "on")
    except Exception:       # noqa: BLE001 - only a hint in Settings
        return ""


def mac_notice_page():
    """Open System Settings at Notifications, at this app's own row where macOS supports that."""
    page = MAC_NOTICE_PAGE
    with contextlib.suppress(Exception):
        from Foundation import NSBundle
        ident = NSBundle.mainBundle().bundleIdentifier()
        if ident:
            page += "?id=" + str(ident)
    subprocess.run(["open", page], timeout=10, capture_output=True)


def mac_notice_delegate(UN):
    """Without it macOS keeps a notice back while the app is in front (the one Settings shows when
    notices are switched on)."""
    import objc
    from Foundation import NSObject

    class RagdollNotices(NSObject, protocols=[objc.protocolNamed("UNUserNotificationCenterDelegate")]):
        def userNotificationCenter_willPresentNotification_withCompletionHandler_(self, center, note, done):
            done(UN.UNNotificationPresentationOptionBanner | UN.UNNotificationPresentationOptionList)
    return RagdollNotices.alloc().init()


def osa_notice(title, body):
    subprocess.run(["osascript", "-e", "on run argv",
                    "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
                    "-e", "end run", title or APP_NAME, body], timeout=10, capture_output=True)


def system_notice(title, body):
    """Tell the owner about new mail outside the window. Never raises."""
    try:
        if sys.platform == "darwin":
            if not mac_notice(title, body):
                osa_notice(title, body)
        elif sys.platform == "win32":
            if WINDOW.hwnd:                     # the taskbar button flashes until the window is opened
                import ctypes

                class Flash(ctypes.Structure):
                    _fields_ = [("size", ctypes.c_uint), ("hwnd", ctypes.c_void_p), ("flags", ctypes.c_uint),
                                ("count", ctypes.c_uint), ("timeout", ctypes.c_uint)]
                info = Flash(ctypes.sizeof(Flash), WINDOW.hwnd, 0x3 | 0xC, 0, 0)
                ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", "-a", APP_NAME, title or APP_NAME, body], timeout=10,
                           capture_output=True)
    except Exception:       # noqa: BLE001 - a notice that can't be shown is not an error
        pass


def detect_folders(found):
    out = {"inbox": "INBOX"}
    for key in ("sent", "drafts", "trash", "junk", "archive"):
        flag = "\\" + key
        hit = next((n for n, fl in found if flag in fl.split()), None)
        if not hit:
            names = {n.lower(): n for n, _ in found}
            hit = next((names[x] for x in FOLDER_NAMES[key] if x in names), None)
        if hit:
            out[key] = hit
    out.setdefault("archive", "Archive")
    return out


# ------------------------------------------------------------------ HTTP server

TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
         ".json": "application/json", ".woff2": "font/woff2"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob: https: http:; font-src 'self' data:; connect-src 'self'; "
       "frame-src 'self' about: data:; media-src 'self' data:; object-src 'none'; base-uri 'none'; "
       "form-action 'none'")


def make_handler(backend, token):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "ragdoll"

        def log_message(self, *args):
            pass

        def host_ok(self):
            port = self.server.server_address[1]
            return self.headers.get("Host") in ("127.0.0.1:%d" % port, "localhost:%d" % port)

        def send(self, code, body, ctype="application/json; charset=utf-8", extra=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if self.close_connection:
                self.send_header("Connection", "close")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.host_ok():
                return self.send(403, b"forbidden", "text/plain")
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                path = "/index.html"
            full = os.path.realpath(os.path.join(STATIC, urllib.parse.unquote(path).lstrip("/")))
            if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
                return self.send(404, b"not found", "text/plain")
            with open(full, "rb") as f:
                body = f.read()
            ext = os.path.splitext(full)[1].lower()
            extra = [("Content-Security-Policy", CSP)] if ext == ".html" else []
            self.send(200, body, TYPES.get(ext, "application/octet-stream"), extra)

        def do_POST(self):
            # On a kept-alive connection an unread body would be parsed as the next request,
            # so every early answer either reads the body or closes the connection.
            try:
                n = max(0, int(self.headers.get("Content-Length") or 0))
            except ValueError:
                self.close_connection = True
                return self.send(400, b'{"ok":false,"error":"bad request"}')
            if not self.host_ok() or not secrets.compare_digest(self.headers.get("X-Token", ""), token):
                self.close_connection = True
                return self.send(403, b'{"ok":false,"error":"forbidden"}')
            if n > 200 * 1024 * 1024:
                self.close_connection = True
                return self.send(413, b'{"ok":false,"error":"That file is too big."}')
            data = self.rfile.read(n) if n else b""
            path = urllib.parse.urlparse(self.path).path
            if path == "/upload":
                name = urllib.parse.unquote(self.headers.get("X-Name", "file"))
                try:
                    out = {"ok": True, "data": backend.upload(name, data)}
                except OSError as e:
                    out = {"ok": False, "error": str(e)}
                return self.send(200, json.dumps(out, ensure_ascii=False).encode())
            if not path.startswith("/api/"):
                return self.send(404, b'{"ok":false,"error":"not found"}')
            try:
                args = json.loads(data or b"{}")
            except ValueError:
                return self.send(400, b'{"ok":false,"error":"bad request"}')
            code, out = backend.call(path[5:], args)
            self.send(code, json.dumps(out, ensure_ascii=False).encode())

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True


# ------------------------------------------------------------------ window

def system_dark():
    try:
        if sys.platform == "darwin":
            r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True,
                               timeout=5)
            return "dark" in r.stdout.lower()
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        pass
    return False


WINDOW = SimpleNamespace(w=None, hwnd=0, tokens=[])


def bring_front():
    """The window to the front, as when its Dock or taskbar icon is clicked."""
    w = WINDOW.w
    if w is None:
        return
    with contextlib.suppress(Exception):
        w.restore()
    with contextlib.suppress(Exception):
        w.show()
    if sys.platform == "darwin":
        with contextlib.suppress(Exception):
            import AppKit
            from PyObjCTools import AppHelper
            AppHelper.callAfter(lambda: AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True))
    elif sys.platform == "win32" and WINDOW.hwnd:
        with contextlib.suppress(Exception):
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(WINDOW.hwnd)


_DRAG = SimpleNamespace(source=None)


def drag_out(path):
    """Start a Finder drag of this file from where the mouse is: the page asks while the button is held on an
    attachment, and a drop on the desktop or a folder copies the file there. macOS only; False when no drag
    could start (no window, the button already let go)."""
    if sys.platform != "darwin" or WINDOW.w is None:
        return False
    try:
        import objc
        from AppKit import NSApp, NSDraggingItem, NSMakeRect, NSObject, NSURL, NSWorkspace
        from PyObjCTools import AppHelper
    except ImportError:
        return False
    if _DRAG.source is None:
        class RagdollDragSource(NSObject, protocols=[objc.protocolNamed("NSDraggingSource")]):
            def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
                return 1                                # NSDragOperationCopy: the file stays in the mail
        _DRAG.source = RagdollDragSource.alloc().init()
    done, ok = threading.Event(), []

    def go():
        try:
            ev = NSApp.currentEvent()
            win = ev.window() if ev is not None else None
            if ev is None or win is None or ev.type() not in (1, 6):    # left mouse down / dragged
                return
            view = win.contentView()
            p = view.convertPoint_fromView_(ev.locationInWindow(), None)
            pic = NSWorkspace.sharedWorkspace().iconForFile_(path)
            pic.setSize_((48, 48))
            item = NSDraggingItem.alloc().initWithPasteboardWriter_(NSURL.fileURLWithPath_(path))
            item.setDraggingFrame_contents_(NSMakeRect(p.x - 24, p.y - 24, 48, 48), pic)
            view.beginDraggingSessionWithItems_event_source_([item], ev, _DRAG.source)
            ok.append(True)
        except Exception:
            pass
        finally:
            done.set()
    AppHelper.callAfter(go)
    done.wait(3)
    return bool(ok)


def poke_page():
    """Ask the page to look now instead of at its next poll."""
    if WINDOW.w is not None:
        with contextlib.suppress(Exception):
            # run_js hands the line to the page as it is; evaluate_js wraps it in eval(), which the
            # page's Content-Security-Policy (script-src 'self') refuses
            run = getattr(WINDOW.w, "run_js", None) or WINDOW.w.evaluate_js
            run("window.ragdollPoll && window.ragdollPoll()")


def dock_badge(n):
    """The inbox's unread count on the Mac Dock icon, nothing when 0. True when it was asked for."""
    if sys.platform != "darwin" or WINDOW.w is None:        # in the browser there is no Dock icon of ours
        return False
    try:
        import AppKit
        from PyObjCTools import AppHelper

        def go():
            with contextlib.suppress(Exception):
                AppKit.NSApplication.sharedApplication().dockTile().setBadgeLabel_(str(n) if n > 0 else "")
        AppHelper.callAfter(go)         # AppKit wants it on the main thread
        return True
    except Exception:
        return False


def mac_clear_titlebar(w):
    """macOS 26 paints the title bar container opaque even when it is 'transparent'; clear it."""
    try:
        box = w.standardWindowButton_(0).superview().superview()       # NSTitlebarContainerView
    except Exception:
        return
    import warnings
    warnings.filterwarnings("ignore", message="PyObjCPointer created")
    stack = [box]
    while stack:
        v = stack.pop()
        layer = v.layer()
        if layer is not None and layer.backgroundColor() is not None and "Widget" not in v.className():
            layer.setBackgroundColor_(None)
        stack.extend(v.subviews())


def mac_full_frame_rate():
    """WebKit draws a page at most 60 times a second unless told otherwise, also on a 120 Hz screen (MacBook Pro):
    scrolling and every animation then look less smooth than in other Mac apps. The switch only counts when it is
    set before the web view is made, and pywebview makes it, so its WebKit is handed a configuration that has it off.
    Anything unexpected leaves pywebview as it is."""
    try:
        import WebKit
        import webview.platforms.cocoa as cocoa
        feat = next((f for f in WebKit.WKPreferences._features()
                     if f.key() == "PreferPageRenderingUpdatesNear60FPSEnabled"), None)
        if feat is None or getattr(cocoa.WebKit, "_ragdoll", False):
            return

        class Config:
            @staticmethod
            def alloc():
                return Config()

            def init(self):
                c = WebKit.WKWebViewConfiguration.alloc().init()
                with contextlib.suppress(Exception):
                    c.preferences()._setEnabled_forFeature_(False, feat)
                return c

        class Kit:
            _ragdoll = True
            WKWebViewConfiguration = Config

            def __getattr__(self, name):
                return getattr(WebKit, name)

        cocoa.WebKit = Kit()
    except Exception:       # noqa: BLE001
        pass


def mac_titlebar(window):
    """Content runs under the title bar; an empty unified toolbar centres the traffic lights in the app's top bar."""
    try:
        import AppKit
        from PyObjCTools import AppHelper
    except ImportError:
        return

    def go():
        w = window.native
        if w is None:
            return
        w.setStyleMask_(w.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
        w.setTitlebarAppearsTransparent_(True)
        w.setTitleVisibility_(AppKit.NSWindowTitleHidden)
        w.setMovableByWindowBackground_(False)
        if w.toolbar() is None:
            bar = AppKit.NSToolbar.alloc().initWithIdentifier_("ragdoll-mail")
            bar.setShowsBaselineSeparator_(False)
            w.setToolbar_(bar)
            w.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnified)
        mac_clear_titlebar(w)
        if not WINDOW.tokens:
            nc = AppKit.NSNotificationCenter.defaultCenter()

            def watch(name, fn):
                WINDOW.tokens.append(nc.addObserverForName_object_queue_usingBlock_(
                    getattr(AppKit, name, name), w, None, lambda _n: fn()))

            def toolbar(visible):
                if w.toolbar() is not None:
                    w.toolbar().setVisible_(visible)        # full screen has no traffic lights to make room for
                mac_clear_titlebar(w)
            for name in ("NSWindowDidBecomeKeyNotification", "NSWindowDidResignKeyNotification",
                         "NSWindowDidEndLiveResizeNotification", "NSWindowDidChangeScreenNotification"):
                watch(name, lambda: mac_clear_titlebar(w))
            watch("NSWindowWillEnterFullScreenNotification", lambda: toolbar(False))
            watch("NSWindowDidExitFullScreenNotification", lambda: toolbar(True))
    AppHelper.callAfter(go)


def win_hwnd(window):
    try:
        return int(window.native.Handle.ToInt64())
    except Exception:
        try:
            import ctypes
            return ctypes.windll.user32.FindWindowW(None, APP_NAME) or 0
        except Exception:
            return 0


def hex_ref(c):
    """'#RRGGBB' -> Windows COLORREF (0x00BBGGRR)."""
    c = (c or "").lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        return None
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return r | g << 8 | b << 16


def window_theme(dark, bg=None, text=None):
    """Match the native title bar to the app theme (it can differ from the system's)."""
    w = WINDOW.w
    if w is None:
        return
    if sys.platform == "darwin":
        try:
            import AppKit
            from PyObjCTools import AppHelper
        except ImportError:
            return

        def go():
            nw = w.native
            if nw is None:
                return
            nw.setAppearance_(AppKit.NSAppearance.appearanceNamed_(
                AppKit.NSAppearanceNameDarkAqua if dark else AppKit.NSAppearanceNameAqua))
            ref = (bg or "").lstrip("#")
            if re.fullmatch(r"[0-9a-fA-F]{6}", ref):
                nw.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
                    int(ref[0:2], 16) / 255, int(ref[2:4], 16) / 255, int(ref[4:6], 16) / 255, 1.0))
            mac_clear_titlebar(nw)
        AppHelper.callAfter(go)
    elif sys.platform == "win32":
        import ctypes
        hwnd = WINDOW.hwnd or win_hwnd(w)
        WINDOW.hwnd = hwnd
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi

        def put(attr, value):
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
        if put(20, 1 if dark else 0):                    # DWMWA_USE_IMMERSIVE_DARK_MODE
            put(19, 1 if dark else 0)                    # same, Windows 10 before 20H1
        for attr, colour in ((35, bg), (36, text)):      # caption colour, caption text (Windows 11)
            ref = hex_ref(colour)
            if ref is not None:
                put(attr, ref)


def run_window(url, home):
    import webview
    dark = system_dark()
    w = webview.create_window(APP_NAME, url, width=1280, height=820, min_size=(880, 560),
                              background_color="#191919" if dark else "#FFFFFF", text_select=True)
    WINDOW.w = w
    if sys.platform == "darwin":
        mac_full_frame_rate()
        w.events.before_show += lambda: mac_titlebar(w)
        w.events.shown += lambda: mac_titlebar(w)
    elif sys.platform == "win32":
        w.events.shown += lambda: window_theme(dark, "#191919" if dark else "#FFFFFF",
                                               "#E8E8E6" if dark else "#191919")
    # pywebview sets this as the Dock icon on macOS, over the bundle's .icns, so give it the Mac one.
    icon = os.path.join(STATIC, "logo-mac.png" if sys.platform == "darwin" else "logo.png")
    webview.start(private_mode=False, storage_path=os.path.join(home, "webview"),
                  icon=icon if os.path.exists(icon) else None)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ragdoll app", description="ragdoll-mail desktop app")
    ap.add_argument("--demo", action="store_true", help="a made-up mailbox; no account needed")
    ap.add_argument("--demo-lang", choices=sorted(DEMO_SETS), help="the demo mailbox in English or Chinese "
                    "(default: the system's language)")
    ap.add_argument("--browser", action="store_true", help="open in the default browser, not a window")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version="ragdoll-mail " + __version__)
    a = ap.parse_args(argv)
    # a plain kill still closes the mailbox and removes the demo's temp folder
    with contextlib.suppress(ValueError, OSError):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        backend = Backend(demo=a.demo, demo_lang=demo_lang(a.demo_lang) if a.demo else "en")
    except R.IndexTooNew as e:
        return too_new(str(e), a.browser)
    token = os.environ.get("RAGDOLL_APP_TOKEN") or secrets.token_urlsafe(24)
    srv = Server(("127.0.0.1", a.port), make_handler(backend, token))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/#t=%s" % (srv.server_address[1], token)
    use_window = not a.browser
    if use_window:
        try:
            import webview  # noqa: F401
        except ImportError:
            use_window = False
            print("pywebview is not installed (pip install pywebview); opening the browser instead.",
                  file=sys.stderr)
    try:
        with R.running("app"):
            if use_window:
                run_window(url, R.CFG.home)
            else:
                print("ragdoll-mail is running at http://127.0.0.1:%d  (Ctrl+C stops it)" % srv.server_address[1])
                if not a.no_open:
                    webbrowser.open(url)
                while True:
                    time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        backend.close()
        srv.shutdown()
        if a.demo:
            shutil.rmtree(R.CFG.home, ignore_errors=True)


def too_new(text, browser=False):
    """This app is older than the ragdoll that last wrote the index: say so, and how to update."""
    print(text, file=sys.stderr)
    page = ("<!doctype html><meta charset=utf-8><body style='font:15px -apple-system,Segoe UI,sans-serif;"
            "padding:40px;line-height:1.6'><h2 style='font-weight:500'>Please update Ragdoll Mail</h2>"
            "<p>%s</p>" % htmlmod.escape(text))
    if browser:
        return 1
    try:
        import webview
    except ImportError:
        return 1
    webview.create_window(APP_NAME, html=page, width=560, height=300)
    webview.start()
    return 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["cli"]:       # the built app is also the ragdoll command: <app> cli search ...
        sys.exit(R.main(sys.argv[2:]))
    sys.exit(main())
