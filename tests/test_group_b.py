"""Offline tests of sending, drafts, scheduled send, the MIME build and files on disk (0.11 group B)."""
import email, imaplib, os, re, shutil, smtplib, sys, tempfile, threading, time, unittest
from email import policy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll as R  # noqa: E402
import ragdoll_app as A  # noqa: E402


def own_cfg(test, **kw):
    """A config of the test's own, in a temp data dir; the old one comes back after the test."""
    old = R.CFG
    home = tempfile.mkdtemp(prefix="ragdoll-b-")
    d = dict(R.DEFAULTS, user="me@example.com", name="Me", utc_offset_hours=8, data_dir=home)
    d.update(kw)
    R.CFG = R.Cfg(d)
    test.addCleanup(shutil.rmtree, home, True)
    test.addCleanup(setattr, R, "CFG", old)
    return home


def msg_of(raw):
    return email.message_from_bytes(raw, policy=policy.default)


class QuoteHeader(unittest.TestCase):
    def setUp(self):
        own_cfg(self)

    def test_addresses_in_the_quote_are_escaped(self):
        raw = (b'From: "x" <"a<img src=x onerror=alert(1)>"@x.com>\r\n'
               b'To: "y" <"b<b>"@y.com>\r\nCc: <"c<i>"@z.com>\r\n'
               b"Subject: <s>hi</s>\r\nDate: Mon, 16 Nov 2026 08:10:47 +0800\r\n"
               b"Content-Type: text/plain; charset=utf-8\r\n\r\nhello\r\n")
        for lang in ("en", "zh"):
            head = R.quote_block(msg_of(raw), lang).split("<blockquote")[0]
            self.assertNotIn("<img", head)
            self.assertNotIn("<b>", head)
            self.assertNotIn("<i>", head)
            self.assertNotIn("<s>", head)
            self.assertIn("&lt;img src=x onerror=alert(1)&gt;", head)
        tags = re.findall(r"<(\w+)", head)
        self.assertEqual(set(tags), {"div"})


def no_server(*a, **k):
    raise OSError("the tests have no mail server")


class DemoBackend(unittest.TestCase):
    """A demo mailbox of the test's own (no account, no network)."""
    def setUp(self):
        self.patch(R, "imap", no_server)
        self.patch(R, "session", no_server)
        self.patch(R, "smtp_open", no_server)
        cfg = R.CFG
        self.b = A.Backend(demo=True)
        self.home = R.CFG.home
        self.addCleanup(self.done, cfg)

    def done(self, cfg):
        self.b.close()
        with self.b.dblock:
            self.b.c.close()
        shutil.rmtree(self.home, ignore_errors=True)
        R.CFG = cfg

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def add_mail(self, raw, folder="INBOX"):
        return R.make_id(folder, self.b.demo_insert(folder, raw, 1763000000, 1, 0))


def with_file(name, data=b"MZ\x90\x00", ctype="application/octet-stream"):
    m = email.message.EmailMessage()
    m["From"] = "x@example.com"
    m["To"] = "me@example.com"
    m["Subject"] = "files"
    m["Message-ID"] = "<files-%d@example.com>" % abs(hash(name))
    m.set_content("see the file")
    mt, st = ctype.split("/")
    m.add_attachment(data, mt, st, filename=name)
    return m.as_bytes(policy=R.OUT_POLICY)


def quarantine(path):
    import subprocess
    r = subprocess.run(["xattr", "-p", "com.apple.quarantine", path], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


class ProgramFiles(DemoBackend):
    def setUp(self):
        super().setUp()
        self.down = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.down, True)
        self.patch(A, "downloads_dir", lambda: self.down)
        self.opened = []
        self.patch(A, "open_path", lambda path, reveal=False: self.opened.append((path, reveal)))

    def test_program_names(self):
        for n in ("invoice.pdf.exe", "A.EXE", "run.bat", "x.cmd", "s.js", "s.vbs", "a.lnk", "a.hta", "a.ps1",
                  "a.scr", "x.exe.", "x.exe ", "Open me.command", "a.terminal", "a.app", "a.pkg", "a.jar", "a.sh",
                  "a.msi", "a.reg", "a.wsf", "a.cpl", "a.appref-ms", "a.application", "a.workflow", "a.scpt"):
            self.assertTrue(R.is_program(n), n)
        for n in ("report.pdf", "data.xlsx", "photo.JPG", "exe", "notes", "exe.txt", "a.zip", ""):
            self.assertFalse(R.is_program(n), n)

    def test_program_is_never_opened(self):
        i = self.add_mail(with_file("invoice.pdf.exe"))
        atts = self.b.build_message(i)["atts"]
        self.assertTrue(atts[0].get("program"))
        out = self.b.api_attachment({"id": i, "i": 0, "name": "invoice.pdf.exe", "action": "open"})
        self.assertEqual(out, {"program": True, "name": "invoice.pdf.exe"})
        self.assertEqual(self.opened, [])
        self.assertFalse(os.path.isdir(os.path.join(self.home, "open")))     # nothing was written either
        out = self.b.api_attachment({"id": i, "i": 0, "name": "invoice.pdf.exe", "action": "show"})
        self.assertEqual(self.opened, [(out["path"], True)])                  # shown in its folder, not run
        self.assertTrue(os.path.isfile(out["path"]))
        saved = self.b.api_attachment({"id": i, "i": 0, "action": "save"})
        self.assertEqual(os.path.dirname(saved["path"]), self.down)
        self.assertEqual(len(self.opened), 1)

    def test_a_named_file_is_not_flagged(self):
        i = self.add_mail(with_file("report.pdf", b"%PDF-1.4", "application/pdf"))
        self.assertNotIn("program", self.b.build_message(i)["atts"][0])
        out = self.b.api_attachment({"id": i, "i": 0, "action": "open"})
        self.assertEqual(self.opened, [(out["path"], False)])

    def test_open_path_refuses_a_program(self):
        ran = []
        self.patch(A.subprocess, "run", lambda *a, **k: ran.append(a))
        self.patch(A.subprocess, "Popen", lambda *a, **k: ran.append(a))
        with self.assertRaises(A.ApiError) as e:
            REAL_OPEN_PATH(os.path.join(self.down, "setup.exe"))
        self.assertIn("is a program", str(e.exception))
        self.assertEqual(ran, [])

    @unittest.skipUnless(sys.platform == "darwin", "macOS quarantine")
    def test_files_from_mail_are_quarantined(self):
        i = self.add_mail(with_file("report.pdf", b"%PDF-1.4", "application/pdf"))
        opened = self.b.api_attachment({"id": i, "i": 0, "action": "open"})["path"]
        saved = self.b.api_attachment({"id": i, "i": 0, "action": "save"})["path"]
        for p in (opened, saved):
            self.assertIn(";Ragdoll Mail;", quarantine(p))

    def test_windows_mark_of_the_web(self):
        import types
        self.patch(R, "sys", types.SimpleNamespace(platform="win32"))
        p = os.path.join(self.down, "a.pdf")
        open(p, "wb").close()
        R.mark_downloaded(p)
        with open(p + ":Zone.Identifier", encoding="ascii", newline="") as f:
            self.assertEqual(f.read(), "[ZoneTransfer]\r\nZoneId=3\r\n")


