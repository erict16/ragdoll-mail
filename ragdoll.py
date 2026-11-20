#!/usr/bin/env python3
"""ragdoll: a mail CLI for one IMAP/SMTP mailbox, made to be driven by an AI agent and checked by a person.

Some servers (Tencent Exmail among them) ignore IMAP text search and return
every mail, so ragdoll keeps a local SQLite index and searches that. The index
is filled in two passes: headers and attachment names for every mail first
(fast), then the start of each body, newest first.

  status                                    index size, bodies still missing, last sync
  sync [--bodies] [--workers N] [--all-folders]
                                            new mail, flags, deletions; --bodies keeps
                                            going until every body is indexed
  search [words] [--folder F] [--from X] [--to X] [--since D] [--until D]
         [--unread] [--starred] [--att] [--limit N] [--json]
                                            all words must match subject, sender,
                                            recipients, attachment names or body;
                                            with no words, the filters alone choose
  list [--folder F] [the same filters] [--limit N] [--json]
                                            one folder (the inbox when none is named)
  folders [--json]                          the folders on the server and what is indexed
  thread <id> [--json]                      the whole conversation, inbox and sent
  read <id> [--new] [--json] [--html FILE] [--eml FILE]
  attach <id> [--out DIR] [--name PART] [--inline]
  draft [--reply <id> [--all] | --forward <id>] [--to A,B] [--cc A,B] [--bcc A,B]
        [--remove A,B] [--subject S] (--body FILE.html | --text "...")
        [--attach FILE ...] [--no-sig] [--high] [--replace <draft id>]
  drafts [--json]
  check <draft id> [--reply] [--blanks-ok] [--no-required-cc] [--json]
  send <draft id> --yes
  delete-draft <draft id> --yes
  mark <id ...> [--read | --unread] [--star | --unstar]
  archive <id ...>                          move to the archive folder
  move <id ...> --to FOLDER                 a short name (inbox, archive, junk) or a
                                            folder name from `folders`
  trash <id ...> --yes                      move to the trash folder
  update [--check] [--rollback] [--json]    get the newest ragdoll from GitHub (see below)

Ids look like inbox:9255, sent:1420, drafts:3 (folder short name and IMAP UID).
Dates are YYYY-MM-DD in the configured time zone.

Config: ~/.config/ragdoll-mail/config.json (or $RAGDOLL_CONFIG); see config.example.json.
The password is read from the environment variable named by "password_env"
(on Windows also from that user variable in the registry). ragdoll never prints it.

Updates: every few hours ragdoll looks for a newer version in the background and, when there
is one, prints one line on stderr. It never replaces itself on its own: `update` does that,
refuses while another ragdoll command runs or the clone has local changes, runs the offline
tests on the new version and puts the old one back if they fail. `update --rollback` goes
back one version. Steps are logged to <data dir>/logs/update.log. Off: "update_check": false
in the config or RAGDOLL_NO_UPDATE_CHECK=1.

Before 0.4.0 this program was called hmail. The first run after that moves ~/.config/hmail and
~/.local/share/hmail to their new names (and the paths in the config with them); the old
HMAIL_* environment variables still work.
"""
import argparse, base64, contextlib, datetime as dt, email, email.header, hashlib, html as htmlmod, imaplib
import json, mimetypes, os, re, smtplib, sqlite3, subprocess, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parsedate_to_datetime
import encodings.aliases, unicodedata

__version__ = "0.8.5"

# Chinese mail clients label text GB2312 but use GBK characters (e.g. 喆 in 陈喆). Strict GB2312
# turns those into "�B", and a reply then carried the broken name (16th Nov 2026). GB18030 is a
# superset of GB2312 and GBK; cp950 likewise of Big5.
for _cs in ("gb2312", "gb_2312", "gb_2312_80", "gb2312_1980", "eucgb2312_cn", "euc_cn", "euccn", "chinese",
            "csiso58gb231280", "iso_ir_58", "csgb2312", "gbk", "cp936", "ms936", "x_gbk", "936"):
    encodings.aliases.aliases[_cs] = "gb18030"
for _cs in ("big5", "big5_tw", "csbig5", "x_x_big5"):
    encodings.aliases.aliases[_cs] = "cp950"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULTS = {
    "user": "",
    "name": "",
    "imap": {"host": "", "port": 993},
    "smtp": {"host": "", "port": 465},
    "password_env": "RAGDOLL_PASSWORD",
    "folders": {"inbox": "INBOX", "sent": "Sent Messages", "drafts": "Drafts",
                "trash": "Deleted Messages", "junk": "Junk", "archive": "Archive"},
    "sync_folders": ["INBOX", "Sent Messages", "Drafts"],
    "data_dir": "~/.local/share/ragdoll-mail",
    "utc_offset_hours": None,       # None: the computer's time zone
    "signature": "",
    "signature_marks": [],
    "require_cc": [],
    "body_bytes": 30000,
    "body_chars": 20000,
    "update_check": True,
}
QUOTE_MARKS = ("发件人", "From:", "原始邮件", "wrote:", "Từ:")
QUOTE_RE = re.compile(
    r"^\s*(-{3,}\s*(原始邮件|Original Message|Forwarded message)|发件人[:：]|From:\s|Từ:\s|"
    r"On .{5,120} wrote:|在 .{5,80}写道[:：])", re.M | re.I)
PREFIX_RE = re.compile(r"^\s*((re|fw|fwd|aw|wg|tr|trả lời|chuyển tiếp|bls|回复|答复|转发)\s*[:：]\s*)+", re.I)
INLINE_ID = re.compile(r"^[0-9A-Fa-f]{8}@[0-9A-Fa-f.]+(\.(png|jpe?g|gif|bmp|webp))?$", re.I)   # Exmail inline-image names
WEEK = "一二三四五六日"
# Fold only at the RFC 5322 hard limit: folding at 78 made Python encode long Message-IDs as
# =?utf-8?q?...?=, which broke threading (sent:1431, 16th Nov 2026); no limit at all let a
# reply-all To line pass 998 characters.
OUT_POLICY = policy.SMTP.clone(max_line_length=998)
PLACEHOLDER_RE = re.compile(r"\[[^\]\n]{0,40}\]|\bX{3,}\b|\bTBD\b|\{\{|待定|待补|待填|【[^】\n]{0,20}】")
ATTACH_WORDS_RE = re.compile(r"(?i)\battach(ed|ment|ments)?\b|\benclosed\b|附件|附上|随附|见附|附图|đính kèm")


# ------------------------------------------------------------------ config

class Cfg:
    def __init__(self, d):
        self.d = d

    def __getattr__(self, k):
        return self.d[k]

    @property
    def tz(self):
        h = self.d.get("utc_offset_hours")
        if h is None:
            return dt.datetime.now().astimezone().tzinfo
        return dt.timezone(dt.timedelta(hours=h))

    @property
    def home(self):
        return os.path.expanduser(self.d["data_dir"])

    def folder(self, name):
        if not name:
            return "INBOX"
        return self.d["folders"].get(name.lower(), name)

    def short(self, folder):
        for k, v in self.d["folders"].items():
            if v == folder:
                return k
        return folder


def env(name):
    """RAGDOLL_<name>, or HMAIL_<name> from before the rename."""
    return os.environ.get("RAGDOLL_" + name) or os.environ.get("HMAIL_" + name)


def move_old_setup(path=None, home=None):
    """Once, after the rename from hmail (0.4.0): move ~/.config/hmail to ~/.config/ragdoll-mail
    and ~/.local/share/hmail to ~/.local/share/ragdoll-mail, and fix the config's paths.
    A folder that cannot be moved (Windows, a file in use) is used where it is.
    Returns (config path, settings to use for this run)."""
    home = home or os.path.expanduser("~")
    exp = lambda p: home + p[1:] if p.startswith("~") else p    # noqa: E731
    same = lambda a, b: os.path.normcase(os.path.normpath(exp(a))) == os.path.normcase(os.path.normpath(b))  # noqa: E731
    over = {}
    if not path:
        new = os.path.join(home, ".config", "ragdoll-mail")
        old = os.path.join(home, ".config", "hmail")
        if not os.path.exists(new) and os.path.isdir(old):
            try:
                os.rename(old, new)
            except OSError:
                new = old
        path = os.path.join(new, "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}                                           # load_config reports a broken file
    changed = False
    old_data = os.path.join(home, ".local", "share", "hmail")
    new_data = os.path.join(home, ".local", "share", "ragdoll-mail")
    dd = raw.get("data_dir")
    if dd is None or same(dd, old_data):
        if os.path.isdir(old_data) and not os.path.exists(new_data):
            try:
                os.rename(old_data, new_data)
            except OSError:
                pass
        if os.path.isdir(old_data):
            over["data_dir"] = old_data                    # could not move it: keep using it
        elif dd is not None:
            raw["data_dir"], changed = "~/.local/share/ragdoll-mail", True
    sig = raw.get("signature")
    if isinstance(sig, str) and sig and not os.path.exists(exp(sig)):
        for to in ("ragdoll", "ragdoll-mail"):             # e.g. a skills/hmail/ folder renamed too
            moved = re.sub(r"(?<=[/\\])hmail(?=[/\\])", to, sig)
            if moved != sig and os.path.exists(exp(moved)):
                raw["signature"], changed = moved, True
                break
    if changed:
        try:
            tmp = "%s.%d.tmp" % (path, os.getpid())
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp, path)
        except OSError:
            over.update({k: raw[k] for k in ("data_dir", "signature") if k in raw})
    return path, over


def load_config(path=None):
    path, over = move_old_setup(path or env("CONFIG"))
    d = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                d[k].update(v)
            else:
                d[k] = v
    d.update(over)
    d["user"] = (d.get("user") or "").strip().lower()
    return Cfg(d)


CFG = load_config()


def die(msg):
    sys.exit(msg)


def password():
    """The mailbox password: the environment variable named by password_env (on Windows also that
    user variable in the registry), else the system keychain (what the app saves)."""
    name = CFG.password_env
    p = os.environ.get(name) or (name == "RAGDOLL_PASSWORD" and os.environ.get("HMAIL_PASSWORD"))
    if not p and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                p = winreg.QueryValueEx(k, name)[0]
        except OSError:
            pass
    if not p and CFG.user:
        p = keychain_get(CFG.user)
    if not p:
        die("%s is not set and no password is saved in the keychain. The mailbox owner sets it; "
            "an agent must never type, print or store it." % name)
    return p


# ------------------------------------------------------------------ keychain
# The app saves the password here (macOS Keychain, Windows Credential Manager), so nobody has to
# set an environment variable. ctypes only, no extra packages.

KEYCHAIN_SERVICE = "ragdoll-mail"


def _mac_security():
    import ctypes
    import ctypes.util
    sec = ctypes.CDLL(ctypes.util.find_library("Security"))
    cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
    sec.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    sec.SecKeychainAddGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
    sec.SecKeychainItemModifyAttributesAndData.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                           ctypes.c_uint32, ctypes.c_char_p]
    sec.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    sec.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    return ctypes, sec, cf


def _mac_find(account, service):
    ctypes, sec, cf = _mac_security()
    s, a = service.encode(), account.encode()
    n, data, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
    err = sec.SecKeychainFindGenericPassword(None, len(s), s, len(a), a, ctypes.byref(n), ctypes.byref(data),
                                             ctypes.byref(item))
    if err:
        return None, None, (ctypes, sec, cf)
    pw = ctypes.string_at(data, n.value).decode("utf-8", "replace")
    sec.SecKeychainItemFreeContent(None, data)
    return pw, item, (ctypes, sec, cf)


def _win_cred():
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    adv.CredFree.argtypes = [ctypes.c_void_p]
    return ctypes, adv, CREDENTIAL


def keychain_get(account, service=KEYCHAIN_SERVICE):
    """The saved password for this mailbox, or None (also when there is no keychain)."""
    try:
        if sys.platform == "darwin":
            pw, item, (ctypes, sec, cf) = _mac_find(account, service)
            if item:
                cf.CFRelease(item)
            return pw
        if sys.platform == "win32":
            ctypes, adv, CREDENTIAL = _win_cred()
            p = ctypes.POINTER(CREDENTIAL)()
            if not adv.CredReadW("%s:%s" % (service, account), 1, 0, ctypes.byref(p)):
                return None
            try:
                c = p.contents
                return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le")
            finally:
                adv.CredFree(p)
    except Exception:
        return None
    return None


def keychain_set(account, pw, service=KEYCHAIN_SERVICE):
    """Save (or replace) the password. Raises OSError when it could not be saved."""
    if sys.platform == "darwin":
        old, item, (ctypes, sec, cf) = _mac_find(account, service)
        b = pw.encode()
        if item:
            err = sec.SecKeychainItemModifyAttributesAndData(item, None, len(b), b)
            cf.CFRelease(item)
        else:
            s, a = service.encode(), account.encode()
            err = sec.SecKeychainAddGenericPassword(None, len(s), s, len(a), a, len(b), b, None)
        if err:
            raise OSError("the keychain refused the password (error %d)" % err)
        return
    if sys.platform == "win32":
        ctypes, adv, CREDENTIAL = _win_cred()
        blob = pw.encode("utf-16-le")
        c = CREDENTIAL()
        c.Type = 1                        # CRED_TYPE_GENERIC
        c.TargetName = "%s:%s" % (service, account)
        c.UserName = account
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = ctypes.cast(ctypes.create_string_buffer(blob, len(blob)), ctypes.POINTER(ctypes.c_char))
        c.Persist = 2                     # CRED_PERSIST_LOCAL_MACHINE
        if not adv.CredWriteW(ctypes.byref(c), 0):
            raise OSError("Credential Manager refused the password (error %d)" % ctypes.get_last_error())
        return
    raise OSError("no keychain on this system: set %s instead" % CFG.password_env)


def keychain_delete(account, service=KEYCHAIN_SERVICE):
    with contextlib.suppress(Exception):
        if sys.platform == "darwin":
            old, item, (ctypes, sec, cf) = _mac_find(account, service)
            if item:
                sec.SecKeychainItemDelete(item)
                cf.CFRelease(item)
        elif sys.platform == "win32":
            ctypes, adv, CREDENTIAL = _win_cred()
            adv.CredDeleteW("%s:%s" % (service, account), 1, 0)


def need_account():
    if not (CFG.user and CFG.imap["host"]):
        die("no account configured: copy config.example.json to ~/.config/ragdoll-mail/config.json")


# ------------------------------------------------------------------ IMAP helpers

