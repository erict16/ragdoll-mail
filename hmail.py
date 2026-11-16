#!/usr/bin/env python3
"""hmail: a mail CLI for one IMAP/SMTP mailbox, built for an AI agent and its owner.

Some servers (Tencent Exmail among them) ignore IMAP text search and return
every mail, so hmail keeps a local SQLite index and searches that. The index
is filled in two passes: headers and attachment names for every mail first
(fast), then the start of each body, newest first.

  status                                    index size, bodies still missing, last sync
  sync [--bodies] [--workers N] [--all-folders]
                                            new mail, flags, deletions; --bodies keeps
                                            going until every body is indexed
  search <words> [--folder F] [--from X] [--to X] [--since D] [--until D]
         [--unread] [--att] [--limit N] [--json]
                                            all words must match subject, sender,
                                            recipients, attachment names or body
  list [--folder F] [--unread] [--since D] [--limit N] [--json]
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

Ids look like inbox:9255, sent:1420, drafts:3 (folder short name and IMAP UID).
Dates are YYYY-MM-DD in the configured time zone.

Config: ~/.config/hmail/config.json (or $HMAIL_CONFIG); see config.example.json.
The password is read from the environment variable named by "password_env"
(on Windows also from that user variable in the registry). hmail never prints it.
"""
import argparse, base64, contextlib, datetime as dt, email, email.header, html as htmlmod, imaplib
import json, mimetypes, os, re, smtplib, sqlite3, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parsedate_to_datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULTS = {
    "user": "",
    "name": "",
    "imap": {"host": "", "port": 993},
    "smtp": {"host": "", "port": 465},
    "password_env": "HMAIL_PASSWORD",
    "folders": {"inbox": "INBOX", "sent": "Sent Messages", "drafts": "Drafts",
                "trash": "Deleted Messages", "junk": "Junk"},
    "sync_folders": ["INBOX", "Sent Messages", "Drafts"],
    "data_dir": "~/.local/share/hmail",
    "utc_offset_hours": 8,
    "signature": "",
    "signature_marks": [],
    "require_cc": [],
    "body_bytes": 30000,
    "body_chars": 20000,
}
QUOTE_MARKS = ("发件人", "From:", "原始邮件", "wrote:", "Từ:")
QUOTE_RE = re.compile(
    r"^\s*(-{3,}\s*(原始邮件|Original Message|Forwarded message)|发件人[:：]|From:\s|Từ:\s|"
    r"On .{5,120} wrote:|在 .{5,80}写道[:：])", re.M | re.I)
PREFIX_RE = re.compile(r"^\s*((re|fw|fwd|aw|wg|tr|trả lời|chuyển tiếp|bls|回复|答复|转发)\s*[:：]\s*)+", re.I)
INLINE_ID = re.compile(r"^[0-9A-Fa-f]{8}@[0-9A-Fa-f.]+$")   # Exmail inline-image names
WEEK = "一二三四五六日"
# No line-length limit when writing: folding long Message-IDs makes Python encode them as
# =?utf-8?q?...?=, which breaks threading (sent:1431, 16th Nov 2026).
OUT_POLICY = policy.SMTP.clone(max_line_length=None)


# ------------------------------------------------------------------ config

class Cfg:
    def __init__(self, d):
        self.d = d

    def __getattr__(self, k):
        return self.d[k]

    @property
    def tz(self):
        return dt.timezone(dt.timedelta(hours=self.d["utc_offset_hours"]))

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


def load_config(path=None):
    path = path or os.environ.get("HMAIL_CONFIG") or os.path.expanduser("~/.config/hmail/config.json")
    d = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                d[k].update(v)
            else:
                d[k] = v
    return Cfg(d)


CFG = load_config()


def die(msg):
    sys.exit(msg)


def password():
    name = CFG.password_env
    p = os.environ.get(name)
    if not p and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                p = winreg.QueryValueEx(k, name)[0]
        except OSError:
            pass
    if not p:
        die("%s is not set. The mailbox owner sets it himself; never type it for him." % name)
    return p


