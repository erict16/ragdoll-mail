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
  open <id>                                 show it in the Ragdoll Mail app (starts the app)
  schedule <draft id> --at WHEN --yes       send later: "2026-11-22 09:00", "09:00" or "+2h";
  schedule --list | <draft id> --cancel     the app sends it at that time while it is open
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
import json, mimetypes, os, re, shlex, smtplib, sqlite3, ssl, subprocess, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parsedate_to_datetime
import encodings.aliases, unicodedata

__version__ = "0.11.0"
FROZEN = bool(getattr(sys, "frozen", False))      # inside the built Ragdoll Mail app

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
# Quoted history, line by line (app.js has the same rules for HTML mail). A separator line or "On ... wrote:" always
# starts it. A "From:" line starts it only as the head of a real header block: a separator line just above it, or
# the next lines carry Sent:, or Subject: with Date:/To:/Cc:, or Date: and To: under a From: with an address.
# A mail's own "From: Shanghai / To: Singapore" is text, not history.
QUOTE_SEP_RE = re.compile(r"^\s*(-{2,}\s*(原始邮件|原始郵件|Original Message|Forwarded message|转发邮件|轉寄郵件|"
                          r"Ursprüngliche Nachricht|Message d'origine|Mensaje original)|"
                          r"On .{5,160} wrote:|在\s?.{3,80}写道[:：])", re.I)
QUOTE_FROM_RE = re.compile(r"^\s*\*?(From|发件人|寄件者|寄件人|Von|De|Từ|差出人|보낸 사람)\*?\s*[:：]", re.I)
QUOTE_HEAD_RE = re.compile(
    r"^\s*\*?(?:(?P<sent>Sent|发送时间|發送時間|寄件日期|Gesendet|Envoyé|Enviado|送信日時|보낸 날짜|Gửi lúc)|"
    r"(?P<date>Date|日期|时间|時間|Datum|Fecha|Ngày|日付|날짜)|(?P<to>To|收件人|收件者|An|À|Para|Đến|宛先|받는 사람)|"
    r"(?P<cc>Cc|抄送|副本|Kopie|Copie)|(?P<subject>Subject|主题|主題|主旨|Betreff|Objet|Asunto|Chủ đề|件名|제목))"
    r"\*?\s*[:：]", re.I)
QUOTE_LINE_RE = re.compile(r"^\s*([-_=*]\s*){5,}$")


def quote_line(lines):
    """The index of the line where quoted history starts (a separator line over its header block included), or -1."""
    for i, line in enumerate(lines):
        if QUOTE_SEP_RE.match(line):
            return i
        if not QUOTE_FROM_RE.match(line):
            continue
        above = next((k for k in range(i - 1, max(-1, i - 3), -1) if lines[k].strip()), None)
        if above is not None and QUOTE_LINE_RE.match(lines[above]):
            return above
        block = []
        for x in lines[i + 1:i + 8]:
            if not x.strip() or QUOTE_FROM_RE.match(x):     # the block ends at an empty line or the next block
                break
            block.append(x)
        keys = {m.lastgroup for m in map(QUOTE_HEAD_RE.match, block) if m}
        if "sent" in keys or ("subject" in keys and keys & {"date", "to", "cc"}) or (
                {"date", "to"} <= keys and "@" in line):
            return i
    return -1


def quote_start(text):
    """Where the quoted history starts in a plain text, or -1."""
    lines = (text or "").split("\n")
    i = quote_line(lines)
    return -1 if i < 0 else sum(len(x) + 1 for x in lines[:i])


PREFIX_RE = re.compile(r"^\s*((re|fw|fwd|aw|wg|tr|trả lời|chuyển tiếp|bls|回复|答复|转发)\s*[:：]\s*)+", re.I)
INLINE_ID = re.compile(r"^[0-9A-Fa-f]{8}@[0-9A-Fa-f.]+(\.(png|jpe?g|gif|bmp|webp))?$", re.I)   # Exmail inline-image names
WEEK = "一二三四五六日"
# Fold only at the RFC 5322 hard limit: folding at 78 made Python encode long Message-IDs as
# =?utf-8?q?...?=, which broke threading (sent:1431, 16th Nov 2026); no limit at all let a
# reply-all To line pass 998 characters.
# The subject and the names in the address lines are the exception: at 998 a Chinese subject became one
# encoded word of hundreds of characters, and RFC 2047 allows 75. Those fold at 76, into words of at most 72.
WORD_HEADERS = frozenset(("subject", "from", "to", "cc", "bcc", "reply-to", "sender"))
WORD_POLICY = policy.SMTP.clone(max_line_length=76)


class OutPolicy(policy.EmailPolicy):
    def _fold(self, name, value, refold_binary=False):
        if name.lower() in WORD_HEADERS:
            return WORD_POLICY._fold(name, value, refold_binary)
        return super()._fold(name, value, refold_binary)


OUT_POLICY = OutPolicy(linesep="\r\n", max_line_length=998)
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
    if not isinstance(raw, dict):
        return path, over                                  # likewise; and it is never written over
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


CONFIG_ERROR = None     # {"path", "error"} when the settings file could not be read (#49)


def load_config(path=None):
    """The settings: config.json over the defaults. A file that can't be read (a stray comma after a
    hand edit) must not stop the app from opening: the defaults are used, the file is left as it is,
    and CONFIG_ERROR says what is wrong so the app can show it."""
    global CONFIG_ERROR
    path, over = move_old_setup(path or env("CONFIG"))
    d = json.loads(json.dumps(DEFAULTS))
    CONFIG_ERROR = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                user = json.load(f)
            if not isinstance(user, dict):
                raise ValueError("the settings are not a JSON object")
            for k, v in user.items():
                if isinstance(d.get(k), dict) and not isinstance(v, dict):
                    raise ValueError("%r must be an object like {...}" % k)
        except (OSError, ValueError) as e:      # json.JSONDecodeError is a ValueError
            CONFIG_ERROR = {"path": path, "error": str(e)}
            user = {}
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                d[k].update(v)
            else:
                d[k] = v
    d.update(over)
    d["user"] = (d.get("user") if isinstance(d.get("user"), str) else "").strip().lower()
    return Cfg(d)


CFG = load_config()


def die(msg):
    sys.exit(msg)


class Refused(SystemExit):
    """die() for a server that stopped part way: `done` says how many went before it stopped."""
    def __init__(self, msg, done):
        super().__init__(msg)
        self.done = done


_SHELL_ENV = {}


def shell_env(name):
    """A variable the person's own login shell sets (in ~/.zshenv, say), or launchd. An app opened
    from the Dock or Finder does not get what the shell profile exports, so the app found no password
    although every terminal had it (21st Nov 2026). Asked once per run, never printed."""
    if sys.platform == "win32" or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        return None
    if name in _SHELL_ENV:
        return _SHELL_ENV[name]
    v = None
    quiet = {"stdin": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "timeout": 8}
    with contextlib.suppress(Exception):
        if sys.platform == "darwin":
            v = subprocess.run(["launchctl", "getenv", name], stdout=subprocess.PIPE, text=True, **quiet).stdout.strip()
        if not v:
            sh = os.environ.get("SHELL") or ("/bin/zsh" if sys.platform == "darwin" else "/bin/sh")
            if os.path.basename(sh) in ("zsh", "bash", "sh", "dash", "ksh", "fish"):
                v = subprocess.run([sh, "-l", "-c", "printenv " + name], stdout=subprocess.PIPE, text=True,
                                   **quiet).stdout.rstrip("\n")
    _SHELL_ENV[name] = v or None
    return v or None