def mutf7(s):
    """Folder name to IMAP modified UTF-7."""
    out, buf = [], ""

    def flush():
        nonlocal buf
        if buf:
            b = base64.b64encode(buf.encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append("&" + b + "-")
            buf = ""
    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf += ch
    flush()
    return "".join(out)


def mutf7_decode(s):
    return re.sub(r"&([^-]*)-", lambda x: "&" if not x.group(1) else base64.b64decode(
        x.group(1).replace(",", "/") + "=" * (-len(x.group(1)) % 4)).decode("utf-16-be"), s)


def q(folder):
    return '"' + mutf7(folder).replace("\\", "\\\\").replace('"', '\\"') + '"'


def imap():
    need_account()
    # a server that does not answer must not hold the caller (the app's one connection) for minutes
    m = imaplib.IMAP4_SSL(CFG.imap["host"], CFG.imap["port"], timeout=15)
    m.login(CFG.user, password())
    with contextlib.suppress(Exception):
        m.sock.settimeout(None)         # signing in is quick, a big mail is not: reads wait as before
    try:        # imaplib keeps the pre-login list; MOVE and UIDPLUS often appear only after login
        typ, data = m.capability()
        if typ == "OK" and data and data[0]:
            m.capabilities = tuple(data[0].decode().upper().split())
    except Exception:
        pass
    return m


def has_cap(m, name):
    return name.upper() in {(x.decode() if isinstance(x, bytes) else x).upper() for x in m.capabilities}


@contextlib.contextmanager
def session():
    m = imap()
    try:
        yield m
    finally:
        try:
            m.logout()
        except Exception:
            pass


def select(m, folder, readonly=True):
    m._sel = None
    typ, data = m.select(q(folder), readonly=readonly)
    if typ != "OK":
        raise LookupError("cannot open folder %s: %s" % (folder, data))
    uidv = int(m.response("UIDVALIDITY")[1][0])
    m._sel = (folder, readonly, uidv)
    return uidv


def use(m, folder, write=False):
    """select(), but a folder this connection already has open stays open: on Exmail a SELECT of a
    big folder costs one to three seconds, even of the folder already open."""
    s = getattr(m, "_sel", None)
    if s and s[0] == folder and (not write or not s[1]):
        getattr(m, "untagged_responses", {}).pop("FETCH", None)     # other clients' flag changes, not ours
        return s[2]
    return select(m, folder, readonly=not write)


def uids_of(m):
    typ, data = m.uid("SEARCH", None, "ALL")
    return [int(x) for x in (data[0] or b"").split()]


def segments(data):
    """imaplib FETCH data -> list of parts per message (literals kept in order)."""
    segs = []
    for item in data:
        if item is None:
            continue
        if isinstance(item, tuple):
            head, lit = item
            if re.match(rb"\d+ \(", head):
                segs.append([head, lit])
            elif segs:
                segs[-1] += [head, lit]
        elif re.match(rb"\d+ \(", item):
            segs.append([item])
        elif segs:
            segs[-1].append(item)
    return segs


def literal_after(seg, pattern):
    for k, part in enumerate(seg):
        if re.search(pattern + rb" \{\d+\}$", part) and k + 1 < len(seg):
            return seg[k + 1]
    return b""


def seg_uid(seg):
    mo = re.search(rb"UID (\d+)", b"".join(p for p in seg if isinstance(p, bytes))[:4000])
    return int(mo.group(1)) if mo else None


def flags_of(blob):
    mo = re.search(rb"FLAGS \(([^)]*)\)", blob)
    f = mo.group(1).decode() if mo else ""
    return int("\\Seen" in f), int("\\Flagged" in f), int("\\Answered" in f)


def look_again(m):
    """A mail that came in after this connection opened its folder is not in the connection's view
    yet, and a FETCH of it answers nothing: NOOP lets the server show it."""
    m.noop()
    getattr(m, "untagged_responses", {}).pop("FETCH", None)


def fetch_one(m, uid, items):
    """{item name: value} of a UID FETCH for one mail; asked once more when the answer is empty."""
    for again in (False, True):
        typ, data = m.uid("FETCH", str(uid), items)
        got = fetch_items(data, uid)
        if got or again:
            return got
        look_again(m)


def fetch_raw(m, folder, uid):
    use(m, folder)
    for again in (False, True):
        typ, data = m.uid("FETCH", str(uid), "(BODY.PEEK[])")
        for item in data:
            if isinstance(item, tuple):
                return item[1]
        if not again:
            look_again(m)
    die("no mail %s (moved or deleted? run search again)" % make_id(folder, uid))


# ---- a big mail without its big files: what opening it needs, in a fraction of the time

LIGHT_MIN = 1536 * 1024     # a mail this big is opened light
LEAVE_OUT = 256 * 1024      # a file part this big stays on the server until it is opened
SHOWN_MAX = 11 * 1024 * 1024    # an image shown in the body comes with the mail up to this size
SECTION_RE = re.compile(r"[0-9]+(\.[0-9]+)*")       # an IMAP body section: 2, 1.3, ...
OURS_RE = re.compile(rb"(?im)^X-Ragdoll-[^\r\n]*\r?\n(?:[ \t][^\r\n]*\r?\n)*")


def imap_parse(data):
    """imaplib response data (bytes, and (head, literal) tuples) -> nested lists of bytes / None."""
    toks = []
    for item in data:
        if item is None:
            continue
        if isinstance(item, tuple):
            toks += re.findall(rb'\(|\)|"(?:[^"\\]|\\.)*"|\{\d+\}|[^\s()"]+', re.sub(rb"\{\d+\}$", b"", item[0]))
            toks.append((item[1],))
        else:
            toks += re.findall(rb'\(|\)|"(?:[^"\\]|\\.)*"|\{\d+\}|[^\s()"]+', item)
    out, stack = [], []
    cur = out
    for t in toks:
        if isinstance(t, tuple):
            cur.append(t[0])
        elif t == b"(":
            stack.append(cur)
            cur.append([])
            cur = cur[-1]
        elif t == b")":
            cur = stack.pop() if stack else out
        elif t.startswith(b'"'):
            cur.append(re.sub(rb'\\(.)', rb"\1", t[1:-1]))
        elif t.upper() == b"NIL":
            cur.append(None)
        elif not re.fullmatch(rb"\{\d+\}", t):
            cur.append(t)
    return out


def fetch_items(data, uid):
    """{item name: value} of the FETCH response for this UID."""
    toks = imap_parse(data)
    for t in toks:                      # imaplib leaves "<n> (...)" of each "* <n> FETCH (...)"
        if isinstance(t, list):
            d = {(t[j].upper() if isinstance(t[j], bytes) else t[j]): t[j + 1] for j in range(0, len(t) - 1, 2)}
            if d.get(b"UID") == str(uid).encode():
                return d
    return {}


def leaves(bs, sec=""):
    """BODYSTRUCTURE -> [(section, type, subtype, shown in the body, encoding, octets, Content-ID)] for
    its leaves, and the sections of its multiparts; None when the mail is a single part."""
    if not bs or not isinstance(bs, list):
        return None
    if isinstance(bs[0], list):
        parts, multis = [], [sec]
        k = 0
        for child in bs:
            if not isinstance(child, list):
                break
            k += 1
            sub = leaves(child, "%s.%d" % (sec, k) if sec else str(k))
            if sub is None:
                return None
            parts += sub[0]
            multis += sub[1]
        return parts, multis
    if not sec:
        return None
    low = lambda v: (v or b"").decode("ascii", "replace").lower()
    try:
        size = int(bs[6] or 0)
    except (ValueError, TypeError, IndexError):
        size = 0
    disp = next((low(x[0]) for x in bs[7:] if isinstance(x, list) and x and isinstance(x[0], bytes)
                 and low(x[0]) in ("inline", "attachment")), "")
    shown = bs[3] is not None and disp != "attachment"     # a Content-ID alone does not: Outlook gives every file one
    return [(sec, low(bs[0]), low(bs[1]), shown, low(bs[5]), size, low(bs[3]).strip().strip("<>"))], []


def keep_part(typ, shown, size):
    if typ in ("text", "message"):
        return True
    if shown:                                   # an image shown in the body
        return size <= SHOWN_MAX
    return size <= LEAVE_OUT


def cid_refs(html):
    """The Content-IDs the HTML body shows (its cid: links)."""
    return {urllib.parse.unquote(x).strip("<>") for x in re.findall(r"""(?i)cid:<?([^"'\s>)]+)""", html or "")}


def fetch_light(m, folder, uid):
    """The mail with its big file parts left empty, or None when that would not help. A part left out
    keeps its own headers and gains X-Ragdoll-Part (its IMAP section) and X-Ragdoll-Size (its bytes)."""
    try:
        return light_mail(m, folder, uid)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None         # a structure this does not know: the caller fetches the whole mail


def light_mail(m, folder, uid):
    use(m, folder)
    found = leaves(fetch_one(m, uid, "(UID BODYSTRUCTURE)").get(b"BODYSTRUCTURE"))
    if not found:
        return None
    parts, multis = found
    out = [p for p in parts if not keep_part(p[1], p[3], p[5])]
    if not out:
        return None
    want = ["BODY.PEEK[HEADER]"] + ["BODY.PEEK[%s.MIME]" % s for s in multis if s] + \
           ["BODY.PEEK[%s.MIME]" % p[0] for p in parts] + ["BODY.PEEK[%s]" % p[0] for p in parts if p not in out]
    typ, data = m.uid("FETCH", str(uid), "(UID %s)" % " ".join(want))
    got = fetch_items(data, uid)

    def item(name):
        v = got.get(name.upper().encode())
        return v if isinstance(v, bytes) else b""
    head = {"": item("BODY[HEADER]")}
    for s in multis:
        if s:
            head[s] = item("BODY[%s.MIME]" % s)
    if not head[""]:
        return None
    left = {p[0]: p for p in out}
    leaf = {p[0] for p in parts}

    def hdr_block(h, extra=b""):
        # an X-Ragdoll header that came with the mail is not ours: only the ones added here count
        return OURS_RE.sub(b"", h.rstrip(b"\r\n") + b"\r\n") + extra + b"\r\n"

    def build(sec):
        if sec in leaf:
            mime = item("BODY[%s.MIME]" % sec)
            if sec in left:
                p = left[sec]
                n = int(p[5] * 57 / 78) if p[4] == "base64" else p[5]
                return hdr_block(mime, b"X-Ragdoll-Part: %s\r\nX-Ragdoll-Size: %d\r\n" % (sec.encode(), n))
            return hdr_block(mime) + item("BODY[%s]" % sec)
        h = head[sec]
        b = email.message_from_bytes(hdr_block(h)).get_boundary()
        if not b:
            raise ValueError("no boundary")
        kids = sorted({x[len(sec) + 1 if sec else 0:].split(".")[0] for x in leaf | set(head)
                       if x and (x.startswith(sec + ".") if sec else True)}, key=int)
        body = b"".join(b"--" + b.encode() + b"\r\n" + build("%s.%s" % (sec, k) if sec else k) + b"\r\n" for k in kids)
        return (hdr_block(h) if sec else b"") + body + b"--" + b.encode() + b"--\r\n"
    raw = hdr_block(head[""]) + build("")
    # a picture the body shows can be marked as a file (Content-Disposition: attachment) and so was
    # left out: it would show blank. Bring in the ones the HTML refers to after all.
    maybe = [p for p in out if p[6] and p[5] <= SHOWN_MAX and (p[1] == "image" or p[1:3] == ("application", "octet-stream"))]
    if maybe:
        refs = cid_refs(bodies(to_msg(raw))[1])
        more = [p for p in maybe if p[6] in refs]
        if more:
            got.update(fetch_one(m, uid, "(UID %s)" % " ".join("BODY.PEEK[%s]" % p[0] for p in more)))
            for p in more:
                if item("BODY[%s]" % p[0]):
                    del left[p[0]]
            raw = hdr_block(head[""]) + build("")
    return raw


def fetch_part_raw(m, folder, uid, sec):
    """One part of a mail, its MIME headers and body as they are on the server."""
    if not SECTION_RE.fullmatch(str(sec)):      # it goes into the IMAP command as it is
        die("bad part number %r" % (sec,))
    use(m, folder)
    got = fetch_one(m, uid, "(UID BODY.PEEK[%s.MIME] BODY.PEEK[%s])" % (sec, sec))
    mime, body = got.get(("BODY[%s.MIME]" % sec).encode()), got.get(("BODY[%s]" % sec).encode())
    if not isinstance(mime, bytes) or not isinstance(body, bytes):
        die("no mail %s (moved or deleted? run search again)" % make_id(folder, uid))
    return OURS_RE.sub(b"", mime.rstrip(b"\r\n") + b"\r\n") + b"\r\n" + body


def fetch_part(m, folder, uid, sec):
    """One part of a mail (its MIME headers and body) as a message, for a file left out of a light mail."""
    return to_msg(fetch_part_raw(m, folder, uid, sec))


def part_path(folder, uidv, uid, sec):
    """Where a file fetched by itself (fetch_part_raw) is kept, beside the light mail it belongs to."""
    return cache_path(folder, uidv, uid)[:-4] + ".part%s.eml" % sec


def light_path(folder, uidv, uid):
    return cache_path(folder, uidv, uid)[:-4] + ".light.eml"


def cache_path(folder, uidv, uid):
    key = hashlib.sha1(("%s|%s|%s" % (folder, uidv, uid)).encode()).hexdigest()
    return os.path.join(CFG.home, "cache", key[:2], key + ".eml")


def cache_get(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def cache_put(path, raw):
    with contextlib.suppress(OSError):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".%d.tmp" % os.getpid()
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, path)


def mail_raw(folder, uid, m=None):
    """One whole mail. The copy the app or an earlier command kept is used when there is one
    (a mail on the server never changes); a draft is always fetched, it may have been replaced."""
    path = None
    if folder != CFG.folders.get("drafts"):
        with contextlib.suppress(sqlite3.Error):
            c = db()
            r = c.execute("select uidv from msgs where folder=? and uid=?", (folder, uid)).fetchone()
            c.close()
            if r:
                path = cache_path(folder, r["uidv"], uid)
                raw = cache_get(path)
                if raw:
                    return raw
    if m is not None:
        raw = fetch_raw(m, folder, uid)
    else:
        with session() as own:
            raw = fetch_raw(own, folder, uid)
    if path:
        cache_put(path, raw)
    return raw


def all_folders(m):
    typ, data = m.list()
    out = []
    for line in data:
        mo = re.search(rb'"([^"]*)"$|(\S+)$', line)
        out.append(mutf7_decode((mo.group(1) or mo.group(2)).decode()))
    return out


# ------------------------------------------------------------------ message helpers

def to_msg(raw):
    return email.message_from_bytes(raw, policy=policy.default)


def nfc(s):
    return unicodedata.normalize("NFC", s) if s else (s or "")


def fix_8bit(s):
    """Text that came in as raw 8-bit bytes (surrogate escapes): decode as UTF-8, else GB18030."""
    if not s or not re.search("[\udc80-\udcff]", s):
        return s
    b = s.encode("utf-8", "surrogateescape")
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("gb18030", "replace")


def hdr(msg, name):
    try:
        raw = next((v for k, v in msg.raw_items() if k.lower() == name.lower()), None)
        if raw is not None and re.search("[\udc80-\udcff]", raw):
            # unencoded GBK header bytes: policy.default would turn them into U+FFFD
            return nfc(str(msg.policy.header_fetch_parse(name, fix_8bit(raw))))
        v = msg.get(name)
        return nfc(str(v)) if v is not None else ""
    except Exception:
        return ""


def fname(p):
    """Attachment filename, repaired when it came as raw 8-bit bytes."""
    try:
        n = p.get_filename()
    except Exception:
        n = None
    if n and "�" in n:         # raw 8-bit GBK name: the library already replaced it, use the raw header
        for hname, pname in (("Content-Disposition", "filename"), ("Content-Type", "name")):
            raw = next((v for k, v in p.raw_items() if k.lower() == hname.lower()), None)
            if raw and re.search("[\udc80-\udcff]", raw):
                try:
                    v = p.policy.header_fetch_parse(hname, fix_8bit(raw)).params.get(pname)
                except Exception:
                    v = None
                if v and "�" not in v:
                    n = v
                    break
    if not n and p.get_content_type() == "message/rfc822":
        sub = p.get_payload(0) if p.is_multipart() else None
        n = ((hdr(sub, "Subject") if sub is not None else "") or "attached mail")[:80] + ".eml"
    return nfc(fix_8bit(n)) if n else n


def part_bytes(p):
    """Bytes of a leaf part; an attached mail (message/rfc822) as its .eml."""
    if p.get_content_type() == "message/rfc822":
        sub = p.get_payload(0) if p.is_multipart() else None
        if sub is not None:
            return sub.as_bytes(policy=OUT_POLICY)
    return p.get_payload(decode=True) or b""


def addrs(value):
    return [(n, a.lower()) for n, a in getaddresses([value or ""]) if a and "@" in a]


def one_line(s):
    """A header value never holds a line break (EmailMessage refuses one; it could also add a header)."""
    return re.sub(r"\s*[\r\n]+\s*", " ", s) if s else s


def fmt_addrs(lst):
    return ", ".join(formataddr((one_line(n), one_line(a))) if n else one_line(a) for n, a in lst)


def html_to_text(h):
    h = re.sub(r"(?is)<(style|script|head)\b.*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>|</blockquote>", "\n", h)
    h = re.sub(r"(?i)</t[dh]>", "\t", h)
    h = htmlmod.unescape(re.sub(r"<[^<>]+>", "", h))      # [^<>]: a stray "<" must not make it quadratic
    h = re.sub(r"[ \t ​]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n\n", h).strip()


def b64_cut(p):
    """The bytes of a base64 part whose end is missing, or None. The index reads only the start of a
    mail; when the cut leaves one base64 character too many, the email module gives the text back
    undecoded, and the preview showed "RGVhciBNcy4g..."."""
    if (p.get("Content-Transfer-Encoding") or "").strip().lower() != "base64":
        return None
    s = p.get_payload()
    if not isinstance(s, str):
        return None
    s = re.sub(r"[^A-Za-z0-9+/]", "", s)
    if len(s) % 4 != 1:
        return None
    try:
        return base64.b64decode(s[:-1] + "=" * (-(len(s) - 1) % 4))
    except ValueError:
        return None


def part_text(p):
    """Text of a part; never raises on an unknown or wrong charset (unknown-8bit, csGB2312, ...)."""
    payload = b64_cut(p)
    if payload is None:
        try:
            return nfc(p.get_content())
        except Exception:
            pass
        payload = p.get_payload(decode=True) or b""
    else:
        try:        # the cut can also split the last character: drop it rather than fail on it
            return nfc(payload.decode(p.get_content_charset() or "utf-8", "ignore"))
        except LookupError:
            pass
    for cs, err in ((p.get_content_charset() or "utf-8", "strict"), ("utf-8", "strict"), ("gb18030", "replace")):
        try:
            return nfc(payload.decode(cs, err))
        except (LookupError, UnicodeDecodeError):
            continue
    return ""


def leaf_parts(msg):
    """Leaf parts, without going inside an attached mail (message/rfc822 is one leaf)."""
    if msg.get_content_type() == "message/rfc822" or not msg.is_multipart():
        yield msg
        return
    for p in msg.get_payload():
        yield from leaf_parts(p)


def bodies(msg):
    """(plain, html) of the main body, never the body of an attached mail."""
    plain = html = ""
    for p in leaf_parts(msg):
        if p is not msg and p.get_content_disposition() == "attachment":
            continue
        ct = p.get_content_type()
        if ct == "text/plain" and not plain and not p.get_filename():
            plain = part_text(p)
        elif ct == "text/html" and not html and not p.get_filename():
            html = part_text(p)
    return plain, html


ENTITY_RE = re.compile(r"&(?:nbsp|amp|lt|gt|quot|#\d{2,5});")


def plain_text(plain):
    """Tencent's mailers write HTML entities into the plain text part ("Hi John,&nbsp;"); turn them
    back into characters. Only a text that has &nbsp; is treated so: elsewhere "&lt;" may be meant."""
    if "&nbsp;" in plain:
        plain = ENTITY_RE.sub(lambda mo: htmlmod.unescape(mo.group()), plain).replace("\xa0", " ")
    return plain


def body_text(msg):
    plain, html = bodies(msg)
    return plain_text(plain).strip() or html_to_text(html)


def new_text(text):
    mo = QUOTE_RE.search(text or "")
    return (text[:mo.start()] if mo else text or "").strip()


IMAGE_MAGIC = ((b"\x89PNG", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF8", "image/gif"),
               (b"BM", "image/bmp"))


def image_type(p):
    """The image type of a part, or "". Some mailers send body images as application/octet-stream:
    then the file name, or failing that the first bytes, tell."""
    if p.get_content_maintype() == "image":
        return p.get_content_type()
    if p.get_content_type() != "application/octet-stream":
        return ""
    guess = mimetypes.guess_type(fname(p) or "")[0] or ""
    if guess.startswith("image/"):
        return guess
    head = (p.get_payload(decode=True) or b"")[:12]
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return next((t for magic, t in IMAGE_MAGIC if head.startswith(magic)), "")


def is_inline(p):
    """An image shown in the body (cid:), not a file: a PDF with a Content-ID is still a file."""
    return (bool(p.get("Content-ID")) and p.get_content_disposition() != "attachment"
            and bool(image_type(p)))


def attachments(msg, inline=False):
    out = []
    for p in leaf_parts(msg):
        if p is msg and (msg.is_multipart() or not (
                p.get_content_disposition() == "attachment" or p.get_filename()
                or p.get_content_maintype() not in ("text", "multipart", "message"))):
            continue     # a mail that is only a file (a scanner's PDF) still shows that file
        is_file = (p.get_content_disposition() == "attachment" or p.get_filename()
                   or p.get_content_type() == "message/rfc822"
                   or (p.get("Content-ID") and not is_inline(p)))
        if is_file and (inline or not is_inline(p)):
            out.append(p)
    return out


def big_attachment_lines(text):
    """Filename/size/expiry lines of a Tencent big-attachment block (never the links)."""
    if "超大附件" not in text and "ftnExs" not in text:
        return []
    return [ln.strip() for ln in text.splitlines()
            if re.search(r"\d+(\.\d+)?\s*[KMG]B?\b|到期", ln) and len(ln.strip()) < 160
            and "http" not in ln][:8] or ["(big attachment block found)"]


def bare_subject(s):
    s = nfc(s or "")
    while True:
        t = PREFIX_RE.sub("", s).strip()
        if t == s:
            return re.sub(r"\s+", " ", t).lower()
        s = t


FWD_HEADER = "X-Forwarded-Message-Id"     # as Thunderbird does; Exmail keeps no forwarded flag


def is_forward_subject(s):
    return bool(re.match(r"(?i)\s*(fw|fwd|转发)\s*[:：]", s or ""))


def forward_source(msg):
    """The Message-ID this mail forwards, or "". Ours carry FWD_HEADER; a WeCom forward sometimes
    keeps the In-Reply-To of the mail it forwards."""
    mid = hdr(msg, FWD_HEADER).strip()
    if not mid and is_forward_subject(hdr(msg, "Subject")):
        mid = hdr(msg, "In-Reply-To").strip()
    return mid


def mark_forwarded(c):
    """forwarded=1 on every mail a forward in Sent points at (not a draft, not someone else's
    forward in the Inbox). Never taken off, like Answered."""
    c.execute("update msgs set forwarded=1 where forwarded=0 and msgid!='' and msgid in "
              "(select fwd from msgs where fwd!='' and folder=?)", (CFG.folders["sent"],))


def make_id(folder, uid):
    return "%s:%d" % (CFG.short(folder), uid)


def parse_id(i):
    if not isinstance(i, str) or ":" not in i:
        die("id must look like inbox:9255 or drafts:3, got %r" % (i,))
    f, uid = i.rsplit(":", 1)
    uid = uid.strip()
    if not (f.strip() and uid.isascii() and uid.isdigit() and 0 < int(uid) < 2 ** 32):
        die("id must look like inbox:9255 or drafts:3, got %r" % i)
    return CFG.folder(f), int(uid)


def local_time(ts):
    try:
        return dt.datetime.fromtimestamp(ts, CFG.tz).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError, OSError, TypeError):    # a broken Date header far out of range
        return "?"


def day_start(s, add_days=0):
    try:
        d = dt.datetime.fromisoformat(s)
    except (ValueError, TypeError):
        die("date must look like 2026-11-16, got %r" % (s,))
    return int((d + dt.timedelta(days=add_days)).replace(tzinfo=CFG.tz).timestamp())


# ------------------------------------------------------------------ index

SCHEMA = """
create table if not exists msgs(id integer primary key, folder text, uidv integer, uid integer,
  msgid text, irt text, refs text, ts integer, frm text, to_ text, cc text, subject text,
  atts text, body text, seen int, flagged int, answered int, size int default 0,
  has_body int default 0, fwd text default '', forwarded int default 0, unique(folder, uidv, uid));
create index if not exists msgs_ts on msgs(ts);
create index if not exists msgs_msgid on msgs(msgid);
create index if not exists msgs_irt on msgs(irt);
create index if not exists msgs_folder_ts on msgs(folder, ts, uid);
create virtual table if not exists fts using fts5(subject, frm, to_, atts, body, tokenize='trigram');
create table if not exists state(folder text primary key, uidv integer);
create table if not exists meta(k text primary key, v text);
create table if not exists links(ref text, id integer);
create index if not exists links_ref on links(ref);
create index if not exists links_id on links(id);
create trigger if not exists msgs_unlink after delete on msgs begin delete from links where id=old.id; end;
"""


def db():
    os.makedirs(CFG.home, exist_ok=True)
    c = sqlite3.connect(os.path.join(CFG.home, "index.db"), timeout=600, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("pragma journal_mode=wal")
    c.execute("pragma synchronous=normal")      # safe with WAL, and each commit no longer waits for the disk
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("pragma table_info(msgs)")}
    if "has_body" not in cols:     # index made by the first version: every row had its body
        c.execute("alter table msgs add column size int default 0")
        c.execute("alter table msgs add column has_body int default 0")
        c.execute("update msgs set has_body=1")
        c.commit()
    if "fwd" not in cols:          # forwarded marks: fwd = the Message-ID a sent forward came from
        c.execute("alter table msgs add column fwd text default ''")
        c.execute("alter table msgs add column forwarded int default 0")
        for r in c.execute("select id, subject, irt from msgs where irt!=''").fetchall():
            if is_forward_subject(r["subject"]):
                c.execute("update msgs set fwd=? where id=?", (r["irt"], r["id"]))
        mark_forwarded(c)
        c.commit()
    c.execute("create index if not exists msgs_fwd on msgs(fwd)")
    if not c.execute("select 1 from meta where k='charset_fix'").fetchone():
        # rows decoded before the GB18030/Big5/raw-8-bit fixes: drop them so the next sync
        # fetches them again with the right names
        bad = c.execute("select id from msgs where instr(frm||to_||cc||subject||atts||body, char(65533))>0"
                        ).fetchall()
        for r in bad:
            c.execute("delete from fts where rowid=?", (r["id"],))
            c.execute("delete from msgs where id=?", (r["id"],))
        c.execute("insert or replace into meta values('charset_fix', ?)", (str(len(bad)),))
        c.commit()
    if not c.execute("select 1 from meta where k='body_fix'").fetchone():
        # 0.8.0 and older: a base64 text cut at the wrong place was stored undecoded (the next sync
        # reads those again), and the entities of Tencent's plain texts were left as they came
        n = 0
        for r in c.execute("select id, body from msgs where has_body=1 and body!=''").fetchall():
            b = r["body"]
            if len(b) > 60 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", b[:400]) and " " not in b[:400].strip():
                c.execute("update msgs set body='', has_body=0 where id=?", (r["id"],))
                c.execute("update fts set body='' where rowid=?", (r["id"],))
            elif "&nbsp;" in b:
                b = plain_text(b)
                c.execute("update msgs set body=? where id=?", (b, r["id"]))
                c.execute("update fts set body=? where rowid=?", (b, r["id"]))
            else:
                continue
            n += 1
        c.execute("insert or replace into meta values('body_fix', ?)", (str(n),))
        c.commit()
    return c


def try_lock(f):
    """Non-blocking exclusive lock on an open file; True when we got it."""
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def unlock(f):
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        pass


@contextlib.contextmanager
def file_lock(name, wait):
    """Process lock in the data dir. Yields False when busy and wait is False."""
    os.makedirs(CFG.home, exist_ok=True)
    f = open(os.path.join(CFG.home, name + ".lock"), "a+")
    got = False
    try:
        while not (got := try_lock(f)) and wait:
            time.sleep(1)
        yield got
    finally:
        if got:
            unlock(f)
        f.close()


def decode_param(raw, extended):
    """One BODYSTRUCTURE parameter value: RFC 2047 words, or RFC 2231 charset''%XX, raw 8-bit."""
    from urllib.parse import unquote_to_bytes
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.decode("gb18030", "replace")
    mo = re.match(r"([\w.-]*)'[^']*'(.*)$", s, re.S) if extended else None
    if mo:
        try:
            return unquote_to_bytes(mo.group(2)).decode(mo.group(1) or "utf-8", "replace")
        except LookupError:
            return unquote_to_bytes(mo.group(2)).decode("utf-8", "replace")
    if extended and "%" in s:
        return unquote_to_bytes(s).decode("utf-8", "replace")
    try:
        return str(email.header.make_header(email.header.decode_header(s)))
    except Exception:
        return s


def bs_names(blob):
    """Attachment names from a BODYSTRUCTURE blob (quoted strings or literals).

    Handles any case, RFC 2231 continuations (FILENAME*0*, FILENAME*1*) and charsets, and drops a
    name that is the cut-off start of another (Exmail gives NAME cut at 30 characters beside the
    full FILENAME: "COMMERCIAL INVOICE ES26-006.pd")."""
    found, group = [], None              # group: [key, extended, [raw pieces]] of a continuation
    pat = rb'"(filename|name)(\*(\d+))?(\*)?" (?:"((?:[^"\\]|\\.)*)"|\{(\d+)\}\r?\n?)'
    for mo in re.finditer(pat, blob, re.I):
        if mo.group(5) is not None:
            raw = re.sub(rb"\\(.)", rb"\1", mo.group(5))
        else:
            n = int(mo.group(6))
            raw = blob[mo.end():mo.end() + n]
        key, extended = mo.group(1).lower(), bool(mo.group(2) or mo.group(4))
        if mo.group(3) is not None:          # continuation pieces arrive in order: *0, *1, ...
            if mo.group(3) == b"0" or group is None or group[0] != key:
                group = [key, extended, []]
                found.append(group)
            group[2].append(raw)
            continue
        group = None
        found.append(decode_param(raw, extended))
    names = []
    for v in found:
        if isinstance(v, list):
            v = decode_param(b"".join(v[2]), v[1])
        s = nfc(v.strip())
        if not s or INLINE_ID.match(s) or s in names:
            continue
        names.append(s)
    return [n for n in names if not any(o != n and o.startswith(n) and len(n) >= 20 for o in names)]


def header_row(seg):
    blob = b"".join(seg)
    msg = to_msg(literal_after(seg, rb"BODY\[HEADER\]"))
    ts = 0
    idate = re.search(rb'INTERNALDATE "([^"]+)"', blob)
    if idate:
        try:
            ts = int(time.mktime(imaplib.Internaldate2tuple(b'INTERNALDATE "' + idate.group(1) + b'"')))
        except Exception:
            ts = 0
    if not ts:
        try:
            ts = int(parsedate_to_datetime(hdr(msg, "Date")).timestamp())
        except Exception:
            ts = 0
    size = re.search(rb"RFC822\.SIZE (\d+)", blob)
    bs = blob.split(b"BODY[HEADER]")[0]
    return {"msgid": hdr(msg, "Message-ID").strip(), "irt": hdr(msg, "In-Reply-To").strip(),
            "fwd": forward_source(msg),
            "refs": hdr(msg, "References"), "ts": ts, "frm": hdr(msg, "From"), "to_": hdr(msg, "To"),
            "cc": hdr(msg, "Cc"), "subject": hdr(msg, "Subject"), "atts": " | ".join(bs_names(bs)),
            "size": int(size.group(1)) if size else 0, "flags": flags_of(blob)}


def sync_headers(m, c, folder, full_flags=False, workers=1, held=None):
    """New mail headers, flags and deletions for one folder. Returns new row count.
    held(folder, since) -> {uid: {"seen": 1, ...}}: flags the caller has changed that the server may
    not have had when it was asked at `since`; they stay as the caller set them."""
    try:
        uidv = select(m, folder)
    except LookupError:
        return 0
    old = c.execute("select uidv from state where folder=?", (folder,)).fetchone()
    if old and old["uidv"] != uidv:
        for r in c.execute("select id from msgs where folder=?", (folder,)).fetchall():
            c.execute("delete from fts where rowid=?", (r["id"],))
        c.execute("delete from msgs where folder=?", (folder,))
    c.execute("insert or replace into state values(?,?)", (folder, uidv))
    c.commit()
    server = set(uids_of(m))
    local = {r["uid"]: r["id"] for r in c.execute(
        "select uid, id from msgs where folder=? and uidv=?", (folder, uidv))}
    for uid, rid in local.items():
        if uid not in server:
            c.execute("delete from msgs where id=?", (rid,))
            c.execute("delete from fts where rowid=?", (rid,))
    # flags: all of them on a full sync, the newest 300 otherwise
    known = sorted(u for u in server if u in local)
    check = known if full_flags else known[-300:]
    for i in range(0, len(check), 500):
        asked = time.time()
        typ, data = m.uid("FETCH", ",".join(map(str, check[i:i + 500])), "(UID FLAGS)")
        mine = held(folder, asked) if held else {}
        for seg in segments(data):
            uid = seg_uid(seg)
            if uid in local:
                seen, flagged, answered = flags_of(b"".join(seg))
                if uid in mine:     # a mail just read in the app must not turn unread again
                    seen, flagged = mine[uid].get("seen", seen), mine[uid].get("flagged", flagged)
                c.execute("update msgs set seen=?, flagged=?, answered=? where id=?",
                          (seen, flagged, answered, local[uid]))
    c.commit()
    new = sorted((u for u in server if u not in local), reverse=True)
    chunks = [new[i:i + 100] for i in range(0, len(new), 100)]
    if len(chunks) > 2 and workers > 1:      # first sync: several connections (the server throttles each)
        ex = ThreadPoolExecutor(max_workers=workers)
        results = (f.result() for f in as_completed([ex.submit(fetch_headers, folder, ch) for ch in chunks]))
    else:
        ex = None
        results = (fetch_headers(folder, ch, m) for ch in chunks)
    done = 0
    for segs in results:
        for seg in segs:
            uid = seg_uid(seg)
            if uid is None or not literal_after(seg, rb"BODY\[HEADER\]"):
                continue        # e.g. an unasked FLAGS update: storing it would leave an empty row
            h = header_row(seg)
            cur = c.execute(
                "insert or ignore into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,"
                "seen,flagged,answered,size,has_body,fwd) values(?,?,?,?,?,?,?,?,?,?,?,?,'',?,?,?,?,0,?)",
                (folder, uidv, uid, h["msgid"], h["irt"], h["refs"], h["ts"], h["frm"], h["to_"], h["cc"],
                 h["subject"], h["atts"], *h["flags"], h["size"], h["fwd"]))
            if cur.rowcount:
                c.execute("insert into fts(rowid,subject,frm,to_,atts,body) values(?,?,?,?,?,'')",
                          (cur.lastrowid, h["subject"], h["frm"], h["to_"] + " " + h["cc"], h["atts"]))
        c.commit()
        done += len(segs)
        print("  %s headers: %d/%d" % (folder, done, len(new)), file=sys.stderr)
    if ex:
        ex.shutdown()
    if new:
        mark_forwarded(c)       # a new forward in Sent, or an original fetched again
        c.commit()
    return len(new)


HEADER_ITEMS = "(UID FLAGS INTERNALDATE RFC822.SIZE BODYSTRUCTURE BODY.PEEK[HEADER])"


def fetch_headers(folder, uids, m=None):
    """FETCH segments for these UIDs, on m or on a new connection."""
    if m is not None:
        typ, data = m.uid("FETCH", ",".join(map(str, uids)), HEADER_ITEMS)
        return segments(data)
    with session() as own:
        select(own, folder)
        typ, data = own.uid("FETCH", ",".join(map(str, uids)), HEADER_ITEMS)
        return segments(data)


def fetch_bodies(folder, uids):
    """Worker: the start of each body for these UIDs, on its own connection."""
    out = {}
    with session() as m:
        select(m, folder)
        for i in range(0, len(uids), 25):
            typ, data = m.uid("FETCH", ",".join(map(str, uids[i:i + 25])),
                              "(UID BODY.PEEK[]<0.%d>)" % CFG.body_bytes)
            for seg in segments(data):
                uid = seg_uid(seg)
                if uid is not None:
                    out[uid] = literal_after(seg, rb"BODY\[\]<0>")
    return out


def store_bodies(c, folder, got):
    for uid, raw in got.items():
        r = c.execute("select id from msgs where folder=? and uid=?", (folder, uid)).fetchone()
        if not r:
            continue
        try:
            text = body_text(to_msg(raw))[:CFG.body_chars] if raw else ""
        except Exception:       # one odd mail must not stop every later search
            text = ""
        c.execute("update msgs set body=?, has_body=1 where id=?", (text, r["id"]))
        c.execute("update fts set body=? where rowid=?", (text, r["id"]))
    c.commit()


def sync_bodies(c, folders, limit=None, workers=1, quiet=False):
    """Bodies for rows that lack them, newest first. limit=None means all."""
    rows = c.execute("select folder, uid from msgs where has_body=0 and folder in (%s) order by ts desc%s"
                     % (",".join("?" * len(folders)), "" if limit is None else " limit %d" % limit),
                     folders).fetchall()
    if not rows:
        return 0
    by_folder = {}
    for r in rows:
        by_folder.setdefault(r["folder"], []).append(r["uid"])
    jobs = []
    for f, uids in by_folder.items():
        for i in range(0, len(uids), 100):
            jobs.append((f, uids[i:i + 100]))
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(fetch_bodies, f, u): f for f, u in jobs}
        for fut in as_completed(futs):
            try:
                got = fut.result()
            except Exception as e:
                print("  body batch failed (%s); it will be retried next sync" % e, file=sys.stderr)
                continue
            store_bodies(c, futs[fut], got)
            done += len(got)
            if not quiet:
                print("  bodies: %d/%d" % (done, len(rows)), file=sys.stderr)
    return done


