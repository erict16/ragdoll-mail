#!/usr/bin/env python3
"""ragdoll-mail desktop app: a window over ragdoll's mailbox and search index.

    ragdoll app                 open the app (pywebview window, else the default browser)
    python ragdoll_app.py --demo --browser
                                a made-up mailbox in the browser, no account needed

The page (app/) talks to a small HTTP server on 127.0.0.1. The server answers only requests
that carry this run's random token, and only for the 127.0.0.1 host name (no DNS rebinding).
"""
import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import html as htmlmod
import imaplib
import json
import mimetypes
import os
import re
import secrets
import shutil
import smtplib
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
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
RELEASES_PAGE = "https://github.com/erict16/ragdoll-mail/releases/latest"
FOLDER_KEYS = ("inbox", "drafts", "sent", "archive", "trash", "junk")
FOLDER_NAMES = {
    "sent": ("sent messages", "sent", "sent items", "sent mail", "[gmail]/sent mail", "已发送", "已发送邮件"),
    "drafts": ("drafts", "draft", "[gmail]/drafts", "草稿箱", "草稿"),
    "trash": ("deleted messages", "trash", "deleted items", "deleted", "[gmail]/trash", "已删除", "已删除邮件"),
    "junk": ("junk", "spam", "junk e-mail", "junk email", "[gmail]/spam", "垃圾邮件", "垃圾箱"),
    "archive": ("archive", "archives", "归档"),
}
PROVIDERS = {       # domain -> (imap host, smtp host); all on 993 / 465
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
}


class ApiError(Exception):
    pass


def fail(msg):
    raise ApiError(msg)


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
        subprocess.Popen(["open", "-R", path] if reveal else ["open", path])
    elif sys.platform == "win32":
        if reveal:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            os.startfile(path)                                  # noqa: S606
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
        if p.is_multipart() or not p.get("Content-ID") or p.get_content_maintype() != "image":
            continue
        data = p.get_payload(decode=True) or b""
        if len(data) <= 8 * 1024 * 1024:
            out[p.get("Content-ID").strip().strip("<>")] = data_uri(p.get_content_type(), data)
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


def part_info(k, p):
    name = R.fname(p) or "attachment"
    try:
        size = len(R.part_bytes(p))
    except Exception:
        size = 0
    return {"i": k, "name": name, "size": size, "type": mimetypes.guess_type(name)[0] or p.get_content_type()}


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

def demo_png(rgb, w=240, h=120):
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def demo_pdf(title):
    text = "BT /F1 18 Tf 72 720 Td (%s) Tj ET" % title.replace("(", "").replace(")", "")
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            "<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text),
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for k, o in enumerate(objs, 1):
        offs.append(len(out))
        out += "%d 0 obj\n%s\nendobj\n" % (k, o)
    xref = len(out)
    out += "xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + "".join("%010d 00000 n \n" % x for x in offs)
    out += "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out.encode()


ME = ("Alex Morgan", "you@example.com")
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
     "北京ABC项目 — 图纸确认",
     "Alex 你好，\n\n附件是北京ABC项目的最新图纸，请在周五前确认尺寸和接线方式。如有问题请随时联系我。\n\n谢谢！\n李明",
     [("ABC项目_总装图_rev3.pdf", "pdf")], False, None, None),
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
    ("inbox", 60 * 140, ("王芳", "wang.fang@example.cn"), [ME], [],
     "下周培训安排",
     "各位好，\n\n下周三下午两点在三楼会议室进行产品培训，请准时参加。\n\n王芳", [], True, None, None),
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
     "Re: 北京ABC项目 — 图纸确认", "李明你好，\n\n图纸已收到，尺寸没有问题。接线方式我们明天确认后回复。\n\nAlex",
     [], True, None, None),
    ("archive", 60 * 24 * 12, ("Acme Industrial", "news@acme-industrial.com"), [ME], [],
     "Acme Industrial newsletter — October", "Our October news: new plant, new products, and a new website.",
     [], True, None, None),
    ("archive", 60 * 24 * 20, ("Tom Becker", "tom.becker@acme-industrial.com"), [ME], [],
     "Shipping marks", "Hi Alex, please use the attached shipping marks on every crate.\n\nTom",
     [("shipping_marks.pdf", "pdf")], True, None, None),
    ("trash", 60 * 24 * 3, ("Deals Daily", "offers@example.net"), [ME], [],
     "50% off everything this weekend", "Don't miss out!", [], True, None, None),
]


