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
import glob
import hashlib
import html as htmlmod
import html.parser as htmlparser
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
UPDATE_EVERY = 12 * 3600       # the app asks for a new release this often while it stays open (#76)
UPDATE_TICK = 5 * 60
UPDATE_FAIL_MSG = "Can't check for updates right now. Try again later."
BREW_UPGRADE = "brew upgrade --cask ragdoll-mail"


def brew_cask():
    """The Mac app was put in place by Homebrew: it updates with brew, not from the download page."""
    if sys.platform != "darwin":
        return False
    return any(os.path.isdir(os.path.join(root, "Caskroom", "ragdoll-mail"))
               for root in ("/opt/homebrew", "/usr/local"))
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
    def __init__(self, msg, detail=None):
        super().__init__(msg)
        self.detail = detail        # the server's own words: for "copy details", never the title


def fail(msg, detail=None):
    raise ApiError(msg, detail)


LANGS = ("system", "en", "zh-Hans", "zh-Hant", "ja", "ko", "es", "fr", "de")
UNDO_SECONDS = (0, 5, 10, 20, 30)
FONTS = ("system", "arial", "helvetica", "georgia", "times", "verdana", "courier", "yahei", "pingfang", "simsun")
# what each font is in CSS, as the page writes it (app.js FONTS, SAFE_FONT for "system")
FONT_CSS = {
    "system": "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', Helvetica, Arial, sans-serif",
    "arial": "Arial, Helvetica, sans-serif", "helvetica": "Helvetica, Arial, sans-serif", "georgia": "Georgia, serif",
    "times": "'Times New Roman', Times, serif", "verdana": "Verdana, Geneva, sans-serif",
    "courier": "'Courier New', Courier, monospace", "yahei": "'Microsoft YaHei', 微软雅黑, sans-serif",
    "pingfang": "'PingFang SC', 苹方, sans-serif", "simsun": "SimSun, 宋体, serif"}
BODY_FONT_RE = re.compile(r'^\s*<div data-rd-body="1" style="(font-family:[^";<>]{1,300});(font-size:\d{1,2}px)"')
FONT_SIZES = (12, 13, 14, 16, 18)
TEXT_SIZES = (12, 13, 14, 15, 16, 18, 20)


GONE_MSG = "This mail is no longer here. It may have been moved or deleted."
CONFIG_MSG = "The settings file can't be read. Sign in again to make a new one."


def explain(e):
    """(a sentence a person can act on, the kind of problem, the raw text) for an exception from
    IMAP, SMTP or ragdoll. The sentence never carries the server's raw words (#58); the kind is
    "auth", "offline", "server" or "config" (#54)."""
    if isinstance(e, R.SendLater) and e.cause is not None:     # a send that stopped before anything left: say why
        return explain(e.cause)
    s = str(e.code if isinstance(e, SystemExit) else e) or e.__class__.__name__
    low = s.lower()
    if isinstance(e, ApiError):
        return s, "server", e.detail
    if isinstance(e, smtplib.SMTPAuthenticationError) or (
            isinstance(e, imaplib.IMAP4.error) and not isinstance(e, imaplib.IMAP4.abort)
            and re.search(r"login|auth|password|credentials|invalid", low)):
        return "Sign-in failed. Check the email address and password in Settings.", "auth", s
    if "is not set and no password is saved" in s:
        return "No password saved. Add it in Settings.", "config", s
    if "no account configured" in s:
        return "No account yet. Add one in Settings.", "config", s
    if s.startswith("the settings file ") and "can't be read" in s:
        return CONFIG_MSG, "config", s
    if isinstance(e, R.IndexTooNew):
        return s, "config", s
    mo = re.match(r"no mail \S+ \(moved or deleted", s)
    if mo:
        return GONE_MSG, "server", s
    mo = re.match(r"cannot open folder (.*?): \[", s, re.S)
    if mo:
        return "Can't open the folder %s on the server." % mo.group(1), "server", s
    mo = re.match(r"the server refused the move after (\d+) mails", s)
    if mo:
        return "The server refused to move the mail (%s moved before it stopped)." % mo.group(1), "server", s
    if isinstance(e, socket.gaierror):
        return "Can't find the mail server. Check the server name and the internet connection.", "offline", s
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "The mail server did not answer in time.", "offline", s
    if isinstance(e, ssl.SSLCertVerificationError):
        return "Secure connection failed. Check the server name and port.", "server", s
    if isinstance(e, ssl.SSLError):
        return "Secure connection failed. Check the server name and port.", "offline", s
    if isinstance(e, ConnectionRefusedError):
        return "The mail server refused the connection. Check the port.", "offline", s
    if isinstance(e, imaplib.IMAP4.abort):
        return "The connection to the mail server dropped.", "offline", s
    if isinstance(e, OSError) and not isinstance(e, FileNotFoundError):
        return "Can't reach the mail server. Check the internet connection.", "offline", s
    if isinstance(e, (imaplib.IMAP4.error, smtplib.SMTPException)):
        return "The mail server refused the request.", "server", s
    return s, "server", s


def friendly(e):
    """A sentence a person can act on, for an exception from IMAP, SMTP or ragdoll."""
    return explain(e)[0]


def error_reply(e):
    """The page's answer for a call that failed: the sentence, and the raw text as detail."""
    msg, _, detail = explain(e)
    if detail and detail != msg:
        print("%s (%s)" % (msg, detail), file=sys.stderr)
        return {"ok": False, "error": msg, "detail": detail}
    return {"ok": False, "error": msg}


def config_path():
    return R.move_old_setup(R.env("CONFIG"))[0]


def cut(m):
    """Shut a connection's socket from another thread: a read that waits on it ends at once, and
    whoever waited gets an error and connects again (#40, #56)."""
    sock = getattr(m, "sock", None)
    if sock is not None:
        with contextlib.suppress(Exception):
            sock.shutdown(socket.SHUT_RDWR)


BUSY_MSG = "Waiting for another sync to finish. New mail comes in when it is done."

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
    if not reveal and R.is_program(path):
        fail("%s is a program, so it was not opened." % os.path.basename(path))
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


# A draft's HTML goes into the editor in the app's own window (not the sandboxed reading frame): only
# plain content tags and attributes pass, rebuilt from the parse so nothing the parser read differently
# survives. The page cleans it once more with the same lists (app/compose-kit.js).
EDITOR_DROP = {"script", "style", "meta", "link", "title", "base", "head", "iframe", "frame", "frameset", "object",
               "embed", "applet", "form", "input", "button", "select", "option", "textarea", "svg", "math", "video",
               "audio", "source", "track", "canvas", "template", "noscript", "portal", "dialog", "marquee", "param",
               "xml"}
EDITOR_KEEP = set("a abbr address article aside b bdi bdo big blockquote br caption center cite code col colgroup dd "
                  "del dfn div dl dt em figcaption figure font footer h1 h2 h3 h4 h5 h6 header hr i img ins kbd li "
                  "main mark nav ol p pre q s samp section small span strike strong sub sup table tbody td tfoot th "
                  "thead tr tt u ul var wbr".split())
EDITOR_VOID = {"br", "hr", "img", "col", "wbr", "meta", "link", "base", "input", "source", "track", "param", "embed"}
EDITOR_ATTRS = {"href", "src", "alt", "title", "colspan", "rowspan", "width", "height", "style", "align", "valign",
                "border", "cellpadding", "cellspacing", "bgcolor", "color", "face", "size", "dir", "start", "type",
                "data-rd-body"}
EDITOR_ATTR_ON = {"href": {"a"}, "src": {"img"}, "start": {"ol"}, "type": {"ol", "ul", "li"}, "data-rd-body": {"div"},
                  "face": {"font"}, "size": {"font"}, "color": {"font"}}
EDITOR_BAD_PROPS = {"position", "z-index", "behavior", "-moz-binding", "-webkit-user-modify", "user-modify",
                    "content", "inset"}


def safe_url(v, attr):
    s = re.sub(r"[\x00-\x20\x7f-\x9f]", "", v or "").lower()
    if attr == "src":
        return bool(re.match(r"(https?:|cid:|data:image/(png|jpe?g|gif|webp|bmp)[;,])", s))
    return bool(re.match(r"(https?:|mailto:|tel:|#)", s))


def clean_style(style):
    out, cur, depth, quote = [], "", 0, ""
    for ch in (style or "") + ";":
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == ";" and not depth and not quote:
            prop, _, val = cur.partition(":")
            prop, val = prop.strip().lower(), val.strip()
            cur = ""
            if not prop or not val or prop in EDITOR_BAD_PROPS:
                continue
            if re.search(r"(?i)expression\s*\(|javascript:|vbscript:|-moz-binding|@import", val):
                continue
            if re.search(r"(?i)url\s*\(", val) and not re.search(
                    r"(?i)url\s*\(\s*[\"']?\s*(https?:|data:image/(png|jpe?g|gif|webp|bmp)[;,]|cid:)", val):
                continue
            out.append("%s: %s" % (prop, val))
        else:
            cur += ch
    return "; ".join(out)


class _EditorHTML(htmlparser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.open = [], [], []

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag == self.skip[-1] and tag not in EDITOR_VOID:
                self.skip.append(tag)
            return
        if tag in EDITOR_DROP:
            if tag not in EDITOR_VOID:
                self.skip.append(tag)
            return
        if tag not in EDITOR_KEEP:
            return
        kept = []
        for k, v in attrs:
            k = (k or "").lower()
            v = v or ""
            if k not in EDITOR_ATTRS or (k in EDITOR_ATTR_ON and tag not in EDITOR_ATTR_ON[k]):
                continue
            if k in ("href", "src") and not safe_url(v, k):
                continue
            if k == "style":
                v = clean_style(v)
                if not v:
                    continue
            kept.append(' %s="%s"' % (k, htmlmod.escape(v, quote=True)))
        if tag == "img" and not any(x.startswith(' src="') for x in kept):
            return
        self.out.append("<%s%s>" % (tag, "".join(kept)))
        if tag not in EDITOR_VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in EDITOR_VOID and self.open and self.open[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag in EDITOR_VOID or tag not in self.open:
            return
        while self.open:
            t = self.open.pop()
            self.out.append("</%s>" % t)
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(htmlmod.escape(data, quote=False))

    def result(self):
        self.close()
        return "".join(self.out) + "".join("</%s>" % t for t in reversed(self.open))


def editor_html(html):
    """A draft's HTML made safe for the compose editor (see EDITOR_KEEP)."""
    p = _EditorHTML()
    p.feed(html or "")
    return p.result()


LINK_RE = re.compile(r"(https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]}])|([\w.+-]+@[\w-]+(?:\.[\w-]+)+)")


SYNC_EVERY = 60          # seconds between two syncs (sync_loop's wake.wait)


def sync_problem(sync):
    """What the page's problem card needs: error_kind (offline / auth / config / server, or None), last_sync (when
    mail last came in) and retry_at (the next automatic try while there is a problem), as epoch seconds or None.
    The sync loop records the kind and the next try itself (Backend.note_error, from the exception: explain());
    a sentence without them (an older state) is sorted by its words, and tried again a minute on."""
    err = sync.get("error")
    kind = None
    if err:
        kind = sync.get("kind") or (
            "config" if err.startswith(("No password saved.", "No account yet.", "The settings file")) else
            "auth" if err.startswith("Sign-in failed.") else
            "offline" if err.startswith(("Can't find the mail server.", "The mail server did not answer",
                                         "Can't reach the mail server", "The connection to the mail server dropped",
                                         "The mail server refused the connection")) else "server")
    retry = sync.get("retry_at")
    if retry is None and "kind" not in sync and sync.get("tried"):
        retry = sync["tried"] + SYNC_EVERY
    return {"error_kind": kind, "last_sync": sync.get("last"),
            "retry_at": retry if err and not sync.get("running") else None}


def linkify(escaped):
    def one(mo):
        if mo.group(1):
            u = htmlmod.unescape(mo.group(1))
            return '<a href="%s">%s</a>' % (htmlmod.escape(u), mo.group(1))
        return '<a href="mailto:%s">%s</a>' % (mo.group(2), mo.group(2))
    return LINK_RE.sub(one, escaped)


def plain_html(text):
    text = (text or "").replace("\r\n", "\n").strip("\n")
    at = R.quote_start(text)
    if at < 0:
        mo = re.search(r"(?m)^(>.*\n?){2,}\Z", text)
        at = mo.start() if mo else -1
    main, quoted = (text[:at], text[at:]) if at > 0 else (text, "")
    out = '<div class="rd-plain">%s</div>' % linkify(htmlmod.escape(main.rstrip()))
    if quoted.strip():
        out += '<div class="rd-plain rd-quote">%s</div>' % linkify(htmlmod.escape(quoted.strip()))
    return out


def has_remote(html):
    return bool(re.search(r"(?i)<img\b[^>]*\ssrc\s*=\s*[\"']?\s*(https?:)?//|url\(\s*[\"']?\s*(https?:)?//|"
                          r"\sbackground\s*=\s*[\"']?\s*https?:", html))


def file_parts(msg, light=False):
    """The mail's files, in a fixed order: not the pictures its text shows (R.is_inline with the body's
    cid: links), whatever their disposition. In a light mail, a picture too big to come with it
    (R.SHOWN_MAX) cannot show, so it is a file to open."""
    refs = R.body_refs(msg)
    return [p for p in R.attachments(msg, inline=True) if not R.is_inline(p, refs) or left_out(p, light)]


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
    out = {"i": k, "name": name, "size": size, "type": mimetypes.guess_type(name)[0] or p.get_content_type()}
    if R.is_program(disk_name(p)):
        out["program"] = True       # opening it would run it: the page offers only save and show
    return out


def mail_name(name):
    """A file's own name as a mail gives it: whole, only without control characters or line breaks."""
    return R.nfc(re.sub(r"[\x00-\x1f\x7f]+", " ", name or "")).strip()[:1000] or "attachment"


def disk_name(p):
    """The name a mail's file gets on disk."""
    name = R.safe_name(R.fname(p) or "attachment")
    if not os.path.splitext(name)[1] and p.get_content_type() != "application/octet-stream":
        name += mimetypes.guess_extension(p.get_content_type()) or ""     # so the system knows which app
    return name



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


# ---- meeting invitations (iCalendar, RFC 5545; replies per iTIP, RFC 5546)

# Outlook names Windows time zones, not IANA ones: the whole Windows -> IANA table (CLDR windowsZones, "001")
WIN_TZ = {
    "Dateline Standard Time": "Etc/GMT+12", "UTC-11": "Etc/GMT+11", "Aleutian Standard Time": "America/Adak",
    "Hawaiian Standard Time": "Pacific/Honolulu", "Marquesas Standard Time": "Pacific/Marquesas",
    "Alaskan Standard Time": "America/Anchorage", "UTC-09": "Etc/GMT+9",
    "Pacific Standard Time (Mexico)": "America/Tijuana", "UTC-08": "Etc/GMT+8",
    "Pacific Standard Time": "America/Los_Angeles", "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time (Mexico)": "America/Mazatlan", "Mountain Standard Time": "America/Denver",
    "Yukon Standard Time": "America/Whitehorse", "Central America Standard Time": "America/Guatemala",
    "Central Standard Time": "America/Chicago", "Easter Island Standard Time": "Pacific/Easter",
    "Central Standard Time (Mexico)": "America/Mexico_City", "Mexico Standard Time": "America/Mexico_City",
    "Mexico Standard Time 2": "America/Chihuahua", "Canada Central Standard Time": "America/Regina",
    "SA Pacific Standard Time": "America/Bogota", "Eastern Standard Time (Mexico)": "America/Cancun",
    "Eastern Standard Time": "America/New_York", "Haiti Standard Time": "America/Port-au-Prince",
    "Cuba Standard Time": "America/Havana", "US Eastern Standard Time": "America/Indiana/Indianapolis",
    "Turks And Caicos Standard Time": "America/Grand_Turk", "Paraguay Standard Time": "America/Asuncion",
    "Atlantic Standard Time": "America/Halifax", "Venezuela Standard Time": "America/Caracas",
    "Central Brazilian Standard Time": "America/Cuiaba", "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago", "Newfoundland Standard Time": "America/St_Johns",
    "Tocantins Standard Time": "America/Araguaina", "E. South America Standard Time": "America/Sao_Paulo",
    "SA Eastern Standard Time": "America/Cayenne", "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "Greenland Standard Time": "America/Nuuk", "Montevideo Standard Time": "America/Montevideo",
    "Magallanes Standard Time": "America/Punta_Arenas", "Saint Pierre Standard Time": "America/Miquelon",
    "Bahia Standard Time": "America/Bahia", "UTC-02": "Etc/GMT+2", "Mid-Atlantic Standard Time": "Etc/GMT+2",
    "Azores Standard Time": "Atlantic/Azores", "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "UTC": "Etc/UTC", "Coordinated Universal Time": "Etc/UTC", "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik", "Sao Tome Standard Time": "Africa/Sao_Tome",
    "Morocco Standard Time": "Africa/Casablanca", "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest", "Romance Standard Time": "Europe/Paris",
    "Central European Standard Time": "Europe/Warsaw", "W. Central Africa Standard Time": "Africa/Lagos",
    "Jordan Standard Time": "Asia/Amman", "GTB Standard Time": "Europe/Bucharest",
    "Middle East Standard Time": "Asia/Beirut", "Egypt Standard Time": "Africa/Cairo",
    "E. Europe Standard Time": "Europe/Chisinau", "Syria Standard Time": "Asia/Damascus",
    "West Bank Standard Time": "Asia/Hebron", "South Africa Standard Time": "Africa/Johannesburg",
    "FLE Standard Time": "Europe/Kyiv", "Israel Standard Time": "Asia/Jerusalem",
    "Jerusalem Standard Time": "Asia/Jerusalem", "South Sudan Standard Time": "Africa/Juba",
    "Kaliningrad Standard Time": "Europe/Kaliningrad", "Sudan Standard Time": "Africa/Khartoum",
    "Libya Standard Time": "Africa/Tripoli", "Namibia Standard Time": "Africa/Windhoek",
    "Arabic Standard Time": "Asia/Baghdad", "Turkey Standard Time": "Europe/Istanbul",
    "Arab Standard Time": "Asia/Riyadh", "Belarus Standard Time": "Europe/Minsk",
    "Russian Standard Time": "Europe/Moscow", "Russia TZ 2 Standard Time": "Europe/Moscow",
    "E. Africa Standard Time": "Africa/Nairobi", "Volgograd Standard Time": "Europe/Volgograd",
    "Iran Standard Time": "Asia/Tehran", "Arabian Standard Time": "Asia/Dubai",
    "Astrakhan Standard Time": "Europe/Astrakhan", "Azerbaijan Standard Time": "Asia/Baku",
    "Russia Time Zone 3": "Europe/Samara", "Mauritius Standard Time": "Indian/Mauritius",
    "Saratov Standard Time": "Europe/Saratov", "Georgian Standard Time": "Asia/Tbilisi",
    "Caucasus Standard Time": "Asia/Yerevan", "Afghanistan Standard Time": "Asia/Kabul",
    "West Asia Standard Time": "Asia/Tashkent", "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
    "Pakistan Standard Time": "Asia/Karachi", "Qyzylorda Standard Time": "Asia/Qyzylorda",
    "India Standard Time": "Asia/Kolkata", "Sri Lanka Standard Time": "Asia/Colombo",
    "Nepal Standard Time": "Asia/Kathmandu", "Central Asia Standard Time": "Asia/Bishkek",
    "Bangladesh Standard Time": "Asia/Dhaka", "Omsk Standard Time": "Asia/Omsk",
    "Myanmar Standard Time": "Asia/Yangon", "SE Asia Standard Time": "Asia/Bangkok",
    "Altai Standard Time": "Asia/Barnaul", "W. Mongolia Standard Time": "Asia/Hovd",
    "North Asia Standard Time": "Asia/Krasnoyarsk", "N. Central Asia Standard Time": "Asia/Novosibirsk",
    "Tomsk Standard Time": "Asia/Tomsk", "China Standard Time": "Asia/Shanghai",
    "North Asia East Standard Time": "Asia/Irkutsk", "Singapore Standard Time": "Asia/Singapore",
    "Malay Peninsula Standard Time": "Asia/Singapore", "W. Australia Standard Time": "Australia/Perth",
    "Taipei Standard Time": "Asia/Taipei", "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar",
    "Aus Central W. Standard Time": "Australia/Eucla", "Transbaikal Standard Time": "Asia/Chita",
    "Tokyo Standard Time": "Asia/Tokyo", "North Korea Standard Time": "Asia/Pyongyang",
    "Korea Standard Time": "Asia/Seoul", "Yakutsk Standard Time": "Asia/Yakutsk",
    "Cen. Australia Standard Time": "Australia/Adelaide", "AUS Central Standard Time": "Australia/Darwin",
    "E. Australia Standard Time": "Australia/Brisbane", "AUS Eastern Standard Time": "Australia/Sydney",
    "West Pacific Standard Time": "Pacific/Port_Moresby", "Tasmania Standard Time": "Australia/Hobart",
    "Vladivostok Standard Time": "Asia/Vladivostok", "Lord Howe Standard Time": "Australia/Lord_Howe",
    "Bougainville Standard Time": "Pacific/Bougainville", "Russia Time Zone 10": "Asia/Srednekolymsk",
    "Magadan Standard Time": "Asia/Magadan", "Norfolk Standard Time": "Pacific/Norfolk",
    "Sakhalin Standard Time": "Asia/Sakhalin", "Central Pacific Standard Time": "Pacific/Guadalcanal",
    "Russia Time Zone 11": "Asia/Kamchatka", "Kamchatka Standard Time": "Asia/Kamchatka",
    "New Zealand Standard Time": "Pacific/Auckland", "UTC+12": "Etc/GMT-12", "Fiji Standard Time": "Pacific/Fiji",
    "Chatham Islands Standard Time": "Pacific/Chatham", "UTC+13": "Etc/GMT-13",
    "Tonga Standard Time": "Pacific/Tongatapu", "Samoa Standard Time": "Pacific/Apia",
    "Line Islands Standard Time": "Pacific/Kiritimati"}

# cities in Outlook's display names ("(UTC+08:00) Beijing, Chongqing, Hong Kong, Urumqi") that are no IANA city
WIN_CITY = {"beijing": "Asia/Shanghai", "osaka": "Asia/Tokyo", "sapporo": "Asia/Tokyo", "new delhi": "Asia/Kolkata",
            "mumbai": "Asia/Kolkata", "chennai": "Asia/Kolkata", "hanoi": "Asia/Bangkok", "abu dhabi": "Asia/Dubai",
            "canberra": "Australia/Sydney", "wellington": "Pacific/Auckland", "brasilia": "America/Sao_Paulo",
            "eastern time (us & canada)": "America/New_York", "central time (us & canada)": "America/Chicago",
            "mountain time (us & canada)": "America/Denver", "pacific time (us & canada)": "America/Los_Angeles",
            "edinburgh": "Europe/London", "bern": "Europe/Zurich", "st. petersburg": "Europe/Moscow",
            "coordinated universal time": "Etc/UTC", "islamabad": "Asia/Karachi", "astana": "Asia/Bishkek",
            "ekaterinburg": "Asia/Yekaterinburg", "kuwait": "Asia/Riyadh", "riyadh": "Asia/Riyadh"}

ICS_LINE = re.compile(r'([A-Za-z0-9-]+)((?:;[A-Za-z0-9-]+=(?:"[^"]*"|[^";:,]*)(?:,(?:"[^"]*"|[^";:,]*))*)*):(.*)')
ICS_PARAM = re.compile(r';([A-Za-z0-9-]+)=((?:"[^"]*"|[^";:,]*)(?:,(?:"[^"]*"|[^";:,]*))*)')


def ics_parse(text):
    """iCalendar text -> its components as a tree: {"name", "props": [(NAME, {PARAM: value}, value, line)], "subs"}.
    Quoted parameter values may hold ":" and ";" (Outlook: TZID="(UTC+01:00) Amsterdam, Berlin, ...")."""
    root = {"name": "", "props": [], "subs": []}
    stack = [root]
    for line in re.sub(r"\r?\n[ \t]", "", text or "").splitlines():
        if not line.strip():
            continue
        m = ICS_LINE.match(line) or re.match(r"([A-Za-z0-9-]+)((?:;[^:]*)?):(.*)", line)
        if not m:
            continue
        name, value = m.group(1).upper(), m.group(3)
        if name == "BEGIN":
            c = {"name": value.strip().upper(), "props": [], "subs": []}
            stack[-1]["subs"].append(c)
            stack.append(c)
            continue
        if name == "END":
            if len(stack) > 1 and stack[-1]["name"] == value.strip().upper():
                stack.pop()
            continue
        params = {k.upper(): v.strip('"') for k, v in ICS_PARAM.findall(m.group(2))}
        stack[-1]["props"].append((name, params, value, line))
    return root


def ics_find(comp, name):
    """Every component called name, at any depth."""
    for s in comp["subs"]:
        if s["name"] == name:
            yield s
        yield from ics_find(s, name)


def ics_prop(comp, name, default=None):
    """The first (value, params) of a property, or default."""
    for n, p, v, _ in comp["props"]:
        if n == name:
            return v, p
    return default


def ics_text(v):
    """An iCalendar TEXT value, unescaped."""
    return re.sub(r"\\([,;:\\])", r"\1", re.sub(r"\\[nN]", "\n", v or "")).strip()


def ics_offset(v):
    """"+0100" / "-0530" / "+013000" -> seconds east of UTC, or None."""
    m = re.fullmatch(r"([+-])(\d\d)(\d\d)(\d\d)?", (v or "").strip())
    if not m:
        return None
    s = int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4) or 0)
    return -s if m.group(1) == "-" else s


