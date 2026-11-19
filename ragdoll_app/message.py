"""From a raw mail to what the page shows (safe HTML, inline pictures, file list) and what the index stores."""

import base64
import html as htmlmod
import mimetypes
import re
import urllib.parse
import urllib.request
from email.utils import make_msgid

import ragdoll as R


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
        if len(data) <= 8 * 1024 * 1024:
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