REAL_OPEN_PATH = A.open_path
REAL_BACKEND = A.Backend


class PlainText(unittest.TestCase):
    """The text part of a mail the app writes: the lines as they show in the HTML."""
    def test_first_line_is_not_glued_to_the_next(self):
        self.assertEqual(R.html_to_text("Hi Tom,<div>Thanks</div><div>Linh</div>"), "Hi Tom,\nThanks\nLinh")

    def test_empty_line_and_trailing_br(self):
        self.assertEqual(R.html_to_text("a<div><br></div><div>b</div>"), "a\n\nb")
        self.assertEqual(R.html_to_text("<div>a<br></div><div>b</div>"), "a\nb")
        self.assertEqual(R.html_to_text("<p>a</p>\n<p>b</p>"), "a\nb")

    def test_lists_keep_bullets_and_numbers(self):
        self.assertEqual(R.html_to_text("Items:<ul><li>one</li><li>two<ul><li>sub</li></ul></li></ul>End"),
                         "Items:\n- one\n- two\n  - sub\nEnd")
        self.assertEqual(R.html_to_text('<ol><li>a</li><li>b</li></ol><ol start="5"><li> c</li></ol>'),
                         "1. a\n2. b\n5. c")

    def test_tables_comments_and_text(self):
        self.assertEqual(R.html_to_text("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>"), "a\tb\nc")
        self.assertEqual(R.html_to_text("<!--[if mso]>x<![endif]--><style>p{}</style>1 &lt; 2 &amp; 3"), "1 < 2 & 3")
        self.assertEqual(R.html_to_text("1 < 2 and 3 > 2"), "1 < 2 and 3 > 2")

    def test_stray_brackets_stay_fast(self):
        import time
        t = time.time()
        R.html_to_text("<" * 200000 + "<div>" * 50000)
        self.assertLess(time.time() - t, 2)

    def test_the_sent_text_part(self):
        own_cfg(self)
        msg = R.build_message("Hi Tom,<div>Thanks</div><ol><li>PO</li><li>Drawing</li></ol>", [("", "t@x.com")], [], "s")
        self.assertIn("Hi Tom,\nThanks\n1. PO\n2. Drawing", msg.get_body(("plain",)).get_content())


def compose(b, **kw):
    a = {"mode": "new", "to": [{"name": "", "addr": "pat@example.com"}], "subject": "Hello",
         "html": "<div>Hello Pat</div>", "atts": []}
    a.update(kw)
    return a


class AttachmentNames(DemoBackend):
    NAMES = ("PO#123: 最终版?.pdf", '合同"A"<草稿>.docx', "很长的文件名" * 20 + ".xlsx")

    def test_upload_keeps_the_real_name_for_the_mail(self):
        atts = [self.b.upload(n, b"data %d" % k) for k, n in enumerate(self.NAMES)]
        self.assertEqual([x["name"] for x in atts], list(self.NAMES))
        for x in atts:     # on disk: a safe name, short enough for any file system
            base = os.path.basename(x["path"])
            self.assertNotRegex(base, r'[:?"<>]')
            self.assertLessEqual(len(base.encode()), 200)
        msg = self.b.build(compose(self.b, atts=atts))
        self.assertEqual([p.get_filename() for p in msg.iter_attachments()], list(self.NAMES))
        again = msg_of(msg.as_bytes(policy=R.OUT_POLICY))       # as the other side reads it
        self.assertEqual([R.fname(p) for p in R.attachments(again)], list(self.NAMES))

    def test_forward_keeps_the_original_names(self):
        i = self.add_mail(with_file(self.NAMES[0], b"%PDF-1.4", "application/pdf"))
        c = self.b.api_compose({"mode": "forward", "id": i})
        self.assertEqual([x["name"] for x in c["atts"]], [self.NAMES[0]])
        msg = self.b.build(compose(self.b, mode="forward", orig=i, atts=c["atts"]))
        self.assertEqual([p.get_filename() for p in msg.iter_attachments()], [self.NAMES[0]])

    def test_a_name_never_breaks_the_header(self):
        x = self.b.upload("a\r\nBcc: evil@x.com\x00.pdf", b"x")
        self.assertEqual(x["name"], "a Bcc: evil@x.com .pdf")
        msg = self.b.build(compose(self.b, atts=[dict(x, name="b\nX-Evil: 1.pdf")]))
        raw = msg.as_bytes(policy=R.OUT_POLICY)
        self.assertNotIn(b"\nX-Evil", raw)
        self.assertNotIn(b"\nBcc", raw)


EW_RE = re.compile(rb"=\?[^?\s]+\?[bBqQ]\?[^?\s]*\?=")


