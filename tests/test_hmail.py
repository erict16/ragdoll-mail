"""Offline tests: python -m unittest discover -s tests"""
import email, os, sqlite3, sys, unittest
from email import policy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hmail  # noqa: E402

hmail.CFG = hmail.Cfg(dict(hmail.DEFAULTS, user="me@example.com", name="Me",
                           signature_marks=["+65 1234 5678"], require_cc=["boss@example.com"]))
SIG = "<div>Me</div><div>M: +65 1234 5678</div>"

ORIG = (b"From: \"Linh\" <linh@cust.vn>\r\nTo: me@example.com, hoa@partner.vn\r\nCc: boss@example.com\r\n"
        b"Subject: =?utf-8?b?5Zue5aSN77yaIEUtVzI2MDA4NA==?=\r\nDate: Mon, 16 Nov 2026 08:10:47 +0800\r\n"
        b"Message-ID: <abc@cust.vn>\r\nReferences: <root@cust.vn>\r\nMIME-Version: 1.0\r\n"
        b"Content-Type: multipart/related; boundary=\"B\"\r\n\r\n--B\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<p>Please send the drawing.</p><img src=\"cid:logo1\">\r\n--B\r\nContent-Type: image/png\r\n"
        b"Content-ID: <logo1>\r\nContent-Transfer-Encoding: base64\r\n\r\niVBORw0KGgo=\r\n--B--\r\n")


def orig():
    return email.message_from_bytes(ORIG, policy=policy.default)


class Basics(unittest.TestCase):
    def test_mutf7_roundtrip(self):
        for s in ("INBOX", "Sent Messages", "其他文件夹", "A&B"):
            self.assertEqual(hmail.mutf7_decode(hmail.mutf7(s)), s)
        self.assertEqual(hmail.mutf7("A&B"), "A&-B")

    def test_bodystructure_names(self):
        blob = (b'("APPLICATION" "OCTET-STREAM" ("NAME" "=?utf-8?b?5LiK5rW3LmR3Zw==?=") NIL NIL "BASE64" 10) '
                b'("IMAGE" "PNG" ("NAME" "61C78120@0F57F725.A1C871690000") NIL) '
                b'("APPLICATION" "PDF" ("NAME" {9}\r\nplain.pdf) NIL)')
        self.assertEqual(hmail.bs_names(blob), ["上海.dwg", "plain.pdf"])

    def test_new_text_and_bare_subject(self):
        self.assertEqual(hmail.new_text("Noted.\n\n发件人: a\nold"), "Noted.")
        self.assertEqual(hmail.bare_subject("回复： Re: Fw: Order 12"), "order 12")

    def test_big_attachment_lines_hide_links(self):
        t = "从腾讯企业邮箱发来的超大附件\nmodel.stp (52.3M, 2026年11月30日 到期)\nhttps://exmail.qq.com/ftnExs_download?x"
        lines = hmail.big_attachment_lines(t)
        self.assertTrue(any("model.stp" in x for x in lines))
        self.assertFalse(any("http" in x for x in lines))

    def test_subjects(self):
        self.assertEqual(hmail.reply_subject("Order"), "Re: Order")
        self.assertEqual(hmail.reply_subject("回复： Order"), "Re: 回复： Order")
        self.assertEqual(hmail.reply_subject("RE: Order"), "RE: Order")
        self.assertEqual(hmail.forward_subject("Re: Order"), "Fw: Re: Order")


class Recipients(unittest.TestCase):
    def test_reply_all_drops_self_and_keeps_cc(self):
        to, cc = hmail.reply_recipients(orig(), True, "me@example.com")
        self.assertEqual([a for _, a in to], ["linh@cust.vn", "hoa@partner.vn"])
        self.assertEqual([a for _, a in cc], ["boss@example.com"])

    def test_reply_to_own_mail_goes_to_its_recipients(self):
        m = email.message_from_bytes(ORIG.replace(b'From: "Linh" <linh@cust.vn>', b"From: me@example.com"),
                                     policy=policy.default)
        to, cc = hmail.reply_recipients(m, True, "me@example.com", remove=["hoa@partner.vn"])
        self.assertEqual([a for _, a in to], [])
        self.assertEqual([a for _, a in cc], ["boss@example.com"])

    def test_extra_and_duplicates(self):
        to, cc = hmail.reply_recipients(orig(), False, "me@example.com", extra_cc=["Boss@example.com", "x@y.z"])
        self.assertEqual([a for _, a in to], ["linh@cust.vn"])
        self.assertEqual([a for _, a in cc], ["boss@example.com", "x@y.z"])