def find_password():
    """The mailbox password, or None: the environment variable named by password_env (on Windows also
    that user variable in the registry, elsewhere also what the login shell or launchd sets), else
    the system keychain (what the app saves)."""
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
    if not p and FROZEN:            # a terminal already has the shell's variables; only the app lacks them
        p = shell_env(name)
    return p or None


def password():
    p = find_password()
    if not p:
        die("%s is not set and no password is saved in the keychain. The mailbox owner sets it; "
            "an agent must never type, print or store it." % CFG.password_env)
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
    if CONFIG_ERROR:
        die("the settings file %s can't be read (%s): fix it, or move it away and set up again"
            % (CONFIG_ERROR["path"], CONFIG_ERROR["error"]))
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


# Seconds one read from the server may wait. It counts from the last byte that came in, so a big
# mail that keeps arriving never runs out of it; a connection that died during sleep or a Wi-Fi
# change does, instead of holding the sync (and its file lock) for good (#40).
IMAP_TIMEOUT = 60
BIG_WAIT = 180      # the wait before the first byte of a big mail or file, which the server builds first


def imap(timeout=None):
    need_account()
    # a server that does not answer must not hold the caller (the app's one connection) for minutes
    m = imaplib.IMAP4_SSL(CFG.imap["host"], CFG.imap["port"], timeout=15)
    m.login(CFG.user, password())
    with contextlib.suppress(Exception):
        m.sock.settimeout(timeout or IMAP_TIMEOUT)
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
def patient(m, secs=None):
    """A longer read timeout for one known-big answer; the connection's own one after it."""
    sock = getattr(m, "sock", None)
    try:
        old = sock.gettimeout()
        sock.settimeout(max(old or 0, secs or BIG_WAIT))
    except Exception:
        yield m
        return
    try:
        yield m
    finally:
        with contextlib.suppress(Exception):
            sock.settimeout(old)


def quit_imap(m, quick=False):
    """LOGOUT. quick: the connection may be dead, so LOGOUT must not wait out the whole timeout."""
    if m is None:
        return
    if quick:
        with contextlib.suppress(Exception):
            m.sock.settimeout(3)
    with contextlib.suppress(Exception):
        m.logout()


@contextlib.contextmanager
def session():
    m = imap()
    ok = False
    try:
        yield m
        ok = True
    finally:
        quit_imap(m, quick=not ok)


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
        with patient(m):
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
    with patient(m):
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


BLOCK_TAGS = frozenset("""div p li ul ol tr table thead tbody tfoot h1 h2 h3 h4 h5 h6 blockquote pre hr
    section article header footer nav main aside address center dl dt dd figure figcaption form fieldset
    details summary""".split())
TOKEN_RE = re.compile(r"<[^<>]*>|[^<]+|<")      # [^<>]: a stray "<" must not make it quadratic
TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)([^<>]*)>")