class EncodedWords(unittest.TestCase):
    """Long Chinese subjects, names and file names within RFC 2047 / 2231, with a name= fallback."""
    def setUp(self):
        self.home = own_cfg(self)

    def built(self, subject, names):
        paths = []
        for k, n in enumerate(names):
            p = os.path.join(self.home, "f%d" % k)
            with open(p, "wb") as f:
                f.write(b"data")
            paths.append((p, n))
        msg = R.build_message("<div>hi</div>", [("张三" * 30, "a@b.com")], [], subject, attach=paths)
        return msg.as_bytes(policy=R.OUT_POLICY)

    def test_every_encoded_word_is_75_or_less(self):
        for n in (20, 60, 200, 400):
            subject = ("报价单" * n)[:n]
            raw = self.built(subject, ["很长的文件名" * (n // 6 + 1) + ".pdf"])
            words = EW_RE.findall(raw)
            self.assertTrue(words)
            self.assertLessEqual(max(map(len, words)), 75, n)
            self.assertLessEqual(max(len(x) for x in raw.split(b"\r\n")), 998)
            back = msg_of(raw)
            self.assertEqual(str(back["Subject"]), subject)
            self.assertEqual(R.addrs(R.hdr(back, "To")), [("张三" * 30, "a@b.com")])   # how the app reads it

    def test_file_names_have_a_name_fallback(self):
        names = ["很长的文件名" * 20 + ".xlsx", "PO#123: 最终版?.pdf", "plain name.txt"]
        raw = self.built("s", names)
        back = msg_of(raw)
        parts = list(back.iter_attachments())
        self.assertEqual([p.get_filename() for p in parts], names)          # RFC 2231 filename*=
        self.assertEqual([p.get_param("name") for p in parts], names)       # Content-Type name=
        self.assertIn(b'name="=?utf-8?B?', raw)
        for p in parts:                                                     # a reader of name= only
            del p["Content-Disposition"]
        self.assertEqual([R.fname(p) for p in parts], names)

    def test_a_sent_draft_keeps_the_encoding(self):
        raw = self.built("报价单" * 70, ["文件" * 40 + ".pdf"])
        self.assertEqual(msg_of(raw).as_bytes(policy=R.OUT_POLICY), raw)  # send_draft parses and writes again

    def test_long_message_ids_still_stay_raw(self):
        mid = "<d0425af1094366e3ae8f29d3fde9e1d11ec2bdcf.b4c078c5aa1b2c3d4e5f60718293a4b5c6d7e8f9@larksuite.com>"
        o = msg_of(b"From: a@b.com\r\nSubject: x\r\nMessage-ID: " + mid.encode() + b"\r\n\r\nhi\r\n")
        raw = R.build_message("<div>x</div>", [("", "a@b.com")], [], "回复：" + "长" * 80, o, "reply").as_bytes(
            policy=R.OUT_POLICY)
        self.assertIn(b"In-Reply-To: " + mid.encode(), raw)


class SendWorld:
    """Stands in for the mail server around R.send_draft: the drafts it holds, what SMTP was handed,
    what was put in Sent. No network."""
    def __init__(self, test, drafts=None):
        import contextlib, time as _time, types
        self.drafts = dict(drafts or {})            # uid -> raw
        self.smtp, self.appended, self.deleted, self.server_sent = [], [], [], set()
        self.files_sent = True                      # the server files SMTP mail in Sent by itself
        self.fail_open = self.fail_login = self.fail_mail = self.fail_data = self.fail_fetch = None
        self.logins = 0
        self.during = None                          # runs while SMTP is taking the mail
        world = self

        class Imap:
            def append(self, folder, flags, when, raw):
                world.appended.append((folder, raw))
                return "OK", [b"[APPENDUID 1 9] done"]

            def logout(self):
                pass

        class Smtp:
            def login(self, user, pw):
                world.logins += 1
                if world.fail_login:
                    raise world.fail_login

            rcpts = None

            def ehlo_or_helo_if_needed(self):
                pass

            def mail(self, frm):
                if world.fail_mail:
                    raise world.fail_mail
                self.rcpts = []
                return 250, b"ok"

            def rcpt(self, r):
                self.rcpts.append(r)
                return 250, b"ok"

            def data(self, out):
                if world.during:
                    world.during()
                if world.fail_data:
                    raise world.fail_data
                world.smtp.append((self.rcpts, out))
                if world.files_sent:
                    world.server_sent.add(R.hdr(msg_of(out), "Message-ID").strip())
                return 250, b"queued"

            def quit(self):
                pass

            def close(self):
                pass

        @contextlib.contextmanager
        def session():
            yield Imap()

        def fetch_raw(m, folder, uid):
            if world.fail_fetch:
                raise world.fail_fetch
            if uid not in world.drafts:
                R.die("no mail %s (moved or deleted? run search again)" % R.make_id(folder, uid))
            return world.drafts[uid]

        def smtp_open(host, port, timeout):
            if world.fail_open:
                raise world.fail_open
            return Smtp()
        quick = types.SimpleNamespace(**{k: getattr(_time, k) for k in dir(_time) if not k.startswith("_")})
        quick.sleep = lambda s: None
        for name, value in (("session", session), ("fetch_raw", fetch_raw), ("smtp_open", smtp_open),
                            ("in_folder", lambda m, folder, mid, last=15: mid in world.server_sent),
                            ("password", lambda: "pw"), ("delete_uid", lambda m, f, u: world.deleted.append(u)),
                            ("mark_original", lambda m, msg: None), ("time", quick)):
            test.patch(R, name, value)


class ComposeDetails(DemoBackend):
    """#20: subject prefixes, the signature's font, a record of Bcc in Sent."""
    def test_subject_prefixes(self):
        for s in ("RE：报价", "Re: x", "回复：报价", "答复: 报价", "回复 : x", "AW: x"):
            self.assertEqual(R.reply_subject(s), s)
        for s in ("转发: x", "转发：x", "FW：x", "Fwd: x", "WG: x"):
            self.assertEqual(R.forward_subject(s), s)
        self.assertEqual(R.reply_subject("报价"), "Re: 报价")
        self.assertEqual(R.reply_subject("转发: x"), "Re: 转发: x")
        self.assertEqual(R.forward_subject("回复：报价"), "Fw: 回复：报价")
        self.assertTrue(R.is_forward_subject("转发：x"))

    def test_signature_has_the_body_font(self):
        body = '<div data-rd-body="1" style="font-family:Arial, Helvetica, sans-serif;font-size:16px">Hi</div>'
        html = self.b.build(compose(self.b, html=body)).get_body(("html",)).get_content()
        self.assertIn('<div data-rd-sig="1" style="font-family:Arial, Helvetica, sans-serif;font-size:16px">', html)
        self.assertLess(html.index("data-rd-body"), html.index("data-rd-sig"))

    def test_signature_font_from_settings_when_the_body_has_none(self):
        self.b.api_prefs({"font": "times", "font_size": 18})
        html = self.b.build(compose(self.b, html="")).get_body(("html",)).get_content()
        self.assertIn("data-rd-sig=\"1\" style=\"font-family:'Times New Roman', Times, serif;font-size:18px\"", html)
        html = self.b.build(compose(self.b, use_signature=False)).get_body(("html",)).get_content()
        self.assertNotIn("data-rd-sig", html)

    def test_bcc_is_kept_in_sent_never_sent(self):
        own_cfg(self)
        draft = R.build_message("<div>x</div>", [("", "to@x.com")], [], "s", bcc=[("Boss", "boss@x.com")])
        w = SendWorld(self, {7: draft.as_bytes(policy=R.OUT_POLICY)})
        w.files_sent = False                        # we put the copy in Sent ourselves
        r = R.send_draft(R.CFG.folders["drafts"], 7)
        self.assertEqual(r["copy_in_sent"], "added by ragdoll")
        rcpts, out = w.smtp[0]
        self.assertEqual(rcpts, ["to@x.com", "boss@x.com"])
        self.assertNotIn(b"boss@x.com", out)       # the mail that went out does not say who was Bcc'd
        self.assertEqual(R.hdr(msg_of(w.appended[0][1]), "Bcc"), "Boss <boss@x.com>")
        with open(R.sent_log(), encoding="utf-8") as f:
            self.assertTrue(f.read().rstrip("\n").endswith("\tBoss <boss@x.com>"))
        self.assertTrue(R.already_sent(R.hdr(draft, "Message-ID")))

    def test_demo_sent_copy_keeps_bcc(self):
        _, out = self.b.call("prepare_send", compose(self.b, bcc=[{"name": "", "addr": "boss@x.com"}]))
        self.b.send_now({"id": out["data"]["id"]})
        r = self.b.q("select folder, uid from msgs where folder=? order by uid desc limit 1", (R.CFG.folders["sent"],))[0]
        self.assertEqual(R.hdr(msg_of(self.b.demo_raw[(r["folder"], r["uid"])]), "Bcc"), "boss@x.com")


PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 40
JPG = b"\xff\xd8\xff\xe0" + b"\0" * 40


def outlook_mail(octet=False):
    """Outlook / Foxmail style: the pictures the text shows are marked as attachments; a real photo
    also has a Content-ID (Outlook gives every file one) but the text does not show it.
    octet: QQ Mail style, the pictures as application/octet-stream."""
    m = email.message.EmailMessage()
    m["From"] = "Linh <linh@cust.vn>"
    m["To"] = "me@example.com"
    m["Subject"] = "Drawing"
    m["Message-ID"] = "<outlook-%d@cust.vn>" % octet
    m["Date"] = "Mon, 16 Nov 2026 08:10:47 +0800"
    m.set_content("see below")
    m.add_alternative('<p>See:</p><img src="cid:image001.png@01DA1234"><p>Logo</p>'
                      '<img src="cid:image002.jpg@01DA1234">', subtype="html")
    html = m.get_body(("html",))
    for cid, name, data in (("image001.png@01DA1234", "image001.png", PNG), ("image002.jpg@01DA1234", "image002.jpg", JPG)):
        mt, st = ("application", "octet-stream") if octet else ("image", name.endswith("png") and "png" or "jpeg")
        html.add_related(data, mt, st, cid="<%s>" % cid, filename=name, disposition="attachment")
    m.add_attachment(JPG, "image", "jpeg", filename="site photo.jpg", cid="<photo@01DA1234>")
    m.add_attachment(b"%PDF-1.4", "application", "pdf", filename="drawing.pdf", cid="<pdf@01DA1234>")
    return m.as_bytes(policy=R.OUT_POLICY)


class PicturesInTheText(DemoBackend):
    """#71 and #16: pictures the text shows by cid:, marked as attachments, are not files; in a reply or
    forward they come along as pictures, not as files."""
    def names(self, msg):
        return [R.fname(p) for p in A.file_parts(msg)]

    def test_outlook_and_qq_pictures_are_not_files(self):
        for octet in (False, True):
            msg = msg_of(outlook_mail(octet))
            self.assertEqual(self.names(msg), ["site photo.jpg", "drawing.pdf"], octet)
            self.assertEqual([R.fname(p) for p in R.attachments(msg)], ["site photo.jpg", "drawing.pdf"])
            i = self.add_mail(outlook_mail(octet))
            m = self.b.build_message(i)
            self.assertEqual([x["name"] for x in m["atts"]], ["site photo.jpg", "drawing.pdf"])
            self.assertEqual(m["html"].count("data:image/"), 2)        # both show in the text

    def test_an_inline_picture_the_text_does_not_show_is_a_file(self):
        m = msg_of(b"From: a@b.c\r\nSubject: s\r\nMIME-Version: 1.0\r\nContent-Type: multipart/related; boundary=B\r\n\r\n"
                   b"--B\r\nContent-Type: text/html\r\n\r\n<p>no picture</p>\r\n--B\r\nContent-Type: image/png\r\n"
                   b"Content-ID: <x@y>\r\nContent-Disposition: inline; filename=x.png\r\n\r\nPNG\r\n--B--\r\n")
        self.assertEqual(self.names(m), ["x.png"])

    def test_reply_and_forward_carry_the_pictures(self):
        for octet in (False, True):
            i = self.add_mail(outlook_mail(octet))
            for mode in ("reply", "forward"):
                c = self.b.api_compose({"mode": mode, "id": i})
                self.assertEqual(c["quote"].count("data:image/"), 2)
                msg = self.b.build(compose(self.b, mode=mode, orig=i, atts=c["atts"]))
                files = [p.get_filename() for p in msg.iter_attachments()]
                self.assertEqual(files, [] if mode == "reply" else ["site photo.jpg", "drawing.pdf"], (mode, octet))
                related = {p["Content-ID"].strip("<>") for p in msg.walk() if p["Content-ID"]}
                self.assertEqual(related, {"image001.png@01DA1234", "image002.jpg@01DA1234"})
                self.assertEqual(A.app_problems(msg, mode == "reply"), [])

    def test_light_mail_pictures(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import test_ragdoll as T
        m = T.BigMailServer()
        light = msg_of(R.fetch_light(m, "INBOX", 7))
        self.assertEqual([R.fname(p) for p in A.file_parts(light, True)], ["big.pdf"])
        # QQ style: the picture as a nameless octet-stream, too big to come with the light mail
        parts = dict(T.BIG_PARTS, **{"2.MIME": b"Content-Type: application/octet-stream\r\nContent-ID: <pic1@x>\r\n"
                                     b"Content-Disposition: attachment\r\nContent-Transfer-Encoding: base64\r\n\r\n"})
        big = T.BIG_STRUCTURE.replace(b'"IMAGE" "PNG" ("NAME" "p.png")', b'"APPLICATION" "OCTET-STREAM" NIL').replace(
            b"300000", b"%d" % (R.SHOWN_MAX + 10))
        light = msg_of(R.fetch_light(T.BigMailServer(structure=big, parts=parts), "INBOX", 7))
        pic = light.get_payload()[1]
        self.assertEqual(pic["X-Ragdoll-Part"], "2")
        self.assertTrue(R.is_inline(pic, R.body_refs(light)))         # the text shows it
        self.assertEqual(len(A.file_parts(light, True)), 2)           # but it could not come along: open it as a file
        self.assertEqual(len(A.file_parts(light, False)), 1)


class OriginalMoved(DemoBackend):
    """#13: a reply or forward draft is saved and sent after its original was moved or deleted."""
    def reply_draft(self, mode="reply"):
        orig = self.add_mail(outlook_mail())
        c = self.b.api_compose({"mode": mode, "id": orig})
        a = compose(self.b, mode=mode, orig=orig, atts=c["atts"], html="<div>Noted</div>")
        a["replace"] = self.b.api_save_draft(dict(a))["id"]
        return orig, a

    def test_moved_original_is_found_again(self):
        orig, a = self.reply_draft()
        self.b.api_move({"ids": [orig], "to": "archive"})
        with self.assertRaises(A.ApiError):
            self.b.raw(orig)
        a["replace"] = self.b.api_save_draft(dict(a))["id"]
        msg = msg_of(self.b.raw(a["replace"]))
        self.assertEqual(R.hdr(msg, "In-Reply-To"), "<outlook-0@cust.vn>")
        self.assertIn("From: Linh", R.bodies(msg)[1])
        reopened = self.b.api_compose({"mode": "draft", "id": a["replace"]})
        self.assertNotEqual(reopened["orig"], orig)                   # where the original is now
        self.assertEqual(self.b.parse(reopened["orig"])[0], R.CFG.folders["archive"])
        self.assertIn("From: Linh", reopened["quote"])
        _, out = self.b.call("prepare_send", dict(a))
        self.assertTrue(out["ok"], out)
        self.assertTrue(self.b.send_now({"id": out["data"]["id"]})["sent"])

    def test_deleted_original_keeps_the_quote_and_thread(self):
        for mode in ("reply", "forward"):
            orig, a = self.reply_draft(mode)
            self.b.demo_delete(orig)
            self.b.exec("delete from msgs where msgid=?", ("<outlook-0@cust.vn>",))      # gone for good
            _, out = self.b.call("save_draft", dict(a))
            self.assertTrue(out["ok"], out)
            msg = msg_of(self.b.raw(out["data"]["id"]))
            html = R.bodies(msg)[1]
            self.assertEqual(html.count("From: Linh"), 1)                 # the quote the draft had, once
            self.assertEqual(R.hdr(msg, "In-Reply-To" if mode == "reply" else R.FWD_HEADER), "<outlook-0@cust.vn>")
            self.assertEqual({p["Content-ID"].strip("<>") for p in msg.walk() if p["Content-ID"]},
                             {"image001.png@01DA1234", "image002.jpg@01DA1234"})   # its pictures too
            self.assertEqual(A.app_problems(msg, mode == "reply"), [])
            reopened = self.b.api_compose({"mode": "draft", "id": out["data"]["id"]})
            self.assertIn("From: Linh", reopened["quote"])
            self.assertIn("data:image/", reopened["quote"])
            a["replace"] = out["data"]["id"]
            _, out = self.b.call("prepare_send", dict(a))
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["data"]["problems"], [])

    def test_new_compose_whose_original_went_still_saves(self):
        orig = self.add_mail(outlook_mail())
        c = self.b.api_compose({"mode": "reply", "id": orig})
        self.b.demo_delete(orig)
        self.b.exec("delete from msgs where msgid=?", ("<outlook-0@cust.vn>",))
        _, out = self.b.call("save_draft", compose(self.b, mode="reply", orig=orig, to=c["to"]))
        self.assertTrue(out["ok"], out)
        self.assertEqual(R.hdr(msg_of(self.b.raw(out["data"]["id"])), "In-Reply-To"), "<outlook-0@cust.vn>")


class DraftServer:
    """The Drafts folder on a server whose connection can drop: `drop` names the step that breaks
    once (after the APPEND was taken, during it with or without the server keeping it)."""
    def __init__(self, test, drop):
        import imaplib
        self.drafts, self.drop, self.next, self.conns = {}, drop, 100, 0
        srv = self

        class Conn:
            sock = None

            def noop(self):
                return "OK", [b""]

            def logout(self):
                pass

        def imap():
            srv.conns += 1
            return Conn()

        def append_draft(m, raw):
            if srv.drop == "append-lost":
                srv.drop = None
                raise imaplib.IMAP4.abort("socket error: EOF")
            srv.next += 1
            srv.drafts[srv.next] = raw
            if srv.drop == "append-kept":
                srv.drop = None
                raise imaplib.IMAP4.abort("socket error: EOF")
            return srv.next

        def select(m, folder, readonly=True):
            if srv.drop == "select":
                srv.drop = None
                raise imaplib.IMAP4.abort("socket error: EOF")
            return 1

        def uid_of_mid(m, folder, mid, last=30):
            return next((u for u, raw in srv.drafts.items() if R.hdr(msg_of(raw), "Message-ID").strip() == mid), 0)

        for name, value in (("imap", imap), ("append_draft", append_draft), ("select", select),
                            ("uid_of_mid", uid_of_mid), ("delete_uid", lambda m, f, u: srv.drafts.pop(u, None))):
            test.patch(R, name, value)


class DraftSavedOnce(DemoBackend):
    """#15: a dropped connection while a draft is saved leaves one copy in Drafts, not two."""
    def save(self, drop):
        srv = DraftServer(self, drop)
        self.b.demo = False
        i, _ = self.b.save(compose(self.b))
        self.assertEqual(len(srv.drafts), 1, drop)
        self.assertEqual(i, R.make_id(R.CFG.folders["drafts"], next(iter(srv.drafts))))
        self.assertEqual(srv.conns, 2)          # it did reconnect
        return srv

    def test_drop_after_the_append(self):
        self.save("select")

    def test_drop_during_an_append_the_server_kept(self):
        self.save("append-kept")

    def test_drop_during_an_append_the_server_lost(self):
        self.save("append-lost")

    def test_draft_is_found_by_its_message_id(self):
        class M:
            def select(self, name, readonly=True):
                return "OK", [b"3"]

            def response(self, code):
                return code, [b"1"]

            def uid(self, cmd, *args):
                if cmd == "SEARCH":
                    return "OK", [b"5 8 9"]
                return "OK", [(b"1 (UID 8 BODY[HEADER.FIELDS (MESSAGE-ID)] {24}", b"Message-ID: <a@b.c>\r\n\r\n"), b")",
                              (b"2 (UID 9 BODY[HEADER.FIELDS (MESSAGE-ID)] {24}", b"Message-ID: <x@y.z>\r\n\r\n"), b")"]
        self.assertEqual(R.uid_of_mid(M(), "Drafts", "<x@y.z>"), 9)
        self.assertEqual(R.uid_of_mid(M(), "Drafts", "<a@b.c>"), 8)
        self.assertEqual(R.uid_of_mid(M(), "Drafts", "<q@b.c>"), 0)


class SendFailures(unittest.TestCase):
    """#3: a failure before anything left the computer is SendLater; one that may have sent is not."""
    def setUp(self):
        own_cfg(self)
        self.draft = R.build_message("<div>x</div>", [("", "to@x.com")], [], "s").as_bytes(policy=R.OUT_POLICY)

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def outcome(self, **fail):
        w = SendWorld(self, {7: self.draft})
        for k, v in fail.items():
            setattr(w, k, v)
        try:
            R.send_draft(R.CFG.folders["drafts"], 7)
        except R.SendLater:
            return "later", w
        except SystemExit as e:
            return "stop: %s" % e.code, w
        except Exception as e:      # noqa: BLE001
            return "error: %s" % type(e).__name__, w
        return "sent", w

    def test_before_anything_left(self):
        for kw in ({"fail_open": OSError("no route")}, {"fail_open": TimeoutError()},
                   {"fail_fetch": imaplib.IMAP4.abort("EOF")}, {"fail_fetch": OSError("down")},
                   {"fail_login": smtplib.SMTPServerDisconnected("gone")},
                   {"fail_mail": smtplib.SMTPServerDisconnected("gone")},
                   {"fail_data": smtplib.SMTPDataError(451, b"try later")}):
            got, w = self.outcome(**kw)
            self.assertEqual(got, "later", kw)
            self.assertEqual(w.smtp, [])
            self.assertIsNone(R.already_sent(R.hdr(msg_of(self.draft), "Message-ID")))

    def test_failures_that_are_not_tried_again(self):
        got, _ = self.outcome(fail_login=smtplib.SMTPAuthenticationError(535, b"bad password"))
        self.assertEqual(got, "error: SMTPAuthenticationError")
        got, _ = self.outcome(fail_data=smtplib.SMTPDataError(552, b"too big"))
        self.assertEqual(got, "error: SMTPDataError")
        got, _ = self.outcome(fail_data=smtplib.SMTPServerDisconnected("cut"))     # it may have gone out
        self.assertEqual(got, "stop: " + R.MAYBE_SENT)
        w = SendWorld(self, {})
        with self.assertRaises(SystemExit) as e:                                    # the draft is gone
            R.send_draft(R.CFG.folders["drafts"], 7)
        self.assertNotIsInstance(e.exception, R.SendLater)

    def test_app_says_what_went_wrong(self):
        self.assertEqual(A.friendly(R.SendLater(TimeoutError())), "The mail server did not answer in time.")


class ScheduledSend(DemoBackend):
    """#3, #14, #62: the scheduled-send loop with a stand-in server."""
    def setUp(self):
        super().setUp()
        self.b.demo = False
        self.w = SendWorld(self)

    def scheduled(self, subject="Later", at=None):
        raw = R.build_message("<div>x</div>", [("", "to@x.com")], [], subject).as_bytes(policy=R.OUT_POLICY)
        drafts = R.CFG.folders["drafts"]
        uid = self.b.demo_insert(drafts, raw, int(time.time()), 1, 0)
        self.w.drafts[uid] = raw
        i = R.make_id(drafts, uid)
        at = at or int(time.time()) + 60
        self.b.api_schedule({"id": i, "at": at})
        return i, at

    def entry(self, i):
        return next((x for x in self.b.sched_list() if x["id"] == i), None)

    def test_failure_before_smtp_is_tried_again_with_a_pause(self):
        i, at = self.scheduled()
        self.w.fail_open = OSError("network is down")
        self.assertEqual(self.b.send_due(now=at + 1), 0)
        x = self.entry(i)
        self.assertEqual((x.get("error"), x["tries"], x["retry_at"]), (None, 1, at + 61))
        self.assertNotIn("sending", x)
        self.assertIn("Can't reach the mail server", x["note"])   # a sentence, never the raw error (#58)
        self.assertEqual(self.b.send_due(now=at + 30), 0)          # not before the pause is over
        self.assertEqual(self.b.send_due(now=at + 62), 0)
        self.assertEqual(self.entry(i)["retry_at"], at + 62 + 120)  # the pause grows
        row = [r for r in self.b.scheduled_rows() if r["id"] == i][0]
        self.assertEqual((row["sched_retry"], row["sched_error"]), (at + 182, None))
        self.w.fail_open = None
        self.assertEqual(self.b.send_due(now=at + 200), 1)
        self.assertIsNone(self.entry(i))
        self.assertEqual(len(self.w.smtp), 1)

    def test_one_failure_does_not_stop_the_others(self):
        gone, at = self.scheduled("Gone")
        ok, _ = self.scheduled("Fine", at)
        del self.w.drafts[R.parse_id(gone)[1]]                     # deleted in webmail: fetch_raw dies
        self.assertEqual(self.b.send_due(now=at + 1), 1)
        self.assertTrue(self.entry(gone)["error"])
        self.assertIsNone(self.entry(ok))
        self.assertEqual(self.b.send_due(now=at + 9999), 0)        # a lasting failure waits for the person

    def test_the_loop_outlives_a_system_exit(self):
        calls = []

        def boom(now=None):
            calls.append(1)
            raise SystemExit("no mail Drafts:9")
        self.b.send_due = boom
        b = self.b
        t = threading.Thread(target=b.sched_loop, daemon=True)
        t.start()
        for _ in range(2):
            b.sched_wake.set()
            end = time.time() + 3
            n = len(calls)
            while len(calls) == n and time.time() < end:
                time.sleep(0.01)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(t.is_alive())
        b.stopping.set()
        b.sched_wake.set()
        t.join(3)

    def test_a_long_send_does_not_block_the_other_screens(self):
        i, at = self.scheduled("Big")
        other, _ = self.scheduled("Other", at + 3600)
        seen = {}

        def meanwhile():
            def other_screens():
                seen["rows"] = len(self.b.scheduled_rows())
                self.b.api_unschedule({"id": other})
                seen["send"] = self.b.call("send", {"id": i})[1]       # the same mail: refused, not sent twice
            t = threading.Thread(target=other_screens)
            t.start()
            t.join(3)
            seen["done"] = not t.is_alive()
        self.w.during = meanwhile
        self.assertEqual(self.b.send_due(now=at + 1), 1)
        self.assertTrue(seen["done"])
        self.assertEqual(seen["rows"], 2)
        self.assertEqual(seen["send"]["error"], "This mail is going out right now.")
        self.assertIsNone(self.entry(other))
        self.assertEqual(len(self.w.smtp), 1)

    def test_another_copy_sending_it_is_left_alone(self):
        i, at = self.scheduled()
        run = os.path.join(R.CFG.home, "run")
        os.makedirs(run, exist_ok=True)
        f = open(os.path.join(run, "424242-app.lock"), "a+")
        self.addCleanup(f.close)
        self.assertTrue(R.try_lock(f))                              # that copy of the app is running
        with self.b.sched_edit() as items:
            items[0]["sending"] = {"pid": 424242, "at": int(time.time())}
        self.assertEqual(self.b.send_due(now=at + 1), 0)
        self.assertFalse(self.b.call("unschedule", {"id": i})[1]["ok"])
        R.unlock(f)                                                 # it quit half way: the mark is stale
        self.assertEqual(self.b.send_due(now=at + 1), 1)
        self.assertEqual(len(self.w.smtp), 1)


class EditScheduled(DemoBackend):
    """#3: changing a scheduled mail keeps it scheduled; it waits while a compose changes it."""
    def test_edit_keeps_the_schedule(self):
        _, out = self.b.call("prepare_send", compose(self.b, subject="Plan"))
        i = out["data"]["id"]
        at = int(time.time()) + 600
        self.b.api_schedule({"id": i, "at": at})
        c = self.b.api_compose({"mode": "draft", "id": i})
        self.assertEqual(self.b.send_due(now=at + 1), 0)            # open in a compose: it waits
        a = compose(self.b, subject="Plan v2", replace=c["replace"])
        new = self.b.api_save_draft(a)["id"]
        self.assertNotEqual(new, i)
        self.assertEqual([(x["id"], x["at"]) for x in self.b.sched_list()], [(new, at)])
        self.assertEqual(self.b.send_due(now=at + 1), 0)
        self.b.editing[new] = 0                                     # the compose closed long ago
        self.assertEqual(self.b.send_due(now=at + 1), 1)
        sent = self.b.q("select subject from msgs where folder=?", (R.CFG.folders["sent"],))
        self.assertIn("Plan v2", [r["subject"] for r in sent])

    def test_page_no_longer_unschedules_on_edit(self):
        js = open(os.path.join(os.path.dirname(A.__file__), "app", "app.js"), encoding="utf-8").read()
        body = js[js.index("function editScheduled"):]
        body = body[:body.index("\n}\n")]
        self.assertNotIn("unschedule", body)
        self.assertIn("still_sched", body)


class OneCopy(unittest.TestCase):
    """#62: a second copy of the app shows the first one and quits."""
    def setUp(self):
        own_cfg(self)

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def test_second_copy_brings_the_first_forward(self):
        first = A.one_instance()
        self.addCleanup(first.close)
        self.assertIsNotNone(first)
        self.assertIsNone(A.one_instance())
        started = []
        self.patch(A, "Backend", lambda *a, **k: started.append(1))
        self.assertEqual(A.main(["--browser", "--no-open"]), 0)
        self.assertEqual(started, [])                               # no second sync or scheduled-send loop
        shown = []
        self.patch(A, "bring_front", lambda: shown.append("window"))
        self.patch(A.webbrowser, "open", lambda u: shown.append(u))
        b = REAL_BACKEND.__new__(REAL_BACKEND)
        b.url = "http://127.0.0.1:1/#t=x"
        self.patch(A.WINDOW, "w", object())
        self.assertTrue(b.take_show())
        self.assertFalse(b.take_show())                             # once per ask
        A.WINDOW.w = None
        A.ask_show()
        self.assertTrue(b.take_show())
        self.assertEqual(shown, ["window", "http://127.0.0.1:1/#t=x"])

    def test_the_lock_goes_with_the_first_copy(self):
        first = A.one_instance()
        first.close()
        again = A.one_instance()
        self.assertIsNotNone(again)
        again.close()


class Tidy(DemoBackend):
    """#18: the cache, opened files and compose files are tidied with age and size limits."""
    DAY = 86400

    def put(self, *parts, size=10, age=0):
        p = os.path.join(self.home, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"x" * size)
        t = time.time() - age * self.DAY
        os.utime(p, (t, t))
        return p

    def test_cache_age_and_size(self):
        old = self.put("cache", "INBOX", "1.eml", age=100)
        a = self.put("cache", "INBOX", "2.eml", size=600, age=5)
        b = self.put("cache", "INBOX", "3.eml", size=600, age=1)
        part = self.put("cache", "INBOX", "4.part2.eml", age=1)          # its light mail is gone
        self.b.prune_cache(90, max_bytes=1000)
        self.assertEqual([os.path.exists(p) for p in (old, a, b, part)], [False, False, True, False])

    def test_opened_files(self):
        stale = self.put("open", "aaa", "old.pdf", age=40)
        used = self.put("open", "bbb", "used.xlsx", size=800, age=3)
        today = self.put("open", "ccc", "today.docx", size=800)
        self.b.made.add(stale)
        self.b.prune_open(time.time(), max_bytes=1000)
        self.assertEqual([os.path.exists(p) for p in (stale, used, today)], [False, False, True])
        self.assertNotIn(stale, self.b.made)
        self.assertFalse(os.path.exists(os.path.dirname(stale)))

    def test_compose_files(self):
        _, out = self.b.call("save_draft", compose(self.b, atts=[self.b.upload("kept.pdf", b"%PDF")]))
        self.assertTrue(out["ok"])
        kept = [x["path"] for x in self.b.compose_state(R.hdr(msg_of(self.b.raw(out["data"]["id"])), "Message-ID"))["atts"]]
        for p in kept:
            t = time.time() - 30 * self.DAY
            os.utime(p, (t, t))
        loose_old = self.put("uploads", "f00", "gone.pdf", age=5)
        loose_new = self.put("uploads", "f01", "new.pdf")
        orphan = self.put("compose", "0" * 40 + ".json", age=3)
        self.b.tidy()
        self.assertTrue(all(os.path.exists(p) for p in kept))          # a saved draft still points at it
        self.assertEqual([os.path.exists(p) for p in (loose_old, loose_new, orphan)], [False, True, False])

    def test_settings_size_and_clear(self):
        self.put("cache", "INBOX", "1.eml", size=1000, age=1)
        self.put("open", "aaa", "a.pdf", size=500, age=3)
        today = self.put("open", "bbb", "b.pdf", size=200)
        self.assertEqual(self.b.call("storage", {})[1]["data"], {"bytes": 1700})
        self.assertEqual(self.b.call("clear_storage", {})[1]["data"], {"bytes": 200})
        self.assertTrue(os.path.exists(today))                          # it may still be open in another app

    def test_tidy_runs_every_day(self):
        runs = []
        self.b.tidy = lambda: (runs.append(1), self.b.stopping.set())
        self.b.tidy_loop()
        self.assertEqual(runs, [1])
        src = open(A.__file__, encoding="utf-8").read()
        self.assertIn("self.stopping.wait(86400)", src[src.index("def tidy_loop"):src.index("def tidy(")])


LANG_MAIL = (b'From: "Linh Tran" <linh@cust.vn>\r\nTo: "Me" <me@example.com>, hoa@partner.vn\r\n'
             b"Cc: boss@example.com\r\nSubject: PO-1234\r\nDate: Mon, 16 Nov 2026 14:05:00 +0800\r\n"
             b"Message-ID: <lang@cust.vn>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPlease send it.\r\n")


class QuoteLanguage(unittest.TestCase):
    """A reply's quote header is in the app's (or the command's) language: Outlook's in English, Foxmail's in Chinese."""
    ZH = ('<div>发件人：&quot;Linh Tran&quot; &lt;linh@cust.vn&gt;</div><div>时间：2026年11月16日 (周一) 14:05</div>'
          '<div>主题：PO-1234</div><div>收件人：&quot;Me&quot; &lt;me@example.com&gt;, '
          '&quot;hoa@partner.vn&quot; &lt;hoa@partner.vn&gt;</div>'
          '<div>抄送：&quot;boss@example.com&quot; &lt;boss@example.com&gt;</div></div>')
    EN = ('<div>From: Linh Tran &lt;linh@cust.vn&gt;</div><div>Sent: Monday, November 16, 2026 2:05 PM</div>'
          '<div>To: Me &lt;me@example.com&gt;; hoa@partner.vn</div><div>Cc: boss@example.com</div>'
          '<div>Subject: PO-1234</div></div>')

    def setUp(self):
        own_cfg(self)

    def head(self, lang=None):
        return R.quote_block(msg_of(LANG_MAIL), lang).split("<blockquote")[0]

    def test_chinese_header_is_foxmails(self):
        for lang in ("zh", "zh-Hans", "zh-Hant"):
            self.assertEqual(self.head(lang), R.QUOTE_HEAD + self.ZH)

    def test_english_header_is_outlooks(self):
        for lang in ("en", "ja", "de", "fr"):       # every other language: the English header
            self.assertEqual(self.head(lang), R.QUOTE_HEAD + self.EN)

    def test_english_date_ignores_the_computers_locale(self):
        raw = LANG_MAIL.replace(b"14:05:00", b"00:07:00").replace(b"Mon, 16", b"Sun, 15")
        self.assertIn("Sent: Sunday, November 15, 2026 12:07 AM", R.quote_block(msg_of(raw), "en"))
        raw = LANG_MAIL.replace(b"14:05:00", b"12:30:00")
        self.assertIn("Sent: Monday, November 16, 2026 12:30 PM", R.quote_block(msg_of(raw), "en"))

    def test_bare_sender_and_no_cc(self):
        raw = LANG_MAIL.replace(b'"Linh Tran" <linh@cust.vn>', b"linh@cust.vn").replace(b"Cc: boss@example.com\r\n", b"")
        en, zh = R.quote_block(msg_of(raw), "en"), R.quote_block(msg_of(raw), "zh")
        self.assertIn("<div>From: linh@cust.vn</div>", en)
        self.assertNotIn("Cc:", en)
        self.assertIn("<div>发件人：&quot;linh@cust.vn&quot; &lt;linh@cust.vn&gt;</div>", zh)
        self.assertNotIn("抄送", zh)

    def test_config_and_system_language(self):
        R.CFG.d["lang"] = "zh"
        self.assertEqual(self.head(), R.QUOTE_HEAD + self.ZH)
        self.assertEqual(self.head("en"), R.QUOTE_HEAD + self.EN)     # the command's --lang wins
        R.CFG.d["lang"] = "en"
        self.assertEqual(self.head(), R.QUOTE_HEAD + self.EN)
        R.CFG.d["lang"] = "system"
        old = R.system_lang
        try:
            for sys_lang, want in (("zh", self.ZH), ("en", self.EN)):
                R.system_lang = lambda: sys_lang
                self.assertEqual(self.head(), R.QUOTE_HEAD + want)
                self.assertEqual(self.head("system"), R.QUOTE_HEAD + want)
        finally:
            R.system_lang = old

    def test_build_message_passes_the_language(self):
        for lang, mark in (("en", "Sent: Monday"), ("zh", "发件人：")):
            msg = R.build_message("<div>OK</div>", [("", "linh@cust.vn")], [], "Re: PO-1234", msg_of(LANG_MAIL),
                                  "reply", lang=lang)
            self.assertIn(mark, msg.get_body(("html",)).get_content())

    def test_both_headers_are_found_as_quoted_history(self):
        for lang in ("en", "zh"):
            with self.subTest(lang=lang):
                html = "<div>Noted.</div><div><br></div>" + R.quote_block(msg_of(LANG_MAIL), lang)
                text = R.html_to_text(html)
                self.assertEqual(R.new_text(text).strip(), "Noted.")
                self.assertTrue(any(x in text for x in R.QUOTE_MARKS))
                self.assertTrue(R.QUOTE_RE.search(text))
                self.assertEqual(R.quote_of(html), R.quote_block(msg_of(LANG_MAIL), lang))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_page_finds_both_headers(self):
        import json, subprocess
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "app.js"), encoding="utf-8") as f:
            js = f.read()
        start, end = js.index("const QUOTE_SEP ="), js.index("// a mail's text as the lines a reader sees")
        cases = [R.html_to_text("<div>Noted.</div><div><br></div>" + R.quote_block(msg_of(LANG_MAIL), lang)).split("\n")
                 for lang in ("en", "zh")]
        want = [R.quote_line(x) for x in cases]
        self.assertTrue(all(i > 0 for i in want), want)
        script = js[start:end] + "\nconsole.log(JSON.stringify(" + json.dumps(cases) + ".map(quoteLine)));"
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), want)