def quick_sync(also=None):
    """Run before every read command: new mail only, never waits for a long sync.
    also: one more folder to bring up to date (the one the command asked for)."""
    c = db()
    folders = list(CFG.sync_folders)
    if also and also not in folders:
        folders.append(also)
    elif just_synced(c):        # the app or the command before this one looked a moment ago
        bodies_later(c, folders)
        return c
    with file_lock("headers", wait=False) as got:
        if not got:
            print("(another ragdoll is syncing; showing the index as it is)", file=sys.stderr)
            return c
        try:
            with session() as m:
                for f in folders:
                    sync_headers(m, c, f)
        except (OSError, imaplib.IMAP4.abort) as e:
            # offline or the server is down: the index still answers
            c.rollback()
            print("(cannot reach the mail server: %s; showing the index as it is)" % e, file=sys.stderr)
            return c
        c.execute("insert or replace into meta values('last_sync', ?)", (str(int(time.time())),))
        c.commit()
    bodies_later(c, folders)
    return c


FRESH = 20      # seconds: a read command within this time of the last look at the server does not look again


def just_synced(c):
    r = c.execute("select v from meta where k='last_sync'").fetchone()
    try:
        return bool(r) and 0 <= time.time() - int(r[0]) < FRESH
    except ValueError:
        return False