def need_account():
    if not (CFG.user and CFG.imap["host"]):
        die("no account configured: copy config.example.json to ~/.config/hmail/config.json")


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
    m = imaplib.IMAP4_SSL(CFG.imap["host"], CFG.imap["port"])
    m.login(CFG.user, password())
    return m


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
    typ, data = m.select(q(folder), readonly=readonly)
    if typ != "OK":
        raise LookupError("cannot open folder %s: %s" % (folder, data))
    return int(m.response("UIDVALIDITY")[1][0])


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


def fetch_raw(m, folder, uid):
    select(m, folder)
    typ, data = m.uid("FETCH", str(uid), "(BODY.PEEK[])")
    for item in data:
        if isinstance(item, tuple):
            return item[1]
    die("no mail %s (moved or deleted? run search again)" % make_id(folder, uid))


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


def hdr(msg, name):
    try:
        v = msg.get(name)
        return str(v) if v is not None else ""
    except Exception:
        return ""


def addrs(value):
    return [(n, a.lower()) for n, a in getaddresses([value or ""]) if a and "@" in a]


def fmt_addrs(lst):
    return ", ".join(formataddr((n, a)) if n else a for n, a in lst)


def html_to_text(h):
    h = re.sub(r"(?is)<(style|script|head)\b.*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>|</blockquote>", "\n", h)
    h = re.sub(r"(?i)</t[dh]>", "\t", h)
    h = htmlmod.unescape(re.sub(r"<[^>]+>", "", h))
    h = re.sub(r"[ \t ​]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n\n", h).strip()


def part_text(p):
    try:
        return p.get_content()
    except Exception:
        payload = p.get_payload(decode=True) or b""
        return payload.decode(p.get_content_charset() or "utf-8", "ignore")


def bodies(msg):
    """(plain, html) of the main body."""
    plain = html = ""
    for p in msg.walk():
        if p.is_multipart() or p.get_content_disposition() == "attachment":
            continue
        ct = p.get_content_type()
        if ct == "text/plain" and not plain:
            plain = part_text(p)
        elif ct == "text/html" and not html:
            html = part_text(p)
    return plain, html


def body_text(msg):
    plain, html = bodies(msg)
    return plain.strip() or html_to_text(html)


def new_text(text):
    mo = QUOTE_RE.search(text or "")
    return (text[:mo.start()] if mo else text or "").strip()


def is_inline(p):
    return bool(p.get("Content-ID")) and p.get_content_disposition() != "attachment"


def attachments(msg, inline=False):
    out = []
    for p in msg.walk():
        if p.is_multipart():
            continue
        if (p.get_content_disposition() == "attachment" or p.get_filename()) and (inline or not is_inline(p)):
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
    s = s or ""
    while True:
        t = PREFIX_RE.sub("", s).strip()
        if t == s:
            return re.sub(r"\s+", " ", t).lower()
        s = t


def make_id(folder, uid):
    return "%s:%d" % (CFG.short(folder), uid)


def parse_id(i):
    if ":" not in i:
        die("id must look like inbox:9255 or drafts:3, got %r" % i)
    f, uid = i.rsplit(":", 1)
    return CFG.folder(f), int(uid)


def local_time(ts):
    return dt.datetime.fromtimestamp(ts, CFG.tz).strftime("%Y-%m-%d %H:%M")


def day_start(s, add_days=0):
    return int((dt.datetime.fromisoformat(s) + dt.timedelta(days=add_days)).replace(tzinfo=CFG.tz).timestamp())


# ------------------------------------------------------------------ index

SCHEMA = """
create table if not exists msgs(id integer primary key, folder text, uidv integer, uid integer,
  msgid text, irt text, refs text, ts integer, frm text, to_ text, cc text, subject text,
  atts text, body text, seen int, flagged int, answered int, size int default 0,
  has_body int default 0, unique(folder, uidv, uid));
create index if not exists msgs_ts on msgs(ts);
create index if not exists msgs_msgid on msgs(msgid);
create index if not exists msgs_irt on msgs(irt);
create virtual table if not exists fts using fts5(subject, frm, to_, atts, body, tokenize='trigram');
create table if not exists state(folder text primary key, uidv integer);
create table if not exists meta(k text primary key, v text);
"""