def demo_message(folder, ts, frm, to, cc, subject, body, atts, mid, irt, refs, inline=False):
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
    msg.set_content(body)
    html = R.text_to_html(body)
    if inline:
        html += '<div><br></div><div><img src="cid:photo1@demo" width="240" height="120" alt="site photo"></div>'
    msg.add_alternative('<div style="font-family:Helvetica,Arial,sans-serif;font-size:14px">%s</div>' % html,
                        subtype="html")
    if inline:
        msg.get_body(("html",)).add_related(demo_png((46, 125, 120)), "image", "png", cid="<photo1@demo>")
    for name, kind in atts:
        if kind == "pdf":
            msg.add_attachment(demo_pdf(name), "application", "pdf", filename=name)
        else:
            msg.add_attachment(b"PK\x03\x04 demo", "application", "octet-stream", filename=name)
    return msg.as_bytes(policy=R.OUT_POLICY)


# ------------------------------------------------------------------ backend

class Backend:
    def __init__(self, demo=False):
        self.demo = demo
        self.lock = threading.RLock()           # the action IMAP connection
        self.dblock = threading.RLock()         # the request db connection
        self.m = None
        self.m_used = 0
        self.rev = 1
        self.sync = {"running": False, "error": None, "last": None}
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.contacts = (0, {})
        self.update = None
        self.server_folders = None
        self.made = set()                       # files the app wrote (only these may be revealed)
        self.demo_raw = {}
        self.thread = None
        if demo:
            self.make_demo()
        self.c = R.db()
        if not demo:
            self.prune_cache()
            threading.Thread(target=self.check_update, daemon=True).start()
            self.start_sync()

    # ---- plumbing

    def call(self, name, args):
        fn = getattr(self, "api_" + name, None)
        if fn is None:
            return 404, {"ok": False, "error": "unknown call %s" % name}
        try:
            return 200, {"ok": True, "data": fn(args or {})}
        except ApiError as e:
            return 200, {"ok": False, "error": str(e)}
        except SystemExit as e:
            return 200, {"ok": False, "error": friendly(e)}
        except (imaplib.IMAP4.error, smtplib.SMTPException, OSError, LookupError) as e:
            return 200, {"ok": False, "error": friendly(e)}

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
                "flagged": bool(r["flagged"]), "answered": bool(r["answered"]),
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

    # ---- sync

    def sync_folders(self):
        fs = list(R.CFG.sync_folders)
        for k in ("archive", "trash"):
            f = R.CFG.folders.get(k)
            if f and f not in fs:
                fs.append(f)
        return fs

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
                self.sync["error"] = None
                self.sync["last"] = int(time.time())
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
        if m is not None:
            with contextlib.suppress(Exception):
                m.logout()

    @staticmethod
    def fingerprint(c):
        return tuple(c.execute("select count(*), coalesce(max(id),0), coalesce(sum(seen),0), "
                               "coalesce(sum(has_body),0), coalesce(sum(answered),0), coalesce(sum(flagged),0) "
                               "from msgs").fetchone())

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
                latest = R.update_state().get("latest") or {}
                if latest.get("behind") and not latest.get("ahead"):
                    self.update = {"version": latest.get("version"), "command": "ragdoll update"}
        except Exception:
            pass

    # ---- api: app state

    def api_boot(self, a):
        return {"configured": configured() or self.demo, "demo": self.demo, "user": R.CFG.user,
                "name": R.CFG.name, "version": __version__, "platform": sys.platform,
                "folders": self.folder_counts(), "theme": self.prefs().get("theme", "system")}

    def folder_counts(self):
        out = []
        for k in ("inbox", "drafts", "sent", "archive", "trash"):
            f = R.CFG.folders.get(k)
            if not f:
                continue
            r = self.q("select count(*) n, coalesce(sum(seen=0),0) u from msgs where folder=?", (f,))[0]
            out.append({"key": k, "total": r["n"], "unread": r["u"]})
        return out

    def api_status(self, a):
        return {"rev": self.rev, "syncing": self.sync["running"], "error": self.sync["error"],
                "last": self.sync["last"], "folders": self.folder_counts(), "update": self.update}

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
        os.makedirs(R.CFG.home, exist_ok=True)
        with open(os.path.join(R.CFG.home, "app.json"), "w", encoding="utf-8") as f:
            json.dump(p, f)
        return p

    # ---- api: lists and reading

    def api_list(self, a):
        key = a.get("folder") or "inbox"
        folder = R.CFG.folders.get(key, key)
        limit = max(1, min(int(a.get("limit") or 100), 500))
        offset = max(0, int(a.get("offset") or 0))
        rows = self.q("select * from msgs where folder=? order by ts desc, uid desc limit ? offset ?",
                      (folder, limit, offset))
        return {"rows": [self.row_json(r) for r in rows], "more": len(rows) == limit}

    def api_search(self, a):
        text = (a.get("q") or "").strip()
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
        return {"rows": [self.row_json(r) for r in rows if r["folder"] not in skip]}

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
        self.set_flag(a["ids"], a.get("flag", "seen"), bool(a.get("on", True)))
        return {}

    def api_move(self, a):
        """Move mails to archive, trash or inbox (dest is the folder key)."""
        dest_key = a["to"]
        if dest_key not in ("archive", "trash", "inbox", "junk"):
            fail("can't move to %s" % dest_key)
        dest = R.CFG.folders.get(dest_key) or ("Archive" if dest_key == "archive" else None)
        if not dest:
            fail("No %s folder is set." % dest_key)
        by = {}
        for i in a["ids"]:
            f, u = self.parse(i)
            if f != dest:
                by.setdefault(f, []).append(u)
        if self.demo:
            for f, uids in by.items():
                for u in uids:
                    r = self.q("select * from msgs where folder=? and uid=?", (f, u))
                    raw = self.demo_raw.pop((f, u), None)
                    if r and raw:
                        self.demo_insert(dest, raw, r[0]["ts"], r[0]["seen"], r[0]["answered"])
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

    def folders(self, m):
        if self.server_folders is None:
            self.server_folders = [n for n, _ in list_folders(m)]
        return self.server_folders

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

    def api_window_theme(self, a):
        window_theme(bool(a.get("dark")), a.get("bg"), a.get("text"))
        return {}

    def api_contacts(self, a):
        q = (a.get("q") or "").strip().lower()
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
                        "refs": R.hdr(msg, "References").strip(),
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
                                       "use_signature", "irt", "refs")}
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
        folder, uid = self.parse(a["id"])
        if folder != R.CFG.folders["drafts"]:
            fail("Only drafts can be sent.")
        if self.demo:
            raw = self.demo_raw.get((folder, uid))
            if raw is None:
                fail("The draft is gone.")
            msg = R.to_msg(raw)
            self.demo_delete(a["id"])
            del msg["Bcc"]
            self.demo_insert(R.CFG.folders["sent"], msg.as_bytes(policy=R.OUT_POLICY), int(time.time()), 1, 0)
            irt = R.hdr(msg, "In-Reply-To").strip()
            if irt:
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

    # ---- settings and setup

    def api_settings(self, a):
        return {"name": R.CFG.name, "user": R.CFG.user, "imap_host": R.CFG.imap.get("host", ""),
                "imap_port": R.CFG.imap.get("port", 993), "smtp_host": R.CFG.smtp.get("host", ""),
                "smtp_port": R.CFG.smtp.get("port", 465), "require_cc": ", ".join(R.CFG.require_cc or []),
                "signature": self.signature(), "has_password": self.has_password(),
                "password_env": os.environ.get(R.CFG.password_env) is not None and not self.demo,
                "folders": dict(R.CFG.folders), "config": config_path(), "demo": self.demo}

    def has_password(self):
        if self.demo:
            return True
        if os.environ.get(R.CFG.password_env):
            return True
        return bool(R.CFG.user and R.keychain_get(R.CFG.user))

    def api_guess_servers(self, a):
        dom = (a.get("user") or "").rpartition("@")[2].lower()
        if dom in PROVIDERS:
            i, s = PROVIDERS[dom]
            return {"imap_host": i, "smtp_host": s}
        return {"imap_host": "imap." + dom if dom else "", "smtp_host": "smtp." + dom if dom else ""}

    def api_test(self, a):
        """Sign in to IMAP and SMTP with these settings; find the special folders."""
        user = (a.get("user") or "").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", user):
            fail("Enter a full email address.")
        pw = a.get("password") or (os.environ.get(R.CFG.password_env) if user == R.CFG.user else None) \
            or R.keychain_get(user)
        if not pw:
            fail("Enter the password.")
        if self.demo:
            return {"folders": dict(R.CFG.folders)}
        ihost, iport = (a.get("imap_host") or "").strip(), int(a.get("imap_port") or 993)
        shost, sport = (a.get("smtp_host") or "").strip(), int(a.get("smtp_port") or 465)
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
            s = smtplib.SMTP_SSL(shost, sport, timeout=20)
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
        if "require_cc" in a:
            raw["require_cc"] = [x.lower() for _, x in people_in(R.split_list(a["require_cc"]))]
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
        d = json.loads(json.dumps(R.DEFAULTS))
        d.update({"user": ME[1], "name": ME[0], "data_dir": home, "imap": {"host": "demo", "port": 993},
                  "smtp": {"host": "demo", "port": 465}})
        sig = os.path.join(home, "signature.html")
        with open(sig, "w", encoding="utf-8") as f:
            f.write('<div style="color:#6b6b6b;font-size:13px">Alex Morgan<br>Sales Engineer · Example Co.'
                    '<br>+1 555 0100</div>')
        d["signature"] = sig
        R.CFG = R.Cfg(d)
        self.c = R.db()
        now = int(time.time())
        mids = {}
        for k, (fk, ago, frm, to, cc, subj, body, atts, seen, thread, key) in enumerate(DEMO):
            ts = now - ago * 60
            mid = "<demo-%d@example.com>" % k
            irt = refs = None
            if thread and thread in mids:
                irt = mids[thread]
                refs = irt
            if thread:
                mids[thread] = mid
            raw = demo_message(fk, ts, frm, to, cc, subj, body, atts, mid, irt, refs,
                               inline=subj.startswith("Re: Site visit"))
            self.demo_insert(R.CFG.folders[fk], raw, ts, int(seen), int(fk == "inbox" and thread == "lunch"))
        self.demo_order_threads()

    def demo_order_threads(self):
        # the demo list is made oldest-thread-first above; nothing else to do, kept for clarity
        return

    def demo_insert(self, folder, raw, ts, seen, answered):
        with self.dblock:
            r = self.c.execute("select coalesce(max(uid),0)+1 from msgs where folder=?", (folder,)).fetchone()
            uid = r[0]
            index_raw(self.c, folder, 1, uid, raw, ts, seen, answered)
        self.demo_raw[(folder, uid)] = raw
        return uid

    def demo_delete(self, i):
        f, u = self.parse(i)
        self.demo_raw.pop((f, u), None)
        with self.dblock:
            self.db_delete(i)

    def close(self):
        self.stopping.set()
        self.wake.set()
        self.drop()