def bodies_later(c, folders):
    """The text of older mail is fetched by a process of its own: no command waits for it."""
    if "unittest" in sys.modules or getattr(sys, "frozen", False):
        return
    if not c.execute("select 1 from msgs where has_body=0 and folder in (%s) limit 1"
                     % ",".join("?" * len(folders)), folders).fetchone():
        return
    with file_lock("bodies", wait=False) as got:
        if not got:
            return              # the app or another command is already at it
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              close_fds=True, cwd=APP_DIR)
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000 | 0x00000200     # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    with contextlib.suppress(OSError):
        subprocess.Popen([sys.executable, "-I", "-B", os.path.abspath(__file__), "bodies"], **kw)


def cmd_bodies(a):
    """Background: bring in the text of mail that has only its headers, then stop."""
    c = db()
    with file_lock("bodies", wait=False) as got:
        if not got:
            return
        for _ in range(500):
            if not sync_bodies(c, list(CFG.sync_folders), limit=150, workers=a.workers, quiet=True):
                break


# ------------------------------------------------------------------ output

def row_out(r, snippet=True):
    d = {"id": make_id(r["folder"], r["uid"]), "date": local_time(r["ts"]), "from": r["frm"],
         "to": r["to_"], "cc": r["cc"], "subject": r["subject"],
         "attachments": [x for x in (r["atts"] or "").split(" | ") if x],
         "unread": not r["seen"], "starred": bool(r["flagged"]), "answered": bool(r["answered"]),
         "forwarded": bool(r["forwarded"]), "body_indexed": bool(r["has_body"])}
    if snippet:
        d["snippet"] = re.sub(r"\s+", " ", new_text(r["body"] or ""))[:200]
    return d


def marks(r):
    """Two columns: ↩ replied, → forwarded."""
    return ("↩" if r["answered"] else " ") + ("→" if r["forwarded"] else " ")


def print_rows(rows, as_json, empty="(nothing found)", total=None):
    """total: how many mails matched before --limit cut the list (said only when some are left out)."""
    cut = total is not None and total > len(rows)
    note = "(showing the newest %d of %d; --limit %d shows all)" % (len(rows), total or 0, total or 0)
    if as_json:
        print(json.dumps([row_out(r) for r in rows], ensure_ascii=False, indent=1))
        if cut:
            print(note, file=sys.stderr)       # the JSON stays a plain list
        return
    for r in rows:
        f = addrs(r["frm"])
        who = (f[0][0] or f[0][1]) if f else ""
        print("%-14s %s %s%s%s %-20s %s%s" % (make_id(r["folder"], r["uid"]), local_time(r["ts"]),
                                            "*" if not r["seen"] else " ", "★" if r["flagged"] else " ",
                                            marks(r), who[:20], r["subject"],
                                          "  [%s]" % r["atts"] if r["atts"] else ""))
    if not rows:
        print(empty)
    if cut:
        print(note)


MAX_TERM = 200     # a longer search word is cut: a 1 MB word kept the index busy for minutes
MAX_TERMS = 30


def like_arg(t, cap=MAX_TERM):
    """A LIKE pattern that finds t literally: % and _ in what was typed are not wildcards."""
    return "%" + re.sub(r"([\\%_])", r"\\\1", t[:cap]) + "%"


def add_filters(a, where, params):
    if getattr(a, "folder", None):
        where.append("m.folder=?")
        params.append(CFG.folder(a.folder))
    elif CFG.folders.get("junk"):           # junk mail is found only when its folder is asked for
        where.append("m.folder!=?")
        params.append(CFG.folders["junk"])
    if getattr(a, "from_", None):
        where.append("m.frm like ? escape '\\'")
        params.append(like_arg(a.from_))
    if getattr(a, "to", None):
        where.append("(m.to_ like ? escape '\\' or m.cc like ? escape '\\')")
        params += [like_arg(a.to)] * 2
    if getattr(a, "since", None):
        where.append("m.ts>=?")
        params.append(day_start(a.since))
    if getattr(a, "until", None):
        where.append("m.ts<?")
        params.append(day_start(a.until, 1))
    if getattr(a, "unread", False):
        where.append("m.seen=0")
    if getattr(a, "starred", False):
        where.append("m.flagged=1")
    if getattr(a, "att", False):
        where.append("m.atts!=''")