def db():
    os.makedirs(CFG.home, exist_ok=True)
    c = sqlite3.connect(os.path.join(CFG.home, "index.db"), timeout=600, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("pragma journal_mode=wal")
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("pragma table_info(msgs)")}
    if "has_body" not in cols:     # index made by the first version: every row had its body
        c.execute("alter table msgs add column size int default 0")
        c.execute("alter table msgs add column has_body int default 0")
        c.execute("update msgs set has_body=1")
        c.commit()
    return c


@contextlib.contextmanager
def file_lock(name, wait):
    """Process lock in the data dir. Yields False when busy and wait is False."""
    os.makedirs(CFG.home, exist_ok=True)
    f = open(os.path.join(CFG.home, name + ".lock"), "a+")
    got = False
    try:
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if not wait:
                    break
                time.sleep(1)
        yield got
    finally:
        if got:
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
        f.close()


def bs_names(blob):
    """Attachment names from a BODYSTRUCTURE blob (quoted strings or literals)."""
    names = []
    for mo in re.finditer(rb'"(?:FILENAME|NAME|filename|name)\*?" (?:"((?:[^"\\]|\\.)*)"|\{(\d+)\}\r?\n?)', blob):
        if mo.group(1) is not None:
            raw = mo.group(1)
        else:
            n = int(mo.group(2))
            raw = blob[mo.end():mo.end() + n]
        try:
            s = str(email.header.make_header(email.header.decode_header(raw.decode("utf-8", "ignore"))))
        except Exception:
            s = raw.decode("utf-8", "ignore")
        if s.lower().startswith("utf-8''"):
            from urllib.parse import unquote
            s = unquote(s[7:])
        if not s or INLINE_ID.match(s) or s in names:
            continue
        names.append(s)
    return names


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
            "refs": hdr(msg, "References"), "ts": ts, "frm": hdr(msg, "From"), "to_": hdr(msg, "To"),
            "cc": hdr(msg, "Cc"), "subject": hdr(msg, "Subject"), "atts": " | ".join(bs_names(bs)),
            "size": int(size.group(1)) if size else 0, "flags": flags_of(blob)}


def sync_headers(m, c, folder, full_flags=False, workers=1):
    """New mail headers, flags and deletions for one folder. Returns new row count."""
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
        typ, data = m.uid("FETCH", ",".join(map(str, check[i:i + 500])), "(UID FLAGS)")
        for seg in segments(data):
            uid = seg_uid(seg)
            if uid in local:
                c.execute("update msgs set seen=?, flagged=?, answered=? where id=?",
                          (*flags_of(b"".join(seg)), local[uid]))
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
            if uid is None:
                continue
            h = header_row(seg)
            cur = c.execute(
                "insert or ignore into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,"
                "seen,flagged,answered,size,has_body) values(?,?,?,?,?,?,?,?,?,?,?,?,'',?,?,?,?,0)",
                (folder, uidv, uid, h["msgid"], h["irt"], h["refs"], h["ts"], h["frm"], h["to_"], h["cc"],
                 h["subject"], h["atts"], *h["flags"], h["size"]))
            if cur.rowcount:
                c.execute("insert into fts(rowid,subject,frm,to_,atts,body) values(?,?,?,?,?,'')",
                          (cur.lastrowid, h["subject"], h["frm"], h["to_"] + " " + h["cc"], h["atts"]))
        c.commit()
        done += len(segs)
        print("  %s headers: %d/%d" % (folder, done, len(new)), file=sys.stderr)
    if ex:
        ex.shutdown()
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
        text = body_text(to_msg(raw))[:CFG.body_chars] if raw else ""
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