def ics_local(v):
    """"20261124T100000" -> a naive datetime, or None."""
    m = re.fullmatch(r"(\d{8})T(\d{4})(\d{2})?Z?", (v or "").strip())
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1) + m.group(2) + (m.group(3) or "00"), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def rule_of(v):
    """An RRULE value -> {KEY: value}."""
    return {k.upper(): x for k, _, x in (p.partition("=") for p in (v or "").split(";")) if k}


def nth_weekday(year, month, wd, n):
    """The day of month of the nth (1..5, or -1 = last) weekday wd (0 = Monday), or None."""
    days = [d for d in range(1, 32) if _valid(year, month, d) and dt.date(year, month, d).weekday() == wd]
    try:
        return days[n - 1] if n > 0 else days[n]
    except IndexError:
        return None


def _valid(y, m, d):
    try:
        dt.date(y, m, d)
        return True
    except ValueError:
        return False


WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


class VTimezone(dt.tzinfo):
    """A time zone as the invitation itself describes it (VTIMEZONE: STANDARD and DAYLIGHT, each with its
    offsets and a yearly rule or fixed dates). Used when the TZID is no name the system knows."""

    def __init__(self, comp):
        self.parts = []
        for s in comp["subs"]:
            if s["name"] not in ("STANDARD", "DAYLIGHT"):
                continue
            start = ics_local((ics_prop(s, "DTSTART") or ("", {}))[0]) or dt.datetime(1601, 1, 1)
            to = ics_offset((ics_prop(s, "TZOFFSETTO") or ("", {}))[0])
            frm = ics_offset((ics_prop(s, "TZOFFSETFROM") or ("", {}))[0])
            if to is None:
                continue
            rdates = []
            for n, _p, v, _l in s["props"]:
                if n == "RDATE":
                    rdates += [d for d in (ics_local(x) for x in v.split(",")) if d]
            rr = ics_prop(s, "RRULE")
            self.parts.append({"start": start, "to": to, "from": frm if frm is not None else to,
                               "rule": rule_of(rr[0]) if rr else None, "rdates": rdates, "dst": s["name"] == "DAYLIGHT"})
        if not self.parts:
            raise ValueError("no offsets")

    def onsets(self, part, year):
        """Local times in this year at which part begins."""
        out = [d for d in [part["start"]] + part["rdates"] if d.year == year]
        r = part["rule"]
        if r and r.get("FREQ", "").upper() == "YEARLY":
            until = ics_local(r.get("UNTIL", "")) or (dt.datetime.strptime(r["UNTIL"][:8], "%Y%m%d")
                                                      if re.fullmatch(r"\d{8}", r.get("UNTIL", "")) else None)
            months = [int(x) for x in r.get("BYMONTH", str(part["start"].month)).split(",") if x.strip().isdigit()]
            for mo in months:
                days = []
                for b in [x for x in r.get("BYDAY", "").split(",") if x]:
                    m = re.fullmatch(r"([+-]?\d)?(MO|TU|WE|TH|FR|SA|SU)", b.strip().upper())
                    if m:
                        days.append(nth_weekday(year, mo, WEEKDAYS.index(m.group(2)), int(m.group(1) or 1)))
                for b in [x for x in r.get("BYMONTHDAY", "").split(",") if x.strip().lstrip("-").isdigit()]:
                    d = int(b)
                    days.append(d if d > 0 else None)
                if not days:
                    days = [part["start"].day]
                for d in days:
                    if d and _valid(year, mo, d):
                        when = dt.datetime(year, mo, d, part["start"].hour, part["start"].minute, part["start"].second)
                        if when >= part["start"] and (until is None or when <= until):
                            out.append(when)
        return out

    def offset_at(self, d):
        """Seconds east of UTC at the wall-clock time d (naive)."""
        best = None
        for part in self.parts:
            for y in (d.year - 1, d.year):
                for on in self.onsets(part, y):
                    if on <= d and (best is None or on > best[0]):
                        best = (on, part)
        if best is None:                    # before every onset: the earliest part's "from"
            first = min(self.parts, key=lambda p: p["start"])
            return first["from"], False
        return best[1]["to"], best[1]["dst"]

    def utcoffset(self, d):
        return dt.timedelta(seconds=self.offset_at(d.replace(tzinfo=None))[0])

    def dst(self, d):
        return dt.timedelta(0)

    def tzname(self, d):
        return None


def zone_city(iana):
    return iana.rsplit("/", 1)[-1].replace("_", " ") if iana and not iana.startswith("Etc/") else ""


_CITIES = None


def win_display_zone(name, year):
    """Outlook's display name "(UTC+01:00) Amsterdam, Berlin, ..." -> (IANA name or None, fixed offset or None).
    A city is taken only when its standard offset is the one in the name."""
    global _CITIES
    m = re.match(r"\(\s*(?:UTC|GMT)\s*(?:([+-])(\d{1,2}):?(\d\d))?\s*\)\s*(.*)", name)
    if not m:
        return None, None
    off = (int(m.group(2)) * 3600 + int(m.group(3)) * 60) * (-1 if m.group(1) == "-" else 1) if m.group(2) else 0
    try:
        from zoneinfo import ZoneInfo, available_timezones
        if _CITIES is None:
            _CITIES = {zone_city(z).lower(): z for z in sorted(available_timezones()) if "/" in z and zone_city(z)}
        rest = m.group(4).strip()
        names = [rest.lower()] + [c.strip().lower() for c in rest.split(",")]
        for c in names:
            z = WIN_CITY.get(c) or _CITIES.get(c)
            if not z:
                continue
            tz = ZoneInfo(z)
            std = min(int(dt.datetime(year, mo, 1, tzinfo=tz).utcoffset().total_seconds()) for mo in (1, 7))
            if std == off:
                return z, off
    except Exception:       # noqa: BLE001 - no time zone database: the offset in the name still holds
        pass
    return None, off


def ics_zone(name, zones, when=None):
    """A TZID -> (tzinfo or None, IANA name or None). Tries an IANA name, a Windows name, the invitation's own
    VTIMEZONE, then the offset in an Outlook display name. None: nobody can tell."""
    name = (name or "").strip().strip('"').strip()
    if not name:
        return None, None
    year = (when or dt.datetime.now()).year
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None
    if ZoneInfo:
        tail = re.search(r"([A-Za-z_]+/[A-Za-z_+-]+(?:/[A-Za-z_+-]+)?)$", name)     # "/mozilla.org/.../Europe/Berlin"
        for z in (WIN_TZ.get(name), name if "/" in name or name.upper() in ("UTC", "GMT") else None,
                  tail.group(1) if tail and tail.group(1) != name else None):
            if z:
                try:
                    return ZoneInfo(z), z
                except Exception:   # noqa: BLE001 - not a name this system knows
                    pass
        z, _ = win_display_zone(name, year)
        if z:
            try:
                tz = ZoneInfo(z)
                vt = zones.get(name)
                if vt is None or when is None or tz.utcoffset(when) == vt.utcoffset(when):
                    return tz, z
            except Exception:       # noqa: BLE001
                pass
    if zones.get(name) is not None:
        return zones[name], None
    _, off = win_display_zone(name, year)
    if off is not None:
        return dt.timezone(dt.timedelta(seconds=off)), None
    return None, None


def ics_zones(cal):
    """{TZID: VTimezone} for the invitation's VTIMEZONE blocks that can be read."""
    out = {}
    for c in ics_find(cal, "VTIMEZONE"):
        tzid = (ics_prop(c, "TZID") or ("", {}))[0].strip().strip('"')
        if tzid:
            with contextlib.suppress(Exception):
                out[tzid] = VTimezone(c)
    return out


def ics_time(value, params, zones=None):
    """An iCalendar date or date-time -> (unix time, all day). A whole day is midnight where the reader is;
    a time with an unknown zone is read as the reader's (ics_when says it is unknown)."""
    return ics_when(value, params, zones or {})[:2]


def ics_when(value, params, zones):
    """-> (unix time, all day, {"iana", "offset", "label"} of the event's zone, or None when floating,
    or {"unknown": True}), (None, False, None) when it can't be read."""
    v = (value or "").strip()
    if re.fullmatch(r"\d{8}", v):
        try:
            d = dt.datetime.strptime(v, "%Y%m%d")
        except ValueError:
            return None, False, None
        return int(d.timestamp()), True, None
    d = ics_local(v)
    if d is None:
        return None, False, None
    if v.upper().endswith("Z"):
        return int(d.replace(tzinfo=dt.timezone.utc).timestamp()), False, None     # UTC says nothing of the zone
    name = (params.get("TZID") or "").strip().strip('"')
    if not name:
        return int(d.timestamp()), False, None          # floating: the same wall-clock time everywhere
    tz, iana = ics_zone(name, zones, d)
    if tz is None:
        return int(d.timestamp()), False, {"unknown": True, "label": name}
    try:
        aware = d.replace(tzinfo=tz)
        off = int(aware.utcoffset().total_seconds())
        ts = int(aware.timestamp())
    except Exception:       # noqa: BLE001 - a zone that can't answer for this date
        return int(d.timestamp()), False, {"unknown": True, "label": name}
    mm = re.match(r"\([^)]*\)\s*([^,]*)", name)
    label = (mm.group(1).strip() if mm and mm.group(1).strip() else "") or zone_city(iana) or name
    return ts, False, {"iana": iana, "offset": off, "label": label}


def ics_duration(v):
    """"PT1H30M" / "P1D" / "-PT15M" -> seconds, or None."""
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", (v or "").strip())
    if not m or not any(m.groups()[1:]):
        return None
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    n = (((w * 7 + d) * 24 + h) * 60 + mi) * 60 + s
    return -n if m.group(1) == "-" else n


def ics_charset_text(p):
    """The calendar part as text: its declared charset, then UTF-8, then GB18030 (as for mail text)."""
    data = R.part_bytes(p)
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for cs, err in ((p.get_content_charset() or "", "strict"), ("utf-8", "strict"), ("gb18030", "replace")):
        if not cs:
            continue
        try:
            return data.decode(cs, err)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


def ics_part(msg):
    """The mail's calendar part (an invitation), or None. The text/calendar part wins over an .ics file."""
    found = None
    for p in msg.walk():
        if p.is_multipart() or p.get_content_type() == "message/rfc822":
            continue
        if p.get_content_type() == "text/calendar":
            return p
        if found is None and (R.fname(p) or "").lower().endswith(".ics"):
            found = p
    return found


# links that join an online meeting, the service named by the first group
JOIN_LINKS = (
    ("teams", r"https://teams\.(?:microsoft|live)\.com/(?:l/meetup-join|meet|dl/launcher)/[^\s<>\"'\\]+"),
    ("zoom", r"https://(?:[\w-]+\.)?zoom(?:gov)?\.(?:us|com|com\.cn)/(?:j|my|w|s|wc)/[^\s<>\"'\\]+"),
    ("meet", r"https://meet\.google\.com/[a-z]{3,4}-[a-z]{3,4}-[a-z]{3,4}[^\s<>\"'\\]*"),
    ("tencent", r"https://(?:meeting\.tencent\.com|voovmeeting\.com|work\.weixin\.qq\.com/meeting)/[^\s<>\"'\\]+"),
    ("webex", r"https://[\w-]+\.webex\.com(?:\.cn)?/[^\s<>\"'\\]+"),
)