class Drafts(unittest.TestCase):
    def build(self, body="<div>Dear Linh,</div><div>Attached.</div>", **kw):
        o = orig()
        to, cc = hmail.reply_recipients(o, True, "me@example.com")
        msg = hmail.build_message(body, to, cc, hmail.reply_subject(hmail.hdr(o, "Subject")), o, "reply",
                                  signature_html=SIG, **kw)
        return email.message_from_bytes(msg.as_bytes(policy=hmail.OUT_POLICY), policy=policy.default)

    def test_reply_has_signature_quote_image_and_headers(self):
        m = self.build()
        self.assertEqual(m["In-Reply-To"], "<abc@cust.vn>")
        self.assertIn("<root@cust.vn>", m["References"])
        self.assertEqual(str(m["Subject"]), "Re: 回复： E-W260084")
        html = m.get_body(("html",)).get_content()
        self.assertLess(html.find("+65 1234 5678"), html.find("发件人"))
        self.assertIn("cid:logo1", html)
        self.assertEqual(hmail.check_message(m, reply=True), [])

    def test_long_message_ids_stay_raw(self):
        long_id = "<d0425af1094366e3ae8f29d3fde9e1d11ec2bdcf.b4c078c5aa1b2c3d4e5f60718293a4b5c6d7e8f9@larksuite.com>"
        o = email.message_from_bytes(ORIG.replace(b"<abc@cust.vn>", long_id.encode()), policy=policy.default)
        msg = hmail.build_message("<div>x</div>", [("", "linh@cust.vn")], [], "Re: x", o, "reply", signature_html=SIG)
        raw = msg.as_bytes(policy=hmail.OUT_POLICY)
        self.assertIn(b"In-Reply-To: " + long_id.encode(), raw)
        self.assertNotIn(b"=?utf-8?q?=3C", raw)

    def test_check_catches_missing_cc_and_bad_table(self):
        o = orig()
        msg = hmail.build_message("<table><tr><td>a</td><td>b</td><td>—</td></tr></table>",
                                  [("", "linh@cust.vn")], [], "Re: x", o, "reply", signature_html=SIG)
        m = email.message_from_bytes(msg.as_bytes(policy=hmail.OUT_POLICY), policy=policy.default)
        problems = " ".join(hmail.check_message(m, reply=True))
        self.assertIn("boss@example.com", problems)
        self.assertIn("word-break", problems)
        self.assertIn("pixel width", problems)
        self.assertIn("blank", problems)

    def test_check_no_signature(self):
        o = orig()
        msg = hmail.build_message("<div>x</div>", [("", "linh@cust.vn")], [("", "boss@example.com")], "Re: x",
                                  o, "reply", signature_html="")
        m = email.message_from_bytes(msg.as_bytes(policy=hmail.OUT_POLICY), policy=policy.default)
        self.assertIn("no signature", hmail.check_message(m, reply=True))

    def test_forward_keeps_attachments(self):
        o = email.message_from_bytes(ORIG.replace(b"--B--", b"--B\r\nContent-Type: application/pdf\r\n"
                                                  b"Content-Disposition: attachment; filename=\"a.pdf\"\r\n"
                                                  b"Content-Transfer-Encoding: base64\r\n\r\nJVBERg==\r\n--B--"),
                                     policy=policy.default)
        msg = hmail.build_message("<div>pls</div>", [("", "x@y.z")], [], "Fw: x", o, "forward", signature_html=SIG)
        self.assertEqual([p.get_filename() for p in hmail.attachments(msg)], ["a.pdf"])


class Index(unittest.TestCase):
    def test_trigram_search_chinese(self):
        c = sqlite3.connect(":memory:")
        c.execute("create virtual table fts using fts5(x, tokenize='trigram')")
        c.execute("insert into fts values('回复： Fw: E-W260084-088 越南MEE 夏洁平')")
        self.assertEqual(c.execute("select count(*) from fts where fts match '\"越南MEE\"'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
