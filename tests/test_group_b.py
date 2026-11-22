"""Offline tests of sending, drafts, scheduled send, the MIME build and files on disk (0.11 group B)."""
import email, os, re, shutil, sys, tempfile, unittest
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
        head = R.quote_block(msg_of(raw)).split("<blockquote")[0]
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


if __name__ == "__main__":
    unittest.main()