def join_link(ev):
    """The online meeting's link: {"url", "kind"}, or None. Looks where the services put it."""
    texts = []
    for n in ("X-MICROSOFT-SKYPETEAMSMEETINGURL", "X-MICROSOFT-ONLINEMEETINGCONFLINK", "X-GOOGLE-CONFERENCE",
              "URL", "LOCATION", "DESCRIPTION", "X-ALT-DESC"):
        for pn, _p, v, _l in ev["props"]:
            if pn == n:
                texts.append(htmlmod.unescape(ics_text(v)))
    for n, _p, v, _l in ev["props"]:
        if n.startswith("X-") and "http" in v:
            texts.append(ics_text(v))
    for t in texts:
        for kind, pat in JOIN_LINKS:
            m = re.search(pat, t, re.I)
            if m:
                return {"url": m.group(0).rstrip(".,;)>]"), "kind": kind}
    return None


def ics_person(value, params):
    addr = re.sub(r"(?i)^mailto:", "", (value or "").strip()).strip().lower()
    return {"name": (params.get("CN") or "").strip().strip('"'), "addr": addr if "@" in addr else ""}


def rrule_info(v, tz, start_local):
    """An RRULE -> what the page needs to say it ({"freq", "interval", "byday", "bymonthday", "count", "until"})."""
    r = rule_of(v)
    freq = r.get("FREQ", "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return None
    out = {"freq": freq, "interval": max(1, int(r["INTERVAL"])) if r.get("INTERVAL", "").isdigit() else 1,
           "byday": [x.strip().upper() for x in r.get("BYDAY", "").split(",") if x.strip()],
           "bymonthday": [int(x) for x in r.get("BYMONTHDAY", "").split(",") if x.strip().lstrip("-").isdigit()],
           "count": int(r["COUNT"]) if r.get("COUNT", "").isdigit() else None, "until": None}
    u = r.get("UNTIL", "").strip()
    if re.fullmatch(r"\d{8}", u):
        out["until_day"] = u
    elif ics_local(u):
        d = ics_local(u)
        out["until"] = int((d.replace(tzinfo=dt.timezone.utc) if u.upper().endswith("Z") else
                            d.replace(tzinfo=tz) if tz else d).timestamp())
    return out


def rrule_next(start, dur, tz, rr, now, exdates=()):
    """The first occurrence (as a naive local start) of a repeating event that has not ended by now, or None when
    the series is over. Covers DAILY, WEEKLY (BYDAY), MONTHLY (BYMONTHDAY or nth BYDAY) and YEARLY."""
    def ts(d):
        return (d.replace(tzinfo=tz) if tz else d).timestamp()
    until = rr.get("until")
    until_day = rr.get("until_day")
    count = rr.get("count")
    n = 0
    k = 0
    iv = rr["interval"]
    while k < 5000:
        if rr["freq"] == "DAILY":
            cands = [start + dt.timedelta(days=k * iv)]
        elif rr["freq"] == "WEEKLY":
            week0 = start - dt.timedelta(days=start.weekday()) + dt.timedelta(weeks=k * iv)
            days = [WEEKDAYS.index(b[-2:]) for b in rr["byday"] if b[-2:] in WEEKDAYS] or [start.weekday()]
            cands = [week0 + dt.timedelta(days=d) for d in sorted(set(days))]
        elif rr["freq"] == "MONTHLY":
            mi = start.month - 1 + k * iv
            y, mo = start.year + mi // 12, mi % 12 + 1
            days = []
            for b in rr["byday"]:
                m = re.fullmatch(r"([+-]?\d)?(MO|TU|WE|TH|FR|SA|SU)", b)
                if m and m.group(1):
                    days.append(nth_weekday(y, mo, WEEKDAYS.index(m.group(2)), int(m.group(1))))
            days += [d for d in rr["bymonthday"] if d > 0] or ([] if days else [start.day])
            cands = [start.replace(year=y, month=mo, day=d) for d in sorted(x for x in days if x) if _valid(y, mo, d)]
        else:
            y = start.year + k * iv
            cands = [start.replace(year=y)] if _valid(y, start.month, start.day) else []
        for c in cands:
            if c < start:
                continue
            if until is not None and ts(c) > until or until_day and c.strftime("%Y%m%d") > until_day:
                return None
            n += 1
            if count and n > count:
                return None
            if c in exdates:
                continue
            if ts(c) + dur > now:
                return c
        k += 1
    return None


def pick_event(cal):
    """The VEVENT the mail is about: the series, unless an occurrence with RECURRENCE-ID was changed later."""
    evs = list(ics_find(cal, "VEVENT"))
    if not evs:
        return None
    def seq(e):
        v = (ics_prop(e, "SEQUENCE") or ("0", {}))[0].strip()
        return int(v) if v.isdigit() else 0
    master = next((e for e in evs if not ics_prop(e, "RECURRENCE-ID")), None)
    others = [e for e in evs if e is not master]
    if master is None:
        return others[0]
    newer = [e for e in others if seq(e) > seq(master)]
    return max(newer, key=seq) if newer else master


def invite_of(msg):
    """What a meeting invitation (or a reply to one, a cancellation, a new time proposed) says, or None.
    {"title", "start", "end", "all_day", "where", "organizer", "method", "cancelled", "uid", ...}."""
    p = ics_part(msg)
    if p is None:
        return None
    try:
        cal = ics_parse(ics_charset_text(p))
    except Exception:       # noqa: BLE001 - a broken calendar part is no invitation
        return None
    vcal = next(ics_find(cal, "VCALENDAR"), cal)
    method = ((ics_prop(vcal, "METHOD") or ics_prop(cal, "METHOD") or ("", {}))[0].strip().upper()
              or (p.get_param("method") or "").upper())
    ev = pick_event(cal)
    if ev is None:
        return None
    zones = ics_zones(cal)
    g = lambda n: ics_prop(ev, n) or ("", {})
    if not ics_prop(ev, "DTSTART"):
        return None
    start, all_day, zone = ics_when(*g("DTSTART"), zones)
    if start is None:
        return None
    end = None
    if ics_prop(ev, "DTEND"):
        end = ics_when(*g("DTEND"), zones)[0]
    elif ics_prop(ev, "DURATION"):
        d = ics_duration(g("DURATION")[0])
        end = start + d if d is not None else None
    if all_day and (end is None or end <= start):
        end = start + 86400
    org = ics_prop(ev, "ORGANIZER")
    organizer = ics_person(*org) if org else {"name": "", "addr": ""}
    people = []
    for n, pa, v, _l in ev["props"]:
        if n == "ATTENDEE":
            x = ics_person(v, pa)
            if not x["addr"] and not x["name"]:
                continue
            x["status"] = (pa.get("PARTSTAT") or "NEEDS-ACTION").upper()
            x["role"] = (pa.get("ROLE") or "REQ-PARTICIPANT").upper()
            x["kind"] = (pa.get("CUTYPE") or "INDIVIDUAL").upper()
            people.append(x)
    seq_v = g("SEQUENCE")[0].strip()
    rid = ics_prop(ev, "RECURRENCE-ID")
    out = {"title": ics_text(g("SUMMARY")[0]), "start": start, "end": end, "all_day": all_day,
           "where": ics_text(g("LOCATION")[0]), "organizer": organizer["name"] or organizer["addr"],
           "organizer_addr": organizer["addr"], "method": method or "PUBLISH",
           "cancelled": method == "CANCEL" or g("STATUS")[0].strip().upper() == "CANCELLED",
           "uid": g("UID")[0].strip(), "seq": int(seq_v) if seq_v.isdigit() else 0,
           "occurrence": bool(rid), "rid": rid[0].strip() if rid else "",
           "zone": zone, "attendees": [x for x in people if x["kind"] not in ("ROOM", "RESOURCE")],
           "about": ics_about(ics_text(g("DESCRIPTION")[0]))[:2000], "join": join_link(ev), "repeat": None,
           "first": [start, end]}
    if all_day:
        s = g("DTSTART")[0].strip()[:8]
        out["day0"] = s
        e = (g("DTEND")[0].strip()[:8] if re.fullmatch(r"\d{8}", g("DTEND")[0].strip()) else None)
        last = (dt.datetime.strptime(e, "%Y%m%d") - dt.timedelta(days=1)) if e and e > s else dt.datetime.strptime(s, "%Y%m%d")
        out["day1"] = last.strftime("%Y%m%d")
    rr = ics_prop(ev, "RRULE")
    if rr and not rid:
        tz = None
        if not all_day and g("DTSTART")[1].get("TZID"):
            tz = ics_zone(g("DTSTART")[1]["TZID"], zones, ics_local(g("DTSTART")[0]))[0]
        local = ics_local(g("DTSTART")[0]) or dt.datetime.strptime(g("DTSTART")[0].strip()[:8], "%Y%m%d")
        if g("DTSTART")[0].strip().upper().endswith("Z"):
            tz = dt.timezone.utc
        info = rrule_info(rr[0], tz, local)
        if info:
            out["repeat"] = info
            exd = set()
            for n, _pa, v, _l in ev["props"]:
                if n == "EXDATE":
                    exd |= {d for d in (ics_local(x) for x in v.split(",")) if d}
            dur = (end - start) if end else 0
            nxt = rrule_next(local, dur, tz, info, time.time(), exd)
            if nxt is not None and nxt != local:
                ns = int((nxt.replace(tzinfo=tz) if tz else nxt).timestamp())
                out["start"], out["end"] = ns, (ns + dur if end else None)
                if all_day:
                    out["day0"] = nxt.strftime("%Y%m%d")
                    out["day1"] = (nxt + dt.timedelta(seconds=max(0, dur - 86400))).strftime("%Y%m%d")
                if zone and zone.get("iana") is not None and tz is not None:
                    out["zone"] = dict(zone, offset=int(nxt.replace(tzinfo=tz).utcoffset().total_seconds()))
            out["repeat"]["over"] = nxt is None
    if method in ("REPLY", "COUNTER"):
        # the attendee who answers (or proposes a new time) is the one ATTENDEE of the reply
        x = next((a for a in people if a["status"] != "NEEDS-ACTION"), people[0] if people else None)
        out["reply"] = {"name": (x or {}).get("name", ""), "addr": (x or {}).get("addr", ""),
                        "status": (x or {}).get("status", ""), "comment": ics_text(g("COMMENT")[0])}
        if not out["reply"]["addr"]:
            f = R.addrs(R.hdr(msg, "From"))
            if f:
                out["reply"]["name"], out["reply"]["addr"] = f[0]
    return out


def ics_about(text):
    """The first part of a DESCRIPTION worth reading: without the join boilerplate that Teams puts after a
    line of underscores, and without lines that are only rules."""
    text = re.split(r"(?m)^\s*_{10,}\s*$", text or "", maxsplit=1)[0]
    lines = [x.rstrip() for x in text.splitlines() if not re.fullmatch(r"\s*[-_=*~.]{4,}\s*", x)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def invite_for(v, me):
    """What the invitation asks of the person reading it: are they the organizer, are they asked, how they answered
    in the invitation itself. Changes v."""
    me = (me or "").lower()
    v["mine"] = bool(me) and v.get("organizer_addr") == me
    x = next((a for a in v.get("attendees") or [] if me and a["addr"] == me), None)
    v["me_status"] = x["status"] if x else None
    v["can_answer"] = bool(x) and not v["mine"] and v.get("method") == "REQUEST" and not v.get("cancelled")
    return v


RSVP_SUBJECT = {"ACCEPTED": "Accepted: %s", "TENTATIVE": "Tentative: %s", "DECLINED": "Declined: %s"}


def ics_fold(line):
    """One content line folded at 75 octets (RFC 5545 3.1), never inside a UTF-8 character."""
    out, cur = [], b""
    for ch in line:
        e = ch.encode()
        if len(cur) + len(e) > (75 if not out else 74):
            out.append(cur)
            cur = b""
        cur += e
    out.append(cur)
    return "\r\n ".join(x.decode() for x in out)


def ics_escape(s):
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n") \
        .replace("\r", "\n").replace("\n", "\\n")


def ics_param_value(v):
    v = (v or "").replace('"', "'")
    return '"%s"' % v if re.search(r"[;:,]", v) else v


def ics_lines(comp):
    """A parsed component back as content lines (each line as it came, unfolded)."""
    out = ["BEGIN:" + comp["name"]]
    out += [line for _n, _p, _v, line in comp["props"]]
    for s in comp["subs"]:
        out += ics_lines(s)
    return out + ["END:" + comp["name"]]


def rsvp_ics(cal, ev, partstat, me, name, note="", now=None):
    """The iTIP REPLY (RFC 5546 3.2.3) to the event ev of the invitation cal: the same UID, SEQUENCE and
    RECURRENCE-ID, the organizer, and one ATTENDEE, the person answering, with PARTSTAT. DTSTAMP is when the
    reply is made, so a later answer replaces an earlier one."""
    used = {p.get("TZID", "").strip() for n, p, _v, _l in ev["props"]
            if n in ("DTSTART", "DTEND", "RECURRENCE-ID") and p.get("TZID")}
    lines = ["BEGIN:VCALENDAR", "PRODID:-//Ragdoll Mail//EN", "VERSION:2.0", "METHOD:REPLY"]
    for z in ics_find(cal, "VTIMEZONE"):
        if (ics_prop(z, "TZID") or ("", {}))[0].strip().strip('"') in used:
            lines += ics_lines(z)
    lines.append("BEGIN:VEVENT")
    for want in ("UID", "RECURRENCE-ID", "SEQUENCE", "DTSTART", "DTEND", "DURATION", "SUMMARY", "LOCATION", "ORGANIZER"):
        lines += [line for n, _p, _v, line in ev["props"] if n == want][:1]
    if not ics_prop(ev, "SEQUENCE"):
        lines.append("SEQUENCE:0")
    lines.append("DTSTAMP:" + dt.datetime.fromtimestamp(now or time.time(), dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    me = (me or "").lower()
    params = next((dict(p) for n, p, v, _l in ev["props"]
                   if n == "ATTENDEE" and ics_person(v, p)["addr"] == me), {})
    for k in ("PARTSTAT", "RSVP"):
        params.pop(k, None)
    if name and not params.get("CN"):
        params["CN"] = name
    lines.append("ATTENDEE" + "".join(";%s=%s" % (k, ics_param_value(v)) for k, v in params.items())
                 + ";PARTSTAT=%s:mailto:%s" % (partstat, me))
    if note:
        lines.append("COMMENT:" + ics_escape(note))
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(ics_fold(x) for x in lines) + "\r\n"


def build_rsvp(orig, partstat, me, name="", note="", subject=None):
    """The answer to the invitation mail orig, to its organizer: text/plain (the note) beside
    text/calendar; method=REPLY. ValueError when the mail holds no invitation to answer."""
    partstat = (partstat or "").upper()
    if partstat not in RSVP_SUBJECT:
        raise ValueError("unknown answer")
    p = ics_part(orig)
    if p is None:
        raise ValueError("no invitation")
    cal = ics_parse(ics_charset_text(p))
    ev = pick_event(cal)
    if ev is None or not ics_prop(ev, "UID"):
        raise ValueError("no invitation")
    org = ics_prop(ev, "ORGANIZER")
    to = ics_person(*org)["addr"] if org else ""
    to_name = ics_person(*org)["name"] if org else ""
    if not to:
        f = R.addrs(R.hdr(orig, "From"))
        to, to_name = (f[0][1], f[0][0]) if f else ("", "")
    if not to:
        raise ValueError("the invitation has no organizer")
    title = ics_text((ics_prop(ev, "SUMMARY") or ("", {}))[0])
    form = subject if subject and "%s" in subject else RSVP_SUBJECT[partstat]
    note = re.sub(r"[\r\n]+", " ", (note or "").strip())[:500]
    msg = EmailMessage()
    msg["From"] = formataddr((R.one_line(name), me)) if name else me
    msg["To"] = formataddr((R.one_line(to_name), to)) if to_name else to
    msg["Subject"] = R.one_line(form.replace("%s", title, 1)).strip()
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(me.split("@")[-1] or None))
    mid = R.hdr(orig, "Message-ID").strip()
    if mid:
        msg["In-Reply-To"] = mid
        msg["References"] = ((R.hdr(orig, "References").strip() + " ") if R.hdr(orig, "References").strip() else "") + mid
    msg.set_content((note or msg["Subject"]) + "\n")
    msg.add_alternative(rsvp_ics(cal, ev, partstat, me, name, note), subtype="calendar",
                        params={"method": "REPLY"})
    return msg


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
    ("inbox", 60 * 170, ("Daniel Ruiz", "d.ruiz@contoso.com"), [ME], [],
     "Weekly supplier sync",
     "Hi Alex,\n\nA short weekly call to go through open orders and shipments. It's on Teams.\n\nDaniel",
     [("meeting.ics", "teams")], True, None, None),
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
    ("inbox", 60 * 170, ("周敏", "zhou.min@fabrikam.cn"), [ME_ZH], [],
     "项目周会（腾讯会议）",
     "各位好，\n\n这周的项目周会改在线上开，请用腾讯会议加入。\n\n周敏", [("meeting.ics", "tencent")], True, None, None),
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


def demo_attendees(people):
    """ATTENDEE lines for [(name, addr, PARTSTAT)]."""
    return "".join('ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=%s;RSVP=TRUE;CN="%s":mailto:%s\r\n' % (st, n, a)
                   for n, a, st in people)


def demo_ics(name, ts, event=DEMO_SETS["en"]["event"], to=()):
    """An invitation for a Wednesday at 14:00 local time still to come, as the mail promises."""
    d = dt.datetime.now() + dt.timedelta(days=1)
    d = (d + dt.timedelta(days=(2 - d.weekday()) % 7 or 7)).replace(hour=14, minute=0, second=0, microsecond=0)
    u = d.astimezone(dt.timezone.utc)
    f = "%Y%m%dT%H%M%SZ"
    title, place, who, addr = event
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Ragdoll Mail demo//EN\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\n"
            "UID:training@demo\r\nSEQUENCE:0\r\nDTSTAMP:%s\r\nDTSTART:%s\r\nDTEND:%s\r\nSUMMARY:%s\r\n"
            "LOCATION:%s\r\nORGANIZER;CN=%s:mailto:%s\r\n%sEND:VEVENT\r\nEND:VCALENDAR\r\n"
            % (u.strftime(f), u.strftime(f), (u + dt.timedelta(hours=1)).strftime(f), title, place, who, addr,
               demo_attendees([(n, a, "NEEDS-ACTION") for n, a in to])))


DEMO_BERLIN = "(UTC+01:00) Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna"


def demo_zone(name, hours):
    """The demo's own time zones; a fixed offset where the system has no time zone database
    (Windows without the tzdata package)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:       # noqa: BLE001
        return dt.timezone(dt.timedelta(hours=hours), name)


def demo_ics_teams(to):
    """A weekly Teams meeting from Outlook in Berlin: a Windows zone name with its VTIMEZONE, a repeat rule,
    the Teams link, people who answered."""
    berlin = demo_zone("Europe/Berlin", 1)
    d = dt.datetime.now(berlin) + dt.timedelta(days=1)
    d = (d + dt.timedelta(days=(1 - d.weekday()) % 7)).replace(hour=10, minute=0, second=0, microsecond=0)
    until = (d + dt.timedelta(days=120)).astimezone(dt.timezone.utc)
    url = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_RGVtbyBtZWV0aW5n%40thread.v2/0?context=demo"
    people = [(n, a, "NEEDS-ACTION") for n, a in to] + [
        ("Jane Doe", "jane.doe@acme-industrial.com", "ACCEPTED"), ("Tom Becker", "tom.becker@acme-industrial.com", "TENTATIVE"),
        ("Priya Natarajan", "priya@fabrikam.com", "DECLINED"), ("Sara Kim", "sara.kim@northwind.io", "NEEDS-ACTION"),
        ("Marco Rossi", "marco.rossi@example.it", "ACCEPTED")]
    about = ("A short weekly call to go through open orders and shipments.\\n\\n" + "_" * 80 +
             "\\nMicrosoft Teams meeting\\nJoin on your computer\\, mobile app or room device\\n" + url +
             "\\nMeeting ID: 371 552 908 114\\nPasscode: 7xQ2pD\\n" + "_" * 80)
    z = '"%s"' % DEMO_BERLIN
    return ("BEGIN:VCALENDAR\r\nPRODID:-//Microsoft Corporation//Outlook 16.0 MIMEDIR//EN\r\nVERSION:2.0\r\n"
            "METHOD:REQUEST\r\nBEGIN:VTIMEZONE\r\nTZID:%s\r\nBEGIN:STANDARD\r\nDTSTART:16010101T030000\r\n"
            "TZOFFSETFROM:+0200\r\nTZOFFSETTO:+0100\r\nRRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10\r\nEND:STANDARD\r\n"
            "BEGIN:DAYLIGHT\r\nDTSTART:16010101T020000\r\nTZOFFSETFROM:+0100\r\nTZOFFSETTO:+0200\r\n"
            "RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\nBEGIN:VEVENT\r\n"
            "ORGANIZER;CN=Daniel Ruiz:mailto:d.ruiz@contoso.com\r\n%s"
            "DESCRIPTION;LANGUAGE=en-US:%s\r\nRRULE:FREQ=WEEKLY;UNTIL=%s;INTERVAL=1;BYDAY=TU;WKST=SU\r\n"
            "UID:040000008200E00074C5B7101A82E00800000000DEMO0001\r\nSUMMARY;LANGUAGE=en-US:Weekly supplier sync\r\n"
            "DTSTART;TZID=%s:%s\r\nDTEND;TZID=%s:%s\r\nCLASS:PUBLIC\r\nPRIORITY:5\r\nDTSTAMP:%s\r\n"
            "TRANSP:OPAQUE\r\nSTATUS:CONFIRMED\r\nSEQUENCE:0\r\nLOCATION;LANGUAGE=en-US:Microsoft Teams Meeting\r\n"
            "X-MICROSOFT-SKYPETEAMSMEETINGURL:%s\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
            % (DEMO_BERLIN, demo_attendees(people), about, until.strftime("%Y%m%dT%H%M%SZ"), z,
               d.strftime("%Y%m%dT%H%M%S"), z, (d + dt.timedelta(minutes=30)).strftime("%Y%m%dT%H%M%S"),
               dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), url))


def demo_ics_tencent(to):
    """A Tencent Meeting invitation in Chinese, in Shanghai time with its VTIMEZONE."""
    d = (dt.datetime.now(demo_zone("Asia/Shanghai", 8)) + dt.timedelta(days=2)).replace(hour=15, minute=0, second=0,
                                                                                   microsecond=0)
    people = [(n, a, "NEEDS-ACTION") for n, a in to] + [
        ("张伟", "zhang.wei@acme-industrial.cn", "ACCEPTED"), ("赵磊", "zhao.lei@acme-industrial.cn", "NEEDS-ACTION"),
        ("李明", "li.ming@example.cn", "ACCEPTED"), ("孙佳", "sun.jia@northwind.cn", "TENTATIVE")]
    url = "https://meeting.tencent.com/dm/Rd9Kx2mDemo"
    about = ("周敏 邀请您参加腾讯会议\\n会议主题：项目周会\\n\\n点击链接入会，或添加至会议列表：\\n" + url +
             "\\n\\n#腾讯会议：482-615-730")
    return ("BEGIN:VCALENDAR\r\nPRODID:-//Tencent//WeMeet//CN\r\nVERSION:2.0\r\nMETHOD:REQUEST\r\n"
            "BEGIN:VTIMEZONE\r\nTZID:Asia/Shanghai\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\n"
            "TZOFFSETFROM:+0800\r\nTZOFFSETTO:+0800\r\nTZNAME:CST\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n"
            "BEGIN:VEVENT\r\nUID:wemeet-482615730@demo\r\nSEQUENCE:0\r\nDTSTAMP:%s\r\n"
            "DTSTART;TZID=Asia/Shanghai:%s\r\nDTEND;TZID=Asia/Shanghai:%s\r\nSUMMARY:项目周会\r\n"
            "LOCATION:腾讯会议\r\nDESCRIPTION:%s\r\nORGANIZER;CN=周敏:mailto:zhou.min@fabrikam.cn\r\n%s"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
            % (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), d.strftime("%Y%m%dT%H%M%S"),
               (d + dt.timedelta(hours=1)).strftime("%Y%m%dT%H%M%S"), about, demo_attendees(people)))


DEMO_ICS = {"teams": demo_ics_teams, "tencent": demo_ics_tencent}


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
            msg.add_attachment(demo_ics(name, ts, event, to), subtype="calendar", filename=name,
                               params={"method": "REQUEST"})
        elif kind in DEMO_ICS:
            msg.add_attachment(DEMO_ICS[kind](to), subtype="calendar", filename=name, params={"method": "REQUEST"})
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
        # error: the sentence; kind / detail / retry_at: what status_fields() hands the page (#54)
        self.sync = {"running": False, "error": None, "last": None, "kind": None, "detail": None, "retry_at": None}
        self.fails = 0                          # sync passes in a row that failed: the retry waits longer
        self.gen = 0                            # goes up when the account or server changes (#59)
        self.pass_gen = 0                       # the generation the sync pass under way began with
        self.redetect = False                   # the folder names are to be found again on the next pass
        self.lock_busy = None                   # since when another process has held the headers lock
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
        self.update_at = 0.0
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
        self.url = None                         # the page's address, token and all (main sets it)
        self.orig_mids = {}                     # id -> Message-ID of each mail a reply or forward was opened on
        self.demo_raw = {}
        self.thread = None
        self.schedlock = threading.RLock()      # the scheduled-send list (scheduled.json)
        self.inflight = set()                   # drafts going out right now (by the schedule or Send)
        self.editing = {}                       # draft id -> when a compose last opened or saved it
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
        self.preflock = threading.Lock()        # app.json: read, change, write as one step (#61)
        self.badge_n = None                     # the unread count the Dock icon shows
        self.holding = {}                        # id -> a mail in its undo pause after Send (hold_send)
        self.sendlock = threading.Lock()
        self.sending_n = 0                      # sends talking to the mail server right now
        self.undo_moves = collections.deque(maxlen=10)    # the last moves, so they can be undone (api_unmove)
        if demo:
            self.make_demo()                    # opens self.c on the demo's own index
        else:
            self.c = R.db()
        self.data_v = self.c.execute("pragma data_version").fetchone()[0]
        if not demo:
            with contextlib.suppress(Exception):
                r = self.q("select v from meta where k='folders'")
                self.found = [tuple(x) for x in json.loads(r[0]["v"])] if r else []
            with contextlib.suppress(Exception):     # the last good sync, by the app or the ragdoll command
                r = self.q("select v from meta where k='last_sync'")
                self.sync["last"] = int(r[0]["v"]) if r else None
            threading.Thread(target=self.tidy_loop, daemon=True).start()
            threading.Thread(target=self.update_loop, daemon=True).start()
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
            return 200, ({"ok": False, "error": str(e), "detail": e.detail} if e.detail
                         else {"ok": False, "error": str(e)})
        except (SystemExit, imaplib.IMAP4.error, smtplib.SMTPException, OSError, LookupError) as e:
            return 200, error_reply(e)
        except Exception as e:      # noqa: BLE001 - a bug must not take the page down with it
            traceback.print_exc(file=sys.stderr)
            return 500, {"ok": False, "error": "Something went wrong (%s)" % type(e).__name__}

    # calls the page makes by itself, not because the user did something
    PASSIVE = frozenset(("status", "list", "boot", "prefs", "notice_state", "cli_state", "window_theme", "win",
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
                raw = self.gone_check(r, lambda: go(lambda m: R.fetch_raw(m, folder, uid)))
                R.cache_put(path, raw)
        finally:
            self.fg -= 1
        return raw

    def gone_check(self, r, fetch):
        """fetch(); a mail the server no longer has (deleted on the phone a moment ago) leaves the
        list at once, and the page is told so in plain words (#58)."""
        try:
            return fetch()
        except SystemExit as e:
            if not str(e.code).startswith("no mail "):
                raise
            with self.dblock:
                self.c.execute("delete from msgs where id=?", (r["id"],))
                self.c.execute("delete from fts where rowid=?", (r["id"],))
                self.c.commit()
            self.bump()
            self.wake.set()
            fail(GONE_MSG, str(e.code))

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

    # ---- files the app keeps on disk: the mail cache, opened files, files kept for a compose.
    # One job tidies them when the app starts and once a day after (an app left open for weeks too).

    CACHE_DAYS, CACHE_MAX = 90, 2 * 1024 ** 3       # mail not opened for 90 days goes; 2 GB at most
    OPEN_DAYS, OPEN_MAX = 30, 1024 ** 3             # opened attachments: 30 days, 1 GB
    UPLOAD_DAYS = 2                                 # a compose's files nothing points at any more
    STATE_DAYS = 1                                  # a compose state whose draft is gone

    def tidy_loop(self):
        while not self.stopping.is_set():
            try:
                self.tidy()
            except Exception:       # noqa: BLE001 - tidying must never take the app down
                traceback.print_exc(file=sys.stderr)
            self.stopping.wait(86400)

    def tidy(self, now=None):
        now = time.time() if now is None else now
        self.prune_cache(self.CACHE_DAYS, now=now, max_bytes=self.CACHE_MAX)
        self.prune_open(now)
        self.prune_uploads(now)

    @staticmethod
    def used_at(path):
        try:
            st = os.stat(path)
        except OSError:
            return 0
        return max(st.st_atime, st.st_mtime)

    @staticmethod
    def files_in(root):
        """[(path, last used, bytes)] of every file under root."""
        out = []
        for d, _, files in os.walk(root):
            for n in files:
                p = os.path.join(d, n)
                with contextlib.suppress(OSError):
                    st = os.stat(p)
                    out.append((p, max(st.st_atime, st.st_mtime), st.st_size))
        return out

    def prune_open(self, now, days=None, max_bytes=None, keep_new=86400):
        """Opened attachments (open/<hash>/name) not used for a while go, the oldest first past the size
        limit; one used in the last day stays (it may be open in Word right now)."""
        root = os.path.join(R.CFG.home, "open")
        days = self.OPEN_DAYS if days is None else days
        max_bytes = self.OPEN_MAX if max_bytes is None else max_bytes
        dirs = []
        for n in os.listdir(root) if os.path.isdir(root) else []:
            d = os.path.join(root, n)
            files = self.files_in(d)
            dirs.append((max([t for _, t, _ in files] or [self.used_at(d)]), sum(s for _, _, s in files), d))
        dirs.sort()
        total = sum(s for _, s, _ in dirs)
        for used, size, d in dirs:
            if used < now - days * 86400 or (total > max_bytes and used < now - keep_new):
                shutil.rmtree(d, ignore_errors=True)
                if not os.path.exists(d):
                    total -= size
                    self.made = {p for p in self.made if not p.startswith(d + os.sep)}

    def prune_uploads(self, now):
        """Files kept for a compose (uploads/<token>/name): kept while a saved compose points at them;
        the others go after UPLOAD_DAYS. A compose state goes when its draft is no longer in Drafts."""
        states = os.path.join(R.CFG.home, "compose")
        drafts = {hashlib.sha1((r["msgid"] or "").strip().encode()).hexdigest() for r in
                  self.q("select msgid from msgs where folder=?", (R.CFG.folders["drafts"],))}
        keep = set()
        for n in os.listdir(states) if os.path.isdir(states) else []:
            p = os.path.join(states, n)
            if n.endswith(".json") and n[:-5] not in drafts and self.used_at(p) < now - self.STATE_DAYS * 86400:
                with contextlib.suppress(OSError):
                    os.remove(p)
                continue
            with contextlib.suppress(OSError, ValueError, TypeError, AttributeError):
                with open(p, encoding="utf-8") as f:
                    for x in json.load(f).get("atts") or []:
                        keep.add(os.path.dirname(os.path.realpath(x["path"])))
        root = os.path.join(R.CFG.home, "uploads")
        for n in os.listdir(root) if os.path.isdir(root) else []:
            d = os.path.join(root, n)
            if os.path.realpath(d) in keep:
                continue
            if max([t for _, t, _ in self.files_in(d)] or [self.used_at(d)]) < now - self.UPLOAD_DAYS * 86400:
                shutil.rmtree(d, ignore_errors=True)

    def downloaded_bytes(self):
        return sum(s for k in ("cache", "open") for _, _, s in self.files_in(os.path.join(R.CFG.home, k)))

    def api_storage(self, a):
        """How much downloaded mail is kept on this computer (the mail cache and opened files)."""
        return {"bytes": self.downloaded_bytes()}

    def api_clear_storage(self, a):
        """Remove the downloaded mail; it is fetched again when it is opened. An opened file changed or
        used in the last day stays: it may still be open in another app."""
        self.prune_cache(0, now=time.time() + 1, max_bytes=0)
        self.prune_open(time.time(), days=1, max_bytes=0)
        with self.schedlock:
            self.built.clear()
        return {"bytes": self.downloaded_bytes()}

    def prune_cache(self, days=90, now=None, max_bytes=None):
        """Mail not opened for `days` goes from the cache, and past max_bytes the least recently used
        first. A file fetched by itself (R.part_path) goes when its light mail goes."""
        root = os.path.join(R.CFG.home, "cache")
        now = time.time() if now is None else now
        cut = now - days * 86400
        files = sorted(self.files_in(root), key=lambda x: x[1])
        total = sum(s for _, _, s in files)
        for p, used, size in files:
            if used < cut or (max_bytes is not None and total > max_bytes):
                with contextlib.suppress(OSError):
                    os.remove(p)
                    total -= size
        for d, _, names in os.walk(root):
            for n in names:
                if ".part" in n and not os.path.exists(os.path.join(d, n.split(".part")[0] + ".light.eml")):
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
        if self.redetect:
            self.redetect = False
            self.use_detected(detect_folders(self.found))
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
            if self.gen != self.pass_gen:
                raise Restart()             # the settings changed: this pass belongs to the old ones
            try:
                R.sync_headers(m, c, f, held=self.held, deep=True)
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

    # seconds before the next try after 1, 2, 3, ... failed passes: soon while the network comes
    # back, then less and less often; signing in again with the same password does not help soon
    RETRY = {"offline": (15, 30, 60, 120, 300), "server": (60, 120, 300, 600), "auth": (300, 900),
             "config": (300,)}

    def note_error(self, e):
        """A failed pass: the sentence, its kind and the raw text for the page; when to try again."""
        msg, kind, detail = explain(e)
        self.fails += 1
        steps = self.RETRY.get(kind, self.RETRY["server"])
        wait = steps[min(self.fails, len(steps)) - 1]
        self.sync.update(error=msg, kind=kind, detail=detail if detail != msg else None,
                         retry_at=int(time.time() + wait))
        return wait

    def clear_error(self):
        self.fails = 0
        self.sync.update(error=None, kind=None, detail=None, retry_at=None)

    def status_fields(self):
        """The problem fields of the status the page polls (#54), from the real sync state:
        error_kind  "offline" (no network, DNS, refused, timed out, dropped), "auth" (sign-in failed),
                    "server" (the server said no, another sync holds the index), "config" (no account,
                    no password saved, the settings file can't be read), or None: no problem;
        last_sync   epoch seconds of the last sync that went through, or None;
        retry_at    epoch seconds of the next automatic try while there is a problem, else None;
        error_detail the raw text behind the error, for "copy details", or None."""
        s = self.sync
        if self.demo:
            return {"error_kind": None, "last_sync": s["last"], "retry_at": None, "error_detail": None}
        return dict(sync_problem(s), error_detail=s["detail"] if s["error"] else None)

    LOCK_RETRY = 10     # seconds before the sync tries again while another process syncs
    LOCK_WARN = 180     # seconds of that before the page is told

    def sync_loop(self):
        c = None
        wait = 0
        while not self.stopping.is_set():
            self.wake.wait(wait or 60)
            self.wake.clear()
            wait = 0
            if self.stopping.is_set():
                break
            if not configured():
                self.config_problem()
                continue
            self.sync["running"] = True
            self.pass_at, self.pass_cut = time.monotonic(), False
            self.pass_gen = self.gen
            try:
                c = own_db(c)
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
                                if self.gen != self.pass_gen:
                                    raise Restart() from None
                                if attempt:
                                    raise
                        c.execute("insert or replace into meta values('last_sync', ?)", (str(int(time.time())),))
                        c.commit()
                if got:
                    self.lock_busy = None
                    self.clear_error()
                    self.sync["last"] = int(time.time())
                else:
                    # the ragdoll command (or one that hangs) has the index: nothing was synced, so
                    # nothing says it was; ask again soon, and say so when it lasts (#53)
                    now = time.time()
                    self.lock_busy = self.lock_busy or now
                    wait = self.LOCK_RETRY
                    if now - self.lock_busy > self.LOCK_WARN:
                        self.sync.update(error=BUSY_MSG, kind="server", detail=None, retry_at=int(now + wait))
                self.start_bodies()
            except Restart:                     # settings saved: start over with the new ones at once
                m, self.sync_m = self.sync_m, None
                R.quit_imap(m, quick=True)
                wait = 0.01
            except BaseException as e:          # noqa: B036 - die() raises SystemExit
                wait = self.note_error(e)
                m, self.sync_m = self.sync_m, None
                R.quit_imap(m, quick=True)
            finally:
                self.sync["running"] = False
                self.pass_at = None
                self.sync["tried"] = int(time.time())
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
                c = own_db(c)
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

    def quiet_wait(self, gen):
        """Wait while somebody opens a mail or has just done something: they go first."""
        while not self.stopping.is_set() and gen == self.gen and (
                self.fg > 0 or time.time() - self.active_at < self.BODY_QUIET):
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
        gen = self.gen
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
                    self.quiet_wait(gen)
                    if self.stopping.is_set() or gen != self.gen:
                        return              # quitting, or the account changed (#59)
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

    def check_update(self, manual=False):
        """Ask for the newest release (#76): at start, every 12 hours while open, after the Mac wakes,
        and from "Check for updates". A quiet check says nothing when it fails; a manual one says so."""
        try:
            if FROZEN:
                req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "ragdoll-mail",
                                                                    "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=15, context=R.tls_context()) as f:
                    d = json.load(f)
                v = (d.get("tag_name") or "").lstrip("v")
                if version_tuple(v) > version_tuple(__version__):
                    up = {"version": v, "url": d.get("html_url") or RELEASES_PAGE}
                    if brew_cask():
                        up["command"] = BREW_UPGRADE
                    self.update = up
                elif v:
                    self.update = None
            elif os.path.isdir(os.path.join(R.APP_DIR, ".git")):
                if manual:
                    R.update_check_background()
                    st = R.update_state()
                    if st.get("check_error"):
                        raise OSError(st["check_error"])
                else:
                    R.maybe_check_later()
                latest = R.update_waiting()
                self.update = ({"version": latest.get("version"), "command": "ragdoll update"}
                               if latest else None)
            self.update_at = time.time()
        except Exception as e:      # noqa: BLE001 - offline, rate limit, a bad answer: try again later
            if manual:
                fail(UPDATE_FAIL_MSG, str(e))
        return self.update

    def update_loop(self):
        """Check again every 12 hours, and soon after a sleep: the wall clock jumps while the
        monotonic one in time.sleep does not."""
        self.check_update()
        while True:
            t0, m0 = time.time(), time.monotonic()
            time.sleep(UPDATE_TICK)
            woke = (time.time() - t0) - (time.monotonic() - m0) > 5 * 60
            if woke or time.time() - self.update_at >= UPDATE_EVERY:
                if woke:
                    time.sleep(30)      # the network comes back a little after the lid opens
                self.check_update()

    def api_check_update(self, a):
        """ "Check for updates" in the account menu: {"update": {...} or None, "version": this one}."""
        if self.demo:
            return {"update": None, "version": __version__}
        return {"update": self.check_update(manual=True), "version": __version__}

    # ---- api: app state

    def config_problem(self):
        """The settings file could not be read (#49): {path, error}, and the page may show the file."""
        e = R.CONFIG_ERROR
        if not e or self.demo:
            return None
        self.made.add(e["path"])
        if not self.sync["error"]:
            self.sync.update(error=CONFIG_MSG, kind="config", detail="%s: %s" % (e["path"], e["error"]),
                             retry_at=None)
        return {"path": e["path"], "error": e["error"]}

    def api_boot(self, a):
        return {"config_error": self.config_problem(), "configured": configured() or self.demo, "demo": self.demo, "user": R.CFG.user,
                "name": R.CFG.name, "version": __version__, "platform": sys.platform,
                "folders": self.folder_counts(), "theme": self.prefs().get("theme", "system"),
                "prefs": self.prefs(), "news": self.news, "asks": self.asks,
                "window": WINDOW.w is not None, "frameless": WINDOW.frameless}

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
                "news": self.news, "asks": self.asks, "bodies": self.bodies, **self.status_fields()}

    def api_sync(self, a):
        if not self.demo:
            self.start_sync()
        return {}

    def prefs(self):
        path = os.path.join(R.CFG.home, "app.json")
        for k in range(10):
            try:
                with open(path, encoding="utf-8") as f:
                    p = json.load(f)
                return p if isinstance(p, dict) else {}
            except PermissionError:     # Windows: the file is being swapped for the new one this moment
                time.sleep(0.02 * (k + 1))
            except (OSError, ValueError):
                return {}
        return {}

    def api_prefs(self, a):
        # one change at a time, each on top of the one before: two at once lost the language (#61)
        with self.preflock:
            p = self.change_prefs(a)
        if a.get("icon") in APP_ICONS:
            set_app_icon(a["icon"])
        return p

    def change_prefs(self, a):
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
        if a.get("icon") in APP_ICONS:
            p["icon"] = a["icon"]
        if a.get("font_size") in FONT_SIZES:
            p["font_size"] = a["font_size"]
        if a.get("text_size") in TEXT_SIZES:
            p["text_size"] = a["text_size"]
        if isinstance(a.get("fmt_bar"), bool):
            p["fmt_bar"] = a["fmt_bar"]
        if isinstance(a.get("notify"), bool):
            p["notify"] = a["notify"]
        # the window's size and place (keep_window_place)
        win = a.get("window")
        if isinstance(win, dict):
            ok = lambda k, lo, hi, none=False: (none and win.get(k) is None) or (      # noqa: E731
                type(win.get(k)) is int and lo <= win[k] <= hi)
            if ok("width", 200, 20000) and ok("height", 200, 20000) and ok("x", -100000, 100000, True) and \
                    ok("y", -100000, 100000, True) and isinstance(win.get("maximized", False), bool):
                p["window"] = {k: win.get(k) for k in ("x", "y", "width", "height")} | {"maximized": win.get("maximized", False)}
        # images from the web: on by default; the senders whose images always load when it is off
        if isinstance(a.get("remote_images"), bool):
            p["remote_images"] = a["remote_images"]
        s = a.get("img_senders")
        if isinstance(s, list) and len(s) <= 2000 and all(isinstance(x, str) and 0 < len(x) <= 320 and "@" in x for x in s):
            p["img_senders"] = list(dict.fromkeys(x.strip().lower() for x in s))
        f = a.get("folded")
        if isinstance(f, list) and len(f) <= 500 and all(isinstance(x, str) and 0 < len(x) <= 500 for x in f):
            p["folded"] = f
        # the owner's own order of their folders, and the folders mail was moved to last (newest first)
        for k, most in (("folder_order", 2000), ("folder_recent", 8)):
            f = a.get(k)
            if isinstance(f, list) and len(f) <= most and all(isinstance(x, str) and 0 < len(x) <= 500 for x in f):
                p[k] = f
        os.makedirs(R.CFG.home, exist_ok=True)
        path = os.path.join(R.CFG.home, "app.json")
        tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as f:     # a reader never sees half a file
            json.dump(p, f)
        for k in range(10):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:     # Windows: a reader has the old file open this moment
                if k == 9:
                    with contextlib.suppress(OSError):
                        os.remove(tmp)
                    raise
                time.sleep(0.02 * (k + 1))
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
        a reply draft is saved and, unless a["open"] is false, the app is asked to open it."""
        if not self.demo:
            fail("only in the demo")
        c = self.api_compose({"mode": "reply", "id": a["id"]})
        i, _ = self.save(dict(c, html=text_in(a, "html")))
        if a.get("open", True):
            self.asks_n += 1
            self.asks.append({"n": self.asks_n, "kind": "open", "id": i, "subject": c["subject"], "at": int(time.time())})
        self.bump()
        return {"id": i}

    def api_search(self, a):
        text = text_in(a, "q").strip()[:500]
        # one page at a time, as in a folder: the list asks for the next one when it is scrolled to the end
        limit = max(1, min(int_in(a, "limit", 200), 500))
        offset = max(0, min(int_in(a, "offset", 0), 10 ** 7))
        ns = SimpleNamespace(limit=limit, offset=offset, folder=None, from_=None, to=None, since=None, until=None,
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
            return {"rows": [], "more": False}
        with self.dblock:
            rows = R.search_rows(self.c, words, ns)
        more = len(rows) == limit
        skip = {R.CFG.folders.get("junk")}
        rows = [r for r in rows if r["folder"] not in skip]
        if not offset:
            self.prefetch(rows[:10])
        return {"rows": [self.row_json(r) for r in rows], "more": more}

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
        if out.get("invite"):
            self.invite_state(out)
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
               "remote": has_remote(body), "atts": [part_info(k, p, light) for k, p in enumerate(file_parts(msg, light))],
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
        undo = self.note_move(by, dest)
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
                    todo = sorted(set(uids))
                    try:
                        R.move_uids(m, f, todo, dest)
                    except R.Refused as e:  # the mail moved before the server stopped leaves the list too (#58)
                        moved[f] = todo[:e.done]
                        raise
                    moved[f] = todo
            moved = {}
            try:
                self.imap(go)
            except BaseException:           # noqa: B036 - re-raised once the index has the part that went
                self.forget_moved(moved)
                if moved:
                    self.wake.set()
                raise
        self.forget_moved(by)
        self.bump()
        if not self.demo:
            if (set(by) | {dest}) - set(self.sync_folders()):
                self.extra_now = True
            self.wake.set()
        self.undo_moves.append(undo)
        return {"moved": sum(len(x) for x in by.values()), "undo": undo["token"]}

    def forget_moved(self, by):
        """Rows of mail that is no longer in its folder on the server leave the index."""
        if not any(by.values()):
            return
        with self.dblock:
            for f, uids in by.items():
                for u in uids:
                    for r in self.c.execute("select id from msgs where folder=? and uid=?", (f, u)).fetchall():
                        self.c.execute("delete from msgs where id=?", (r["id"],))
                        self.c.execute("delete from fts where rowid=?", (r["id"],))
            self.c.commit()
        self.bump()

    # ---- undo a move that reached the server (Cmd+Z): each mail is found again in the folder it went to by
    # its Message-ID (a new UID there is not known) and moved back to the folder it came from

    def note_move(self, by, dest):
        items = []
        for f, uids in by.items():
            for u in uids:
                for r in self.q("select msgid from msgs where folder=? and uid=?", (f, u)):
                    if (r["msgid"] or "").strip():
                        items.append((f, r["msgid"].strip()))
        return {"token": secrets.token_hex(6), "dest": dest, "items": items}

    def api_unmove(self, a):
        job = next((x for x in self.undo_moves if x["token"] == a.get("token")), None)
        if job is None:
            fail("That move can't be undone any more.")
        self.undo_moves.remove(job)
        dest, back = job["dest"], {}
        for f, mid in job["items"]:
            back.setdefault(f, []).append(mid)
        moved = 0
        if self.demo:
            for f, mids in back.items():
                for mid in mids:
                    for r in self.q("select * from msgs where folder=? and msgid=?", (dest, mid)):
                        raw = self.demo_raw.pop((dest, r["uid"]), None)
                        if raw:
                            self.demo_insert(f, raw, r["ts"], r["seen"], r["answered"], r["flagged"])
                            self.demo_delete(R.make_id(dest, r["uid"]))
                            moved += 1
        else:
            def go(m):
                n = 0
                for f, mids in back.items():
                    R.use(m, dest, write=True)
                    uids = []
                    for mid in mids:
                        typ, data = m.uid("SEARCH", "HEADER", "Message-ID", '"%s"' % mid.replace('"', ""))
                        if typ == "OK" and data and data[0]:
                            uids += [int(x) for x in data[0].split()]
                    if uids:
                        R.move_uids(m, dest, sorted(set(uids)), f)
                        n += len(set(uids))
                return n
            moved = self.imap(go)
            with self.dblock:
                for mids in back.values():
                    for mid in mids:
                        for r in self.c.execute("select id from msgs where folder=? and msgid=?", (dest, mid)).fetchall():
                            self.c.execute("delete from msgs where id=?", (r["id"],))
                            self.c.execute("delete from fts where rowid=?", (r["id"],))
                self.c.commit()
            self.extra_now = True
            self.wake.set()
        self.bump()
        return {"moved": moved}

    def folders(self, m):
        if self.server_folders is None:
            self.server_folders = [n for n, _ in list_folders(m)]
        return self.server_folders

    # ---- the owner's own folders: make (inside another too), rename, move, delete, and empty Trash or Junk

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

    def subtree(self, key, sep):
        """[(folder, its flags)]: the folder and every folder inside it, the deepest first."""
        return sorted([(n, f) for n, f in self.found if n == key or n.startswith(key + sep)],
                      key=lambda x: -x[0].count(sep))

    def rename_rows(self, old, new, sep):
        """The mail already listed follows its folder to the new name (the folders inside it too), and so do
        the copies of it kept on disk, so nothing is fetched again."""
        inside = lambda f: f == old or f.startswith(old + sep)     # noqa: E731
        with self.dblock:
            names = {r[0] for r in self.c.execute("select folder from msgs union select folder from state").fetchall()}
            keep = []
            for f in names:
                if inside(f):
                    to = new + f[len(old):]
                    keep += [(f, to, r[0], r[1]) for r in
                             self.c.execute("select uidv, uid from msgs where folder=?", (f,)).fetchall()]
                    self.c.execute("delete from state where folder=?", (to,))
                    self.c.execute("update msgs set folder=? where folder=?", (to, f))
                    self.c.execute("update state set folder=? where folder=?", (to, f))
            self.c.commit()
        for f, to, uidv, uid in keep:
            cache_move((f, uidv, uid), (to, uidv, uid))

    def drop_rows(self, folder, uids=None):
        """Mail gone from the server for good: out of the index and off the disk. uids None: the whole folder."""
        with self.dblock:
            if uids is None:
                rows = self.c.execute("select id, uidv, uid from msgs where folder=?", (folder,)).fetchall()
            else:
                rows = []
                uids = sorted(set(uids))
                for k in range(0, len(uids), 500):
                    rows += self.c.execute("select id, uidv, uid from msgs where folder=? and uid in (%s)"
                                           % ",".join("?" * len(uids[k:k + 500])), (folder, *uids[k:k + 500])).fetchall()
            for r in rows:
                self.c.execute("delete from msgs where id=?", (r["id"],))
                self.c.execute("delete from fts where rowid=?", (r["id"],))
            self.c.commit()
        for r in rows:
            self.demo_raw.pop((folder, r["uid"]), None)
            cache_drop((folder, r["uidv"], r["uid"]))
        return len(rows)

    def api_folder_new(self, a):
        """{"name", "parent": an own folder to make it in (else beside the others)} -> {"key", "sep"}."""
        label = folder_label(a.get("name"))
        parent = a.get("parent")
        if parent is not None:
            parent = self.own_folder({"key": parent})[0]
        if self.demo:
            sep = "/"
            base = parent or self.own_parent(sep)
            name = base + sep + label if base else label
            self.free_name(name, label)
            self.found.append((name, ""))
        else:
            def go(m):
                sep = folder_sep(m)
                if sep in label:
                    fail("A folder name can't have %s in it." % sep)
                self.refresh_folders(m)
                if parent:
                    self.own_folder({"key": parent})
                base = parent or self.own_parent(sep)
                name = base + sep + label if base else label
                self.free_name(name, label)
                typ, data = m.create(R.q(name))
                if typ != "OK":
                    fail("The mail server said: %s" % said(data))
                with contextlib.suppress(Exception):
                    m.subscribe(R.q(name))
                self.refresh_folders(m)
                return name, sep
            name, sep = self.imap(go)
        self.bump()
        return {"key": name, "sep": sep}

    def demo_rename(self, key, name):
        self.found = [(name + n[len(key):], f) if n == key or n.startswith(key + "/") else (n, f) for n, f in self.found]
        for (f, u) in list(self.demo_raw):
            if f == key or f.startswith(key + "/"):
                self.demo_raw[(name + f[len(key):], u)] = self.demo_raw.pop((f, u))
        self.rename_rows(key, name, "/")

    def server_rename(self, m, key, name, sep):
        """RENAME on the server; the folders inside go along, and stay subscribed under their new names."""
        inner = [n for n, _ in self.subtree(key, sep)]
        R.select(m, R.CFG.folders.get("inbox") or "INBOX", readonly=True)
        typ, data = m.rename(R.q(key), R.q(name))
        if typ != "OK":
            fail("The mail server said: %s" % said(data))
        for n in inner:
            with contextlib.suppress(Exception):
                m.unsubscribe(R.q(n))
                m.subscribe(R.q(name + n[len(key):]))
        self.rename_rows(key, name, sep)
        self.refresh_folders(m)

    def api_folder_rename(self, a):
        """{"key", "name"} -> {"key": the new name, "sep"}. The folders inside keep their places in it."""
        key, old = self.own_folder(a)
        label = folder_label(a.get("name"))
        name = key[:len(key) - len(old)] + label
        if self.demo:
            if name != key:
                self.free_name(name, label)
                self.demo_rename(key, name)
            sep = "/"
        else:
            def go(m):
                sep = folder_sep(m)
                if name == key:
                    return sep
                if sep in label:
                    fail("A folder name can't have %s in it." % sep)
                self.refresh_folders(m)
                self.own_folder(a)
                self.free_name(name, label)
                self.server_rename(m, key, name, sep)
                return sep
            sep = self.imap(go)
            if name != key:
                self.extra_now = True
                self.wake.set()
        self.bump()
        return {"key": name, "sep": sep}

    def move_target(self, key, a, sep):
        """The new name of an own folder put in a.parent ("" the server's top level), or with a.top where
        new folders go."""
        if a.get("top") is True:
            parent = self.own_parent(sep)
        elif isinstance(a.get("parent"), str):
            parent = a["parent"]
        else:
            fail("bad request")
        if parent:
            if parent.upper() == "INBOX" or parent in [R.CFG.folders.get(k) for k in ("drafts", "sent", "trash", "junk")]:
                fail("A folder can't go inside %s." % parent)
            if parent not in [n for n, _ in self.found]:
                fail("The folder %s is no longer on the server." % parent)
            if parent == key or parent.startswith(key + sep):
                fail("A folder can't go inside itself.")
        leaf = key.rpartition(sep)[2]
        return (parent + sep + leaf if parent else leaf), leaf

    def api_folder_move(self, a):
        """{"key": an own folder, "parent": the folder to put it in ("" for the server's top level), or
        "top": true for where new folders go} -> {"key": its new name, "was": the folder it was in, "sep"}.
        It is a RENAME: the folders and the mail inside go along."""
        key, _ = self.own_folder(a)
        if self.demo:
            sep = "/"
            name, leaf = self.move_target(key, a, sep)
            if name != key:
                self.free_name(name, leaf)
                self.demo_rename(key, name)
        else:
            def go(m):
                sep = folder_sep(m)
                self.refresh_folders(m)
                self.own_folder(a)
                name, leaf = self.move_target(key, a, sep)
                if name != key:
                    self.free_name(name, leaf)
                    self.server_rename(m, key, name, sep)
                return name, sep
            name, sep = self.imap(go)
            if name != key:
                self.extra_now = True
                self.wake.set()
        self.bump()
        return {"key": name, "was": key.rpartition(sep)[0], "sep": sep}

    def server_count(self, m, folder):
        typ, data = m.status(R.q(folder), "(MESSAGES)")
        mo = re.search(rb"MESSAGES\s+(\d+)", b" ".join(x for x in data or [] if isinstance(x, bytes)))
        if typ != "OK" or not mo:
            fail("The mail server said: %s" % said(data))
        return int(mo.group(1))

    def api_folder_delete(self, a):
        """{"key"} deletes a folder with no mail and no folders inside. {"key", "check": true} -> {"mails", "folders"}:
        what is in it and in the folders inside it. {"key", "trash": true}: that mail goes to Trash (never deleted
        for good here), then the folders inside and the folder itself are deleted."""
        key, label = self.own_folder(a)
        check, trash = a.get("check") is True, a.get("trash") is True
        bin_ = R.CFG.folders.get("trash")
        if trash and not bin_:
            fail("No %s folder is set." % "trash")
        if self.demo:
            names = self.subtree(key, "/")
            mails = self.q("select count(*) n from msgs where folder in (%s)" % ",".join("?" * len(names)),
                           [n for n, _ in names])[0]["n"]
            if check:
                return {"mails": mails, "folders": len(names) - 1}
            if not trash:
                if len(names) > 1:
                    fail("%s has folders inside it. Delete those first." % label)
                if mails:
                    fail("%s still has mail in it. Move the mail out first." % label)
            for n, _ in names:
                for r in self.q("select uid, ts, seen, answered, flagged from msgs where folder=?", (n,)):
                    raw = self.demo_raw.get((n, r["uid"]))
                    if raw:
                        self.demo_insert(bin_, raw, r["ts"], r["seen"], r["answered"], r["flagged"])
            gone = {n for n, _ in names}
            self.found = [(n, f) for n, f in self.found if n not in gone]
        else:
            def go(m):
                sep = folder_sep(m)
                self.refresh_folders(m)
                self.own_folder(a)
                names = self.subtree(key, sep)
                if check:
                    return {"mails": sum(self.server_count(m, n) for n, f in names if "\\noselect" not in f.split()),
                            "folders": len(names) - 1}
                if not trash:
                    if len(names) > 1:
                        fail("%s has folders inside it. Delete those first." % label)
                    if self.server_count(m, key):
                        fail("%s still has mail in it. Move the mail out first." % label)
                else:
                    if bin_ not in self.folders(m):
                        fail("The folder %s is no longer on the server." % bin_)
                    for n, f in names:
                        if "\\noselect" in f.split():
                            continue
                        R.select(m, n, readonly=False)
                        uids = R.uids_of(m)
                        if uids:
                            R.move_uids(m, n, uids, bin_)
                R.select(m, R.CFG.folders.get("inbox") or "INBOX", readonly=True)
                for n, _ in names:
                    with contextlib.suppress(Exception):
                        m.unsubscribe(R.q(n))
                    typ, data = m.delete(R.q(n))
                    if typ != "OK":
                        self.refresh_folders(m)
                        fail("The mail server said: %s" % said(data))
                self.refresh_folders(m)
                return names
            out = self.imap(go)
            if check:
                return out
            names = out
            self.extra_now = True
            self.wake.set()
        for n, _ in names:
            self.drop_rows(n)
            self.exec("delete from state where folder=?", (n,))
        self.bump()
        return {"deleted": [n for n, _ in names]}

    def api_folder_empty(self, a):
        """{"key": "trash" or "junk"}: every mail in it is deleted for good -> {"count"}.
        {"key", "check": true} -> {"count"}: how many there are, nothing deleted."""
        k = a.get("key")
        if k not in ("trash", "junk"):
            fail("can't empty %s" % k)
        folder = R.CFG.folders.get(k)
        if not folder:
            fail("No %s folder is set." % k)
        if self.demo:
            n = self.q("select count(*) n from msgs where folder=?", (folder,))[0]["n"]
            if a.get("check") is not True:
                self.drop_rows(folder)
                self.bump()
            return {"count": n}

        def go(m):
            if a.get("check") is True:
                return None, self.server_count(m, folder)
            R.select(m, folder, readonly=False)
            uids = R.uids_of(m)
            for i in range(0, len(uids), 500):
                batch = ",".join(map(str, uids[i:i + 500]))
                typ, data = m.uid("STORE", batch, "+FLAGS.SILENT", "(\\Deleted)")
                if typ != "OK":
                    fail("The mail server said: %s" % said(data))
                if R.has_cap(m, "UIDPLUS"):
                    m.uid("EXPUNGE", batch)
            if uids and not R.has_cap(m, "UIDPLUS"):
                m.expunge()
            R.select(m, R.CFG.folders.get("inbox") or "INBOX", readonly=True)
            return uids, len(uids)
        uids, n = self.imap(go)
        if uids is not None:
            self.drop_rows(folder, uids)
            self.bump()
        return {"count": n}

    def files_of(self, i):
        """(the mail's files, whether the mail is the light one)."""
        raw, light = self.view(i)
        return file_parts(R.to_msg(raw), light), light

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
            raw = self.gone_check(r, lambda: self.download(lambda m: R.fetch_part_raw(m, r["folder"], r["uid"], sec)))
            R.cache_put(path, raw)
        return R.to_msg(raw)

    def write_part(self, p, save):
        """The file written to Downloads under a name that is free there (save), or to a folder of
        its own to open it from. Returns its path. Opening the same file again opens the copy made the
        first time: a second copy of the same name would not open in Excel ("a workbook with the same
        name is already open"), and changes made in the first copy stay."""
        name = disk_name(p)
        data = R.part_bytes(p)
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
                R.mark_downloaded(path)
                self.made.add(path)
                return path
        tmp = path + ".part"
        with open(tmp, "wb") as f:      # the app that opens it never sees half a file
            f.write(data)
        os.replace(tmp, path)
        R.mark_downloaded(path)
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
        action = a.get("action")
        save = action == "save"
        if action in (None, "open") and R.is_program(disk_name(parts[k])):
            # a program runs when it is opened: say so, and let the page offer save and show in folder
            return {"program": True, "name": disk_name(parts[k])}
        path = self.write_part(self.whole_part(a["id"], parts[k], light), save)
        if action == "drag":
            # the file under its own name in the app's open folder; Finder copies it where it is dropped
            return {"path": path, "name": os.path.basename(path), "dragging": drag_out(path)}
        if action == "show":
            open_path(path, reveal=True)
        elif not save:
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
                    with urllib.request.urlopen(req, timeout=15, context=R.tls_context()) as r:
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

    # ---- meeting invitations: what was answered, what changed (invites.json, per UID and occurrence)

    INVITE_LOCK = threading.Lock()

    def invites_path(self):
        return os.path.join(R.CFG.home, "invites.json")

    def invites_load(self):
        try:
            with open(self.invites_path(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def invites_save(self, d):
        os.makedirs(R.CFG.home, exist_ok=True)
        if len(d) > 2000:          # the oldest meetings go first
            for k in sorted(d, key=lambda k: d[k].get("t", 0))[:len(d) - 2000]:
                del d[k]
        tmp = self.invites_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, self.invites_path())

    @staticmethod
    def invite_key(v):
        return v["uid"] + ("|" + v["rid"] if v.get("rid") else "")

    def invite_state(self, out):
        """What the invitation means for the person reading it: organizer or asked to answer, how they
        answered here, and for an updated invitation (a higher SEQUENCE) what changed since the one before."""
        v = invite_for(out["invite"], R.CFG.user)
        if not v.get("uid") or v["method"] not in ("REQUEST", "PUBLISH", "ADD", "CANCEL"):
            return
        snap = {"start": v["first"][0], "end": v["first"][1], "where": v["where"], "all_day": v["all_day"]}
        with self.INVITE_LOCK:
            d = self.invites_load()
            e = d.setdefault(self.invite_key(v), {})
            seen = e.setdefault("seen", {})
            if seen.get(str(v["seq"])) != snap:
                seen[str(v["seq"])] = snap
                e["t"] = int(time.time())
                with contextlib.suppress(OSError):
                    self.invites_save(d)
        v["updated"] = v["method"] == "REQUEST" and v["seq"] > 0 and not v["cancelled"]
        before = [int(s) for s in seen if s.lstrip("-").isdigit() and int(s) < v["seq"]]
        if before and v["updated"]:
            old = seen[str(max(before))]
            was = {}
            if (old.get("start"), old.get("end")) != (snap["start"], snap["end"]):
                was.update(start=old.get("start"), end=old.get("end"), all_day=old.get("all_day"))
            if old.get("where", "") != snap["where"]:
                was["where"] = old.get("where", "")
            v["was"] = was or None
        ans = e.get("answer")
        v["answer"] = ans["status"] if ans and ans.get("seq", 0) >= v["seq"] and not v["cancelled"] else None

    def invite_in(self, i):
        """(the mail, its invitation as the reader sees it) for a mail id; fails when it holds none."""
        msg = R.to_msg(self.view(i)[0])
        v = invite_of(msg)
        if v is None:
            fail("This mail has no invitation.")
        return msg, invite_for(v, R.CFG.user)

    def save_built(self, msg):
        """A mail built here (not from the compose page) saved as a draft -> its id."""
        raw = msg.as_bytes(policy=R.OUT_POLICY)
        drafts = R.CFG.folders["drafts"]
        if self.demo:
            uid = self.demo_insert(drafts, raw, int(time.time()), 1, 0)
        else:
            def go(m):
                return R.append_draft(m, raw), R.select(m, drafts)
            uid, uidv = self.imap(go)
            if uid:
                with self.dblock:
                    index_raw(self.c, drafts, uidv, uid, raw, int(time.time()), 1, 0)
        self.bump()
        if not uid:
            fail("The draft was saved but the server did not say where. Open Drafts and send it from there.")
        return R.make_id(drafts, uid)

    def api_rsvp(self, a):
        """Accept / Maybe / Decline: the iTIP reply to the organizer, saved as a draft. The page sends it with
        api_rsvp_send after the undo pause, the way a mail from compose goes."""
        msg, v = self.invite_in(a["id"])
        if not v["can_answer"]:
            fail("This invitation can't be answered from here.")
        try:
            reply = build_rsvp(msg, a.get("answer"), R.CFG.user, R.CFG.name, a.get("note") or "", a.get("subject"))
        except ValueError as e:
            fail("Can't answer this invitation: %s." % e)
        return {"draft": self.save_built(reply)}

    def api_rsvp_send(self, a):
        """Send the reply api_rsvp saved, then remember the answer for this meeting."""
        _msg, v = self.invite_in(a["id"])
        status = (a.get("answer") or "").upper()
        if status not in RSVP_SUBJECT:
            fail("Can't answer this invitation: unknown answer.")
        r = self.api_send({"id": a["draft"]})
        with self.INVITE_LOCK:
            d = self.invites_load()
            e = d.setdefault(self.invite_key(v), {})
            e["answer"] = {"status": status, "seq": v["seq"], "at": int(time.time())}
            e["t"] = int(time.time())
            with contextlib.suppress(OSError):
                self.invites_save(d)
        return {"answer": status, "problems_after_sending": r.get("problems_after_sending") or []}

    def api_join(self, a):
        """Open the online meeting's link (Teams, Zoom, Google Meet, Tencent Meeting, Webex) in the browser."""
        _msg, v = self.invite_in(a["id"])
        if not v.get("join"):
            fail("This invitation has no meeting link.")
        if not self.demo:
            webbrowser.open(v["join"]["url"])
        return {"url": v["join"]["url"]}

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
        R.mark_downloaded(path)
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

    def api_win(self, a):
        """Windows, the app's own title bar: the window buttons, moving the window, and whether it is maximized."""
        return win_do(a.get("do"))

    def api_window_theme(self, a):
        window_theme(bool(a.get("dark")), a.get("bg"), a.get("text"), system=a.get("system") is True)
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

    # ---- signatures: a list in the config, each with a name, and one default for new mail and one for
    # replies and forwards. Before there was a list, the one signature file is the list's only entry.
    # The file stays the default for new mail, so the ragdoll command goes on using it.

    def signatures(self):
        """[{id, name, html}]"""
        got = R.CFG.d.get("signatures")
        if isinstance(got, list):
            return [{"id": str(x.get("id") or k + 1), "name": str(x.get("name") or ""), "html": str(x.get("html") or "")}
                    for k, x in enumerate(got) if isinstance(x, dict)]
        one = self.signature()
        return [{"id": "1", "name": "", "html": one}] if one.strip() else []

    def sig_defaults(self):
        """(id for new mail, id for replies and forwards); "" is none"""
        ids = [x["id"] for x in self.signatures()]
        if not isinstance(R.CFG.d.get("signatures"), list):
            return (ids[0], ids[0]) if ids else ("", "")
        pick = lambda k: R.CFG.d.get(k) if R.CFG.d.get(k) in ids else ""     # noqa: E731
        return pick("signature_new"), pick("signature_reply")

    def sig_for(self, mode, sid=None):
        """(id, html) of the signature a compose in this mode starts with, or of sid when it is one"""
        sigs = {x["id"]: x["html"] for x in self.signatures()}
        if sid is None or sid not in sigs:
            new, reply = self.sig_defaults()
            sid = reply if mode in ("reply", "replyall", "forward") else new
        return sid, sigs.get(sid, "")

    def api_signatures(self, a):
        new, reply = self.sig_defaults()
        return {"signatures": self.signatures(), "sig_new": new, "sig_reply": reply}

    def api_save_signatures(self, a):
        """Keep the list of signatures and the two defaults. The demo keeps them until it closes."""
        sigs, seen = [], set()
        for x in a.get("signatures") or []:
            if not isinstance(x, dict):
                continue
            sid = str(x.get("id") or "").strip()[:40] or secrets.token_hex(4)
            if sid in seen:
                sid = secrets.token_hex(4)
            seen.add(sid)
            sigs.append({"id": sid, "name": str(x.get("name") or "").strip()[:60], "html": str(x.get("html") or "")})
        ids = [x["id"] for x in sigs]
        new = a.get("sig_new") if a.get("sig_new") in ids else ""
        reply = a.get("sig_reply") if a.get("sig_reply") in ids else ""
        keep = {"signatures": sigs, "signature_new": new, "signature_reply": reply}
        if self.demo:
            R.CFG.d.update(keep)
            self.bump()
            return self.api_signatures({})
        path = config_path()
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            raw = {}
        except ValueError:
            fail("The settings file %s is broken; fix or remove it first." % path)
        raw.update(keep)
        html = next((x["html"] for x in sigs if x["id"] == new), "")
        cur = os.path.expanduser(R.CFG.signature or "")
        mine = os.path.join(os.path.dirname(path), "signature.html")
        target = cur if cur and os.path.realpath(cur) == os.path.realpath(mine) else mine
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(html)
        raw["signature"] = target if html.strip() else ""
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
        R.CFG = R.load_config(path)
        self.bump()
        return self.api_signatures({})

    def upload_dir(self):
        d = os.path.join(R.CFG.home, "uploads", secrets.token_hex(6))
        os.makedirs(d, exist_ok=True)
        return d

    def keep_file(self, name, data):
        """The file kept for a compose. On disk it has a safe name; "name" is its own, whole name, the one
        the mail gives it ("PO#123: 最终版?.pdf" stays so)."""
        name = mail_name(name)
        path = os.path.join(self.upload_dir(), R.safe_name(name))
        with open(path, "wb") as f:
            f.write(data)
        return {"path": path, "name": name, "size": len(data)}

    def api_compose(self, a):
        mode = a.get("mode") or "new"
        sid, sig = self.sig_for(mode)
        out = {"mode": mode, "orig": None, "replace": None, "to": [], "cc": [], "bcc": [], "subject": "",
               "html": "", "atts": [], "quote": "", "signature": sig, "sig_id": sid, "use_signature": True,
               "signatures": self.signatures()}
        if mode in ("reply", "replyall", "forward"):
            orig = R.to_msg(self.raw(a["id"]))
            out["orig"] = a["id"]
            self.orig_mids[a["id"]] = R.hdr(orig, "Message-ID").strip()
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
            self.editing[a["id"]] = time.time()     # a scheduled one waits while it is being changed
            msg = R.to_msg(self.raw(a["id"]))
            state = self.compose_state(R.hdr(msg, "Message-ID"))
            if state:
                out.update(state)
                out["html"] = editor_html(state.get("html") or "")
                out["replace"] = a["id"]
                out["sig_id"], out["signature"] = self.sig_for(state.get("mode"), state.get("sig_id"))
                if state.get("orig"):
                    with contextlib.suppress(ApiError, SystemExit, Exception):
                        orig, i = self.find_orig(dict(state, replace=a["id"]))
                        if orig is not None:
                            out["orig"] = i
                            out["quote"] = page_html(R.quote_block(orig), cid_map(orig))
                        else:       # the original is gone: the quote the draft already has
                            out["quote"] = page_html(R.quote_of(R.bodies(msg)[1]), cid_map(msg))
                out["atts"] = [x for x in state.get("atts", []) if os.path.isfile(x["path"])]
                return out
            plain, html = R.bodies(msg)
            out.update({"to": people_json(R.hdr(msg, "To")), "cc": people_json(R.hdr(msg, "Cc")),
                        "bcc": people_json(R.hdr(msg, "Bcc")), "subject": R.hdr(msg, "Subject"),
                        "html": editor_html(page_html(html, cid_map(msg))) if html.strip()
                        else R.text_to_html(plain),
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

    def body_font(self, body):
        """The font the body is written in (the page wraps it in data-rd-body), else the one in Settings."""
        mo = BODY_FONT_RE.match(body or "")
        if mo:
            return "%s;%s" % mo.groups()
        p = self.prefs()
        size = p.get("font_size") if p.get("font_size") in FONT_SIZES else 14
        return "font-family:%s;font-size:%dpx" % (FONT_CSS.get(p.get("font"), FONT_CSS["system"]), size)

    def find_orig(self, a):
        """The mail a reply or forward (a["orig"]) answers: (its message, its id now), or (None, None).
        Moved since (archived, filed): found again by its Message-ID, which the draft itself keeps."""
        i = a.get("orig")
        try:
            return R.to_msg(self.raw(i)), i
        except (ApiError, SystemExit):
            pass
        mid = a.get("orig_mid") or self.orig_mids.get(i)
        old = self.old_draft(a)
        if not mid and old is not None:
            mid = R.hdr(old, R.FWD_HEADER if a.get("mode") == "forward" else "In-Reply-To").strip()
        for r in self.q("select folder, uid from msgs where msgid=? order by ts desc", (mid,)) if mid else []:
            j = R.make_id(r["folder"], r["uid"])
            if j != i:
                try:
                    return R.to_msg(self.raw(j)), j
                except (ApiError, SystemExit):
                    continue
        return None, None

    def old_draft(self, a):
        """The saved draft this compose replaces, as a message, or None."""
        i = a.get("replace")
        if not i:
            return None
        try:
            if self.parse(i)[0] != R.CFG.folders["drafts"]:
                return None
            return R.to_msg(self.raw(i))
        except (ApiError, SystemExit):
            return None

    def build(self, a):
        mode = a.get("mode") or "new"
        orig = old = None
        if a.get("orig"):
            orig, i = self.find_orig(a)
            if orig is not None:
                a["orig"] = i                   # where it is now: the saved state keeps that
                a["orig_mid"] = R.hdr(orig, "Message-ID").strip()
            else:
                old = self.old_draft(a)         # gone for good: the quote the last save made stays
        to, cc, bcc = people_in(a.get("to")), people_in(a.get("cc")), people_in(a.get("bcc"))
        to, cc = R.clean_recipients(to, cc, set())
        subject = (a.get("subject") or "").strip()
        atts = []
        root = os.path.realpath(os.path.join(R.CFG.home, "uploads"))
        for x in a.get("atts") or []:
            p = os.path.realpath(x["path"])
            if not p.startswith(root + os.sep) or not os.path.isfile(p):
                fail("An attachment is missing: %s" % x.get("name", ""))
            atts.append((p, mail_name(x.get("name") if isinstance(x.get("name"), str) else "") or os.path.basename(p)))
        body, images = data_images(a.get("html") or "")
        sig = self.sig_for(mode, a.get("sig_id"))[1] if a.get("use_signature", True) else ""
        msg = R.build_message(body, to, cc, subject, orig, "reply" if mode in ("reply", "replyall") else None,
                              bcc, atts, sig, font=self.body_font(body),
                              quote_html=R.quote_of(R.bodies(old)[1]) if old is not None else "", quote_src=old)
        if a.get("orig") and orig is None:
            # the original is gone: the threading the last save had is kept, so the reply stays in its thread
            mid = a.get("orig_mid") or self.orig_mids.get(a["orig"]) or ""
            for h in ("In-Reply-To", "References", R.FWD_HEADER):
                v = R.hdr(old, h).strip() if old is not None else ""
                if not v and mid and (h == R.FWD_HEADER) == (mode == "forward"):
                    v = mid
                if v and not msg[h]:
                    msg[h] = v
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
                    if old in self.inflight:
                        fail("This mail is going out right now, so the change was not saved.")
                    self.editing[old] = time.time()     # not sent by the schedule while it changes
                self.drop_state(old)
        if self.demo:
            uid = self.demo_insert(drafts, raw, int(time.time()), 1, 0)
            if old:
                self.demo_delete(old)
        else:
            mid, done = R.hdr(msg, "Message-ID").strip(), {}

            def go(m):
                # self.imap runs this again on a new connection when the old one dropped: a draft the
                # server already took is found by its Message-ID, not saved a second time
                if "uid" not in done and done.get("sent"):
                    found = R.uid_of_mid(m, drafts, mid)
                    if found:
                        done["uid"] = found
                if "uid" not in done:
                    done["sent"] = True
                    done["uid"] = R.append_draft(m, raw)
                uidv = R.select(m, drafts)
                if old and not done.get("old_gone"):
                    with contextlib.suppress(Exception):
                        R.delete_uid(m, *self.parse(old))
                    done["old_gone"] = True
                return done["uid"], uidv
            uid, uidv = self.imap(go)
            with self.dblock:
                if old:
                    self.db_delete(old)
                if uid:
                    index_raw(self.c, drafts, uidv, uid, raw, int(time.time()), 1, 0)
        if old and uid:
            self.sched_move(old, R.make_id(drafts, uid))   # still scheduled, now as the saved draft
        state = {k: a.get(k) for k in ("mode", "orig", "orig_mid", "to", "cc", "bcc", "subject", "html", "atts",
                                       "use_signature", "irt", "refs", "fwd", "sig_id")}
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
        """Send the saved draft a["id"] now; with a["delay"] (seconds), after the undo pause (hold_send)."""
        if a.get("delay"):
            return self.hold_send(a["id"], a["delay"])
        return self.send_listed(a)

    def send_listed(self, a):
        """Send the saved draft now. The scheduled-send list is locked only to take the mail off it,
        not while it goes out: a long upload does not hold up the other screens."""
        i = a["id"]
        with self.sched_edit() as items:
            x = next((y for y in items if y["id"] == i), {"id": i})
            if self.going_out(x):
                fail("This mail is going out right now.")
            items[:] = [y for y in items if y["id"] != i]
            self.inflight.add(i)
        try:
            return self.send_now(a)
        finally:
            with self.schedlock:
                self.inflight.discard(i)

    # ---- the undo pause after Send
    # The page counts the pause down and then asks for the send (api_send_wait). The backend holds the
    # mail too, so a closed page does not drop it: a mail still held a moment after its pause ends goes out
    # by itself. The window's closing handler asks the page first, and waits for a send that has started.

    SEND_GRACE = 3          # seconds after the pause before the backend sends a mail the page never asked for

    def hold_send(self, i, delay):
        folder, _ = self.parse(i)
        if folder != R.CFG.folders["drafts"]:
            fail("Only drafts can be sent.")
        try:
            delay = max(0.0, min(120.0, float(delay)))
        except (TypeError, ValueError):
            fail("bad delay")
        with self.sendlock:
            job = self.holding.get(i)
            if job and job["state"] in ("held", "sending"):
                return {"held": True, "at": job["at"]}
            job = {"state": "held", "at": time.time() + delay, "done": threading.Event(), "result": None, "error": None}
            job["timer"] = threading.Timer(delay + self.SEND_GRACE, self.run_held, (i,))
            job["timer"].daemon = True
            self.holding[i] = job
        job["timer"].start()
        return {"held": True, "at": job["at"]}

    def run_held(self, i):
        """Send the held mail i now, once (the page and the timer may both ask). Returns its job."""
        with self.sendlock:
            job = self.holding.get(i)
            if not job or job["state"] != "held":
                return job
            job["state"] = "sending"
            job["timer"].cancel()
        try:
            job["result"] = self.send_listed({"id": i})
            job["state"] = "sent"
        except (Exception, SystemExit) as e:       # noqa: BLE001 - the page shows the reason
            job["error"] = str(e) if isinstance(e, ApiError) else friendly(e)
            job["state"] = "failed"
        finally:
            job["done"].set()
        return job

    def api_send_cancel(self, a):
        """Undo: keep the held mail as a draft. cancelled is false when it had already started to go."""
        with self.sendlock:
            job = self.holding.get(a["id"])
            if job is None or job["state"] in ("held", "cancelled"):
                if job is not None:
                    job["timer"].cancel()
                    job["state"] = "cancelled"
                    job["done"].set()
                    del self.holding[a["id"]]
                return {"cancelled": True}
        return {"cancelled": False}

    def api_send_wait(self, a):
        """The pause is over: send the held mail now, or wait for the send already on its way."""
        i = a["id"]
        job = self.run_held(i)
        if job is None:
            return self.api_send({"id": i})
        job["done"].wait(600)
        with self.sendlock:
            if self.holding.get(i) is job and job["state"] in ("sent", "failed"):
                del self.holding[i]
        if job["state"] == "failed":
            fail(job["error"])
        if job["state"] != "sent":
            return {"sent": False, "cancelled": job["state"] == "cancelled", "problems_after_sending": []}
        return job["result"]

    def send_state(self):
        """(mails held in their undo pause, sends talking to the server now)"""
        with self.sendlock:
            return sum(1 for j in self.holding.values() if j["state"] == "held"), self.sending_n

    def wait_sends(self, most=120):
        end = time.time() + most
        while time.time() < end and (self.send_state()[1] or any(
                j["state"] == "sending" for j in list(self.holding.values()))):
            time.sleep(0.1)

    def api_close_asked(self, a):
        """The page shows its question about the mail on its way (window_closing), or put it away."""
        WINDOW.asked = 2 if a.get("open", True) else 0
        return {}

    def api_quit_window(self, a):
        """The page has dealt with the mail on its way: let the window close."""
        WINDOW.quit_ok = True
        if WINDOW.w is not None:
            threading.Thread(target=close_window, daemon=True).start()
        return {}

    def send_now(self, a):
        with self.sendlock:
            self.sending_n += 1
        try:
            return self.send_draft_now(a)
        finally:
            with self.sendlock:
                self.sending_n -= 1

    def send_draft_now(self, a):
        folder, uid = self.parse(a["id"])
        if folder != R.CFG.folders["drafts"]:
            fail("Only drafts can be sent.")
        if self.demo:
            raw = self.demo_raw.get((folder, uid))
            if raw is None:
                fail("The draft is gone.")
            msg = R.to_msg(raw)
            self.drop_state(a["id"])
            self.demo_delete(a["id"])
            bcc = R.hdr(msg, "Bcc").strip()
            del msg["Bcc"]
            sent = R.sent_copy(msg.as_bytes(policy=R.OUT_POLICY), bcc)     # Sent keeps who was Bcc'd
            self.demo_insert(R.CFG.folders["sent"], sent, int(time.time()), 1, 0)
            fwd = R.forward_source(msg)
            irt = R.hdr(msg, "In-Reply-To").strip()
            if fwd:
                self.exec("update msgs set forwarded=1 where msgid=?", (fwd,))
            elif irt:
                self.exec("update msgs set answered=1 where msgid=?", (irt,))
            self.bump()
            return {"sent": True, "problems_after_sending": []}
        r = R.send_draft(folder, uid)
        self.drop_state(a["id"])
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

    RETRY_MAX = 3600        # a mail that could not go out is tried again after 1, 2, 4, ... minutes, then hourly
    HOLD = 15 * 60          # a scheduled draft being changed in a compose waits this long after its last save

    def sched_save(self, items):
        with self.schedlock:
            os.makedirs(R.CFG.home, exist_ok=True)
            tmp = "%s.%d.tmp" % (self.sched_path(), os.getpid())
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False)
            os.replace(tmp, self.sched_path())

    @contextlib.contextmanager
    def sched_edit(self):
        """The list to change in place; saved when it changed. Locked for this app's threads and for
        other processes (the ragdoll command, a second copy of the app) alike, and only for as long as
        the list changes: never while a mail is going out."""
        with self.schedlock, R.file_lock("sched", True):
            items = self.sched_list()
            before = json.dumps(items, sort_keys=True)
            yield items
            if json.dumps(items, sort_keys=True) != before:
                self.sched_save(items)
                self.bump()

    def sched_drop(self, i):
        with self.sched_edit() as items:
            n = len(items)
            items[:] = [x for x in items if x["id"] != i]
            return len(items) != n

    def sched_move(self, old, new):
        """A scheduled draft saved again (as a new draft): it stays scheduled, at the same time."""
        with self.sched_edit() as items:
            for x in items:
                if x["id"] == old:
                    x["id"] = new
                    for k in ("error", "tries", "retry_at", "note", "sending"):
                        x.pop(k, None)
            self.editing[new] = time.time()
            self.editing.pop(old, None)

    def going_out(self, x):
        """True while the mail of this entry is being sent, here or by another copy of the app."""
        if x["id"] in self.inflight:
            return True
        s = x.get("sending")
        if not isinstance(s, dict):
            return False
        # ours but no longer in flight: left by a send that ended without tidying up
        return s.get("pid") != os.getpid() and R.pid_running(s.get("pid"))

    def sched_claim(self, i, now):
        """Mark a due mail as going out, so nothing else sends it meanwhile. False when it is not due,
        is being sent already, or is being changed in a compose."""
        with self.sched_edit() as items:
            x = next((y for y in items if y["id"] == i), None)
            if (x is None or x["at"] > now or x.get("error") or (x.get("retry_at") or 0) > now
                    or self.going_out(x) or self.editing.get(i, 0) > time.time() - self.HOLD):
                return False
            x["sending"] = {"pid": os.getpid(), "at": int(time.time())}
            self.inflight.add(i)
            return True

    def sched_after(self, i, now, error=None, later=None):
        """A scheduled send that failed: for good (error, shown), or before anything left (later: tried
        again with a growing pause; the already-sent and Sent checks still guard against a double send)."""
        with self.sched_edit() as items:
            for x in items:
                if x["id"] != i:
                    continue
                x.pop("sending", None)
                if error:
                    x["error"] = error
                    for k in ("tries", "retry_at", "note"):
                        x.pop(k, None)
                else:
                    x["tries"] = int(x.get("tries") or 0) + 1
                    x["retry_at"] = int(now + min(60 * 2 ** (x["tries"] - 1), self.RETRY_MAX))
                    x["note"] = later

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
        with self.sched_edit() as items:
            self.row(i)
            if i in self.inflight:
                fail("This mail is going out right now.")
            items[:] = [x for x in items if x["id"] != i] + [{"id": i, "at": at}]
            self.editing.pop(i, None)
        self.sched_wake.set()
        return {"id": i, "at": at}

    def api_unschedule(self, a):
        """Keep the mail as a draft and do not send it."""
        with self.sched_edit() as items:
            x = next((y for y in items if y["id"] == a["id"]), None)
            if x is not None and self.going_out(x):
                fail("This mail is going out right now.")
            items[:] = [y for y in items if y["id"] != a["id"]]
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
            r["sched_retry"] = x.get("retry_at")
            r["sched_note"] = x.get("note")
            out.append(r)
        return out

    def sched_loop(self):
        while not self.stopping.is_set():
            self.sched_wake.wait(15)
            self.sched_wake.clear()
            if self.stopping.is_set():
                break
            try:
                self.send_due()
            except (Exception, SystemExit):     # noqa: BLE001 - the loop must outlive any one mail
                traceback.print_exc(file=sys.stderr)

    def send_due(self, now=None):
        """Send every scheduled mail that is due, one at a time. A failure before anything left this
        computer (no network after sleep, the server did not answer) is tried again later; any other
        failure stays in the list with its reason: a send that broke half way could go out twice."""
        now = time.time() if now is None else now
        sent = 0
        for x in sorted(self.sched_list(), key=lambda x: x["at"]):
            if not self.sched_claim(x["id"], now):
                continue
            try:
                self.send_now({"id": x["id"]})
            except R.SendLater as e:
                self.sched_after(x["id"], now, later=friendly(e))
            except (Exception, SystemExit) as e:    # noqa: BLE001 - every reason is shown to the person
                self.sched_after(x["id"], now, error=str(e) if isinstance(e, ApiError) else friendly(e))
            else:
                self.sched_drop(x["id"])
                sent += 1
            finally:
                with self.schedlock:
                    self.inflight.discard(x["id"])
        return sent

    def api_delete_draft(self, a):
        folder, uid = self.parse(a["id"])
        if folder != R.CFG.folders["drafts"]:
            fail("Only drafts can be deleted this way.")
        with self.schedlock:
            if a["id"] in self.inflight:
                fail("This mail is going out right now.")
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
            with contextlib.suppress(Exception):
                self.take_show()
            self.stopping.wait(1)

    def take_show(self):
        """The app was opened again (a second copy found this one running): show this one's window,
        or in the browser this one's page."""
        path = show_flag()
        if not os.path.exists(path):
            return False
        with contextlib.suppress(OSError):
            os.remove(path)
        if WINDOW.w is not None:
            bring_front()
        elif self.url:
            webbrowser.open(self.url)
        return True

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
                "signature": self.signature(), **self.api_signatures({}), "has_password": self.has_password(),
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
            m = imaplib.IMAP4_SSL(ihost, iport, ssl_context=R.tls_context(), timeout=20)
        except Exception as e:
            fail("Incoming server: " + friendly(e), str(e))
        try:
            try:
                m.login(user, pw)
            except imaplib.IMAP4.error as e:
                fail("Incoming server: sign-in failed. Check the address and password; some providers "
                     "need an app password.", str(e))
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
            fail("Outgoing server: sign-in failed. Check the address and password; some providers "
                 "need an app password.", e.smtp_error.decode(errors="replace")[:200])
        except Exception as e:
            fail("Outgoing server: " + friendly(e), str(e))
        return {"folders": found}

    def api_save_settings(self, a):
        if self.demo:
            fail("Settings can't be changed in the demo.")
        path = config_path()
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("not a JSON object")
        except FileNotFoundError:
            raw = {}
        except ValueError:
            # a file that can't be read is not written over: a copy of it stays beside the new one (#49)
            keep = "%s.broken-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
            try:
                shutil.copy2(path, keep)
            except OSError as e:
                fail("The settings file %s can't be read, and no copy of it could be kept." % path, str(e))
            print("the settings file could not be read; a copy is kept at %s" % keep, file=sys.stderr)
            self.made.add(keep)
            raw = {}
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
        write_config(path, raw)
        old = (R.CFG.user, R.CFG.imap.get("host"), R.CFG.imap.get("port"), R.CFG.home)
        R.CFG = R.load_config(path)
        new = (R.CFG.user, R.CFG.imap.get("host"), R.CFG.imap.get("port"), R.CFG.home)
        if new[3] != old[3]:
            with self.dblock:
                self.c = R.db()
        if new != old:
            # another account or server: no connection, loop or cached mail of the old one goes on (#59)
            self.restart_sync(clear=bool(old[0]) and new[0] != old[0] and new[3] == old[3],
                              redetect=not a.get("folders"))
        self.drop()
        self.server_folders = None
        self.contacts = (0, {})
        self.clear_error()
        self.start_sync()
        self.bump()
        return self.api_boot({})

    def restart_sync(self, clear, redetect):
        """The account or server changed: every loop drops its connection and starts again with the
        new settings. clear: another account in the same index; its mail, folders and cache go."""
        self.gen += 1
        self.pre.clear()
        for m in (self.m, self.dm, self.sync_m, self.pre_m, self.body_m):
            cut(m)
        end = time.time() + 10      # the pass and the text download under way end at their next step
        while (self.sync["running"] or self.bodies is not None) and time.time() < end:
            time.sleep(0.02)
        self.drop()
        with self.dlock:
            self.drop_download()
        self.folder_status, self.extra_at, self.redetect = {}, 0, redetect
        if not clear:
            return
        with self.dblock:
            c = self.c
            c.execute("delete from msgs")
            c.execute("delete from fts")
            c.execute("delete from state")
            c.execute("delete from links")
            c.execute("delete from meta where k in ('folders', 'last_sync') or k like 'modseq:%' or k like 'sweep:%'")
            c.commit()
        shutil.rmtree(os.path.join(R.CFG.home, "cache"), ignore_errors=True)
        self.found, self.news, self.news_mark, self.counts = [], [], None, None
        self.built.clear()
        with self.marklock:
            self.marks.clear()
        self.sync["last"] = None

    def use_detected(self, fs):
        """The special folders found on the server after a change of account or server, saved without
        a "Test connection" (which finds them itself): the old provider's names would fail (#59)."""
        path = config_path()
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        folders = dict(R.DEFAULTS["folders"], **fs)
        sync = [folders["inbox"], folders["sent"], folders["drafts"]]
        if raw.get("folders") == folders and raw.get("sync_folders") == sync:
            return
        raw["folders"], raw["sync_folders"] = folders, sync
        write_config(path, raw)
        R.CFG = R.load_config(path)
        self.bump()

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
        # a full signature for new mail and a short one for replies, to switch between
        zh = ds is DEMO_SETS["zh"]
        full = '<div style="color:#6b6b6b;font-size:13px">%s</div>' % ds["signature"]
        short = '<div style="color:#6b6b6b;font-size:13px">%s</div>' % ds["signature"].split("<br>")[0]
        d["signatures"] = [{"id": "full", "name": "完整" if zh else "Full", "html": full},
                           {"id": "short", "name": "简短" if zh else "Short", "html": short}]
        d["signature_new"], d["signature_reply"] = "full", "short"
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


class Restart(Exception):
    """The settings changed while a sync pass ran: it stops, and the next one uses the new ones."""


def own_db(c):
    """A loop's own index connection, made again when the index moved (another data_dir)."""
    want = os.path.realpath(os.path.join(R.CFG.home, "index.db"))
    if c is not None:
        try:
            if os.path.realpath(c.execute("pragma database_list").fetchone()[2]) == want:
                return c
        except Exception:       # noqa: BLE001 - closed or broken: made again
            pass
        with contextlib.suppress(Exception):
            c.close()
    return R.db()


def write_config(path, raw):
    """config.json written whole or not at all: to a file beside it, then put in its place."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


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


def cache_files(k):
    """The copies of one mail kept on disk (k = folder, uidvalidity, uid): whole, light, and its files."""
    whole = R.cache_path(*k)
    return [whole, R.light_path(*k)] + glob.glob(glob.escape(whole[:-4]) + ".part*.eml")


def cache_move(old, new):
    """A renamed folder's mail keeps its copies on disk: they are filed under the folder's name."""
    for p in cache_files(old):
        if os.path.exists(p):
            to = R.cache_path(*new)[:-4] + p[len(R.cache_path(*old)) - 4:]
            with contextlib.suppress(OSError):
                os.makedirs(os.path.dirname(to), exist_ok=True)
                os.replace(p, to)


def cache_drop(k):
    for p in cache_files(k):
        with contextlib.suppress(OSError):
            os.remove(p)


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


WINDOW = SimpleNamespace(w=None, hwnd=0, tokens=[], backend=None, quit_ok=False, asked=0, frameless=False, proc=None)


def close_window():
    with contextlib.suppress(Exception):
        WINDOW.w.destroy()


def page_call(js):
    """Run a line in the page, from any thread but the window's own (run_js waits for that one)."""
    def go():
        with contextlib.suppress(Exception):
            run = getattr(WINDOW.w, "run_js", None) or WINDOW.w.evaluate_js
            run(js)
    threading.Thread(target=go, daemon=True).start()


def window_closing():
    """The window is closing, or the app quitting. A mail in its undo pause: the page asks whether to send
    it now, cancel it or keep the window open (and closes it itself, api_quit_window). A send talking to
    the mail server: it finishes first, then the window closes. False keeps the window open."""
    b = WINDOW.backend
    if WINDOW.quit_ok or b is None:
        return True
    held, active = b.send_state()
    if held and WINDOW.asked == 0:
        WINDOW.asked = 1
        page_call("window.ragdollClosing && window.ragdollClosing()")
        return False
    if held and WINDOW.asked == 2:          # the page answers: it shows its question (again)
        page_call("window.ragdollClosing && window.ragdollClosing()")
        return False
    # (asked before and the page never showed its question: it can't answer, so what it holds goes now)
    if held or active:
        def finish():
            for i in [k for k, j in list(b.holding.items()) if j["state"] == "held"]:
                b.run_held(i)
            b.wait_sends()
            WINDOW.quit_ok = True
            close_window()
        threading.Thread(target=finish, daemon=True).start()
        return False
    return True


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


def win_frameless(hwnd):
    """Windows: no title bar strip, as on the Mac. The window keeps its real frame, so it still resizes from its
    edges, snaps to the screen's sides and keeps its shadow; only the caption is taken out of the frame
    (WM_NCCALCSIZE), and the page draws the window buttons (win_do, .win-ctl in the page)."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    u32.CallWindowProcW.restype = LRESULT
    u32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u32.SetWindowLongPtrW.restype = ctypes.c_void_p
    u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    u32.IsZoomed.argtypes = [wintypes.HWND]

    class NCCALC(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    def frame_y(h):
        # a maximized window reaches past the screen by its sizing frame: keep that much off the top
        try:
            dpi = u32.GetDpiForWindow(h)
            return u32.GetSystemMetricsForDpi(33, dpi) + u32.GetSystemMetricsForDpi(92, dpi)   # SM_CYFRAME, SM_CXPADDEDBORDER
        except Exception:
            return u32.GetSystemMetrics(33) + u32.GetSystemMetrics(92)

    old = None

    def proc(h, msg, wp, lp):
        if msg == 0x0083 and wp:                                    # WM_NCCALCSIZE
            r = ctypes.cast(lp, ctypes.POINTER(NCCALC)).contents.rgrc[0]
            top = r.top
            res = u32.CallWindowProcW(old, h, msg, wp, lp)          # the sides and the foot keep their frame
            r.top = top + (frame_y(h) if u32.IsZoomed(h) else 0)    # the caption goes
            return res
        return u32.CallWindowProcW(old, h, msg, wp, lp)

    cb = WNDPROC(proc)
    old = u32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(cb, ctypes.c_void_p))     # GWLP_WNDPROC
    if not old:
        return False
    WINDOW.proc = cb                                                # keep the callback alive
    # SWP_FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER | NOACTIVATE: the frame is measured again
    u32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010)
    WINDOW.frameless = True
    return True


def win_do(what):
    """The page's window buttons and title bar on Windows (win_frameless)."""
    if sys.platform != "win32" or not WINDOW.hwnd:
        return {"max": False, "frameless": False}
    import ctypes
    u32, hwnd = ctypes.windll.user32, WINDOW.hwnd
    zoomed = bool(u32.IsZoomed(hwnd))
    cmd = {"min": 0xF020, "max": 0xF120 if zoomed else 0xF030, "close": 0xF060}.get(what)   # SC_MINIMIZE, SC_RESTORE/MAXIMIZE, SC_CLOSE
    if cmd:
        u32.PostMessageW(hwnd, 0x0112, cmd, 0)                     # WM_SYSCOMMAND: as if the real buttons were pressed
    elif what == "drag":
        # Windows moves the window itself, so it snaps to the sides and to the top; that has to start on the
        # window's own thread, with the page's hold on the mouse let go first
        def go():
            u32.ReleaseCapture()
            u32.SendMessageW(hwnd, 0x00A1, 2, 0)                    # WM_NCLBUTTONDOWN on HTCAPTION
        try:
            from System import Action
            WINDOW.w.native.BeginInvoke(Action(go))
        except Exception:
            u32.PostMessageW(hwnd, 0x0112, 0xF012, 0)               # SC_MOVE by the caption
    return {"max": bool(u32.IsZoomed(hwnd)), "frameless": WINDOW.frameless}


# the app icons people can pick (Settings, Appearance): the file for the page, the Mac and Windows
APP_ICONS = {"classic": ("logo.png", "logo-mac.png", "logo.ico"),
             "painted": ("logo-painted.png", "logo-painted-mac.png", "logo-painted.ico")}


def app_icon_file(name):
    """The icon file this system shows for the window, the taskbar or the Dock."""
    page, mac, ico = APP_ICONS.get(name) or APP_ICONS["classic"]
    f = os.path.join(STATIC, mac if sys.platform == "darwin" else ico if sys.platform == "win32" else page)
    return f if os.path.exists(f) else None


def set_app_icon(name):
    """Show the picked icon now: the Dock on a Mac, the window and its taskbar button on Windows. The icon of
    the app file itself (Finder, a pinned taskbar shortcut) stays the one it was built with."""
    f = app_icon_file(name)
    if not f or WINDOW.w is None:
        return
    try:
        if sys.platform == "darwin":
            import AppKit
            from PyObjCTools import AppHelper
            AppHelper.callAfter(lambda: AppKit.NSApplication.sharedApplication().setApplicationIconImage_(
                AppKit.NSImage.alloc().initWithContentsOfFile_(f)))
        elif sys.platform == "win32" and WINDOW.hwnd:
            import ctypes
            u32 = ctypes.windll.user32
            u32.LoadImageW.restype = ctypes.c_void_p
            u32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
            for which, metric in ((1, 11), (0, 49)):                   # ICON_BIG / SM_CXICON, ICON_SMALL / SM_CXSMICON
                size = u32.GetSystemMetrics(metric)
                h = u32.LoadImageW(None, f, 1, size, size, 0x0010)      # IMAGE_ICON, LR_LOADFROMFILE
                if h:
                    u32.SendMessageW(WINDOW.hwnd, 0x0080, which, h)    # WM_SETICON
    except Exception:       # noqa: BLE001 - the icon stays as it was
        traceback.print_exc(file=sys.stderr)


def hex_ref(c):
    """'#RRGGBB' -> Windows COLORREF (0x00BBGGRR)."""
    c = (c or "").lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        return None
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return r | g << 8 | b << 16


def mac_appearance(AppKit, dark, system):
    """The window's appearance: None follows macOS (theme System), else Aqua or DarkAqua is forced. A forced one
    is all the page sees, so with System it would never hear macOS switch between light and dark."""
    if system:
        return None
    return AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua if dark else AppKit.NSAppearanceNameAqua)


def window_theme(dark, bg=None, text=None, system=False):
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
            nw.setAppearance_(mac_appearance(AppKit, dark, system))
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


def one_instance():
    """The open lock file when this is the only copy of the app on this mailbox, else None. The lock
    goes with the process, also when it crashes."""
    os.makedirs(R.CFG.home, exist_ok=True)
    f = open(os.path.join(R.CFG.home, "app-instance.lock"), "a+")
    if R.try_lock(f):
        return f
    f.close()
    return None


def show_flag():
    return os.path.join(R.CFG.home, "asks", "show-window")


def ask_show():
    """Ask the copy of the app that runs to show itself (Backend.take_show)."""
    os.makedirs(os.path.dirname(show_flag()), exist_ok=True)
    with open(show_flag(), "w") as f:
        f.write(str(os.getpid()))


WINDOW_SIZE = (1280, 820)
WINDOW_MIN = (880, 560)


def fit_window(saved, areas):
    """Where the window opens and how big: the saved place (prefs "window": x, y, width, height, maximized), kept
    inside the screen it was on, never larger than that screen's work area. areas: the screens' work areas as
    (x, y, width, height), top-left origin, the main screen first. A window on a screen that is gone opens in the
    middle of the main one; with nothing saved it opens at the default size, centred. x and y are None when no
    screen is known (the window system places it)."""
    saved = saved if isinstance(saved, dict) else {}
    num = lambda v: v if type(v) in (int, float) else None     # noqa: E731
    w, h = num(saved.get("width")), num(saved.get("height"))
    w, h = (int(w), int(h)) if w and h and w >= 200 and h >= 200 else WINDOW_SIZE
    x, y = num(saved.get("x")), num(saved.get("y"))
    out = {"width": w, "height": h, "x": None, "y": None, "maximized": saved.get("maximized") is True}
    areas = [a for a in areas or () if a[2] > 0 and a[3] > 0]
    if not areas:
        return out

    def overlap(a):
        return max(0, min(x + w, a[0] + a[2]) - max(x, a[0])) * max(0, min(y + h, a[1] + a[3]) - max(y, a[1]))
    area = max(areas, key=overlap) if x is not None and y is not None else None
    if area is None or overlap(area) == 0:
        area, x, y = areas[0], None, None
    ax, ay, aw, ah = (int(v) for v in area)
    w = max(min(w, aw), min(WINDOW_MIN[0], aw))
    h = max(min(h, ah), min(WINDOW_MIN[1], ah))
    if x is None:
        x, y = ax + (aw - w) // 2, ay + (ah - h) // 2
    out.update(width=w, height=h, x=int(min(max(x, ax), ax + aw - w)), y=int(min(max(y, ay), ay + ah - h)))
    return out


def screen_areas():
    """The screens' work areas (no menu bar, Dock or taskbar), top-left origin, the main screen first; [] if unknown."""
    try:
        if sys.platform == "darwin":
            import AppKit
            screens = AppKit.NSScreen.screens()
            top = screens[0].frame().size.height
            return [(v.origin.x, top - v.origin.y - v.size.height, v.size.width, v.size.height)
                    for v in (s.visibleFrame() for s in screens)]
        import webview
        out = []
        for s in webview.screens:
            f = getattr(s, "frame", None)        # Windows: the work area
            out.append((f.X, f.Y, f.Width, f.Height) if hasattr(f, "Width") else (s.x, s.y, s.width, s.height))
        return out
    except Exception:       # noqa: BLE001
        return []


def window_place():
    """The window's place for this start (see fit_window)."""
    saved = None
    with contextlib.suppress(Exception):
        saved = WINDOW.backend.prefs().get("window")
    return fit_window(saved, screen_areas())


def keep_window_place(w, place):
    """Remember the window's size and place: on resize and move (a second after the last one) and on close.
    A maximized, full-screen or minimized window keeps the size it had before. Never stops the window closing."""
    state = {k: place.get(k) for k in ("x", "y", "width", "height", "maximized")}
    flags = {"max": bool(place.get("maximized")), "min": False, "timer": None}

    def save():
        with contextlib.suppress(Exception):
            WINDOW.backend.api_prefs({"window": dict(state)})

    def later():
        if flags["timer"]:
            flags["timer"].cancel()
        flags["timer"] = threading.Timer(1.0, save)
        flags["timer"].daemon = True
        flags["timer"].start()

    def resized(width, height):
        if not (flags["max"] or flags["min"]):
            state.update(width=int(width), height=int(height))
            later()

    def moved(x, y):
        if not (flags["max"] or flags["min"]) and x > -30000 and y > -30000:     # Windows parks a minimized one there
            state.update(x=int(x), y=int(y))
            later()

    def maximized():
        flags["max"] = True
        if sys.platform != "darwin":           # on a Mac this is full screen, not kept for the next start
            state["maximized"] = True
            later()

    def minimized():
        flags["min"] = True

    def restored():
        flags["max"] = flags["min"] = False
        if state["maximized"]:
            state["maximized"] = False
            later()

    def closing():
        if flags["timer"]:
            flags["timer"].cancel()
        save()

    ev = w.events
    ev.resized += resized
    ev.moved += moved
    ev.maximized += maximized
    ev.minimized += minimized
    ev.restored += restored
    ev.closing += closing
    if sys.platform == "darwin" and place.get("x") is not None:
        ev.before_show += lambda: mac_place(w, place)


def mac_place(w, place):
    """Put the Mac window where it was (pywebview reads x and y against the focused screen, not the main one)."""
    try:
        import AppKit
        nw = w.native
        top = AppKit.NSScreen.screens()[0].frame().size.height
        nw.setFrame_display_(AppKit.NSMakeRect(place["x"], top - place["y"] - place["height"],
                                               place["width"], place["height"]), True)
    except Exception:       # noqa: BLE001
        pass


def run_window(url, home):
    import webview
    dark = system_dark()
    place = window_place()
    mac = sys.platform == "darwin"
    w = webview.create_window(APP_NAME, url, width=place["width"], height=place["height"], min_size=WINDOW_MIN,
                              x=None if mac else place["x"], y=None if mac else place["y"],
                              maximized=place["maximized"] and not mac,
                              background_color="#191919" if dark else "#FFFFFF", text_select=True)
    WINDOW.w = w
    keep_window_place(w, place)
    w.events.closing += window_closing      # a mail on its way is sent or asked about first
    if sys.platform == "darwin":
        mac_full_frame_rate()
        w.events.before_show += lambda: mac_titlebar(w)
        w.events.shown += lambda: mac_titlebar(w)
    elif sys.platform == "win32":
        def shown():
            WINDOW.hwnd = WINDOW.hwnd or win_hwnd(w)
            try:
                if WINDOW.hwnd:
                    win_frameless(WINDOW.hwnd)
            except Exception:       # noqa: BLE001 - the window keeps Windows' own title bar
                traceback.print_exc(file=sys.stderr)
            window_theme(dark, "#191919" if dark else "#FFFFFF", "#E8E8E6" if dark else "#191919")
        w.events.shown += shown
    if sys.platform == "win32":     # the page moves the window through Windows itself (win_do "drag"), not pywebview
        webview.settings["DRAG_REGION_SELECTOR"] = ".pywebview-drag-off"
    # pywebview sets this as the Dock icon on macOS, over the bundle's .icns, and as the window's icon on
    # Windows, which needs an .ico: the icon the person picked, in the file this system takes
    picked = (WINDOW.backend.prefs().get("icon") if WINDOW.backend else None) or "classic"
    webview.start(private_mode=False, storage_path=os.path.join(home, "webview"), icon=app_icon_file(picked))


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
    # one copy of the app per mailbox: a second one (a double-click on a slow start, a second app
    # bundle) would sync and send scheduled mail beside the first. It brings the first one forward.
    instance = None
    if not a.demo:
        instance = one_instance()
        if instance is None:
            ask_show()
            print("Ragdoll Mail is already open; it was brought to the front.", file=sys.stderr)
            return 0
    try:
        backend = Backend(demo=a.demo, demo_lang=demo_lang(a.demo_lang) if a.demo else "en")
    except R.IndexTooNew as e:
        return too_new(str(e), a.browser)
    WINDOW.backend = backend                # the window keeps its size and place in the prefs
    token = os.environ.get("RAGDOLL_APP_TOKEN") or secrets.token_urlsafe(24)
    srv = Server(("127.0.0.1", a.port), make_handler(backend, token))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/#t=%s" % (srv.server_address[1], token)
    backend.url = url
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