def quick_sync():
    """Run before every read command: new mail only, never waits for a long sync."""
    c = db()
    with file_lock("headers", wait=False) as got:
        if not got:
            print("(another hmail is syncing; showing the index as it is)", file=sys.stderr)
            return c
        with session() as m:
            for f in CFG.sync_folders:
                sync_headers(m, c, f)
        c.execute("insert or replace into meta values('last_sync', ?)", (str(int(time.time())),))
        c.commit()
    with file_lock("bodies", wait=False) as got:
        if got:
            sync_bodies(c, CFG.sync_folders, limit=40, workers=1, quiet=True)
    return c


# ------------------------------------------------------------------ output

def row_out(r, snippet=True):
    d = {"id": make_id(r["folder"], r["uid"]), "date": local_time(r["ts"]), "from": r["frm"],
         "to": r["to_"], "cc": r["cc"], "subject": r["subject"],
         "attachments": [x for x in (r["atts"] or "").split(" | ") if x],
         "unread": not r["seen"], "answered": bool(r["answered"]), "body_indexed": bool(r["has_body"])}
    if snippet:
        d["snippet"] = re.sub(r"\s+", " ", new_text(r["body"] or ""))[:200]
    return d


def print_rows(rows, as_json, empty="(nothing found)"):
    if as_json:
        print(json.dumps([row_out(r) for r in rows], ensure_ascii=False, indent=1))
        return
    for r in rows:
        f = addrs(r["frm"])
        who = (f[0][0] or f[0][1]) if f else ""
        print("%-14s %s %s %-20s %s%s" % (make_id(r["folder"], r["uid"]), local_time(r["ts"]),
                                          "*" if not r["seen"] else " ", who[:20], r["subject"],
                                          "  [%s]" % r["atts"] if r["atts"] else ""))
    if not rows:
        print(empty)


def add_filters(a, where, params):
    if getattr(a, "folder", None):
        where.append("m.folder=?")
        params.append(CFG.folder(a.folder))
    if getattr(a, "from_", None):
        where.append("m.frm like ?")
        params.append("%" + a.from_ + "%")
    if getattr(a, "to", None):
        where.append("(m.to_ like ? or m.cc like ?)")
        params += ["%" + a.to + "%"] * 2
    if getattr(a, "since", None):
        where.append("m.ts>=?")
        params.append(day_start(a.since))
    if getattr(a, "until", None):
        where.append("m.ts<?")
        params.append(day_start(a.until, 1))
    if getattr(a, "unread", False):
        where.append("m.seen=0")
    if getattr(a, "att", False):
        where.append("m.atts!=''")


def search_rows(c, words, a):
    where, params = [], []
    long_terms = []
    for t in words:
        if len(t) >= 3:
            long_terms.append('"%s"' % t.replace('"', '""'))
        else:
            where.append("(m.subject like ? or m.frm like ? or m.to_ like ? or m.cc like ? "
                         "or m.atts like ? or m.body like ?)")
            params += ["%" + t + "%"] * 6
    if long_terms:
        where.insert(0, "m.id in (select rowid from fts where fts match ?)")
        params.insert(0, " AND ".join(long_terms))
    add_filters(a, where, params)
    sql = "select m.* from msgs m %s order by m.ts desc limit ?" % (("where " + " and ".join(where)) if where else "")
    return c.execute(sql, params + [a.limit]).fetchall()


# ------------------------------------------------------------------ read commands

def cmd_status(a):
    c = db()
    total = c.execute("select count(*) from msgs").fetchone()[0]
    missing = c.execute("select count(*) from msgs where has_body=0").fetchone()[0]
    last = c.execute("select v from meta where k='last_sync'").fetchone()
    per = c.execute("select folder, count(*) n from msgs group by folder").fetchall()
    d = {"mails": total, "bodies_missing": missing, "last_sync": local_time(int(last[0])) if last else None,
         "folders": {r["folder"]: r["n"] for r in per}, "index": os.path.join(CFG.home, "index.db")}
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
    c = db() if a.no_sync else quick_sync()
    print_rows(search_rows(c, a.words, a), a.json)
    if not a.json:
        missing = c.execute("select count(*) from msgs where has_body=0").fetchone()[0]
        if missing:
            print("(%d older mails are searchable by subject, people and attachment names only; "
                  "their bodies are still being indexed)" % missing, file=sys.stderr)