def app_problems(msg, reply):
    """ragdoll's pre-send check, worded for the app (no CLI flags; no table-layout rules)."""
    out = []
    for p in R.check_message(msg, reply, blanks_ok=False, required_cc=True, attach_ok=False):
        if "table" in p or "no quoted history" in p or "signature" in p:
            continue
        out.append(re.split(r";\s*(?=.*--)", p)[0])
    return out


def index_raw(c, folder, uidv, uid, raw, ts, seen, answered):
    msg = R.to_msg(raw)
    names = [R.fname(p) or "" for p in file_parts(msg)]
    body = R.body_text(msg)[:R.CFG.body_chars]
    c.execute("insert or ignore into state values(?,?)", (folder, uidv))
    cur = c.execute(
        "insert or ignore into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,"
        "answered,size,has_body) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,1)",
        (folder, uidv, uid, R.hdr(msg, "Message-ID").strip(), R.hdr(msg, "In-Reply-To").strip(),
         R.hdr(msg, "References"), ts, R.hdr(msg, "From"), R.hdr(msg, "To"), R.hdr(msg, "Cc"),
         R.hdr(msg, "Subject"), " | ".join(names), body, seen, answered, len(raw)))
    if cur.rowcount:
        c.execute("insert into fts(rowid,subject,frm,to_,atts,body) values(?,?,?,?,?,?)",
                  (cur.lastrowid, R.hdr(msg, "Subject"), R.hdr(msg, "From"),
                   R.hdr(msg, "To") + " " + R.hdr(msg, "Cc"), " | ".join(names), body))
    c.commit()


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
            if not self.host_ok() or not secrets.compare_digest(self.headers.get("X-Token", ""), token):
                return self.send(403, b'{"ok":false,"error":"forbidden"}')
            n = int(self.headers.get("Content-Length") or 0)
            if n > 200 * 1024 * 1024:
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
            return ctypes.windll.user32.FindWindowW(None, "ragdoll-mail") or 0
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
    w = webview.create_window("ragdoll-mail", url, width=1280, height=820, min_size=(880, 560),
                              background_color="#191919" if dark else "#FFFFFF", text_select=True)
    WINDOW.w = w
    if sys.platform == "darwin":
        w.events.before_show += lambda: mac_titlebar(w)
        w.events.shown += lambda: mac_titlebar(w)
    elif sys.platform == "win32":
        w.events.shown += lambda: window_theme(dark, "#191919" if dark else "#FFFFFF",
                                               "#E8E8E6" if dark else "#191919")
    icon = os.path.join(STATIC, "logo.png")
    webview.start(private_mode=False, storage_path=os.path.join(home, "webview"),
                  icon=icon if os.path.exists(icon) else None)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ragdoll app", description="ragdoll-mail desktop app")
    ap.add_argument("--demo", action="store_true", help="a made-up mailbox; no account needed")
    ap.add_argument("--browser", action="store_true", help="open in the default browser, not a window")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version="ragdoll-mail " + __version__)
    a = ap.parse_args(argv)
    backend = Backend(demo=a.demo)
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


if __name__ == "__main__":
    main()