class AppQuoteLanguage(DemoBackend):
    """The app: the language set in Settings, else the demo mailbox's, else the computer's."""
    def quote(self):
        orig = self.add_mail(LANG_MAIL)
        return self.b.api_compose({"mode": "reply", "id": orig})["quote"]

    def test_demo_mailbox_language_by_default(self):
        self.assertIn("Sent: Monday, November 16, 2026 2:05 PM", self.quote())
        self.b.demo_set = A.DEMO_SETS["zh"]
        self.assertIn("时间：2026年11月16日 (周一) 14:05", self.quote())

    def test_settings_language_wins(self):
        for lang, mark in (("zh-Hans", "发件人："), ("zh-Hant", "发件人："), ("en", "Sent: "), ("ja", "Sent: ")):
            with self.subTest(lang=lang):
                self.b.api_prefs({"lang": lang})
                self.assertIn(mark, self.quote())

    def test_system_language_outside_the_demo(self):
        self.b.demo = False
        self.b.api_prefs({"lang": "system"})
        self.assertEqual(self.b.quote_lang(), "system")
        self.b.demo = True
        self.assertEqual(self.b.quote_lang(), "en")

    def test_saved_reply_has_the_same_header(self):
        self.b.api_prefs({"lang": "zh-Hans"})
        orig = self.add_mail(LANG_MAIL)
        c = self.b.api_compose({"mode": "reply", "id": orig})
        a = compose(self.b, mode="reply", orig=orig, to=c["to"], subject=c["subject"])
        html = R.bodies(msg_of(self.b.raw(self.b.api_save_draft(a)["id"])))[1]
        self.assertEqual(html.count("发件人："), 1)
        self.assertNotIn("Sent: ", html)


if __name__ == "__main__":
    unittest.main()