def cmd_list(a):
    c = db() if a.no_sync else quick_sync()
    a.folder = a.folder or "inbox"
    where, params = [], []
    add_filters(a, where, params)
    sql = "select m.* from msgs m where %s order by m.ts desc limit ?" % " and ".join(where)
    print_rows(c.execute(sql, params + [a.limit]).fetchall(), a.json)


def thread_rows(c, row):
    ids = {row["msgid"]} | set(re.findall(r"<[^>]+>", (row["refs"] or "") + " " + (row["irt"] or "")))
    ids.discard("")
    seen = {}
    for _ in range(6):
        marks = ",".join("?" * len(ids)) or "''"
        rows = c.execute("select * from msgs where msgid in (%s) or irt in (%s)" % (marks, marks),
                         list(ids) * 2).fetchall()
        like = c.execute("select * from msgs where " + " or ".join(["refs like ?"] * len(ids)),
                         ["%" + i + "%" for i in ids]).fetchall() if ids else []
        grew = False
        for r in rows + like:
            if r["id"] not in seen:
                seen[r["id"]] = r
                for x in [r["msgid"]] + re.findall(r"<[^>]+>", (r["refs"] or "") + " " + (r["irt"] or "")):
                    if x and x not in ids:
                        ids.add(x)
                        grew = True
        if not grew:
            break
    # same bare subject within 180 days catches clients that drop References
    bs = bare_subject(row["subject"])
    if bs:
        for r in c.execute("select * from msgs where ts between ? and ?",
                           (row["ts"] - 180 * 86400, row["ts"] + 180 * 86400)).fetchall():
            if r["id"] not in seen and bare_subject(r["subject"]) == bs:
                seen[r["id"]] = r
    seen[row["id"]] = row
    return sorted(seen.values(), key=lambda r: r["ts"])


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
    with session() as m:
        raw = fetch_raw(m, folder, uid)
    msg = to_msg(raw)
    plain, html = bodies(msg)
    text = plain.strip() or html_to_text(html)
    atts = [{"name": p.get_filename() or "(no name)", "kb": len(p.get_payload(decode=True) or b"") // 1024,
             "inline": is_inline(p)} for p in attachments(msg, inline=True)]
    atts = [x for x in atts if not (x["inline"] and INLINE_ID.match(x["name"]))]
    if a.html:
        open(a.html, "w", encoding="utf-8").write(html or "<pre>%s</pre>" % htmlmod.escape(plain))
    if a.eml:
        open(a.eml, "wb").write(raw)
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


def safe_name(n):
    return re.sub(r'[\\/:*?"<>|\r\n]', "_", n).strip() or "attachment"


