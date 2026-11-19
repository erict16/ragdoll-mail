"""Folders: the ones the mail server has, which of them the app follows, and their names."""

import json
import re
import sqlite3

import ragdoll as R
from .common import fail


FOLDER_NAMES = {
    "sent": ("sent messages", "sent", "sent items", "sent mail", "[gmail]/sent mail", "已发送", "已发送邮件"),
    "drafts": ("drafts", "draft", "[gmail]/drafts", "草稿箱", "草稿"),
    "trash": ("deleted messages", "trash", "deleted items", "deleted", "[gmail]/trash", "已删除", "已删除邮件"),
    "junk": ("junk", "spam", "junk e-mail", "junk email", "[gmail]/spam", "垃圾邮件", "垃圾箱"),
    "archive": ("archive", "archives", "归档"),
}


def list_folders(m):
    """[(name, lowercased flags)] from LIST."""
    return [(n, fl) for n, fl, _ in list_folders_full(m)]


def list_folders_full(m):
    """[(name, lowercased flags, hierarchy delimiter)] from LIST."""
    typ, data = m.list()
    out = []
    for line in data or []:
        if isinstance(line, tuple):
            line = re.sub(rb"\{\d+\}$", b"", line[0]) + b'"' + line[1].replace(b"\\", b"\\\\").replace(b'"', b'\\"') + b'"'
        if not line:
            continue
        mo = re.match(rb'\(([^)]*)\)\s+("(?:[^"\\]|\\.)*"|NIL)\s+(.+)$', line)
        if not mo:
            continue
        delim = "" if mo.group(2) == b"NIL" else re.sub(rb"\\(.)", rb"\1", mo.group(2)[1:-1]).decode("utf-8", "replace")
        name = mo.group(3).strip()
        if name.startswith(b'"') and name.endswith(b'"'):
            name = re.sub(rb"\\(.)", rb"\1", name[1:-1])
        out.append((R.mutf7_decode(name.decode("utf-8", "replace")), mo.group(1).decode().lower(), delim))
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


class Folders:
    """Which folders there are. (Part of Backend.)"""

    # ---- sync

    def sync_folders(self):
        fs = list(R.CFG.sync_folders)
        names = {n for n, _ in self.listed}
        for k in ("archive", "trash", "junk"):
            f = R.CFG.folders.get(k)
            if f and f not in fs and (k != "junk" or f in names):
                fs.append(f)
        return fs + [n for n, _ in self.extra_folders() if n not in fs]

    def load_listed(self):
        try:
            r = self.q("select v from meta where k='server_folders'")
            return [(str(n), str(d)) for n, d in json.loads(r[0]["v"])] if r else []
        except (ValueError, TypeError, sqlite3.Error):
            return []

    def note_folders(self, m, c):
        """Keep the list of the server's folders, so the user's own folders show in the sidebar."""
        found = list_folders_full(m)
        self.server_folders = [n for n, _, _ in found]
        skip = {"\\noselect", "\\nonexistent", "\\all", "\\flagged", "\\important"}
        listed = [(n, d) for n, fl, d in found if not skip & set(fl.split())]
        if listed != self.listed:
            self.listed = listed
            c.execute("insert or replace into meta values('server_folders', ?)", (json.dumps(listed, ensure_ascii=False),))
            c.commit()
            self.bump()

    def extra_folders(self):
        """The user's own folders: on the server, and not one of the app's fixed ones. [(name, delimiter)]"""
        fixed = {v for v in R.CFG.folders.values() if v} | set(R.CFG.sync_folders)
        return sorted(((n, d) for n, d in self.listed if n not in fixed and n.upper() != "INBOX"),
                      key=lambda x: x[0].lower())

    def folder_of(self, key):
        """The server folder behind a list key: 'inbox', 'trash', … or 'f:<name>' for one of the user's own."""
        if isinstance(key, str) and key.startswith("f:"):
            if key[2:] not in {n for n, _ in self.extra_folders()}:
                fail("There is no folder %s." % key[2:])
            return key[2:]
        return R.CFG.folders.get(key)

    def folders(self, m):
        if self.server_folders is None:
            self.server_folders = [n for n, _ in list_folders(m)]
        return self.server_folders