def html_to_text(h):
    """The text of an HTML mail, line by line as it shows: a block (<div>, <p>, a table row, ...) starts
    a line of its own, also after a bare first line ("Hi,<div>Thanks</div>"); list items keep their
    bullet or number."""
    h = re.sub(r"(?is)<(style|script|head)\b.*?</\1>|<!--.*?-->", " ", h or "")
    out = []
    lists = []                  # the lists we are in: [ordered, next number]

    def line():
        if out and not out[-1].endswith("\n"):
            out.append("\n")
    for mo in TOKEN_RE.finditer(h):
        tok = mo.group()
        tag = TAG_RE.fullmatch(tok) if tok.startswith("<") else None
        if tag is None:
            if tok.startswith("<") and len(tok) > 1 and (tok[1] in "!?/" or tok[1].isalpha()):
                continue        # some other markup: <!doctype>, <?xml>, <o:p>, ...
            text = htmlmod.unescape(tok)
            if "\n" in text and not text.strip():
                continue        # the HTML's own line breaks between tags show as nothing
            out.append(text.replace("\x00", "").replace("\x01", ""))
            continue
        close, name, rest = tag.group(1), tag.group(2).lower(), tag.group(3)
        if name == "br":
            out.append("\n")
        elif name in ("td", "th"):
            if close:
                out.append("\t")
        elif name in ("ul", "ol"):
            line()
            if close:
                if lists:
                    lists.pop()
            else:
                start = re.search(r"""(?i)\bstart\s*=\s*["']?(-?\d{1,6})""", rest)
                lists.append([name == "ol", int(start.group(1)) if start else 1])
        elif name == "li":
            line()
            if not close:
                ordered, n = lists[-1] if lists else (False, 1)
                if ordered:
                    lists[-1][1] += 1
                # \x00: two spaces of a nested list's indent, \x01: the space after the bullet;
                # the clean-up below leaves them alone
                out.append("\x00" * max(0, len(lists) - 1) + ("%d.\x01" % n if ordered else "-\x01"))
        elif name in BLOCK_TAGS:
            line()
    text = re.sub("[  ​　]+", " ", "".join(out))
    text = re.sub(r"(?m)^[ \t]+|[ \t]+$|(?<=\x01) +", "", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text.replace("\x00", "  ").replace("\x01", " ")


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


META_CHARSET_RE = re.compile(rb"""(?i)<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""")
HIGH_PAIR_RE = re.compile(rb"[\x80-\xff]{2}")
# tried in turn when the part names no charset or the wrong one: Chinese first (most of this
# mail), then the other East Asian ones; GB18030 also reads GBK and GB2312
GUESS_CHARSETS = ("utf-8", "gb18030", "big5", "shift_jis", "euc-kr")


def decode_strict(b, cs):
    """b in charset cs, strictly; a character cut off at the very end (the index reads only the start
    of a mail) is dropped. None when cs does not fit."""
    try:
        return b.decode(cs)
    except LookupError:
        return None
    except UnicodeDecodeError as e:
        if e.end >= len(b) and e.start >= len(b) - 4:
            try:
                return b[:e.start].decode(cs)
            except UnicodeDecodeError:
                return None
        return None


def decode_text(b, declared=None, html=False):
    """Bytes of a text part to text: the declared charset when it fits, then an HTML part's own
    <meta charset>, then UTF-8 and the East Asian charsets in turn. Text whose 8-bit bytes all stand
    alone cannot be multi-byte: Western (cp1252, Latin-1). Last, GB18030 with replacement (#46)."""
    tries = [declared] if declared else []
    if html:
        mo = META_CHARSET_RE.search(b[:8192])
        if mo:
            tries.append(mo.group(1).decode("ascii", "ignore").lower())
    if re.search(rb"[\x80-\xff]", b) and not HIGH_PAIR_RE.search(b):
        tries += ["utf-8", "cp1252", "latin-1"]
    tries += GUESS_CHARSETS
    seen = set()
    for cs in tries:
        if cs in seen:
            continue
        seen.add(cs)
        s = decode_strict(b, cs)
        if s is not None:
            return s
    return b.decode("gb18030", "replace")


def part_text(p):
    """Text of a part; never raises on an unknown or wrong charset (unknown-8bit, csGB2312, ...).
    The bytes are decoded here: get_content() reads a part without a charset as ASCII and turned
    every Chinese character into "�" (#46)."""
    payload = b64_cut(p)
    if payload is None:
        try:
            payload = p.get_payload(decode=True)
        except Exception:
            payload = None
        if not isinstance(payload, bytes):
            try:
                return nfc(p.get_content())
            except Exception:
                return ""
    declared = p.get_content_charset()
    if declared in ("unknown-8bit", "x-unknown", "us-ascii", "ascii") and re.search(rb"[\x80-\xff]", payload):
        declared = None         # 8-bit bytes the label cannot be right about
    return nfc(decode_text(payload, declared, p.get_content_type() == "text/html"))


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
    at = quote_start(text)
    return (text[:at] if at >= 0 else text or "").strip()


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


def is_inline(p, refs=None):
    """A picture shown in the mail's text, not a file. refs: the Content-IDs the HTML body shows
    (body_refs). Then a part is such a picture when its Content-ID is one of them and it is an image
    (by its type, its name or its bytes, or a nameless octet-stream a light mail left on the server),
    whatever its disposition: Outlook, Foxmail and QQ Mail mark these pictures as attachments. An image
    the body does not show is a file. A PDF with a Content-ID is always a file.
    Without refs: an image with a Content-ID that is not marked as an attachment."""
    cid = (p.get("Content-ID") or "").strip().strip("<>")
    if not cid:
        return False
    if refs is None:
        return p.get_content_disposition() != "attachment" and bool(image_type(p))
    return cid in refs and (bool(image_type(p)) or p.get_content_type() == "application/octet-stream")


def body_refs(msg):
    """The Content-IDs the mail's HTML body shows."""
    return cid_refs(bodies(msg)[1])


def attachments(msg, inline=False):
    out = []
    refs = body_refs(msg)
    for p in leaf_parts(msg):
        if p is msg and (msg.is_multipart() or not (
                p.get_content_disposition() == "attachment" or p.get_filename()
                or p.get_content_maintype() not in ("text", "multipart", "message"))):
            continue     # a mail that is only a file (a scanner's PDF) still shows that file
        is_file = (p.get_content_disposition() == "attachment" or p.get_filename()
                   or p.get_content_type() == "message/rfc822"
                   or (p.get("Content-ID") and not is_inline(p, refs)))
        if is_file and (inline or not is_inline(p, refs)):
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
    return bool(FWD_PREFIX_RE.match(s or ""))


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

# The index's own version, kept in meta 'schema'. Raise it only when an older ragdoll could no
# longer read the index safely; that older copy (the app or the command line, which update apart)
# then stops with a clear message instead of reading it wrong.
SCHEMA_VERSION = 2
RELEASES_PAGE = "https://github.com/erict16/ragdoll-mail/releases/latest"


class IndexTooNew(LookupError):
    pass


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
    r = c.execute("select v from meta where k='schema'").fetchone()
    have = int(r[0]) if r and str(r[0]).isdigit() else 0
    if have > SCHEMA_VERSION:
        c.close()
        raise IndexTooNew("This mail index was made by a newer Ragdoll Mail (index version %d; this copy "
                          "reads up to %d). Update this copy: the app from %s, the command line with "
                          "`ragdoll update`." % (have, SCHEMA_VERSION, RELEASES_PAGE))
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
    if not c.execute("select 1 from meta where k='charset_fix2'").fetchone():
        # 0.10 and older read a text part without a charset as ASCII: "报价单" was stored as "���"
        bad = c.execute("select id from msgs where has_body=1 and instr(body, char(65533))>0").fetchall()
        for r in bad:
            c.execute("update msgs set body='', has_body=0 where id=?", (r["id"],))
            c.execute("update fts set body='' where rowid=?", (r["id"],))
        c.execute("insert or replace into meta values('charset_fix2', ?)", (str(len(bad)),))
        c.commit()
    if have < SCHEMA_VERSION:
        c.execute("insert or replace into meta values('schema', ?)", (str(SCHEMA_VERSION),))
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


def sync_headers(m, c, folder, full_flags=False, workers=1, held=None, deep=False):
    """New mail headers, flags and deletions for one folder. Returns new row count.
    held(folder, since) -> {uid: {"seen": 1, ...}}: flags the caller has changed that the server may
    not have had when it was asked at `since`; they stay as the caller set them.
    deep: the flags of older mail too (deep_flags), not only of the newest 300."""
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
    local = {r["uid"]: r for r in c.execute(
        "select uid, id, seen, flagged, answered from msgs where folder=? and uidv=?", (folder, uidv))}
    for uid, r in local.items():
        if uid not in server:
            c.execute("delete from msgs where id=?", (r["id"],))
            c.execute("delete from fts where rowid=?", (r["id"],))
    flags = Flags(c, folder, local, held)
    # flags: all of them on a full sync, the newest 300 otherwise
    known = sorted(u for u in server if u in local)
    check = known if full_flags else known[-300:]
    fetch_flags(m, check, flags)
    if deep and not full_flags and len(known) > 300:
        deep_flags(m, c, folder, uidv, known[:-300], flags)
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


class Flags:
    """Puts the server's flags into the index rows of one folder; a row is written only when they
    differ, and a flag the caller holds (held) stays as the caller set it."""
    def __init__(self, c, folder, local, held):
        self.c, self.folder, self.local, self.held = c, folder, local, held

    def mine(self, asked):
        return self.held(self.folder, asked) if self.held else {}

    def put(self, uid, mine, seen=None, flagged=None, answered=None):
        r = self.local.get(uid)
        if r is None:
            return
        if uid in mine:     # a mail just read in the app must not turn unread again
            seen = mine[uid].get("seen", seen)
            flagged = mine[uid].get("flagged", flagged)
        new = [r["seen"] if seen is None else int(seen), r["flagged"] if flagged is None else int(flagged),
               r["answered"] if answered is None else int(answered)]
        if new != [r["seen"], r["flagged"], r["answered"]]:
            self.c.execute("update msgs set seen=?, flagged=?, answered=? where id=?", (*new, r["id"]))


def fetch_flags(m, uids, flags, extra=""):
    """FLAGS of these UIDs (or of "1:*" with a modifier in extra) into the index."""
    sets = [uids] if isinstance(uids, str) else [",".join(map(str, uids[i:i + 500])) for i in range(0, len(uids), 500)]
    for s in sets:
        if not s:
            continue
        asked = time.time()
        typ, data = m.uid("FETCH", s, "(UID FLAGS)" + extra)
        if typ != "OK":
            continue            # e.g. a mail expunged a moment ago: the next pass asks again
        mine = flags.mine(asked)
        for seg in segments(data):
            uid = seg_uid(seg)
            if uid is not None:
                flags.put(uid, mine, *flags_of(b"".join(seg)))


SWEEP = 2000        # older mails whose flags are asked for on each pass, in turn, when CONDSTORE is missing


def search_set(m, key):
    typ, data = m.uid("SEARCH", None, key)
    if typ != "OK":
        return None
    return {int(x) for x in b" ".join(x for x in data if isinstance(x, bytes)).split() if x.isdigit()}


def highest_modseq(m, folder):
    try:
        v = m.untagged_responses.pop("HIGHESTMODSEQ", None)
        if not v:
            typ, data = m.status(q(folder), "(HIGHESTMODSEQ)")
            mo = re.search(rb"HIGHESTMODSEQ (\d+)", b" ".join(x for x in data if isinstance(x, bytes))) if typ == "OK" else None
            return int(mo.group(1)) if mo else None
        return int(v[-1])
    except (imaplib.IMAP4.abort, OSError):
        raise
    except Exception:       # noqa: BLE001 - a server that does not say: the other way is used
        return None


def deep_flags(m, c, folder, uidv, older, flags):
    """Read / unread and the other flags of mail older than the newest 300, which were never asked
    for again (#47). With CONDSTORE: only the flags changed since the last pass (CHANGEDSINCE).
    Without: UID SEARCH UNSEEN and FLAGGED give seen and flagged of every mail in two commands, and
    a rolling sweep of SWEEP mails per pass brings in the rest (answered) in turn."""
    if has_cap(m, "CONDSTORE"):
        key = "modseq:" + folder
        r = c.execute("select v from meta where k=?", (key,)).fetchone()
        was = (r[0].split() + ["", ""])[:2] if r else ["", ""]
        now = highest_modseq(m, folder)
        if now is not None:
            if was[0] == str(uidv) and was[1].isdigit():
                if int(was[1]) != now:
                    fetch_flags(m, "1:*", flags, " (CHANGEDSINCE %d)" % int(was[1]))
                c.execute("insert or replace into meta values(?, ?)", (key, "%d %d" % (uidv, now)))
                return
            c.execute("insert or replace into meta values(?, ?)", (key, "%d %d" % (uidv, now)))
            # the first pass: everything once, the way below; from the next pass on only changes
    asked = time.time()
    unseen, flagged = search_set(m, "UNSEEN"), search_set(m, "FLAGGED")
    mine = flags.mine(asked)
    for u in older:
        flags.put(u, mine, None if unseen is None else u not in unseen, None if flagged is None else u in flagged)
    key = "sweep:" + folder
    r = c.execute("select v from meta where k=?", (key,)).fetchone()
    at = int(r[0]) if r and str(r[0]).isdigit() else None
    below = [u for u in older if at is None or u < at] or older     # the oldest reached: from the top again
    turn = below[-SWEEP:]
    fetch_flags(m, turn, flags)
    c.execute("insert or replace into meta values(?, ?)", (key, str(turn[0])))


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


BODY_BATCH = 50     # mails per FETCH command: one command for many mails, never one each


def fetch_bodies_on(m, folder, uids, per=BODY_BATCH):
    """{uid: the start of its body} for these UIDs, on a connection the caller keeps (and keeps the
    folder open on: the next batch of the same folder needs no SELECT)."""
    use(m, folder)
    out = {}
    for i in range(0, len(uids), per):
        typ, data = m.uid("FETCH", ",".join(map(str, uids[i:i + per])),
                          "(UID BODY.PEEK[]<0.%d>)" % CFG.body_bytes)
        for seg in segments(data):
            uid = seg_uid(seg)
            if uid is not None:
                out[uid] = literal_after(seg, rb"BODY\[\]<0>")
    return out


def fetch_bodies(folder, uids):
    """Worker: the start of each body for these UIDs, on its own connection."""
    with session() as m:
        return fetch_bodies_on(m, folder, uids, per=25)


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
        elif re.search(r"[A-Za-z]", t):    # LIKE: case does not matter for these letters
            where.append("(" + " or ".join("m.%s like ? escape '\\'" % k
                                           for k in ("subject", "frm", "to_", "cc", "atts", "body")) + ")")
            params += [like_arg(t)] * 6
        else:                               # a short Chinese word: a plain substring test, about half the time
            where.append("(" + " or ".join("instr(m.%s, ?) > 0" % k
                                           for k in ("subject", "frm", "to_", "cc", "atts", "body")) + ")")
            params += [t] * 6
    if long_terms:
        where.insert(0, "m.id in (select rowid from fts where fts match ?)")
        params.insert(0, " AND ".join(long_terms))
    add_filters(a, where, params)
    return (("where " + " and ".join(where)) if where else ""), params


def search_rows(c, words, a):
    """The newest matches first; a.offset (when set) skips that many, for the next page."""
    where, params = search_where(words, a)
    return c.execute("select m.* from msgs m %s order by m.ts desc, m.id desc limit ? offset ?" % where,
                     params + [a.limit, max(0, getattr(a, "offset", 0) or 0)]).fetchall()


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
             "inline": is_inline(p, body_refs(msg))} for p in attachments(msg, inline=True)]
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