def cmd_attach(a):
    folder, uid = parse_id(a.id)
    with session() as m:
        raw = fetch_raw(m, folder, uid)
    out = os.path.expanduser(a.out or ".")
    os.makedirs(out, exist_ok=True)
    n = 0
    for p in attachments(to_msg(raw), inline=a.inline):
        name = p.get_filename() or "attachment"
        if a.name and a.name.lower() not in name.lower():
            continue
        path = os.path.join(out, safe_name(name))
        with open(path, "wb") as f:
            f.write(p.get_payload(decode=True) or b"")
        print("saved %s (%d KB)" % (os.path.abspath(path), os.path.getsize(path) // 1024))
        n += 1
    if not n:
        die("no attachment matched")


# ------------------------------------------------------------------ drafts

def split_list(s):
    return [x.strip() for x in (s or "").replace(";", ",").split(",") if x.strip()]


def quote_block(orig):
    plain, html = bodies(orig)
    if not html:
        html = '<div style="white-space:pre-wrap">%s</div>' % htmlmod.escape(plain)
    html = re.sub(r"(?is)^.*?<body[^>]*>|</body>.*$", "", html)
    try:
        t = parsedate_to_datetime(hdr(orig, "Date")).astimezone(CFG.tz)
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
    return clean_recipients(to + [("", x.lower()) for x in extra_to],
                            cc + [("", x.lower()) for x in extra_cc], {user, *(x.lower() for x in remove)})


def clean_recipients(to, cc, drop):
    seen, out_to, out_cc = set(), [], []
    for lst, out in ((to, out_to), (cc, out_cc)):
        for n, ad in lst:
            ad = ad.lower()
            if ad in drop or ad in seen:
                continue
            seen.add(ad)
            out.append((n, ad))
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
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(CFG.user.split("@")[-1] or None))
    if high:
        msg["X-Priority"] = "1"
        msg["Importance"] = "High"
    if mode == "reply" and orig is not None:
        mid = hdr(orig, "Message-ID").strip()
        if mid:
            msg["In-Reply-To"] = mid
            msg["References"] = (hdr(orig, "References") + " " + mid).strip()
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
            if cid in used and cid not in done:
                mt, st = p.get_content_type().split("/", 1)
                hpart.add_related(p.get_payload(decode=True) or b"", mt, st, cid="<%s>" % cid,
                                  filename=p.get_filename())
                done.add(cid)
        if mode == "forward":
            for p in attachments(orig):
                mt, st = p.get_content_type().split("/", 1)
                msg.add_attachment(p.get_payload(decode=True) or b"", mt, st, filename=p.get_filename())
    for f in attach:
        ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
        mt, st = ctype.split("/", 1)
        with open(f, "rb") as fh:
            msg.add_attachment(fh.read(), mt, st, filename=os.path.basename(f))
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
    select(m, folder, readonly=False)
    m.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)")
    m.expunge()


