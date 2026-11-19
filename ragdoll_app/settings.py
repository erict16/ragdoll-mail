"""The account: showing, testing and saving its settings, and the first-run setup."""

import contextlib
import imaplib
import json
import os
import re
import smtplib

import ragdoll as R
from .common import config_path, fail, friendly, int_in, people_in, text_in
from .folders import detect_folders, list_folders


FOLDER_KEYS = ("inbox", "drafts", "sent", "archive", "trash", "junk")


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


class Settings:
    """Account settings and setup. (Part of Backend.)"""

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
            self.listed = self.load_listed()
        self.drop()
        self.server_folders = None
        self.contacts = (0, {})
        self.note_mark = None                   # maybe another mailbox: mark it afresh
        self.sync["error"] = None
        self.start_sync()
        self.bump()
        return self.api_boot({})