# Files that run code when opened (Windows, macOS, Linux). The app never opens one of these from a mail:
# it only saves it or shows it in its folder.
PROGRAM_EXTS = frozenset("""
    exe com scr pif cpl msi msp mst msc msix msixbundle appx appxbundle appinstaller application appref-ms
    bat cmd ps1 ps1xml ps2 ps2xml psc1 psc2 psd1 psm1 vb vbe vbs js jse ws wsc wsf wsh hta jar jnlp
    lnk url scf inf reg gadget chm hlp diagcab library-ms search-ms searchconnector-ms settingcontent-ms
    xbap xll iso img vhd vhdx py pyw pyc pyz pyzw pl rb
    app command terminal tool pkg mpkg workflow action scpt scptd applescript osax prefpane kext
    mobileconfig fileloc inetloc webloc
    sh bash zsh csh ksh fish run bin desktop
""".split())


def is_program(name):
    """True when opening a file of this name would run it. Windows ignores dots and spaces at the end
    of a name, so "invoice.exe." counts too."""
    n = (name or "").strip().rstrip(". ").lower()
    return "." in n and n.rsplit(".", 1)[1] in PROGRAM_EXTS


ZONE_ID = "[ZoneTransfer]\r\nZoneId=3\r\n"     # Windows: "this file came from the internet"


def mark_downloaded(path):
    """Mark a file written from a mail as downloaded, as a browser does: Windows' Mark-of-the-Web
    (Zone.Identifier, so SmartScreen and Office Protected View step in) and the macOS quarantine flag
    (so Gatekeeper asks before anything in it runs). Best effort: some disks cannot hold the mark."""
    try:
        if sys.platform == "win32":
            with open(path + ":Zone.Identifier", "w", encoding="ascii", newline="") as f:
                f.write(ZONE_ID)
        elif sys.platform == "darwin":
            import ctypes
            libc = ctypes.CDLL("/usr/lib/libc.dylib", use_errno=True)
            libc.setxattr.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t,
                                      ctypes.c_uint32, ctypes.c_int)
            v = ("0081;%08x;Ragdoll Mail;" % int(time.time())).encode()
            libc.setxattr(os.fsencode(path), b"com.apple.quarantine", v, len(v), 0, 0)
    except (OSError, AttributeError, ValueError):
        pass


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
        mark_downloaded(path)
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


