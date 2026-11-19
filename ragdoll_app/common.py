"""Things every part of the app uses: where files are, the error the page is shown, small helpers."""

import imaplib
import os
import re
import smtplib
import socket
import ssl
import subprocess
import sys

import ragdoll as R


__version__ = R.__version__


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the folder with ragdoll.py and app/


STATIC = os.path.join(getattr(sys, "_MEIPASS", HERE), "app")


FROZEN = bool(getattr(sys, "frozen", False))


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