def cmd_draft(a):
    if not (a.body or a.text):
        die("give --body FILE.html or --text")
    for f in a.attach or []:
        if not os.path.isfile(f):
            die("attachment not found: %s" % f)
    body = open(a.body, encoding="utf-8").read() if a.body else text_to_html(a.text)
    sig = ""
    if not a.no_sig and CFG.signature:
        with open(os.path.expanduser(CFG.signature), encoding="utf-8") as f:
            sig = f.read()
    with session() as m:
        orig, mode = None, None
        src = a.reply or a.forward
        if src:
            folder, uid = parse_id(src)
            orig = to_msg(fetch_raw(m, folder, uid))
            mode = "reply" if a.reply else "forward"
        drop = {CFG.user, *(x.lower() for x in split_list(a.remove))}
        if mode == "reply":
            to, cc = reply_recipients(orig, a.all, CFG.user, split_list(a.to), split_list(a.cc),
                                      split_list(a.remove))
            subject = a.subject or reply_subject(hdr(orig, "Subject"))
        else:
            to, cc = clean_recipients([("", x.lower()) for x in split_list(a.to)],
                                      [("", x.lower()) for x in split_list(a.cc)], drop)
            subject = a.subject or (forward_subject(hdr(orig, "Subject")) if mode == "forward" else "")
        if not subject:
            die("give --subject")
        msg = build_message(body, to, cc, subject, orig, mode, split_list(a.bcc), a.attach or [], sig, a.high)
        new_uid = append_draft(m, msg.as_bytes(policy=OUT_POLICY))
        if a.replace:
            f2, u2 = parse_id(a.replace)
            delete_uid(m, f2, u2)
    os.makedirs(os.path.join(CFG.home, "drafts"), exist_ok=True)
    preview = os.path.join(CFG.home, "drafts", "%d.html" % new_uid)
    with open(preview, "w", encoding="utf-8") as f:
        f.write(msg.get_body(("html",)).get_content())
    print(json.dumps({"id": "%s:%d" % (CFG.short(CFG.folders["drafts"]), new_uid), "to": msg.get("To", ""),
                      "cc": msg.get("Cc", ""), "subject": subject,
                      "attachments": [p.get_filename() for p in attachments(msg)],
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
    tables = re.findall(r"<table\b[^>]*>", new, re.I)
    if any("word-break:normal" not in t.replace(" ", "") for t in tables):
        problems.append("a table does not reset word-break:normal, so cells can split letter by letter")
    for t, body in re.findall(r"(<table\b[^>]*>)(.*?)</tr>", new, re.I | re.S):
        first = re.sub(r"<colgroup.*?</colgroup>", "", body, flags=re.I | re.S)
        ncols = sum(int(s or 1) for s in re.findall(r"<t[dh]\b(?:[^>]*colspan=\"?(\d+))?[^>]*>", first, re.I))
        if ncols >= 3 and not re.search(r"(?<![-\w])width:\d+px", t.replace(" ", "")):
            problems.append("a %d-column table has no fixed pixel width" % ncols)
            break
    cells = [re.sub(r"<[^>]+>|&nbsp;|\s", "", c).lower()
             for attrs, c in re.findall(r"<td\b([^>]*)>(.*?)</td>", new, re.I | re.S) if "colspan" not in attrs]
    blanks = sum(c in ("", "-", "—", "–", "tbc", "?") for c in cells) + new.count("TBC")
    if tables and blanks and not blanks_ok:
        problems.append("%d blank/—/TBC value(s) in the table; say which rows miss what, then use --blanks-ok"
                        % blanks)
    return problems


def check_message(msg, reply, blanks_ok=False, required_cc=True):
    plain, html = bodies(msg)
    text = html or plain
    problems = []
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
        problems.append("the sender himself is a recipient")
    if required_cc:
        for x in CFG.require_cc:
            if x.lower() not in everyone:
                problems.append("%s is not in To or Cc" % x)
    problems += table_problems(html, sig_at if marks else -1, blanks_ok)
    return problems


def cmd_check(a):
    folder, uid = parse_id(a.id)
    with session() as m:
        raw = fetch_raw(m, folder, uid)
    msg = to_msg(raw)
    problems = check_message(msg, a.reply, a.blanks_ok, not a.no_required_cc)
    d = {"to": hdr(msg, "To"), "cc": hdr(msg, "Cc"), "subject": hdr(msg, "Subject"),
         "attachments": [{"name": p.get_filename(), "kb": len(p.get_payload(decode=True) or b"") // 1024}
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
    return mid.encode() in blob


def cmd_send(a):
    if not a.yes:
        die("send needs --yes, given only after the owner approved this exact draft")
    folder, uid = parse_id(a.id)
    if folder != CFG.folders["drafts"]:
        die("send only sends drafts (drafts:UID)")
    with session() as m:
        raw = fetch_raw(m, folder, uid)
        msg = to_msg(raw)
        rcpts = [x for _, x in addrs(hdr(msg, "To")) + addrs(hdr(msg, "Cc")) + addrs(hdr(msg, "Bcc"))]
        if not rcpts:
            die("the draft has no recipients")
        del msg["Bcc"]
        out = msg.as_bytes(policy=OUT_POLICY)
        s = smtplib.SMTP_SSL(CFG.smtp["host"], CFG.smtp["port"], timeout=120)
        try:
            s.login(CFG.user, password())
            refused = s.sendmail(CFG.user, rcpts, out)
        finally:
            try:
                s.quit()
            except Exception:
                pass
        mid = hdr(msg, "Message-ID").strip()
        sent = CFG.folders["sent"]
        saved = False
        for _ in range(3):          # some servers file SMTP mail in Sent by themselves
            time.sleep(3)
            if in_folder(m, sent, mid):
                saved = True
                break
        if not saved:
            m.append(q(sent), "(\\Seen)", imaplib.Time2Internaldate(time.time()), out)
        delete_uid(m, folder, uid)
        irt = hdr(msg, "In-Reply-To").strip()
        if irt:
            r = db().execute("select folder, uid from msgs where msgid=? order by ts desc limit 1", (irt,)).fetchone()
            if r:
                try:
                    select(m, r["folder"], readonly=False)
                    m.uid("STORE", str(r["uid"]), "+FLAGS", "(\\Answered)")
                except Exception:
                    pass
    print(json.dumps({"sent": True, "to": hdr(msg, "To"), "cc": hdr(msg, "Cc"), "subject": hdr(msg, "Subject"),
                      "refused": refused, "attachments": [p.get_filename() for p in attachments(msg)],
                      "copy_in_sent": "server" if saved else "added by hmail"}, ensure_ascii=False, indent=1))


def move_uids(m, folder, uids, dest):
    """Move UIDs within the mailbox (MOVE when the server has it, else COPY + delete)."""
    select(m, folder, readonly=False)
    caps = " ".join(x.decode() if isinstance(x, bytes) else x for x in m.capabilities).upper()
    moved = 0
    for i in range(0, len(uids), 200):
        batch = ",".join(map(str, uids[i:i + 200]))
        if "MOVE" in caps.split():
            typ, data = m.uid("MOVE", batch, q(dest))
        else:
            typ, data = m.uid("COPY", batch, q(dest))
            if typ == "OK":
                m.uid("STORE", batch, "+FLAGS.SILENT", "(\\Deleted)")
                if "UIDPLUS" in caps.split():
                    m.uid("EXPUNGE", batch)
                else:
                    m.expunge()
        if typ != "OK":
            die("the server refused the move after %d mails: %s" % (moved, data))
        moved += len(uids[i:i + 200])
    return moved


def cmd_trash(a):
    """Move mails to the trash folder (recoverable from there)."""
    ids = list(a.ids)
    if a.from_file:
        with open(a.from_file, encoding="utf-8") as f:
            ids += [x.strip() for x in f if x.strip()]
    if not ids:
        die("no ids given")
    by_folder = {}
    for i in ids:
        f, u = parse_id(i)
        by_folder.setdefault(f, []).append(u)
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
    c = db()
    for f, uids in by_folder.items():
        for u in uids:
            r = c.execute("select id from msgs where folder=? and uid=?", (f, u)).fetchone()
            if r:
                c.execute("delete from msgs where id=?", (r["id"],))
                c.execute("delete from fts where rowid=?", (r["id"],))
    c.commit()
    print("moved %d mails to %s" % (total, CFG.folders["trash"]))


def cmd_delete_draft(a):
    if not a.yes:
        die("delete-draft needs --yes")
    folder, uid = parse_id(a.id)
    if folder != CFG.folders["drafts"]:
        die("only drafts can be deleted with this command")
    with session() as m:
        delete_uid(m, folder, uid)
    print("deleted %s" % a.id)


# ------------------------------------------------------------------ main

def parser():
    ap = argparse.ArgumentParser(prog="hmail", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status").set_defaults(fn=cmd_status)
    p = sp.add_parser("sync")
    p.add_argument("--bodies", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--all-folders", action="store_true")
    p.set_defaults(fn=cmd_sync)
    for name, fn in (("search", cmd_search), ("list", cmd_list)):
        p = sp.add_parser(name)
        if name == "search":
            p.add_argument("words", nargs="+")
            p.add_argument("--from", dest="from_")
            p.add_argument("--to")
            p.add_argument("--until")
            p.add_argument("--att", action="store_true")
        p.add_argument("--folder")
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
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_check)
    p = sp.add_parser("send")
    p.add_argument("id")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_send)
    p = sp.add_parser("trash")
    p.add_argument("ids", nargs="*")
    p.add_argument("--from-file", help="one id per line")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_trash)
    p = sp.add_parser("delete-draft")
    p.add_argument("id")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_delete_draft)
    return ap


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        a.fn(a)
    except imaplib.IMAP4.error as e:
        die("mail server refused: %s" % e)
    except LookupError as e:
        die(str(e))


if __name__ == "__main__":
    main()