QUOTE_HEAD = '<div style="padding:8px 0;border-top:1px solid #e0e0e0;font-size:13px;color:#646a73">'


def quote_of(html):
    """The quoted history (quote_block) in a mail made here, or ""."""
    k = (html or "").find(QUOTE_HEAD)
    return html[k:] if k >= 0 else ""


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

    esc = htmlmod.escape        # every name, address and subject here comes from the sender

    def people(v):
        return ", ".join("&quot;%s&quot; &lt;%s&gt;" % (esc(n or a_), esc(a_)) for n, a_ in addrs(v))
    cc = people(hdr(orig, "Cc"))
    head = (QUOTE_HEAD +
            '<div>发件人：&quot;%s&quot; &lt;%s&gt;</div><div>时间：%d年%d月%d日 (周%s) %s</div>'
            '<div>主题：%s</div><div>收件人：%s</div>%s</div>'
            % (esc(fn or fa), esc(fa), t.year, t.month, t.day, WEEK[t.weekday()],
               t.strftime("%H:%M"), esc(hdr(orig, "Subject")), people(hdr(orig, "To")),
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


# a reply or forward prefix as mail apps write it, with an ASCII or a full-width colon (RE：, 回复：)
REPLY_PREFIX_RE = re.compile(r"(?i)\s*(re|aw|回复|答复|回覆|答覆|trả lời)\s*[:：]")
FWD_PREFIX_RE = re.compile(r"(?i)\s*(fw|fwd|wg|tr|转发|轉寄|轉發|chuyển tiếp)\s*[:：]")


def reply_subject(s):
    """Re: + the full original subject; only an existing reply prefix is not doubled."""
    return s if REPLY_PREFIX_RE.match(s or "") else "Re: " + (s or "")


def forward_subject(s):
    return s if FWD_PREFIX_RE.match(s or "") else "Fw: " + (s or "")


def text_to_html(t):
    return "".join("<div>%s</div>" % (htmlmod.escape(x) or "<br>") for x in t.split("\n"))


def build_message(body_html, to, cc, subject, orig=None, mode=None, bcc=(), attach=(),
                  signature_html="", high=False, font="", quote_html="", quote_src=None):
    """The draft as an EmailMessage. mode: None (new), 'reply' or 'forward'. font: the body's font as CSS
    (font-family:...;font-size:...): the signature is wrapped in it too, or Outlook shows it in Times.
    quote_html, quote_src: with no orig, a quote already made (quote_of an earlier draft) and the mail
    that holds its pictures."""
    if font and signature_html.strip():
        signature_html = '<div data-rd-sig="1" style="%s">%s</div>' % (re.sub(r'["<>&\\]', "", font), signature_html)
    html = body_html + "<div><br></div>" + signature_html
    if orig is not None:
        html += "<div><br></div>" + quote_block(orig)
    elif quote_html:
        html += "<div><br></div>" + quote_html
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
    src = orig if orig is not None else quote_src
    if src is not None:
        done = set()
        for p in src.walk():
            if p.is_multipart() or not p.get("Content-ID"):
                continue
            cid = p.get("Content-ID").strip().strip("<>")
            if cid in used and cid not in done and is_inline(p, used):
                mt, st = image_type(p).split("/", 1)
                add_file(hpart, p.get_payload(decode=True) or b"", mt, st, fname(p), cid="<%s>" % cid)
                done.add(cid)
        if mode == "forward" and orig is not None:
            for p in attachments(orig):
                if p.get_content_type() == "message/rfc822":     # keep an attached mail as a .eml file
                    add_file(msg, part_bytes(p), "application", "octet-stream", fname(p))
                    continue
                mt, st = p.get_content_type().split("/", 1)
                add_file(msg, part_bytes(p), mt, st, fname(p))
    for f in attach:
        # a path, or (path, the file's own name): the name on disk may be a safe stand-in for it
        f, name = f if isinstance(f, tuple) else (f, os.path.basename(f))
        name = one_line(name or "").strip() or os.path.basename(f)
        ctype = mimetypes.guess_type(name)[0] or mimetypes.guess_type(f)[0] or "application/octet-stream"
        if ctype.startswith("message/"):     # a .eml file: add_attachment wants a Message object for these
            ctype = "application/octet-stream"
        mt, st = ctype.split("/", 1)
        with open(f, "rb") as fh:
            add_file(msg, fh.read(), mt, st, name)
    return msg


def add_file(holder, data, mt, st, name, cid=None):
    """Add a file to the mail, or with cid a picture its HTML shows (holder: the HTML part), under the
    file's own name: as RFC 2231 filename*= (what the email module writes) and, for the mail apps that
    read only that, as name= in RFC 2047 words on Content-Type, as Thunderbird and Outlook write it."""
    name = one_line(name or "").strip() or None
    if cid:
        holder.add_related(data, mt, st, cid=cid, filename=name)
    else:
        holder.add_attachment(data, mt, st, filename=name)
    if name:
        name_param(list(holder.iter_parts())[-1], name)


def name_param(part, name):
    if name.isascii():
        part.set_param("name", name)
        return
    words, cur = [], b""
    for ch in name:         # whole characters in each word; 42 bytes = 56 base64 = a 68-character word
        b = ch.encode()
        if cur and len(cur) + len(b) > 42:
            words.append(cur)
            cur = b""
        cur += b
    words.append(cur)
    value = "=?utf-8?B?%s?=" % "?=\n =?utf-8?B?".join(base64.b64encode(w).decode() for w in words)
    keep = "".join('; %s="%s"' % (k, v) for k, v in (part.get_params() or [])[1:]
                   if k.lower() != "name" and isinstance(v, str) and v.isascii() and '"' not in v)
    # set as it is to be written: the email module would turn the words back into RFC 2231
    for k, (h, _) in enumerate(part._headers):
        if h.lower() == "content-type":
            part._headers[k] = (h, '%s%s;\n name="%s"' % (part.get_content_type(), keep, value))
            break


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
    with contextlib.suppress(OSError):
        if app_running():               # the app shows a short note with a button to open it
            tell_app("draft", "%s:%d" % (CFG.short(CFG.folders["drafts"]), new_uid), subject)


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


def uid_of_mid(m, folder, mid, last=30):
    """The UID of the mail with this Message-ID among the folder's last ones, or 0."""
    select(m, folder)
    u = uids_of(m)[-last:]
    want = (mid or "").strip().strip("<>").encode()
    if not u or not want:
        return 0
    typ, data = m.uid("FETCH", ",".join(map(str, u)), "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
    for seg in segments(data or []):
        if b"<" + want + b">" in b"".join(p for p in seg if isinstance(p, bytes)):
            return seg_uid(seg) or 0
    return 0


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


def log_sent(mid, subject, bcc=""):
    """One line per mail sent: Message-ID, when, subject, and who was Bcc'd (the mail itself no longer says)."""
    os.makedirs(CFG.home, exist_ok=True)
    with open(sent_log(), "a", encoding="utf-8") as f:
        f.write("%s\t%s\t%s\t%s\n" % (mid, dt.datetime.now(CFG.tz).strftime("%Y-%m-%d %H:%M:%S"),
                                      re.sub(r"\s+", " ", subject)[:200], re.sub(r"\s+", " ", bcc or "")))


def sent_copy(out, bcc):
    """The copy for Sent: the mail as it went out, plus its Bcc line, as other mail apps keep it.
    Only this copy has it; the mail sent over SMTP never does."""
    if not bcc:
        return out
    copy = to_msg(out)
    copy["Bcc"] = one_line(bcc)
    return copy.as_bytes(policy=OUT_POLICY)


def cmd_send(a):
    if not a.yes:
        die("send needs --yes, given only after the owner approved this exact draft")
    folder, uid = drafts_only(a.id, "send")
    print(json.dumps(send_draft(folder, uid), ensure_ascii=False, indent=1))


def smtp_open(host, port, timeout):
    """465 is TLS from the first byte. 587 (iCloud and others) and 25 start plain and must switch to
    TLS with STARTTLS before anything else; a server that cannot is refused, never used in the clear."""
    if int(port) in (587, 25):
        s = smtplib.SMTP(host, int(port), timeout=timeout)
        try:
            s.starttls(context=ssl.create_default_context())
        except Exception:
            with contextlib.suppress(Exception):
                s.close()
            raise
        return s
    return smtplib.SMTP_SSL(host, int(port), timeout=timeout)


# A company domain's mail servers, from who receives its mail (its MX records):
# (MX host pattern, IMAP host, SMTP host, SMTP port). {1} is the pattern's first group.
MX_SERVERS = (
    (r"mxbiz\d*\.qq\.com", "imap.exmail.qq.com", "smtp.exmail.qq.com", 465),          # Tencent Exmail
    (r"(?:.+\.)?aspmx\.l\.google\.com|.+\.googlemail\.com|smtp\.google\.com",
     "imap.gmail.com", "smtp.gmail.com", 465),                                       # Google Workspace
    (r".+\.mxhichina\.com", "imap.qiye.aliyun.com", "smtp.qiye.aliyun.com", 465),     # Alibaba Mail
    (r".+\.mxmail\.netease\.com|.*qiye163mx.*", "imap.qiye.163.com", "smtp.qiye.163.com", 465),  # NetEase
    (r".+\.mail\.icloud\.com", "imap.mail.me.com", "smtp.mail.me.com", 587),           # iCloud custom domain
    (r".+\.messagingengine\.com", "imap.fastmail.com", "smtp.fastmail.com", 465),       # Fastmail
    (r"mx\d*\.zoho\.(com|eu|in|com\.au|com\.cn|jp)", "imap.zoho.{1}", "smtp.zoho.{1}", 465),  # Zoho
    (r"mx\.yandex\.(?:net|ru)", "imap.yandex.com", "smtp.yandex.com", 465),             # Yandex 360
)


def mx_hosts(domain, timeout=6):
    """The domain's mail exchangers, best first, from the system's own DNS (nslookup is on every
    Mac and Windows). [] when it cannot tell."""
    if not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", domain or ""):
        return []
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # no console window
    try:
        out = subprocess.run(["nslookup", "-type=mx", domain], capture_output=True, text=True,
                             timeout=timeout, **kw).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = re.findall(r"(?:MX preference = (\d+), )?mail exchanger = (?:(\d+) )?(\S+)", out or "")
    hosts = sorted((int(a or b or 0), h.rstrip(".").lower()) for a, b, h in found)
    return list(dict.fromkeys(h for _, h in hosts))


def servers_from_mx(domain):
    """{imap_host, smtp_host, smtp_port} for a domain whose mail a known service receives, else None."""
    for mx in mx_hosts(domain):
        for pat, imap, smtp, port in MX_SERVERS:
            m = re.fullmatch(pat, mx)
            if m:
                g = (m.group(0),) + m.groups()
                return {"imap_host": imap.format(*g), "smtp_host": smtp.format(*g), "smtp_port": port}
    return None


class SendLater(SystemExit):
    """Sending stopped before anything left this machine (no network, the server did not answer,
    it said "try later"): trying again later cannot send the mail twice. .cause is what went wrong."""
    def __init__(self, cause):
        super().__init__("not sent, nothing left this computer: %s" % (cause or type(cause).__name__))
        self.cause = cause


MAYBE_SENT = ("The connection broke while the mail was going out, so it may have been sent. "
              "Check Sent before you send it again.")


def smtp_send(s, frm, rcpts, out):
    """sendmail in its two halves: until DATA nothing has left (SendLater on a failure there); a break
    while the mail itself goes out may have sent it (MAYBE_SENT). Returns the refused recipients."""
    try:
        s.ehlo_or_helo_if_needed()
        code, resp = s.mail(frm)
        if code != 250:
            raise smtplib.SMTPSenderRefused(code, resp, frm)
        refused = {}
        for r in rcpts:
            code, resp = s.rcpt(r)
            if code not in (250, 251):
                refused[r] = (code, resp)
        if len(refused) == len(rcpts):
            raise smtplib.SMTPRecipientsRefused(refused)
    except (smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused):
        raise                                   # the server will not take it: trying again does not help
    except (OSError, smtplib.SMTPException) as e:
        raise SendLater(e) from e
    try:
        code, resp = s.data(out)
    except smtplib.SMTPDataError as e:          # the server answered: it did not take the mail
        if 400 <= e.smtp_code < 500:
            raise SendLater(e) from e
        raise
    except (OSError, smtplib.SMTPException):
        die(MAYBE_SENT)
    return refused


def send_draft(folder, uid, wait=3):
    """Send one draft over SMTP, make sure Sent has a copy, delete the draft, mark the original
    answered. Returns what happened; dies (SystemExit) before sending when it must not go out, and
    raises SendLater when it stopped before anything left (a network or server hiccup)."""
    sent = CFG.folders["sent"]
    try:
        with session() as m:
            raw = fetch_raw(m, folder, uid)
            msg = to_msg(raw)
            mid = hdr(msg, "Message-ID").strip()
            when = already_sent(mid) or ("(found in Sent)" if mid and in_folder(m, sent, mid, last=40) else None)
    except SystemExit:
        raise
    except Exception as e:      # noqa: BLE001 - the draft was not even read: nothing went out
        raise SendLater(e) from e
    if when:
        die("NOT SENT AGAIN: this draft already went out %s. Check Sent; remove the draft with delete-draft."
            % when)
    if not mid:
        mid = make_msgid(domain=(CFG.user.split("@")[-1] or None))
        msg["Message-ID"] = mid
    rcpts = [x for _, x in addrs(hdr(msg, "To")) + addrs(hdr(msg, "Cc")) + addrs(hdr(msg, "Bcc"))]
    if not rcpts:
        die("the draft has no recipients")
    bcc = hdr(msg, "Bcc").strip()
    del msg["Bcc"]
    del msg["Date"]
    msg["Date"] = formatdate(localtime=True)     # the time it is sent, not when the draft was made
    out = msg.as_bytes(policy=OUT_POLICY)        # what goes out: never a Bcc line
    keep = sent_copy(out, bcc)
    pw = password()
    try:
        s = smtp_open(CFG.smtp["host"], CFG.smtp["port"], 300)
    except (OSError, smtplib.SMTPException) as e:
        raise SendLater(e) from e
    try:
        try:
            s.login(CFG.user, pw)
        except smtplib.SMTPAuthenticationError:
            raise                               # a wrong password stays wrong
        except (OSError, smtplib.SMTPException) as e:
            raise SendLater(e) from e
        refused = smtp_send(s, CFG.user, rcpts, out)
    finally:
        try:
            s.quit()
        except Exception:
            pass
    log_sent(mid, hdr(msg, "Subject"), bcc)      # from here on a retry refuses instead of sending twice
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
                typ, data = m.append(q(sent), "(\\Seen)", imaplib.Time2Internaldate(time.time()), keep)
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
            raise Refused("the server refused the move after %d mails: %s" % (moved, data), moved)
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
# installed with pip or pipx (no git clone to pull): the package manager updates it
PIP_INSTALL = not os.path.isdir(os.path.join(APP_DIR, ".git")) and "-packages" in APP_DIR
# installed with Homebrew (brew install erict16/tap/ragdoll): Homebrew updates it
BREW_INSTALL = not os.path.isdir(os.path.join(APP_DIR, ".git")) and "/Cellar/" in APP_DIR.replace(os.sep, "/")
UPDATE_REF = "refs/ragdoll/update"
UPDATE_EVERY = 6 * 3600


def update_remote():
    return env("UPDATE_REMOTE") or "origin"     # a path or URL for tests


def update_enabled():
    # the built app updates as a whole, from the release page (the app shows when there is one)
    return (not FROZEN and not PIP_INSTALL and not BREW_INSTALL and not env("NO_UPDATE_CHECK")
            and CFG.d.get("update_check", True))


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


def pid_running(pid, cmd="app"):
    """True when process pid still runs `cmd` (its run marker is locked)."""
    if not isinstance(pid, int):
        return False
    path = os.path.join(CFG.home, "run", "%d-%s.lock" % (pid, cmd))
    if not os.path.exists(path):
        return False
    try:
        f = open(path, "a+")
    except OSError:
        return True
    try:
        free = try_lock(f)
        if free:
            unlock(f)
        return not free
    finally:
        f.close()


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
    if FROZEN:
        die("this ragdoll comes with the Ragdoll Mail app: get the newest app from " + RELEASES_PAGE)
    if PIP_INSTALL:
        die("this ragdoll was installed with pip: run  pipx upgrade ragdoll-mail  (or  pip install -U ragdoll-mail)")
    if BREW_INSTALL:
        die("this ragdoll was installed with Homebrew: run  brew upgrade ragdoll")
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


# ------------------------------------------------------------------ the app and the command line
# The app and ragdoll share one config, one keychain entry and one index. What is here joins them
# for a person who has only the app: the `ragdoll` command made from the app, a hand-off from an
# agent to the app (`open`, and a note when a draft is ready), and sending later.

OURS = "made by Ragdoll Mail"


def cli_argv():
    """How a shell starts this ragdoll: the built app's own program, or Python and this file."""
    if FROZEN:
        exe = sys.executable
        if sys.platform == "win32":
            # the window program has no console, so the release ships ragdoll.exe beside it
            if os.path.basename(exe).lower() != "ragdoll.exe":
                exe = os.path.join(os.path.dirname(exe), "ragdoll.exe")
            return [exe]
        return [exe, "cli"]
    return [sys.executable or "python3", "-I", os.path.abspath(__file__)]


def mac_bundle(exe=None):
    """The .app folder this program sits in, or None."""
    m = re.match(r"^(.*?\.app)/Contents/MacOS/", exe or sys.executable or "")
    return m.group(1) if m else None


def shell_profiles(home):
    return [os.path.join(home, n) for n in (".zprofile", ".zshrc", ".bash_profile", ".bashrc", ".profile")]


def install_cli(home=None):
    """Make the `ragdoll` command for this copy. It writes a small launcher, never over one it did
    not make, and puts its folder on the PATH of new terminals. Returns what it did."""
    home = home or os.path.expanduser("~")
    argv = cli_argv()
    if FROZEN and sys.platform == "darwin":
        b = mac_bundle() or ""
        if b.startswith("/Volumes/") or "/AppTranslocation/" in b:
            raise OSError("Move Ragdoll Mail into Applications, open it from there, then try again.")
    if FROZEN and not os.path.exists(argv[0]):
        raise OSError("ragdoll.exe is missing next to the app. Unpack the whole download again.")
    if sys.platform == "win32":
        d = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local"),
                         "ragdoll-mail", "bin")
        path = os.path.join(d, "ragdoll.cmd")
        body = "@echo off\r\nrem %s\r\n%s %%*\r\n" % (OURS, subprocess.list2cmdline(argv))
    else:
        d = os.path.join(home, ".local", "bin")
        path = os.path.join(d, "ragdoll")
        body = "#!/bin/sh\n# %s\nexec %s \"$@\"\n" % (OURS, " ".join(shlex.quote(x) for x in argv))
    out = {"path": path, "command": argv, "made": False, "kept": False, "path_added": None}
    old = None
    with contextlib.suppress(OSError):
        with open(path, encoding="utf-8", errors="replace") as f:
            old = f.read()
    if old is not None and OURS not in old:
        out["kept"] = True              # somebody's own launcher (the README's, say): leave it alone
    elif old != body:
        os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(body)
        os.chmod(tmp, 0o755)
        os.replace(tmp, path)
        out["made"] = True
    out["path_added"] = add_to_path(d, home)
    return out


def add_to_path(d, home):
    """Put d on the PATH of new terminals. Returns where it was added, or None when it was there."""
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as k:
            try:
                cur, kind = winreg.QueryValueEx(k, "Path")
            except FileNotFoundError:
                cur, kind = "", winreg.REG_EXPAND_SZ
            parts = [x for x in cur.split(";") if x]
            if any(os.path.normcase(os.path.expandvars(x)).rstrip("\\") == os.path.normcase(d) for x in parts):
                return None
            winreg.SetValueEx(k, "Path", 0, kind, ";".join(parts + [d]))
        with contextlib.suppress(Exception):      # tell Explorer, so new terminals see it
            import ctypes
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 2, 5000, None)
        return "the user PATH"
    rel = "$HOME/" + os.path.relpath(d, home) if d.startswith(home + os.sep) else d
    for p in shell_profiles(home):
        with contextlib.suppress(OSError):
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if d in text or rel in text or "~/" + os.path.relpath(d, home) in text:
                return None
    shell = os.path.basename(os.environ.get("SHELL") or ("/bin/zsh" if sys.platform == "darwin" else "/bin/bash"))
    p = os.path.join(home, ".zprofile" if shell == "zsh" else ".bash_profile" if sys.platform == "darwin"
                     else ".profile")
    with open(p, "a", encoding="utf-8") as f:
        f.write('\n# %s: the ragdoll command\nexport PATH="%s:$PATH"\n' % (OURS, rel))
    return p


# ---- hand-off to the app: a small file in <data dir>/asks that the running app picks up

def tell_app(kind, mail_id, subject=""):
    d = os.path.join(CFG.home, "asks")
    os.makedirs(d, exist_ok=True)
    name = "%d-%d" % (time.time_ns(), os.getpid())
    tmp = os.path.join(d, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"kind": kind, "id": mail_id, "subject": subject, "at": int(time.time())}, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(d, name + ".json"))