def search_where(words, a):
    """(where clause, params) for the words and the filters in a."""
    where, params = [], []
    long_terms = []
    for t in (nfc(w)[:MAX_TERM] for w in words[:MAX_TERMS]):
        if not t:
            continue
        if len(t) >= 3:
            long_terms.append('"%s"' % t.replace('"', '""'))
        else:
            where.append("(" + " or ".join("m.%s like ? escape '\\'" % k
                                           for k in ("subject", "frm", "to_", "cc", "atts", "body")) + ")")
            params += [like_arg(t)] * 6
    if long_terms:
        where.insert(0, "m.id in (select rowid from fts where fts match ?)")
        params.insert(0, " AND ".join(long_terms))
    add_filters(a, where, params)
    return (("where " + " and ".join(where)) if where else ""), params


def search_rows(c, words, a):
    where, params = search_where(words, a)
    return c.execute("select m.* from msgs m %s order by m.ts desc limit ?" % where, params + [a.limit]).fetchall()


def search_total(c, words, a):
    where, params = search_where(words, a)
    return c.execute("select count(*) from msgs m %s" % where, params).fetchone()[0]


# ------------------------------------------------------------------ read commands

def cmd_status(a):
    c = db()
    total = c.execute("select count(*) from msgs").fetchone()[0]
    missing = c.execute("select count(*) from msgs where has_body=0").fetchone()[0]
    last = c.execute("select v from meta where k='last_sync'").fetchone()
    per = c.execute("select folder, count(*) n from msgs group by folder").fetchall()
    d = {"mails": total, "bodies_missing": missing, "last_sync": local_time(int(last[0])) if last else None,
         "folders": {r["folder"]: r["n"] for r in per}, "index": os.path.join(CFG.home, "index.db"),
         "version": __version__}
    st = update_state()
    latest = update_waiting()
    if latest:
        d["update_available"] = latest.get("version")
    if st.get("check_error"):
        d["update_check_error"] = st["check_error"]
    print(json.dumps(d, ensure_ascii=False, indent=1))


def cmd_sync(a):
    c = db()
    with file_lock("headers", wait=True):
        with session() as m:
            folders = all_folders(m) if a.all_folders else CFG.sync_folders
        for f in folders:
            # a fresh connection per folder: the server drops one left idle during a long parallel fetch
            for attempt in (1, 2):
                try:
                    with session() as m:
                        n = sync_headers(m, c, f, full_flags=True, workers=a.workers)
                    print("%s: %d new" % (f, n))
                    break
                except (imaplib.IMAP4.abort, OSError) as e:
                    if attempt == 2:
                        raise
                    print("  %s: connection dropped (%s), retrying" % (f, e), file=sys.stderr)
        c.execute("insert or replace into meta values('last_sync', ?)", (str(int(time.time())),))
        c.commit()
    if a.bodies:
        with file_lock("bodies", wait=True):
            n = sync_bodies(c, folders, limit=None, workers=a.workers)
            print("bodies indexed: %d" % n)
    cmd_status(a)


def cmd_search(a):
    if not a.words and not any((a.folder, a.from_, a.to, a.since, a.until, a.unread, a.starred, a.att)):
        die("give a word or a filter (--from, --to, --since, --until, --folder, --unread, --starred, --att)")
    c = db() if a.no_sync else quick_sync(CFG.folder(a.folder) if a.folder else None)
    rows = search_rows(c, a.words, a)
    print_rows(rows, a.json, total=search_total(c, a.words, a) if len(rows) >= a.limit else None)
    if not a.json:
        missing = c.execute("select count(*) from msgs where has_body=0").fetchone()[0]
        if missing:
            print("(%d older mails are searchable by subject, people and attachment names only; "
                  "their bodies are still being indexed)" % missing, file=sys.stderr)


def cmd_list(a):
    a.folder = a.folder or "inbox"
    c = db() if a.no_sync else quick_sync(CFG.folder(a.folder))
    rows = search_rows(c, [], a)
    print_rows(rows, a.json, total=search_total(c, [], a) if len(rows) >= a.limit else None)


def cmd_folders(a):
    """The folders on the server, the short name ragdoll has for each, and what the index holds."""
    with session() as m:
        names = all_folders(m)
    n = {r["folder"]: (r["n"], r["u"]) for r in db().execute(
        "select folder, count(*) n, coalesce(sum(seen=0),0) u from msgs group by folder")}
    out = [{"folder": f, "short": CFG.short(f) if CFG.short(f) != f else None,
            "indexed": n.get(f, (0, 0))[0], "unread": n.get(f, (0, 0))[1],
            "synced": f in CFG.sync_folders} for f in names]
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    for d in out:
        print("%-24s %-8s %6d indexed, %d unread%s" % (d["folder"], d["short"] or "", d["indexed"], d["unread"],
                                                      "" if d["synced"] else "  (indexed only when asked for)"))


def fill_links(c):
    """links(ref, id): every Message-ID a mail names (its own, In-Reply-To, References) and its bare
    subject, so a thread is found without reading the whole index. Filled for rows that lack it."""
    top = c.execute("select coalesce(max(id),0) from links").fetchone()[0]
    rows = c.execute("select id, msgid, irt, refs, subject from msgs where id>?", (top,)).fetchall()
    if not rows:
        return
    out = []
    for r in rows:
        refs = {r["msgid"] or ""} | set(re.findall(r"<[^<>]+>", (r["refs"] or "") + " " + (r["irt"] or "")))
        if r["irt"]:
            refs.add(r["irt"])
        refs.discard("")
        bs = bare_subject(r["subject"])
        if bs:
            refs.add("s:" + bs)
        refs.add("")            # every mail has a row, so the newest id in links is the newest one done
        out += [(x, r["id"]) for x in refs]
    c.executemany("insert into links(ref, id) values(?,?)", out)
    c.commit()


def thread_rows(c, row):
    fill_links(c)
    ids = {row["msgid"]} | set(re.findall(r"<[^<>]+>", (row["refs"] or "") + " " + (row["irt"] or "")))
    ids.discard("")
    ids.discard(None)
    seen = set()
    new = set(ids)
    for _ in range(6):
        if not new:
            break
        q, found = sorted(new), set()
        for k in range(0, len(q), 500):
            part = q[k:k + 500]
            found |= {r[0] for r in c.execute("select id from links where ref in (%s)" % ",".join("?" * len(part)), part)}
        fresh = sorted(found - seen)
        seen |= found
        new = set()
        for k in range(0, len(fresh), 500):
            part = fresh[k:k + 500]
            for r in c.execute("select msgid, irt, refs from msgs where id in (%s)" % ",".join("?" * len(part)), part):
                for x in [r["msgid"], r["irt"]] + re.findall(r"<[^<>]+>", (r["refs"] or "") + " " + (r["irt"] or "")):
                    if x and x not in ids:
                        ids.add(x)
                        new.add(x)
    # same bare subject within 180 days catches clients that drop References
    bs = bare_subject(row["subject"])
    if bs:
        seen |= {r[0] for r in c.execute(
            "select l.id from links l join msgs m on m.id=l.id where l.ref=? and m.ts between ? and ?",
            ("s:" + bs, row["ts"] - 180 * 86400, row["ts"] + 180 * 86400))}
    seen.discard(row["id"])
    out = {row["id"]: row}
    seen = sorted(seen)
    for k in range(0, len(seen), 500):
        part = seen[k:k + 500]
        for r in c.execute("select * from msgs where id in (%s)" % ",".join("?" * len(part)), part):
            out[r["id"]] = r
    return sorted(out.values(), key=lambda r: (r["ts"] or 0, r["id"]))


def cmd_thread(a):
    c = db() if a.no_sync else quick_sync()
    folder, uid = parse_id(a.id)
    row = c.execute("select * from msgs where folder=? and uid=?", (folder, uid)).fetchone()
    if not row:
        die("%s is not in the index; run search again" % a.id)
    rows = thread_rows(c, row)
    if a.json:
        print(json.dumps([row_out(r) for r in rows], ensure_ascii=False, indent=1))
        return
    for r in rows:
        f = addrs(r["frm"])
        who = (f[0][0] or f[0][1]) if f else ""
        print("── %s  %s  %s  %s" % (make_id(r["folder"], r["uid"]), local_time(r["ts"]), who, r["subject"]))
        if r["atts"]:
            print("   [%s]" % r["atts"])
        nt = new_text(r["body"] or "")
        print("   " + (re.sub(r"\n+", "\n   ", nt[:600]) if r["has_body"] else "(body not indexed yet: read it)"))


def cmd_read(a):
    folder, uid = parse_id(a.id)
    raw = mail_raw(folder, uid)
    msg = to_msg(raw)
    plain, html = bodies(msg)
    text = plain.strip() or html_to_text(html)
    atts = [{"name": fname(p) or "(no name)", "kb": len(part_bytes(p)) // 1024,
             "inline": is_inline(p)} for p in attachments(msg, inline=True)]
    atts = [x for x in atts if not (x["inline"] and INLINE_ID.match(x["name"]))]
    if a.html:
        with open(a.html, "w", encoding="utf-8") as f:
            f.write(with_meta(html or "<pre>%s</pre>" % htmlmod.escape(plain)))
    if a.eml:
        with open(a.eml, "wb") as f:
            f.write(raw)
    d = {"id": a.id, "date": hdr(msg, "Date"), "from": hdr(msg, "From"), "to": hdr(msg, "To"),
         "cc": hdr(msg, "Cc"), "subject": hdr(msg, "Subject"), "message_id": hdr(msg, "Message-ID"),
         "attachments": atts, "big_attachments": big_attachment_lines(html_to_text(html) or plain),
         "text": new_text(text) if a.new else text}
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return
    for k in ("from", "to", "cc", "date", "subject"):
        if d[k]:
            print("%-8s %s" % (k.capitalize() + ":", d[k]))
    for x in atts:
        print("Attach:  %s (%d KB)%s" % (x["name"], x["kb"], " inline" if x["inline"] else ""))
    for ln in d["big_attachments"]:
        print("Big att: %s" % ln)
    print()
    print(d["text"])


RESERVED = {"con", "prn", "aux", "nul", *("com%d" % i for i in range(1, 10)), *("lpt%d" % i for i in range(1, 10))}


def safe_name(n, max_bytes=200):
    n = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", n or "").strip().rstrip(". ") or "attachment"
    if os.path.splitext(n)[0].lower() in RESERVED:
        n = "_" + n
    if len(n.encode()) > max_bytes:      # most file systems stop at 255 bytes; keep room for " (2)"
        stem, ext = os.path.splitext(n)
        ext = ext if len(ext.encode()) <= 20 else ""
        stem = stem.encode()[:max_bytes - len(ext.encode())].decode("utf-8", "ignore").rstrip(". ")
        n = (stem or "attachment") + ext
    return n


def unique_path(folder, name, used):
    """folder/name, or folder/name (2).ext when this run already wrote that name."""
    stem, ext = os.path.splitext(name)
    path, k = os.path.join(folder, name), 2
    while path.lower() in used:
        path, k = os.path.join(folder, "%s (%d)%s" % (stem, k, ext)), k + 1
    used.add(path.lower())
    return path


def with_meta(html):
    """HTML saved to disk says it is UTF-8, or Chinese shows garbled when opened."""
    return html if re.search(r"(?i)<meta[^>]+charset", html[:2000]) else '<meta charset="utf-8">' + html


