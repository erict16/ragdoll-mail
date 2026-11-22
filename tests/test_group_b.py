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


if __name__ == "__main__":
    unittest.main()