def take_asks(max_age=600):
    """The hand-offs waiting for the app, oldest first; each is read once."""
    d = os.path.join(CFG.home, "asks")
    out = []
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not n.endswith(".json"):
            continue
        p = os.path.join(d, n)
        try:
            with open(p, encoding="utf-8") as f:
                x = json.load(f)
        except (OSError, ValueError):
            x = None
        with contextlib.suppress(OSError):
            os.remove(p)
        if isinstance(x, dict) and x.get("id") and time.time() - (x.get("at") or 0) < max_age:
            out.append(x)
    return out


def app_running():
    return "app" in busy_commands()


def start_app():
    """Open the app (the built one when there is one)."""
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "darwin":
        b = mac_bundle() if FROZEN else None
        if not b and os.path.isdir("/Applications/Ragdoll Mail.app"):
            b = "/Applications/Ragdoll Mail.app"
        if b:
            subprocess.Popen(["open", b], **quiet)
            return
    if FROZEN and sys.platform == "win32":
        exe = os.path.join(os.path.dirname(sys.executable), "Ragdoll Mail.exe")
        if os.path.exists(exe):
            subprocess.Popen([exe], creationflags=0x00000008, **quiet)      # DETACHED_PROCESS
            return
    app = os.path.join(APP_DIR, "ragdoll_app.py")
    if not os.path.exists(app):
        raise OSError("the app is not here; open Ragdoll Mail yourself")
    kw = {"creationflags": 0x00000008} if sys.platform == "win32" else {"start_new_session": True}
    subprocess.Popen([sys.executable, "-I", app], **quiet, **kw)