def cmd_attach(a):
    folder, uid = parse_id(a.id)
    raw = mail_raw(folder, uid)
    out = os.path.expanduser(a.out or ".")
    os.makedirs(out, exist_ok=True)
    n, used = 0, set()
    for p in attachments(to_msg(raw), inline=a.inline):
        name = fname(p) or "attachment"
        if a.name and a.name.lower() not in name.lower():
            continue
        path = unique_path(out, safe_name(name), used)
        with open(path, "wb") as f:
            f.write(part_bytes(p))
        print("saved %s (%d KB)" % (os.path.abspath(path), os.path.getsize(path) // 1024))
        n += 1
    if not n:
        die("no attachment matched")


# ------------------------------------------------------------------ drafts

def split_list(s):
    return [x.strip() for x in (s or "").replace(";", ",").split(",") if x.strip()]


def parse_people(s):
    """--to/--cc/--bcc value -> [(name, address)]: plain addresses or "Name <a@b>" (commas in
    quoted names are fine). Dies on something that is not an address."""
    out = []
    for n, ad in getaddresses([(s or "").replace(";", ",")]):
        ad = ad.strip().lower()
        if not ad and not n:
            continue
        if "@" not in ad or " " in ad:
            die("not an email address: %r (in %r)" % (ad or n, s))
        out.append((n.strip(), ad))
    return out


def clean_quoted_html(html):
    """The original's HTML as a fragment: no <html>/<head>/<body>, and above all no <meta charset=gb2312>,
    which would make some readers decode our whole UTF-8 reply as GB2312."""
    html = re.sub(r"(?is)<head\b.*?</head>", "", html)
    html = re.sub(r"(?is)^.*?<body[^>]*>|</body>.*$", "", html)
    html = re.sub(r"(?is)<!doctype[^>]*>|</?html\b[^>]*>|<meta\b[^>]*>|<base\b[^>]*>|<title\b.*?</title>", "", html)
    return html


def quote_block(orig):
    plain, html = bodies(orig)
    if not html:
        html = '<div style="white-space:pre-wrap">%s</div>' % htmlmod.escape(plain)
    html = clean_quoted_html(html)
    try:
        t = parsedate_to_datetime(hdr(orig, "Date"))
        if t.tzinfo is None:         # "-0000": time zone unknown, the time itself is UTC
            t = t.replace(tzinfo=dt.timezone.utc)
        t = t.astimezone(CFG.tz)
    except Exception:
        t = dt.datetime.now(CFG.tz)
    f = addrs(hdr(orig, "From"))
    fn, fa = f[0] if f else ("", "")

    def people(v):
        return ", ".join("&quot;%s&quot; &lt;%s&gt;" % (htmlmod.escape(n or a_), a_) for n, a_ in addrs(v))
    cc = people(hdr(orig, "Cc"))
    head = ('<div style="padding:8px 0;border-top:1px solid #e0e0e0;font-size:13px;color:#646a73">'
            '<div>发件人：&quot;%s&quot; &lt;%s&gt;</div><div>时间：%d年%d月%d日 (周%s) %s</div>'
            '<div>主题：%s</div><div>收件人：%s</div>%s</div>'
            % (htmlmod.escape(fn or fa), fa, t.year, t.month, t.day, WEEK[t.weekday()],
               t.strftime("%H:%M"), htmlmod.escape(hdr(orig, "Subject")), people(hdr(orig, "To")),
               "<div>抄送：%s</div>" % cc if cc else ""))
    return head + ('<blockquote style="margin:0 0 0 4px;padding-left:8px;border-left:2px solid #d0d3d6">'
                   + html + "</blockquote>")


def reply_recipients(orig, reply_all, user, extra_to=(), extra_cc=(), remove=()):
    """(to, cc) for a reply. On the owner's own mail, reply to its recipients."""
    frm = addrs(hdr(orig, "From"))
    if frm and frm[0][1] == user:
        to = addrs(hdr(orig, "To"))
        cc = addrs(hdr(orig, "Cc")) if reply_all else []
    else:
        to = addrs(hdr(orig, "Reply-To")) or frm
        cc = []
        if reply_all:
            to += addrs(hdr(orig, "To"))
            cc = addrs(hdr(orig, "Cc"))
    extra_to = [x if isinstance(x, tuple) else ("", x.lower()) for x in extra_to]
    extra_cc = [x if isinstance(x, tuple) else ("", x.lower()) for x in extra_cc]
    remove = {x.lower() for x in remove}
    # the owner's own address is dropped when it comes from the original mail, kept when named on purpose
    to, cc = clean_recipients(to, cc, {user.lower(), *remove})
    return clean_recipients(to + extra_to, cc + extra_cc, remove)


def clean_recipients(to, cc, drop):
    seen, out_to, out_cc = set(), [], []
    for lst, out in ((to, out_to), (cc, out_cc)):
        for n, ad in lst:
            ad = ad.lower()
            if ad in drop or ad in seen:
                continue
            seen.add(ad)
            out.append(("" if "�" in (n or "") else n, ad))    # a broken name: bare address
    return out_to, out_cc


def reply_subject(s):
    """Re: + the full original subject; only an existing Re: is not doubled."""
    return s if re.match(r"(?i)\s*re\s*:", s) else "Re: " + s


def forward_subject(s):
    return s if re.match(r"(?i)\s*(fw|fwd)\s*:", s) else "Fw: " + s


def text_to_html(t):
    return "".join("<div>%s</div>" % (htmlmod.escape(x) or "<br>") for x in t.split("\n"))


def build_message(body_html, to, cc, subject, orig=None, mode=None, bcc=(), attach=(),
                  signature_html="", high=False):
    """The draft as an EmailMessage. mode: None (new), 'reply' or 'forward'."""
    html = body_html + "<div><br></div>" + signature_html
    if orig is not None:
        html += "<div><br></div>" + quote_block(orig)
    msg = EmailMessage()
    msg["From"] = formataddr((CFG.name, CFG.user)) if CFG.name else CFG.user
    if to:
        msg["To"] = fmt_addrs(to)
    if cc:
        msg["Cc"] = fmt_addrs(cc)
    if bcc:
        msg["Bcc"] = fmt_addrs(bcc)
    msg["Subject"] = one_line(subject)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(CFG.user.split("@")[-1] or None))
    if high:
        msg["X-Priority"] = "1"
        msg["Importance"] = "High"
    if mode == "reply" and orig is not None:
        mid = hdr(orig, "Message-ID").strip()
        if mid:
            msg["In-Reply-To"] = mid
            refs = hdr(orig, "References").strip() or hdr(orig, "In-Reply-To").strip()
            msg["References"] = (refs + " " + mid).strip()
    if mode == "forward" and orig is not None and hdr(orig, "Message-ID").strip():
        msg[FWD_HEADER] = hdr(orig, "Message-ID").strip()
    msg.set_content(html_to_text(html))
    msg.add_alternative(html, subtype="html")
    hpart = msg.get_body(("html",))
    used = set(re.findall(r"(?i)cid:([^\"'\s>)]+)", html))
    if orig is not None:
        done = set()
        for p in orig.walk():
            if p.is_multipart() or not p.get("Content-ID"):
                continue
            cid = p.get("Content-ID").strip().strip("<>")
            if cid in used and cid not in done and is_inline(p):
                mt, st = image_type(p).split("/", 1)
                hpart.add_related(p.get_payload(decode=True) or b"", mt, st, cid="<%s>" % cid,
                                  filename=fname(p))
                done.add(cid)
        if mode == "forward":
            for p in attachments(orig):
                if p.get_content_type() == "message/rfc822":     # keep an attached mail as a .eml file
                    msg.add_attachment(part_bytes(p), "application", "octet-stream", filename=one_line(fname(p)))
                    continue
                mt, st = p.get_content_type().split("/", 1)
                msg.add_attachment(part_bytes(p), mt, st, filename=one_line(fname(p)))
    for f in attach:
        ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
        if ctype.startswith("message/"):     # a .eml file: add_attachment wants a Message object for these
            ctype = "application/octet-stream"
        mt, st = ctype.split("/", 1)
        with open(f, "rb") as fh:
            msg.add_attachment(fh.read(), mt, st, filename=one_line(os.path.basename(f)))
    return msg


def append_draft(m, raw):
    select(m, CFG.folders["drafts"], readonly=False)
    before = set(uids_of(m))
    typ, data = m.append(q(CFG.folders["drafts"]), "(\\Draft \\Seen)",
                         imaplib.Time2Internaldate(time.time()), raw)
    if typ != "OK":
        die("the server did not save the draft: %s" % data)
    mo = re.search(rb"APPENDUID \d+ (\d+)", b" ".join(x for x in data if isinstance(x, bytes)))
    if mo:
        return int(mo.group(1))
    select(m, CFG.folders["drafts"], readonly=False)
    new = set(uids_of(m)) - before
    return max(new) if new else 0


def delete_uid(m, folder, uid):
    """Remove one mail. UID EXPUNGE when the server has UIDPLUS, so other mails another client
    marked deleted in the same folder are not wiped with it."""
    use(m, folder, write=True)
    typ, data = m.uid("STORE", str(uid), "+FLAGS.SILENT", "(\\Deleted)")
    if typ != "OK":
        raise imaplib.IMAP4.error("could not mark %s deleted: %s" % (make_id(folder, uid), data))
    if has_cap(m, "UIDPLUS"):
        m.uid("EXPUNGE", str(uid))
    else:
        m.expunge()


def drafts_only(i, what):
    f, u = parse_id(i)
    if f != CFG.folders["drafts"]:
        die("%s only works on drafts (drafts:UID), got %s" % (what, i))
    return f, u


def read_body_file(path):
    try:
        with open(path, encoding="utf-8-sig") as f:      # -sig: a BOM from PowerShell Out-File
            return f.read()
    except UnicodeDecodeError:
        die("%s is not UTF-8 (PowerShell Set-Content writes ANSI): save it as UTF-8" % path)


def cmd_draft(a):
    if not (a.body or a.text):
        die("give --body FILE.html or --text")
    for f in a.attach or []:
        if not os.path.isfile(f):
            die("attachment not found: %s" % f)
    if a.replace:
        drafts_only(a.replace, "--replace")      # never expunge a mail in Inbox or Sent by mistake
    body = read_body_file(a.body) if a.body else text_to_html(a.text)
    sig = ""
    if not a.no_sig and CFG.signature:
        with open(os.path.expanduser(CFG.signature), encoding="utf-8") as f:
            sig = f.read()
    with session() as m:
        orig, mode = None, None
        src = a.reply or a.forward
        if src:
            folder, uid = parse_id(src)
            orig = to_msg(mail_raw(folder, uid, m))
            mode = "reply" if a.reply else "forward"
        remove = [ad for _, ad in parse_people(a.remove)]
        drop = set(remove)          # an address named in --to/--cc is meant, the owner's own included
        if mode == "reply":
            to, cc = reply_recipients(orig, a.all, CFG.user, parse_people(a.to), parse_people(a.cc), remove)
            subject = a.subject or reply_subject(hdr(orig, "Subject"))
        else:
            to, cc = clean_recipients(parse_people(a.to), parse_people(a.cc), drop)
            subject = a.subject or (forward_subject(hdr(orig, "Subject")) if mode == "forward" else "")
        if not subject:
            die("give --subject")
        msg = build_message(body, to, cc, subject, orig, mode, parse_people(a.bcc), a.attach or [], sig, a.high)
        new_uid = append_draft(m, msg.as_bytes(policy=OUT_POLICY))
        if a.replace:
            f2, u2 = drafts_only(a.replace, "--replace")
            delete_uid(m, f2, u2)
    os.makedirs(os.path.join(CFG.home, "drafts"), exist_ok=True)
    preview = os.path.join(CFG.home, "drafts", "%d.html" % new_uid)
    with open(preview, "w", encoding="utf-8") as f:
        f.write(with_meta(msg.get_body(("html",)).get_content()))
    print(json.dumps({"id": "%s:%d" % (CFG.short(CFG.folders["drafts"]), new_uid), "to": msg.get("To", ""),
                      "cc": msg.get("Cc", ""), "subject": subject,
                      "attachments": [fname(p) for p in attachments(msg)],
                      "preview_html": preview}, ensure_ascii=False, indent=1))


def cmd_drafts(a):
    c = db()
    with session() as m:
        sync_headers(m, c, CFG.folders["drafts"], full_flags=True)
    rows = c.execute("select * from msgs where folder=? order by ts desc", (CFG.folders["drafts"],)).fetchall()
    print_rows(rows, a.json, empty="(no drafts)")


# ------------------------------------------------------------------ check

def table_problems(html, sig_at, blanks_ok):
    new = html[:sig_at] if sig_at >= 0 else html
    problems = []
    # [^<>] and str.find instead of [^>] and .*? : broken or unclosed tags made these regexes quadratic
    tables = re.findall(r"<table\b[^<>]*>", new, re.I)
    if any("word-break:normal" not in t.replace(" ", "") for t in tables):
        problems.append("a table does not reset word-break:normal, so cells can split letter by letter")
    low = new.lower()
    pos, table_re = 0, re.compile(r"<table\b[^<>]*>", re.I)
    while True:
        mo = table_re.search(new, pos)
        end = low.find("</tr>", mo.end()) if mo else -1
        if end < 0:
            break
        t, body, pos = mo.group(0), new[mo.end():end], end + 5
        first = re.sub(r"<colgroup.*?</colgroup>", "", body, flags=re.I | re.S) if "</colgroup>" in body.lower() else body
        ncols = sum(int(s or 1) for s in re.findall(r"<t[dh]\b(?:[^<>]*colspan=\"?(\d+))?[^<>]*>", first, re.I))
        if ncols >= 3 and not re.search(r"(?<![-\w])width:\d+px", t.replace(" ", "")):
            problems.append("a %d-column table has no fixed pixel width" % ncols)
            break
    cells, pos, td_re = [], 0, re.compile(r"<td\b([^<>]*)>", re.I)
    while True:
        mo = td_re.search(new, pos)
        end = low.find("</td>", mo.end()) if mo else -1
        if end < 0:
            break
        if "colspan" not in mo.group(1):
            cells.append(re.sub(r"<[^<>]+>|&nbsp;|\s", "", new[mo.end():end]).lower())
        pos = end + 5
    blanks = sum(c in ("", "-", "—", "–", "tbc", "?") for c in cells) + new.count("TBC")
    if tables and blanks and not blanks_ok:
        problems.append("%d blank/—/TBC value(s) in the table; say which rows miss what, then use --blanks-ok"
                        % blanks)
    return problems


def check_message(msg, reply, blanks_ok=False, required_cc=True, attach_ok=False):
    plain, html = bodies(msg)
    text = html or plain
    problems = []
    reply = reply or bool(hdr(msg, "In-Reply-To").strip())
    marks = CFG.signature_marks
    sig_at = min([text.find(x) for x in marks if x in text] or [-1]) if marks else len(text)
    quote_at = min([text.find(x) for x in QUOTE_MARKS if x in text] or [-1])
    if marks:
        if sig_at < 0:
            problems.append("no signature")
        elif reply and 0 <= quote_at < sig_at:
            problems.append("no signature in the new text (the one found is inside the quoted history)")
    if reply and (quote_at < 0 or (marks and quote_at < sig_at)):
        problems.append("no quoted history after the signature")
    cids = {p.get("Content-ID").strip().strip("<>") for p in msg.walk() if p.get("Content-ID")}
    refs = set(re.findall(r'''(?i)(?:src|background)\s*=\s*["']?cid:([^"'\s>]+)''', html))
    if refs - cids:
        problems.append("%d image(s) in the mail have no image part" % len(refs - cids))
    to, cc = addrs(hdr(msg, "To")), addrs(hdr(msg, "Cc"))
    everyone = {x for _, x in to + cc}
    if not to:
        problems.append("To is empty")
    if CFG.user in everyone:
        problems.append("the sender is also a recipient")
    if required_cc:
        for x in CFG.require_cc:
            if x.lower() not in everyone:
                problems.append("%s is not in To or Cc" % x)
    problems += table_problems(html, sig_at if marks else -1, blanks_ok)
    # the new words only: before the signature, else before the quoted history
    cut = sig_at if marks and sig_at >= 0 else quote_at
    new_words = html_to_text(text[:cut] if cut >= 0 else text) if html else (text[:cut] if cut >= 0 else text)
    subject = hdr(msg, "Subject")
    if not bare_subject(subject):
        problems.append("the subject is empty")
    files = attachments(msg)
    broken = [k for k, v in (("To", hdr(msg, "To")), ("Cc", hdr(msg, "Cc")), ("subject", subject),
                             ("new text", new_words)) if "�" in v]
    broken += ["attachment name %s" % fname(p) for p in files if "�" in (fname(p) or "")]
    if broken:
        problems.append("garbled characters (�) in: %s" % ", ".join(broken))
    holes = sorted(set(PLACEHOLDER_RE.findall(new_words)))
    if holes and not blanks_ok:
        problems.append("placeholder(s) left in the text: %s; fill them or use --blanks-ok" % ", ".join(holes[:5]))
    if ATTACH_WORDS_RE.search(new_words) and not files and not attach_ok:
        problems.append("the text mentions an attachment but nothing is attached; add --attach or use --attach-ok")
    return problems


def cmd_check(a):
    folder, uid = parse_id(a.id)
    with session() as m:
        raw = fetch_raw(m, folder, uid)
    msg = to_msg(raw)
    problems = check_message(msg, a.reply, a.blanks_ok, not a.no_required_cc, a.attach_ok)
    d = {"to": hdr(msg, "To"), "cc": hdr(msg, "Cc"), "subject": hdr(msg, "Subject"),
         "attachments": [{"name": fname(p), "kb": len(part_bytes(p)) // 1024}
                         for p in attachments(msg)], "ok": not problems, "problems": problems}
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    else:
        print("To:      %s\nCc:      %s\nSubject: %s" % (d["to"], d["cc"], d["subject"]))
        for x in d["attachments"]:
            print("Attach:  %s (%d KB)" % (x["name"], x["kb"]))
        print("CHECK FAILED:\n- " + "\n- ".join(problems) if problems else "CHECK OK")
    if problems:
        sys.exit(1)


# ------------------------------------------------------------------ send

def in_folder(m, folder, mid, last=15):
    select(m, folder)
    u = uids_of(m)[-last:]
    if not u or not mid:
        return False
    typ, data = m.uid("FETCH", ",".join(map(str, u)), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
    blob = b"".join(x[1] if isinstance(x, tuple) else x for x in data if x)
    # Exmail rewrites <id@dom> as <E7A71F8638388FB7+id@dom> when it sends, so match the id itself
    return (mid.strip().strip("<>") + ">").encode() in blob


def sent_log():
    return os.path.join(CFG.home, "sent.log")


def already_sent(mid):
    """When this Message-ID was sent from this machine, else None."""
    if not mid or not os.path.exists(sent_log()):
        return None
    with open(sent_log(), encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p and p[0] == mid:
                return p[1] if len(p) > 1 else "?"
    return None


def log_sent(mid, subject):
    os.makedirs(CFG.home, exist_ok=True)
    with open(sent_log(), "a", encoding="utf-8") as f:
        f.write("%s\t%s\t%s\n" % (mid, dt.datetime.now(CFG.tz).strftime("%Y-%m-%d %H:%M:%S"),
                                  re.sub(r"\s+", " ", subject)[:200]))


def cmd_send(a):
    if not a.yes:
        die("send needs --yes, given only after the owner approved this exact draft")
    folder, uid = drafts_only(a.id, "send")
    print(json.dumps(send_draft(folder, uid), ensure_ascii=False, indent=1))


def send_draft(folder, uid, wait=3):
    """Send one draft over SMTP, make sure Sent has a copy, delete the draft, mark the original
    answered. Returns what happened; dies (SystemExit) before sending when it must not go out."""
    sent = CFG.folders["sent"]
    with session() as m:
        raw = fetch_raw(m, folder, uid)
        msg = to_msg(raw)
        mid = hdr(msg, "Message-ID").strip()
        when = already_sent(mid) or ("(found in Sent)" if mid and in_folder(m, sent, mid, last=40) else None)
    if when:
        die("NOT SENT AGAIN: this draft already went out %s. Check Sent; remove the draft with delete-draft."
            % when)
    if not mid:
        mid = make_msgid(domain=(CFG.user.split("@")[-1] or None))
        msg["Message-ID"] = mid
    rcpts = [x for _, x in addrs(hdr(msg, "To")) + addrs(hdr(msg, "Cc")) + addrs(hdr(msg, "Bcc"))]
    if not rcpts:
        die("the draft has no recipients")
    del msg["Bcc"]
    del msg["Date"]
    msg["Date"] = formatdate(localtime=True)     # the time it is sent, not when the draft was made
    out = msg.as_bytes(policy=OUT_POLICY)
    s = smtplib.SMTP_SSL(CFG.smtp["host"], CFG.smtp["port"], timeout=300)
    try:
        s.login(CFG.user, password())
        refused = s.sendmail(CFG.user, rcpts, out)
    finally:
        try:
            s.quit()
        except Exception:
            pass
    log_sent(mid, hdr(msg, "Subject"))           # from here on a retry refuses instead of sending twice
    saved, cleanup = False, []
    try:
        # a fresh connection: the first one may have timed out during a long upload
        with session() as m:
            for _ in range(4):      # the server files SMTP mail in Sent by itself, sometimes late
                time.sleep(wait)
                if in_folder(m, sent, mid, last=30):
                    saved = True
                    break
            if not saved:
                typ, data = m.append(q(sent), "(\\Seen)", imaplib.Time2Internaldate(time.time()), out)
                if typ == "OK":
                    pass
                elif b"saved by smtp" in b" ".join(x for x in data if isinstance(x, bytes)).lower():
                    saved = True        # Exmail: "Mail has saved by smtp!" = it filed its own copy
                else:
                    cleanup.append("no copy in Sent: %s" % data)
            delete_uid(m, folder, uid)
            mark_original(m, msg)
    except Exception as e:
        cleanup.append("the mail WAS sent, but tidying up failed (%s): do not send it again; "
                       "check Sent and remove the draft with delete-draft" % e)
    return {"sent": True, "to": hdr(msg, "To"), "cc": hdr(msg, "Cc"), "subject": hdr(msg, "Subject"),
            "refused": refused, "attachments": [fname(p) for p in attachments(msg)],
            "copy_in_sent": "server" if saved else ("added by ragdoll" if not cleanup else "unknown"),
            "problems_after_sending": cleanup}


def mark_original(m, msg):
    """After sending: mark the mail it answers (\\Answered, on the server too, so WeCom shows it)
    or forwards (in the index only: Exmail keeps no forwarded flag)."""
    c = db()
    fwd = forward_source(msg)
    irt = "" if fwd else hdr(msg, "In-Reply-To").strip()
    if fwd:
        c.execute("update msgs set forwarded=1 where msgid=?", (fwd,))
    if irt:
        c.execute("update msgs set answered=1 where msgid=?", (irt,))
        r = c.execute("select folder, uid from msgs where msgid=? order by ts desc limit 1", (irt,)).fetchone()
        if r:
            try:
                select(m, r["folder"], readonly=False)
                m.uid("STORE", str(r["uid"]), "+FLAGS", "(\\Answered)")
            except Exception:
                pass
    c.commit()


def move_uids(m, folder, uids, dest):
    """Move UIDs within the mailbox (MOVE when the server has it, else COPY + delete)."""
    use(m, folder, write=True)
    moved = 0
    for i in range(0, len(uids), 200):
        batch = ",".join(map(str, uids[i:i + 200]))
        if has_cap(m, "MOVE"):
            typ, data = m.uid("MOVE", batch, q(dest))
        else:
            typ, data = m.uid("COPY", batch, q(dest))
            if typ == "OK":
                m.uid("STORE", batch, "+FLAGS.SILENT", "(\\Deleted)")
                if has_cap(m, "UIDPLUS"):
                    m.uid("EXPUNGE", batch)
                else:
                    m.expunge()
        if typ != "OK":
            die("the server refused the move after %d mails: %s" % (moved, data))
        moved += len(uids[i:i + 200])
    return moved


def ids_by_folder(a):
    """(ids, {server folder: [uids]}) from the ids on the command line and --from-file."""
    ids = list(a.ids)
    if getattr(a, "from_file", None):
        with open(a.from_file, encoding="utf-8") as f:
            ids += [x.strip() for x in f if x.strip()]
    if not ids:
        die("no ids given")
    by_folder = {}
    for i in ids:
        f, u = parse_id(i)
        if u not in by_folder.setdefault(f, []):
            by_folder[f].append(u)
    return ids, by_folder


def forget_rows(c, by_folder):
    """Take moved mails out of the index; the next sync finds them in their new folder."""
    for f, uids in by_folder.items():
        for u in uids:
            r = c.execute("select id from msgs where folder=? and uid=?", (f, u)).fetchone()
            if r:
                c.execute("delete from msgs where id=?", (r["id"],))
                c.execute("delete from fts where rowid=?", (r["id"],))
    c.commit()


def cmd_mark(a):
    """Read / unread and star / unstar, on the server and in the index."""
    todo = [(col, flag, on) for col, flag, on, want in (
        ("seen", "\\Seen", 1, a.read), ("seen", "\\Seen", 0, a.unread),
        ("flagged", "\\Flagged", 1, a.star), ("flagged", "\\Flagged", 0, a.unstar)) if want]
    if not todo:
        die("say what to mark: --read, --unread, --star or --unstar")
    ids, by_folder = ids_by_folder(a)
    c = db()
    missing = [make_id(f, u) for f, uids in by_folder.items() for u in uids
               if not c.execute("select 1 from msgs where folder=? and uid=?", (f, u)).fetchone()]
    if missing:
        die("no such mail in the index: %s (moved or deleted? run search again)" % ", ".join(missing[:10]))
    with session() as m:
        for f, uids in by_folder.items():
            select(m, f, readonly=False)
            for i in range(0, len(uids), 200):
                batch = ",".join(map(str, uids[i:i + 200]))
                for col, flag, on in todo:
                    typ, data = m.uid("STORE", batch, "+FLAGS.SILENT" if on else "-FLAGS.SILENT", "(%s)" % flag)
                    if typ != "OK":
                        die("the server refused: %s" % data)
    n = sum(len(u) for u in by_folder.values())
    for f, uids in by_folder.items():
        for col, flag, on in todo:
            c.executemany("update msgs set %s=? where folder=? and uid=?" % col, [(on, f, u) for u in uids])
    c.commit()
    words = {("seen", 1): "read", ("seen", 0): "unread", ("flagged", 1): "starred", ("flagged", 0): "not starred"}
    print("marked %d mail%s %s" % (n, "" if n == 1 else "s", " and ".join(words[(col, on)] for col, _, on in todo)))


def move_dest(m, name):
    """The server folder for a short name or a folder name. Only the archive folder is made when missing."""
    key = (name or "").strip()
    if not key:
        die("say where to: --to FOLDER (see `ragdoll folders`)")
    names = all_folders(m)
    dest = CFG.folders.get(key.lower())
    if not dest and key.lower() == "archive":
        dest = next((n for n in names if n.lower() in ("archive", "archives", "已归档", "归档")), "Archive")
    if not dest:
        dest = next((n for n in names if n == key), None) or next((n for n in names if n.lower() == key.lower()), None)
    if not dest:
        die("no folder %r on the server. There are: %s" % (name, ", ".join(names)))
    if dest not in names:
        if key.lower() != "archive":
            die("the %s folder %r in the config is not on the server. There are: %s" % (key, dest, ", ".join(names)))
        typ, data = m.create(q(dest))
        if typ != "OK":
            die("could not make the folder %s: %s" % (dest, data))
    return dest


def cmd_move(a):
    """Move mails to another folder of the same mailbox. Nothing is deleted; move back to undo."""
    to = "archive" if a.cmd == "archive" else a.to
    if (to or "").strip().lower() == "trash" or to == CFG.folders.get("trash"):
        die("to the trash: ragdoll trash <ids> --yes (only after the owner approved the list)")
    ids, by_folder = ids_by_folder(a)
    with session() as m:
        dest = move_dest(m, to)
        if dest == CFG.folders.get("trash"):
            die("to the trash: ragdoll trash <ids> --yes (only after the owner approved the list)")
        by_folder.pop(dest, None)
        total = 0
        for f, uids in by_folder.items():
            total += move_uids(m, f, sorted(uids), dest)
    forget_rows(db(), by_folder)
    print("moved %d mail%s to %s" % (total, "" if total == 1 else "s", dest))
    if total and dest not in CFG.sync_folders:
        print("(see them with: ragdoll list --folder %s)" % (CFG.short(dest) if " " not in CFG.short(dest)
                                                             else '"%s"' % dest))


def cmd_trash(a):
    """Move mails to the trash folder (recoverable from there)."""
    ids, by_folder = ids_by_folder(a)
    if not a.yes:
        print("would move %d mails to %s: %s" % (len(ids), CFG.folders["trash"],
                                                 {CFG.short(f): len(u) for f, u in by_folder.items()}))
        print("rerun with --yes, only after the owner approved this list")
        return
    total = 0
    with session() as m:
        for f, uids in by_folder.items():
            if f == CFG.folders["trash"]:
                continue
            total += move_uids(m, f, sorted(set(uids)), CFG.folders["trash"])
    forget_rows(db(), by_folder)
    print("moved %d mails to %s" % (total, CFG.folders["trash"]))


def cmd_delete_draft(a):
    if not a.yes:
        die("delete-draft needs --yes")
    folder, uid = drafts_only(a.id, "delete-draft")
    with session() as m:
        delete_uid(m, folder, uid)
    print("deleted %s" % a.id)


# ------------------------------------------------------------------ main

# ------------------------------------------------------------------ update
# Modelled on S2Arm's updater: look in the background and only tell; replace only when asked
# (`update`), never while another ragdoll command runs or the clone has local changes; test the
# new version before keeping it and put the old one back by itself when the test fails; say
# what changed; log every step. A failed check shows nothing (no network = no noise).

APP_DIR = os.path.dirname(os.path.abspath(__file__))
UPDATE_REF = "refs/ragdoll/update"
UPDATE_EVERY = 6 * 3600


def update_remote():
    return env("UPDATE_REMOTE") or "origin"     # a path or URL for tests


def update_enabled():
    return not env("NO_UPDATE_CHECK") and CFG.d.get("update_check", True)


def update_log(text):
    try:
        d = os.path.join(CFG.home, "logs")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "update.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (dt.datetime.now(CFG.tz).isoformat(timespec="seconds"), text))
    except OSError:
        pass


def update_state(new=None):
    path = os.path.join(CFG.home, "update.json")
    if new is None:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    try:
        os.makedirs(CFG.home, exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass
    return new


def patch_state(**kw):
    st = update_state()
    for k, v in kw.items():
        if v is None:
            st.pop(k, None)
        else:
            st[k] = v
    return update_state(st)


def git(repo, *args, timeout=60, quiet=False):
    """(code, stdout, stderr). quiet: never ask for a password or passphrase (background)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    if quiet and not env.get("GIT_SSH_COMMAND"):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=15"
    try:
        r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return 127, "", "git is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "git %s took longer than %d s" % (args[0], timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def last_line(text):
    lines = [x for x in (text or "").splitlines() if x.strip()]
    return lines[-1].strip() if lines else ""


def version_at(repo, rev):
    for name in ("ragdoll.py", "hmail.py"):         # hmail.py before 0.4.0
        code, out, _ = git(repo, "show", rev + ":" + name)
        m = re.search(r'^__version__ = "([^"]+)"', out, re.M) if code == 0 else None
        if m:
            return m.group(1)
    code, out, _ = git(repo, "rev-parse", "--short", rev)
    return out if code == 0 else "?"


def fetch_latest(repo, quiet=False):
    """Fetch main from the remote into UPDATE_REF and compare it with HEAD."""
    code, top, err = git(repo, "rev-parse", "--show-toplevel")
    if code or os.path.realpath(top) != os.path.realpath(repo):
        return {"error": "%s is not a git clone of ragdoll, so it cannot update itself" % repo}
    code, _, err = git(repo, "fetch", "--quiet", "--no-tags", update_remote(), "+main:" + UPDATE_REF,
                       timeout=90, quiet=quiet)
    if code:
        return {"error": "could not get the newest version from %s: %s" % (update_remote(), last_line(err))}
    _, head, _ = git(repo, "rev-parse", "HEAD")
    _, sha, _ = git(repo, "rev-parse", UPDATE_REF)
    _, behind, _ = git(repo, "rev-list", "--count", "HEAD.." + UPDATE_REF)
    _, ahead, _ = git(repo, "rev-list", "--count", UPDATE_REF + "..HEAD")
    _, log, _ = git(repo, "log", "--no-merges", "--format=%s", "-n", "30", "HEAD.." + UPDATE_REF)
    return {"head": head, "sha": sha, "behind": int(behind or 0), "ahead": int(ahead or 0),
            "current": version_at(repo, "HEAD"), "version": version_at(repo, UPDATE_REF),
            "notes": [x for x in log.splitlines() if x.strip()]}


@contextlib.contextmanager
def running(cmd):
    """Mark this command as running, so `update` does not swap ragdoll under it."""
    f = path = None
    try:
        d = os.path.join(CFG.home, "run")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "%d-%s.lock" % (os.getpid(), cmd))
        f = open(path, "a+")
        try_lock(f)
    except OSError:
        pass
    try:
        yield
    finally:
        if f:
            unlock(f)
            f.close()
            with contextlib.suppress(OSError):
                os.remove(path)


def busy_commands():
    """Other ragdoll commands running now (their run marker is still locked)."""
    d = os.path.join(CFG.home, "run")
    mine = "%d-" % os.getpid()
    out = []
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".lock") or name.startswith(mine):
            continue
        path = os.path.join(d, name)
        try:
            f = open(path, "a+")
        except OSError:
            out.append(name[:-5].split("-", 1)[-1])
            continue
        free = try_lock(f)
        if free:
            unlock(f)
        f.close()
        if free:
            with contextlib.suppress(OSError):
                os.remove(path)          # left by a command that crashed
        else:
            out.append(name[:-5].split("-", 1)[-1])
    return out


def update_gate(repo):
    """Why ragdoll must not be replaced right now, or None."""
    code, branch, _ = git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    if branch != "main":
        return "this clone is on %s, not main" % (branch or "a detached commit")
    code, dirty, _ = git(repo, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        return "this clone has changed files (%s); commit or undo them first" % ", ".join(
            x[3:] for x in dirty.splitlines()[:5])
    busy = busy_commands()
    if busy:
        return "another ragdoll command is running (%s); update when it is done" % ", ".join(busy)
    return None


def self_test(repo):
    """Run the new version before keeping it: --version, then the offline tests."""
    env = dict(os.environ, RAGDOLL_NO_UPDATE_CHECK="1", HMAIL_NO_UPDATE_CHECK="1")
    steps = [[sys.executable, "-I", "-B", "ragdoll.py", "--version"]]
    if os.path.isdir(os.path.join(repo, "tests")):
        steps.append([sys.executable, "-I", "-B", "-m", "unittest", "discover", "-s", "tests"])
    for cmd in steps:
        try:
            r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=600, env=env, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        if r.returncode:
            return False, last_line(r.stderr) or last_line(r.stdout) or "exit code %d" % r.returncode
    return True, ""


def do_update(repo, check_only=False):
    """state: current | available | updated | refused | failed."""
    info = fetch_latest(repo)
    if "error" in info:
        update_log("check failed: " + info["error"])
        return {"state": "failed", "reason": info["error"], "by_hand": "git -C \"%s\" pull --ff-only" % repo}
    patch_state(checked_at=int(time.time()), latest=info, check_error=None)
    base = {"current": info["current"], "version": info["version"], "notes": info["notes"]}
    if not info["behind"]:
        return dict(base, state="current")
    if info["ahead"]:
        return dict(base, state="refused", reason="this clone has %d commit(s) that are not on the remote; "
                                                   "push them first" % info["ahead"])
    if check_only:
        return dict(base, state="available")
    why = update_gate(repo)
    if why:
        update_log("update to %s refused: %s" % (info["version"], why))
        return dict(base, state="refused", reason=why)
    with file_lock("update", wait=False) as got:
        if not got:
            return dict(base, state="refused", reason="another ragdoll update is running")
        old = info["head"]
        update_log("updating %s (%s) -> %s (%s)" % (info["current"], old[:8], info["version"], info["sha"][:8]))
        code, _, err = git(repo, "merge", "--ff-only", "--quiet", info["sha"])
        if code:
            update_log("merge failed: " + last_line(err))
            return dict(base, state="failed", reason="could not apply it: " + last_line(err),
                        by_hand="git -C \"%s\" pull --ff-only" % repo)
        ok, why = self_test(repo)
        if not ok:
            git(repo, "reset", "--hard", "--quiet", old)
            update_log("self-test failed, put %s back: %s" % (old[:8], why))
            return dict(base, state="failed", reason="the new version failed its self-test, so %s was put "
                                                     "back: %s" % (info["current"], why))
        patch_state(previous={"sha": old, "version": info["current"]}, skip=None,
                    latest=dict(info, head=info["sha"], behind=0, current=info["version"], notes=[]))
        update_log("updated to %s, self-test passed" % info["version"])
        return dict(base, state="updated")


def do_rollback(repo):
    st = update_state()
    prev = st.get("previous")
    if not prev:
        return {"state": "refused", "reason": "ragdoll has not been updated on this computer, nothing to go back to"}
    if git(repo, "cat-file", "-e", prev["sha"] + ":ragdoll.py")[0]:
        return {"state": "refused", "reason": "the version before is the old hmail, which cannot read the "
                "renamed config and data folders; going back is not possible"}
    why = update_gate(repo)
    if why:
        return {"state": "refused", "reason": why}
    _, head, _ = git(repo, "rev-parse", "HEAD")
    code, _, _ = git(repo, "merge-base", "--is-ancestor", prev["sha"], head)
    if code:
        return {"state": "refused", "reason": "the clone has moved on since the last update"}
    now = version_at(repo, "HEAD")
    code, _, err = git(repo, "reset", "--hard", "--quiet", prev["sha"])
    if code:
        return {"state": "failed", "reason": last_line(err)}
    patch_state(previous=None, skip=head, latest=None)      # do not offer the version just left again
    update_log("rolled back %s (%s) -> %s (%s)" % (now, head[:8], prev["version"], prev["sha"][:8]))
    return {"state": "rolled_back", "current": prev["version"], "was": now}


def update_check_background():
    with file_lock("update-check", wait=False) as got:
        if not got:
            return
        info = fetch_latest(APP_DIR, quiet=True)
        if "error" in info:
            patch_state(checked_at=int(time.time()), check_error=info["error"])
            update_log("background check failed: " + info["error"])
            return
        patch_state(checked_at=int(time.time()), latest=info, check_error=None)
        if info["behind"]:
            update_log("found %s (%d change(s)); you have %s" % (info["version"], info["behind"], info["current"]))


def maybe_check_later():
    """Start a background check when the last one is old. Never waits for it."""
    if not update_enabled() or not os.path.exists(os.path.join(APP_DIR, ".git")):
        return
    st = update_state()
    now = time.time()
    if now - st.get("checked_at", 0) < UPDATE_EVERY or now - st.get("check_started", 0) < 600:
        return
    patch_state(check_started=int(now))
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              close_fds=True, cwd=APP_DIR)
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000 | 0x00000200     # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True                     # no terminal: ssh cannot stop to ask
    with contextlib.suppress(OSError):
        subprocess.Popen([sys.executable, "-I", "-B", os.path.abspath(__file__), "update",
                          "--background-check"], **kw)


def update_waiting():
    """What the last check found, when a newer ragdoll is waiting for this clone as it is now; else None.
    A check made before the clone moved (another branch, an update) says nothing about it."""
    st = update_state()
    latest = st.get("latest") or {}
    if not latest.get("behind") or latest.get("ahead") or latest.get("sha") == st.get("skip"):
        return None
    code, head, _ = git(APP_DIR, "rev-parse", "HEAD", timeout=10)
    return latest if code == 0 and head == latest.get("head") else None


def update_notice():
    """One line on stderr when a newer ragdoll is waiting (stdout stays clean for --json)."""
    if not update_enabled():
        return
    latest = update_waiting()
    if latest:
        print("ragdoll %s is out (%d change(s); this is %s). Run: ragdoll update"
              % (latest.get("version"), latest["behind"], __version__), file=sys.stderr)


def cmd_update(a):
    if a.background_check:
        return update_check_background()
    r = do_rollback(APP_DIR) if a.rollback else do_update(APP_DIR, check_only=a.check)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        notes = "".join("\n  - " + x for x in r.get("notes") or [])
        print({"current": "ragdoll %(current)s is the newest version.",
               "available": "ragdoll %(version)s is out (this is %(current)s). What changed:" + notes
                            + "\nRun: ragdoll update",
               "updated": "Updated ragdoll %(current)s -> %(version)s; the self-test passed. What changed:" + notes,
               "rolled_back": "Back on ragdoll %(current)s (was %(was)s). It will not offer %(was)s again.",
               "refused": "NOT UPDATED: %(reason)s",
               "failed": "NOT UPDATED: %(reason)s"}[r["state"]] % r)
        if r.get("by_hand"):
            print("By hand: " + r["by_hand"])
    if r["state"] in ("refused", "failed"):
        sys.exit(1)


def parser():
    ap = argparse.ArgumentParser(prog="ragdoll", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version="ragdoll " + __version__)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status").set_defaults(fn=cmd_status)
    p = sp.add_parser("bodies", help=argparse.SUPPRESS)
    p.add_argument("--workers", type=int, default=3)
    p.set_defaults(fn=cmd_bodies)
    p = sp.add_parser("sync")
    p.add_argument("--bodies", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--all-folders", action="store_true")
    p.set_defaults(fn=cmd_sync)
    for name, fn in (("search", cmd_search), ("list", cmd_list)):
        p = sp.add_parser(name)
        if name == "search":
            p.add_argument("words", nargs="*")
        p.add_argument("--from", dest="from_", help="part of the sender's name or address")
        p.add_argument("--to", help="part of a To or Cc name or address")
        p.add_argument("--until", help="up to and including this day")
        p.add_argument("--att", action="store_true", help="only mail with attachments")
        p.add_argument("--starred", action="store_true")
        p.add_argument("--folder", help="a short name (inbox, sent, drafts, ...) or a folder name from `folders`")
        p.add_argument("--since")
        p.add_argument("--unread", action="store_true")
        p.add_argument("--limit", type=int, default=20)
        p.add_argument("--json", action="store_true")
        p.add_argument("--no-sync", action="store_true")
        p.set_defaults(fn=fn)
    p = sp.add_parser("thread")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-sync", action="store_true")
    p.set_defaults(fn=cmd_thread)
    p = sp.add_parser("read")
    p.add_argument("id")
    p.add_argument("--new", action="store_true", help="only the text above the quoted history")
    p.add_argument("--json", action="store_true")
    p.add_argument("--html")
    p.add_argument("--eml")
    p.set_defaults(fn=cmd_read)
    p = sp.add_parser("attach")
    p.add_argument("id")
    p.add_argument("--out")
    p.add_argument("--name")
    p.add_argument("--inline", action="store_true")
    p.set_defaults(fn=cmd_attach)
    p = sp.add_parser("draft")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--reply")
    g.add_argument("--forward")
    p.add_argument("--all", action="store_true")
    p.add_argument("--to")
    p.add_argument("--cc")
    p.add_argument("--bcc")
    p.add_argument("--remove")
    p.add_argument("--subject")
    p.add_argument("--body")
    p.add_argument("--text")
    p.add_argument("--attach", action="append")
    p.add_argument("--no-sig", action="store_true")
    p.add_argument("--high", action="store_true")
    p.add_argument("--replace")
    p.set_defaults(fn=cmd_draft)
    p = sp.add_parser("drafts")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_drafts)
    p = sp.add_parser("check")
    p.add_argument("id")
    p.add_argument("--reply", action="store_true")
    p.add_argument("--blanks-ok", action="store_true")
    p.add_argument("--no-required-cc", action="store_true")
    p.add_argument("--attach-ok", action="store_true", help="the text mentions an attachment on purpose")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_check)
    p = sp.add_parser("send")
    p.add_argument("id")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_send)
    p = sp.add_parser("folders", help="the folders on the server")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_folders)
    p = sp.add_parser("mark", help="read / unread, star / unstar")
    p.add_argument("ids", nargs="*")
    p.add_argument("--from-file", help="one id per line")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--read", action="store_true")
    g.add_argument("--unread", action="store_true")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--star", action="store_true")
    g.add_argument("--unstar", action="store_true")
    p.set_defaults(fn=cmd_mark)
    p = sp.add_parser("archive", help="move mails to the archive folder")
    p.add_argument("ids", nargs="*")
    p.add_argument("--from-file", help="one id per line")
    p.set_defaults(fn=cmd_move)
    p = sp.add_parser("move", help="move mails to another folder")
    p.add_argument("ids", nargs="*")
    p.add_argument("--to", help="a short name (inbox, archive, junk) or a folder name from `folders`")
    p.add_argument("--from-file", help="one id per line")
    p.set_defaults(fn=cmd_move)
    p = sp.add_parser("trash")
    p.add_argument("ids", nargs="*")
    p.add_argument("--from-file", help="one id per line")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_trash)
    p = sp.add_parser("delete-draft")
    p.add_argument("id")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_delete_draft)
    sp.add_parser("app", help="open the desktop app (ragdoll app --help)", add_help=False)
    p = sp.add_parser("update", help="get the newest ragdoll from GitHub, test it, keep it")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="only say whether there is a newer version")
    g.add_argument("--rollback", action="store_true", help="go back to the version before the last update")
    g.add_argument("--background-check", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_update)
    return ap


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["app"]:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)            # python -I leaves the script folder off the path
        try:
            import ragdoll_app
        except ImportError:
            die("the desktop app needs the full clone (ragdoll_app.py and app/ next to ragdoll.py)")
        return ragdoll_app.main(argv[1:])
    a = parser().parse_args(argv)
    if a.cmd == "update":
        return a.fn(a)
    if a.cmd == "bodies":
        with running(a.cmd):
            return a.fn(a)
    maybe_check_later()
    try:
        with running(a.cmd):
            a.fn(a)
    except imaplib.IMAP4.error as e:
        die("mail server refused: %s" % e)
    except LookupError as e:
        die(str(e))
    finally:
        update_notice()


if __name__ == "__main__":
    main()