def cmd_open(a):
    folder, uid = parse_id(a.id)
    c = db()
    r = c.execute("select subject from msgs where folder=? and uid=? order by uidv desc limit 1", (folder, uid)).fetchone()
    tell_app("open", a.id, r["subject"] if r else "")
    state = "running"
    if not app_running():
        start_app()
        state = "started"
    print(json.dumps({"id": a.id, "app": state}, ensure_ascii=False))


# ---- send later. The list is the app's (scheduled.json): the app sends each mail when it is due,
# while it is open; one that came due while it was closed goes out when it starts.

def sched_path():
    return os.path.join(CFG.home, "scheduled.json")


def sched_read():
    try:
        with open(sched_path(), encoding="utf-8") as f:
            d = json.load(f)
        return [x for x in d if isinstance(x, dict) and x.get("id") and isinstance(x.get("at"), (int, float))]
    except (OSError, ValueError):
        return []


def sched_write(items):
    os.makedirs(CFG.home, exist_ok=True)
    tmp = "%s.%d.tmp" % (sched_path(), os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp, sched_path())


def parse_when(s, now=None):
    """'2026-11-22 09:00', '09:00' (the next one) or '+2h' / '+30m' / '+1d', in the configured time zone."""
    now = now or dt.datetime.now(CFG.tz)
    s = (s or "").strip()
    m = re.fullmatch(r"\+(\d{1,5})\s*([mhd])", s)
    if m:
        return now + dt.timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[m.group(2)]: int(m.group(1))})
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})", s)
    if m:
        y, mo, d, h, mi = map(int, m.groups())
        return dt.datetime(y, mo, d, h, mi, tzinfo=now.tzinfo)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if m:
        t = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        return t if t > now else t + dt.timedelta(days=1)
    raise ValueError("give the time as 2026-11-22 09:00, 09:00 or +2h")


def cmd_schedule(a):
    if a.list or not a.id:
        c = db()
        out = []
        for x in sorted(sched_read(), key=lambda x: x["at"]):
            folder, uid = parse_id(x["id"])
            r = c.execute("select subject, to_ from msgs where folder=? and uid=? order by uidv desc limit 1",
                          (folder, uid)).fetchone()
            out.append({"id": x["id"], "at": local_time(x["at"]), "subject": r["subject"] if r else "",
                        "to": r["to_"] if r else "", "error": x.get("error")})
        if a.json:
            print(json.dumps(out, ensure_ascii=False, indent=1))
        else:
            for x in out:
                print("%s  %-12s %s%s" % (x["at"], x["id"], x["subject"], "  FAILED: " + x["error"] if x["error"] else ""))
            print("(nothing scheduled)" if not out else "")
        return
    drafts_only(a.id, "schedule")
    if a.cancel:
        with file_lock("sched", True):      # the app changes the list too (ragdoll_app.sched_edit)
            items = sched_read()
            keep = [x for x in items if x["id"] != a.id]
            if len(keep) == len(items):
                die("%s is not scheduled" % a.id)
            if any(isinstance(x.get("sending"), dict) and pid_running(x["sending"].get("pid"))
                   for x in items if x["id"] == a.id):
                die("%s is going out right now" % a.id)
            sched_write(keep)
        print(json.dumps({"id": a.id, "scheduled": False}))
        return
    if not a.yes:
        die("schedule needs --yes, given only after the owner approved this exact draft")
    try:
        when = parse_when(a.at)
    except ValueError as e:
        die(str(e))
    at = int(when.timestamp())
    if at < time.time() - 60:
        die("that time has already passed")
    if at > time.time() + 5 * 366 * 86400:
        die("pick a time within the next five years")
    with file_lock("sched", True):
        items = [x for x in sched_read() if x["id"] != a.id] + [{"id": a.id, "at": at}]
        sched_write(items)
    print(json.dumps({"id": a.id, "at": local_time(at), "app_running": app_running(),
                      "note": "Ragdoll Mail sends it at that time while the app is open; if the app is "
                              "closed then, it goes out when the app next starts."}, ensure_ascii=False, indent=1))



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
    p = sp.add_parser("open", help="show a mail or draft in the Ragdoll Mail app (starts it when closed)")
    p.add_argument("id")
    p.set_defaults(fn=cmd_open)
    p = sp.add_parser("schedule", help="send a draft later (the app sends it); --list shows what is waiting")
    p.add_argument("id", nargs="?")
    p.add_argument("--at", help="2026-11-22 09:00, 09:00 (the next one) or +2h")
    p.add_argument("--cancel", action="store_true", help="keep it as a draft and do not send it")
    p.add_argument("--list", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_schedule)
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
