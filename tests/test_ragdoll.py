"""Offline tests: python -m unittest discover -s tests"""
import base64, contextlib, email, io, json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time, unittest
from email import policy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll  # noqa: E402

ragdoll.CFG = ragdoll.Cfg(dict(ragdoll.DEFAULTS, user="me@example.com", name="Me", utc_offset_hours=8,
                           signature_marks=["+1 555 0100"], require_cc=["boss@example.com"]))
SIG = "<div>Me</div><div>M: +1 555 0100</div>"

ORIG = (b"From: \"Linh\" <linh@cust.vn>\r\nTo: me@example.com, hoa@partner.vn\r\nCc: boss@example.com\r\n"
        b"Subject: =?utf-8?b?5Zue5aSN77yaIFBPLTEyMzQ=?=\r\nDate: Mon, 16 Nov 2026 08:10:47 +0800\r\n"
        b"Message-ID: <abc@cust.vn>\r\nReferences: <root@cust.vn>\r\nMIME-Version: 1.0\r\n"
        b"Content-Type: multipart/related; boundary=\"B\"\r\n\r\n--B\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<p>Please send the drawing.</p><img src=\"cid:logo1\">\r\n--B\r\nContent-Type: image/png\r\n"
        b"Content-ID: <logo1>\r\nContent-Transfer-Encoding: base64\r\n\r\niVBORw0KGgo=\r\n--B--\r\n")


def orig():
    return email.message_from_bytes(ORIG, policy=policy.default)


class Basics(unittest.TestCase):
    def test_mutf7_roundtrip(self):
        for s in ("INBOX", "Sent Messages", "其他文件夹", "A&B"):
            self.assertEqual(ragdoll.mutf7_decode(ragdoll.mutf7(s)), s)
        self.assertEqual(ragdoll.mutf7("A&B"), "A&-B")

    def test_bodystructure_names(self):
        blob = (b'("APPLICATION" "OCTET-STREAM" ("NAME" "=?utf-8?b?5LiK5rW3LmR3Zw==?=") NIL NIL "BASE64" 10) '
                b'("IMAGE" "PNG" ("NAME" "61C78120@0F57F725.A1C871690000") NIL) '
                b'("IMAGE" "PNG" ("NAME" "A71D6834@7680436B.0A0FF86A00000000.png") NIL) '
                b'("APPLICATION" "PDF" ("NAME" {9}\r\nplain.pdf) NIL)')
        self.assertEqual(ragdoll.bs_names(blob), ["上海.dwg", "plain.pdf"])

    def test_new_text_and_bare_subject(self):
        self.assertEqual(ragdoll.new_text("Noted.\n\n发件人: a\nold"), "Noted.")
        self.assertEqual(ragdoll.bare_subject("回复： Re: Fw: Order 12"), "order 12")

    def test_big_attachment_lines_hide_links(self):
        t = "从腾讯企业邮箱发来的超大附件\nmodel.stp (52.3M, 2026年11月30日 到期)\nhttps://mail.example.com/download?x"
        lines = ragdoll.big_attachment_lines(t)
        self.assertTrue(any("model.stp" in x for x in lines))
        self.assertFalse(any("http" in x for x in lines))

    def test_subjects(self):
        self.assertEqual(ragdoll.reply_subject("Order"), "Re: Order")
        self.assertEqual(ragdoll.reply_subject("回复： Order"), "Re: 回复： Order")
        self.assertEqual(ragdoll.reply_subject("RE: Order"), "RE: Order")
        self.assertEqual(ragdoll.forward_subject("Re: Order"), "Fw: Re: Order")


class Recipients(unittest.TestCase):
    def test_reply_all_drops_self_and_keeps_cc(self):
        to, cc = ragdoll.reply_recipients(orig(), True, "me@example.com")
        self.assertEqual([a for _, a in to], ["linh@cust.vn", "hoa@partner.vn"])
        self.assertEqual([a for _, a in cc], ["boss@example.com"])

    def test_reply_to_own_mail_goes_to_its_recipients(self):
        m = email.message_from_bytes(ORIG.replace(b'From: "Linh" <linh@cust.vn>', b"From: me@example.com"),
                                     policy=policy.default)
        to, cc = ragdoll.reply_recipients(m, True, "me@example.com", remove=["hoa@partner.vn"])
        self.assertEqual([a for _, a in to], [])
        self.assertEqual([a for _, a in cc], ["boss@example.com"])

    def test_extra_and_duplicates(self):
        to, cc = ragdoll.reply_recipients(orig(), False, "me@example.com", extra_cc=["Boss@example.com", "x@y.z"])
        self.assertEqual([a for _, a in to], ["linh@cust.vn"])
        self.assertEqual([a for _, a in cc], ["boss@example.com", "x@y.z"])


class Drafts(unittest.TestCase):
    def build(self, body="<div>Dear Linh,</div><div>Noted, thank you.</div>", **kw):
        o = orig()
        to, cc = ragdoll.reply_recipients(o, True, "me@example.com")
        msg = ragdoll.build_message(body, to, cc, ragdoll.reply_subject(ragdoll.hdr(o, "Subject")), o, "reply",
                                  signature_html=SIG, **kw)
        return email.message_from_bytes(msg.as_bytes(policy=ragdoll.OUT_POLICY), policy=policy.default)

    def test_reply_has_signature_quote_image_and_headers(self):
        m = self.build()
        self.assertEqual(m["In-Reply-To"], "<abc@cust.vn>")
        self.assertIn("<root@cust.vn>", m["References"])
        self.assertEqual(str(m["Subject"]), "Re: 回复： PO-1234")
        html = m.get_body(("html",)).get_content()
        self.assertLess(html.find("+1 555 0100"), html.find("发件人"))
        self.assertIn("cid:logo1", html)
        self.assertEqual(ragdoll.check_message(m, reply=True), [])

    def test_long_message_ids_stay_raw(self):
        long_id = "<d0425af1094366e3ae8f29d3fde9e1d11ec2bdcf.b4c078c5aa1b2c3d4e5f60718293a4b5c6d7e8f9@larksuite.com>"
        o = email.message_from_bytes(ORIG.replace(b"<abc@cust.vn>", long_id.encode()), policy=policy.default)
        msg = ragdoll.build_message("<div>x</div>", [("", "linh@cust.vn")], [], "Re: x", o, "reply", signature_html=SIG)
        raw = msg.as_bytes(policy=ragdoll.OUT_POLICY)
        self.assertIn(b"In-Reply-To: " + long_id.encode(), raw)
        self.assertNotIn(b"=?utf-8?q?=3C", raw)

    def test_check_catches_missing_cc_and_bad_table(self):
        o = orig()
        msg = ragdoll.build_message("<table><tr><td>a</td><td>b</td><td>—</td></tr></table>",
                                  [("", "linh@cust.vn")], [], "Re: x", o, "reply", signature_html=SIG)
        m = email.message_from_bytes(msg.as_bytes(policy=ragdoll.OUT_POLICY), policy=policy.default)
        problems = " ".join(ragdoll.check_message(m, reply=True))
        self.assertIn("boss@example.com", problems)
        self.assertIn("word-break", problems)
        self.assertIn("pixel width", problems)
        self.assertIn("blank", problems)

    def test_check_no_signature(self):
        o = orig()
        msg = ragdoll.build_message("<div>x</div>", [("", "linh@cust.vn")], [("", "boss@example.com")], "Re: x",
                                  o, "reply", signature_html="")
        m = email.message_from_bytes(msg.as_bytes(policy=ragdoll.OUT_POLICY), policy=policy.default)
        self.assertIn("no signature", ragdoll.check_message(m, reply=True))

    def test_forward_keeps_attachments(self):
        o = email.message_from_bytes(ORIG.replace(b"--B--", b"--B\r\nContent-Type: application/pdf\r\n"
                                                  b"Content-Disposition: attachment; filename=\"a.pdf\"\r\n"
                                                  b"Content-Transfer-Encoding: base64\r\n\r\nJVBERg==\r\n--B--"),
                                     policy=policy.default)
        msg = ragdoll.build_message("<div>pls</div>", [("", "x@y.z")], [], "Fw: x", o, "forward", signature_html=SIG)
        self.assertEqual([p.get_filename() for p in ragdoll.attachments(msg)], ["a.pdf"])


def parse(raw):
    return email.message_from_bytes(raw, policy=policy.default)


def built(msg):
    return parse(msg.as_bytes(policy=ragdoll.OUT_POLICY))


class Charsets(unittest.TestCase):
    """A GBK-only character in a name labelled GB2312 must not turn into �."""

    def test_gb2312_label_with_gbk_character(self):
        m = parse(b"From: =?GB2312?B?s8KGtA==?= <rose@x.cn>\r\nTo: me@example.com\r\nSubject: s\r\n\r\nx\r\n")
        self.assertEqual(ragdoll.hdr(m, "From"), "陈喆 <rose@x.cn>")
        to, _ = ragdoll.reply_recipients(m, False, "me@example.com")
        self.assertEqual(to, [("陈喆", "rose@x.cn")])
        self.assertIn("陈喆", ragdoll.quote_block(m))

    def test_gb2312_body(self):
        m = parse(b"From: a@b.c\r\nSubject: s\r\nContent-Type: text/plain; charset=gb2312\r\n"
                  b"Content-Transfer-Encoding: 8bit\r\n\r\n" + "陈喆你好".encode("gbk") + b"\r\n")
        self.assertEqual(ragdoll.body_text(m), "陈喆你好")

    def test_raw_8bit_gbk_headers_and_filename(self):
        raw = (b"From: " + "陈喆".encode("gbk") + b" <z@x.cn>\r\nSubject: " + "报价".encode("gbk") +
               b"\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=\"B\"\r\n\r\n--B\r\n"
               b"Content-Type: text/plain; charset=utf-8\r\n\r\nhi\r\n--B\r\nContent-Type: application/pdf\r\n"
               b"Content-Disposition: attachment; filename=\"" + "报价.pdf".encode("gbk") + b"\"\r\n\r\nx\r\n--B--\r\n")
        m = parse(raw)
        self.assertEqual(ragdoll.hdr(m, "From"), "陈喆 <z@x.cn>")
        self.assertEqual(ragdoll.hdr(m, "Subject"), "报价")
        self.assertEqual([ragdoll.fname(p) for p in ragdoll.attachments(m)], ["报价.pdf"])

    def test_big5(self):
        m = parse(b"From: a@b.c\r\nSubject: =?big5?B?" + __import__("base64").b64encode("碁€".encode("cp950")) +
                  b"?=\r\n\r\nx\r\n")
        self.assertEqual(ragdoll.hdr(m, "Subject"), "碁€")

    def test_unknown_charset_does_not_crash(self):
        m = parse(b"From: a@b.c\r\nSubject: s\r\nContent-Type: text/plain; charset=unknown-8bit\r\n\r\n"
                  + "Chào anh".encode("utf-8") + b"\r\n")
        self.assertEqual(ragdoll.body_text(m), "Chào anh")

    def test_vietnamese_nfc(self):
        decomposed = "Trả lời: Order 1"
        self.assertEqual(ragdoll.bare_subject(decomposed), "order 1")

    def test_broken_name_falls_back_to_bare_address(self):
        to, cc = ragdoll.clean_recipients([("赵�B", "rose@x.cn")], [], set())
        self.assertEqual(to, [("", "rose@x.cn")])


class AttachedMail(unittest.TestCase):
    RAW = (b"From: a@b.c\r\nTo: me@example.com\r\nSubject: s\r\nMIME-Version: 1.0\r\n"
           b"Content-Type: multipart/mixed; boundary=\"O\"\r\n\r\n--O\r\nContent-Type: text/plain\r\n\r\nOUTER TEXT\r\n"
           b"--O\r\nContent-Type: message/rfc822\r\nContent-Disposition: attachment; filename=\"fwd.eml\"\r\n\r\n"
           b"From: x@y.z\r\nSubject: inner\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=\"I\"\r\n\r\n"
           b"--I\r\nContent-Type: text/html\r\n\r\n<p>INNER</p>\r\n--I\r\nContent-Type: application/pdf\r\n"
           b"Content-Disposition: attachment; filename=\"inner.pdf\"\r\n\r\nx\r\n--I--\r\n--O--\r\n")

    def test_body_and_attachments_stay_outside(self):
        m = parse(self.RAW)
        plain, html = ragdoll.bodies(m)
        self.assertIn("OUTER TEXT", plain)
        self.assertEqual(html, "")
        self.assertEqual([ragdoll.fname(p) for p in ragdoll.attachments(m)], ["fwd.eml"])
        self.assertIn(b"inner.pdf", ragdoll.part_bytes(ragdoll.attachments(m)[0]))

    def test_forward_keeps_the_eml(self):
        msg = ragdoll.build_message("<div>pls</div>", [("", "x@y.z")], [], "Fw: s", parse(self.RAW), "forward",
                                  signature_html=SIG)
        self.assertEqual([ragdoll.fname(p) for p in ragdoll.attachments(built(msg))], ["fwd.eml"])

    def test_pdf_with_content_id_is_a_file(self):
        raw = ORIG.replace(b"--B--", b"--B\r\nContent-Type: application/pdf; name=\"spec.pdf\"\r\n"
                           b"Content-ID: <p1>\r\nContent-Transfer-Encoding: base64\r\n\r\nJVBERg==\r\n--B--")
        msg = ragdoll.build_message("<div>pls</div>", [("", "x@y.z")], [], "Fw: x", parse(raw), "forward",
                                  signature_html=SIG)
        self.assertEqual([ragdoll.fname(p) for p in ragdoll.attachments(built(msg))], ["spec.pdf"])


class Safety(unittest.TestCase):
    def test_replace_only_takes_drafts(self):
        with self.assertRaises(SystemExit):
            ragdoll.drafts_only("inbox:9255", "--replace")
        self.assertEqual(ragdoll.drafts_only("drafts:3", "--replace"), ("Drafts", 3))

    def test_parse_people(self):
        self.assertEqual(ragdoll.parse_people('"Doe, Jane" <Jane@X.com>; b@c.d'), [("Doe, Jane", "jane@x.com"),
                                                                                ("", "b@c.d")])
        with self.assertRaises(SystemExit):
            ragdoll.parse_people("not an address")

    def test_check_catches_garble_placeholder_and_missing_attachment(self):
        msg = ragdoll.build_message("<div>Dear [Name],</div><div>Please find attached 赵�B.</div>",
                                  [("", "linh@cust.vn")], [("", "boss@example.com")], "Re: x", orig(), "reply",
                                  signature_html=SIG)
        problems = " ".join(ragdoll.check_message(built(msg), reply=False))
        self.assertIn("garbled", problems)
        self.assertIn("[Name]", problems)
        self.assertIn("mentions an attachment", problems)
        self.assertNotIn("mentions an attachment",
                         " ".join(ragdoll.check_message(built(msg), reply=True, attach_ok=True)))

    def test_long_to_line_folds(self):
        to = [("", "person%02d@example-company.com.vn" % i) for i in range(40)]
        raw = ragdoll.build_message("<div>x</div>", to, [], "Re: x", signature_html=SIG).as_bytes(policy=ragdoll.OUT_POLICY)
        self.assertLessEqual(max(len(x) for x in raw.split(b"\r\n")), 998)

    def test_references_fall_back_to_in_reply_to(self):
        o = parse(ORIG.replace(b"References: <root@cust.vn>\r\n", b"In-Reply-To: <root@cust.vn>\r\n"))
        m = built(ragdoll.build_message("<div>x</div>", [("", "a@b.c")], [], "Re: x", o, "reply", signature_html=SIG))
        self.assertEqual(m["References"], "<root@cust.vn> <abc@cust.vn>")

    def test_quote_strips_foreign_charset_meta_and_utc_date(self):
        o = parse(ORIG.replace(b"<p>Please", b"<html><head><meta charset=gb2312></head><body><p>Please")
                  .replace(b"+0800", b"-0000"))
        q = ragdoll.quote_block(o)
        self.assertNotIn("gb2312", q.lower())
        self.assertIn("16:10", q)        # 08:10 UTC shown as 16:10 at +08

    def test_bodystructure_continuation_charset_and_cut_names(self):
        blob = (b'("APPLICATION" "PDF" ("NAME" "COMMERCIAL INVOICE INV-0006.pd") NIL NIL "BASE64" 1 NIL '
                b'("ATTACHMENT" ("FILENAME" "COMMERCIAL INVOICE INV-0006.pdf"))) '
                b'("APPLICATION" "PDF" NIL NIL NIL "BASE64" 1 NIL ("ATTACHMENT" ("filename*0*" "utf-8\'\'%E6%8A%A5" '
                b'"filename*1*" "%E4%BB%B7.pdf"))) '
                b'("APPLICATION" "PDF" NIL NIL NIL "BASE64" 1 NIL ("ATTACHMENT" ("FILENAME*" "gb2312\'\'%B3%C2%86%B4.pdf")))')
        self.assertEqual(ragdoll.bs_names(blob), ["COMMERCIAL INVOICE INV-0006.pdf", "报价.pdf", "陈喆.pdf"])

    def test_already_sent_log(self):
        import tempfile
        old = ragdoll.CFG.d["data_dir"]
        ragdoll.CFG.d["data_dir"] = tempfile.mkdtemp()
        try:
            self.assertIsNone(ragdoll.already_sent("<a@b>"))
            ragdoll.log_sent("<a@b>", "Re: x")
            self.assertTrue(ragdoll.already_sent("<a@b>"))
            self.assertIsNone(ragdoll.already_sent("<c@b>"))
        finally:
            ragdoll.CFG.d["data_dir"] = old

    def test_in_folder_matches_exmail_rewritten_id(self):
        class M:
            def select(self, *a, **k):
                return "OK", [b"1"]

            def response(self, k):
                return k, [b"1"]

            def uid(self, cmd, *a):
                if cmd == "SEARCH":
                    return "OK", [b"5"]
                return "OK", [(b"5 (UID 5 BODY[HEADER.FIELDS (MESSAGE-ID)] {60}",
                               b"Message-ID: <E7A71F8638388FB7+1794.47644@example.com>\r\n\r\n"), b")"]
        self.assertTrue(ragdoll.in_folder(M(), "Sent Messages", "<1794.47644@example.com>"))
        self.assertFalse(ragdoll.in_folder(M(), "Sent Messages", "<94.47644@example.com>x"))

    def test_safe_unique_names(self):
        used = set()
        self.assertEqual(ragdoll.safe_name("CON.pdf"), "_CON.pdf")
        a = ragdoll.unique_path("d", "image.png", used)
        b = ragdoll.unique_path("d", "image.png", used)
        self.assertNotEqual(a, b)
        self.assertTrue(b.endswith("image (2).png"))


class Index(unittest.TestCase):
    def test_trigram_search_chinese(self):
        c = sqlite3.connect(":memory:")
        c.execute("create virtual table fts using fts5(x, tokenize='trigram')")
        c.execute("insert into fts values('回复： Fw: PO-1234-088 北京ABC项目 李明')")
        self.assertEqual(c.execute("select count(*) from fts where fts match '\"北京ABC\"'").fetchone()[0], 1)

    def test_search_offline_uses_index(self):
        old_dir, old_imap = ragdoll.CFG.d["data_dir"], ragdoll.imap
        ragdoll.CFG.d["data_dir"] = tempfile.mkdtemp()
        def no_network():
            raise OSError("network is unreachable")
        ragdoll.imap = no_network
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                c = ragdoll.quick_sync()
            self.assertIn("showing the index as it is", err.getvalue())
            c.close()
        finally:
            ragdoll.imap = old_imap
            shutil.rmtree(ragdoll.CFG.d["data_dir"], ignore_errors=True)
            ragdoll.CFG.d["data_dir"] = old_dir


class FakeIMAP:
    """Stands in for the server: keeps what was asked, says OK."""
    def __init__(self, folders, caps=("IMAP4REV1", "MOVE", "UIDPLUS")):
        self.folders, self.capabilities, self.calls = list(folders), caps, []

    def list(self):
        return "OK", [('(\\HasNoChildren) "/" "%s"' % ragdoll.mutf7(f)).encode() for f in self.folders]

    def select(self, name, readonly=True):
        self.calls.append(("select", name, readonly))
        return "OK", [b"1"]

    def response(self, code):
        return code, [b"1"]

    def uid(self, *args):
        self.calls.append(("uid",) + args)
        return "OK", [b""]

    def create(self, name):
        self.calls.append(("create", name))
        return "OK", [b""]

    def expunge(self):
        self.calls.append(("expunge",))
        return "OK", [b""]

    def logout(self):
        pass


class ListMarkMove(unittest.TestCase):
    """search / list with filters only, the total note, mark, move, archive, folders."""
    SERVER = ["INBOX", "Sent Messages", "Drafts", "Deleted Messages", "Junk", "其他文件夹", "其他文件夹/2025归档"]

    def setUp(self):
        self.old_dir, self.old_imap = ragdoll.CFG.d["data_dir"], ragdoll.imap
        ragdoll.CFG.d["data_dir"] = tempfile.mkdtemp()
        self.c = ragdoll.db()
        self.fake = FakeIMAP(self.SERVER)
        ragdoll.imap = lambda: self.fake
        self.add("INBOX", 1, "Linh <linh@cust.vn>", "Order 12", seen=0, atts="po.pdf")
        self.add("INBOX", 2, "Hoa <hoa@partner.vn>", "Drawing", flagged=1)
        self.add("INBOX", 3, "Linh <linh@cust.vn>", "Thanks", flagged=1, atts="a.dwg")
        self.add("Junk", 4, "Spam <win@spam.example>", "You won", seen=0)
        self.c.commit()

    def tearDown(self):
        self.c.close()
        ragdoll.imap = self.old_imap
        shutil.rmtree(ragdoll.CFG.d["data_dir"], ignore_errors=True)
        ragdoll.CFG.d["data_dir"] = self.old_dir

    def add(self, folder, uid, frm, subject, seen=1, flagged=0, atts=""):
        cur = self.c.execute(
            "insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,answered,"
            "has_body) values(?,1,?,?,'','',?,?,'me@example.com','',?,?,'',?,?,0,1)",
            (folder, uid, "<%d@x>" % uid, 1700000000 + uid, frm, subject, atts, seen, flagged))
        self.c.execute("insert into fts(rowid,subject,frm,to_,atts,body) values(?,?,?,?,?,'')",
                       (cur.lastrowid, subject, frm, "me@example.com", atts))

    def run_cmd(self, *argv):
        """(stdout, stderr) of one command; a refusal comes back as SystemExit."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            a = ragdoll.parser().parse_args(list(argv))
            a.fn(a)
        return out.getvalue(), err.getvalue()

    def row(self, folder, uid):
        return self.c.execute("select * from msgs where folder=? and uid=?", (folder, uid)).fetchone()

    def test_search_needs_a_word_or_a_filter(self):
        with self.assertRaises(SystemExit) as e:
            self.run_cmd("search", "--no-sync")
        self.assertIn("give a word or a filter", str(e.exception))

    def test_search_with_filters_only(self):
        ids = lambda *argv: [r["id"] for r in json.loads(self.run_cmd("search", "--no-sync", "--json", *argv)[0])]
        self.assertEqual(ids("--unread"), ["inbox:1"])                       # the unread junk mail is left out
        self.assertEqual(ids("--starred"), ["inbox:3", "inbox:2"])
        self.assertEqual(ids("--from", "linh", "--att"), ["inbox:3", "inbox:1"])
        self.assertEqual(ids("--from", "linh", "--starred", "--att"), ["inbox:3"])
        self.assertEqual(ids("--folder", "junk"), ["junk:4"])
        self.assertEqual(ids("won"), [])
        self.assertEqual(ids("won", "--folder", "junk"), ["junk:4"])

    def test_list_says_the_total_when_cut(self):
        out, _ = self.run_cmd("list", "--no-sync", "--limit", "2")
        self.assertIn("(showing the newest 2 of 3; --limit 3 shows all)", out)
        self.assertNotIn("inbox:1 ", out)
        out, _ = self.run_cmd("list", "--no-sync", "--limit", "3")
        self.assertNotIn("showing the newest", out)
        out, err = self.run_cmd("list", "--no-sync", "--limit", "2", "--json")
        self.assertEqual(len(json.loads(out)), 2)                           # the JSON stays a plain list
        self.assertIn("(showing the newest 2 of 3", err)

    def test_mark(self):
        out, _ = self.run_cmd("mark", "inbox:1", "inbox:2", "--read", "--star")
        self.assertEqual(out.strip(), "marked 2 mails read and starred")
        self.assertIn(("select", ragdoll.q("INBOX"), False), self.fake.calls)
        self.assertIn(("uid", "STORE", "1,2", "+FLAGS.SILENT", "(\\Seen)"), self.fake.calls)
        self.assertIn(("uid", "STORE", "1,2", "+FLAGS.SILENT", "(\\Flagged)"), self.fake.calls)
        self.assertEqual([(self.row("INBOX", u)["seen"], self.row("INBOX", u)["flagged"]) for u in (1, 2)], [(1, 1)] * 2)
        out, _ = self.run_cmd("mark", "inbox:3", "--unread", "--unstar")
        self.assertEqual(out.strip(), "marked 1 mail unread and not starred")
        self.assertIn(("uid", "STORE", "3", "-FLAGS.SILENT", "(\\Seen)"), self.fake.calls)
        self.assertEqual((self.row("INBOX", 3)["seen"], self.row("INBOX", 3)["flagged"]), (0, 0))

    def test_mark_refusals(self):
        with self.assertRaises(SystemExit) as e:
            self.run_cmd("mark", "inbox:1")
        self.assertIn("say what to mark", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            self.run_cmd("mark", "inbox:99", "--read")
        self.assertIn("no such mail in the index: inbox:99", str(e.exception))
        self.assertEqual(self.fake.calls, [])                               # nothing reached the server

    def test_move_to_a_server_folder(self):
        dest = "其他文件夹/2025归档"
        out, _ = self.run_cmd("move", "inbox:1", "inbox:3", "--to", dest)
        self.assertIn("moved 2 mails to " + dest, out)
        self.assertIn('ragdoll list --folder ' + dest, out)                 # not a synced folder: say how to see them
        self.assertIn(("uid", "MOVE", "1,3", ragdoll.q(dest)), self.fake.calls)
        self.assertFalse([c for c in self.fake.calls if c[0] == "create"])
        self.assertIsNone(self.row("INBOX", 1))
        self.assertIsNotNone(self.row("INBOX", 2))

    def test_move_without_the_move_command(self):
        self.fake.capabilities = ("IMAP4REV1", "UIDPLUS")
        self.run_cmd("move", "junk:4", "--to", "inbox")
        calls = [c for c in self.fake.calls if c[0] == "uid"]
        self.assertEqual(calls, [("uid", "COPY", "4", ragdoll.q("INBOX")),
                                 ("uid", "STORE", "4", "+FLAGS.SILENT", "(\\Deleted)"), ("uid", "EXPUNGE", "4")])
        self.assertIsNone(self.row("Junk", 4))

    def test_move_refusals(self):
        for to in ("trash", "Deleted Messages"):
            with self.assertRaises(SystemExit) as e:
                self.run_cmd("move", "inbox:1", "--to", to)
            self.assertIn("ragdoll trash <ids> --yes", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            self.run_cmd("move", "inbox:1", "--to", "Nowhere")
        self.assertIn("no folder 'Nowhere' on the server", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            self.run_cmd("move", "inbox:1")
        self.assertIn("say where to", str(e.exception))
        self.assertFalse([c for c in self.fake.calls if c[0] in ("uid", "create")])
        self.assertIsNotNone(self.row("INBOX", 1))

    def test_archive_makes_the_folder_once(self):
        out, _ = self.run_cmd("archive", "inbox:2")
        self.assertIn("moved 1 mail to Archive", out)
        self.assertIn(("create", ragdoll.q("Archive")), self.fake.calls)
        self.assertIn(("uid", "MOVE", "2", ragdoll.q("Archive")), self.fake.calls)
        self.fake.folders.append("Archive")
        self.fake.calls.clear()
        self.run_cmd("archive", "inbox:3")
        self.assertFalse([c for c in self.fake.calls if c[0] == "create"])

    def test_folders(self):
        rows = {d["folder"]: d for d in json.loads(self.run_cmd("folders", "--json")[0])}
        self.assertEqual(list(rows), self.SERVER)
        self.assertEqual(rows["INBOX"], {"folder": "INBOX", "short": "inbox", "indexed": 3, "unread": 1, "synced": True})
        self.assertEqual((rows["Junk"]["short"], rows["Junk"]["unread"], rows["Junk"]["synced"]), ("junk", 1, False))
        self.assertIsNone(rows["其他文件夹/2025归档"]["short"])
        out, _ = self.run_cmd("folders")
        self.assertIn("(indexed only when asked for)", out)


class ReplyForwardMarks(unittest.TestCase):
    def setUp(self):
        self.old = ragdoll.CFG.d["data_dir"]
        ragdoll.CFG.d["data_dir"] = tempfile.mkdtemp()
        self.c = ragdoll.db()

    def tearDown(self):
        self.c.close()
        shutil.rmtree(ragdoll.CFG.d["data_dir"], ignore_errors=True)
        ragdoll.CFG.d["data_dir"] = self.old

    def add(self, folder, uid, msgid, subject, fwd="", irt=""):
        self.c.execute("insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,"
                       "flagged,answered,has_body,fwd) values(?,1,?,?,?,'',?,'','','',?,'','',1,0,0,1,?)",
                       (folder, uid, msgid, irt, uid, subject, fwd))

    def flag(self, msgid):
        return self.c.execute("select forwarded from msgs where msgid=?", (msgid,)).fetchone()[0]

    def test_forward_carries_source_reply_does_not(self):
        o = orig()
        fw = ragdoll.build_message("<div>x</div>", [("", "a@b.c")], [], "Fw: x", o, "forward")
        self.assertEqual(fw[ragdoll.FWD_HEADER], "<abc@cust.vn>")
        self.assertEqual(ragdoll.forward_source(fw), "<abc@cust.vn>")
        re_ = ragdoll.build_message("<div>x</div>", [("", "a@b.c")], [], "Re: x", o, "reply")
        self.assertIsNone(re_[ragdoll.FWD_HEADER])
        self.assertEqual(ragdoll.forward_source(re_), "")

    def test_wecom_forward_with_in_reply_to(self):
        m = email.message_from_bytes(b"Subject: =?utf-8?b?6L2s5Y+R77yaIHg=?=\r\nIn-Reply-To: <o@x>\r\n\r\nx",
                                     policy=policy.default)
        self.assertEqual(ragdoll.forward_source(m), "<o@x>")

    def test_only_sent_forwards_mark_the_original(self):
        sent, drafts = ragdoll.CFG.folders["sent"], ragdoll.CFG.folders["drafts"]
        for i, mid in enumerate(("<a@x>", "<b@x>", "<c@x>"), 1):
            self.add("INBOX", i, mid, "hello")
        self.add(sent, 10, "<s1@x>", "Fw: hello", fwd="<a@x>")
        self.add(drafts, 11, "<d1@x>", "Fw: hello", fwd="<b@x>")              # not sent yet
        self.add("INBOX", 12, "<i1@x>", "Fw: hello", fwd="<c@x>", irt="<c@x>")  # someone else's forward
        ragdoll.mark_forwarded(self.c)
        self.assertEqual([self.flag(m) for m in ("<a@x>", "<b@x>", "<c@x>")], [1, 0, 0])

    def test_list_shows_marks(self):
        r = {"answered": 1, "forwarded": 1}
        self.assertEqual(ragdoll.marks(r), "↩→")
        self.assertEqual(ragdoll.marks({"answered": 0, "forwarded": 0}), "  ")
        self.add("INBOX", 1, "<a@x>", "hello")
        self.c.execute("update msgs set forwarded=1")
        row = self.c.execute("select * from msgs").fetchone()
        self.assertTrue(ragdoll.row_out(row)["forwarded"])

    def test_old_index_gets_the_columns(self):
        self.c.close()
        path = os.path.join(ragdoll.CFG.home, "index.db")
        os.remove(path)
        old = sqlite3.connect(path)
        old.execute("create table msgs(id integer primary key, folder text, uidv integer, uid integer, msgid text, "
                    "irt text, refs text, ts integer, frm text, to_ text, cc text, subject text, atts text, "
                    "body text, seen int, flagged int, answered int, size int default 0, has_body int default 0, "
                    "unique(folder, uidv, uid))")
        old.execute("insert into msgs(folder,uidv,uid,msgid,irt,subject) values('INBOX',1,1,'<o@x>','','hi')")
        old.execute("insert into msgs(folder,uidv,uid,msgid,irt,subject) values(?,1,2,'<s@x>','<o@x>','转发: hi')",
                    (ragdoll.CFG.folders["sent"],))
        old.commit()
        old.close()
        self.c = ragdoll.db()
        self.assertEqual(self.flag("<o@x>"), 1)


class OctetImages(unittest.TestCase):
    RAW = ORIG.replace(b"Content-Type: image/png\r\n",
                       b"Content-Type: application/octet-stream; name=\"image001.png\"\r\n")

    def test_octet_stream_body_image_kept_in_reply(self):
        o = email.message_from_bytes(self.RAW, policy=policy.default)
        part = [p for p in o.walk() if p.get("Content-ID")][0]
        self.assertTrue(ragdoll.is_inline(part))
        self.assertEqual(ragdoll.attachments(o), [])
        msg = ragdoll.build_message("<div>x</div>", [("", "a@b.c")], [], "Re: x", o, "reply")
        imgs = [p for p in msg.walk() if p.get("Content-ID")]
        self.assertEqual(len(imgs), 1)
        self.assertEqual(imgs[0].get_content_type(), "image/png")

    def test_octet_stream_without_name_sniffed(self):
        raw = ORIG.replace(b"Content-Type: image/png\r\n", b"Content-Type: application/octet-stream\r\n")
        o = email.message_from_bytes(raw, policy=policy.default)
        part = [p for p in o.walk() if p.get("Content-ID")][0]
        self.assertEqual(ragdoll.image_type(part), "image/png")

    def test_pdf_with_content_id_is_still_a_file(self):
        raw = ORIG.replace(b"Content-Type: image/png\r\n",
                           b"Content-Type: application/octet-stream; name=\"po.pdf\"\r\n").replace(
            b"iVBORw0KGgo=", b"JVBERi0xLjQ=")
        o = email.message_from_bytes(raw, policy=policy.default)
        part = [p for p in o.walk() if p.get("Content-ID")][0]
        self.assertFalse(ragdoll.is_inline(part))


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class Update(unittest.TestCase):
    """update against a local remote: check, update, self-test rollback, gates, rollback."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.remote = os.path.join(self.tmp, "remote")
        self.app = os.path.join(self.tmp, "app")
        os.makedirs(self.remote)
        self.git(self.remote, "init", "-q", "-b", "main")
        self.write_version("0.3.0")
        self.commit(self.remote, "First")
        subprocess.run(["git", "clone", "-q", self.remote, self.app], check=True)
        self.old = (ragdoll.CFG, os.environ.get("RAGDOLL_UPDATE_REMOTE"), ragdoll.self_test)
        ragdoll.CFG = ragdoll.Cfg(dict(ragdoll.DEFAULTS, data_dir=os.path.join(self.tmp, "data")))
        os.environ["RAGDOLL_UPDATE_REMOTE"] = self.remote
        ragdoll.self_test = lambda repo: (True, "")

    def tearDown(self):
        ragdoll.CFG, remote, ragdoll.self_test = self.old
        if remote is None:
            os.environ.pop("RAGDOLL_UPDATE_REMOTE", None)
        else:
            os.environ["RAGDOLL_UPDATE_REMOTE"] = remote

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                              check=True, capture_output=True, text=True).stdout.strip()

    def write_version(self, v):
        with open(os.path.join(self.remote, "ragdoll.py"), "w") as f:
            f.write('__version__ = "%s"\n' % v)

    def commit(self, repo, msg):
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", msg)

    def release(self, v, msg):
        self.write_version(v)
        self.commit(self.remote, msg)

    def head(self):
        return self.git(self.app, "rev-parse", "HEAD")

    def test_a_check_from_before_the_clone_moved_is_not_offered(self):
        old, ragdoll.APP_DIR = ragdoll.APP_DIR, self.app
        try:
            found = {"behind": 2, "ahead": 0, "sha": "new", "head": self.head(), "version": "0.3.1"}
            ragdoll.update_state({"latest": found})
            self.assertEqual(ragdoll.update_waiting()["version"], "0.3.1")
            ragdoll.update_state({"latest": dict(found, head="where the clone was before")})
            self.assertIsNone(ragdoll.update_waiting())
            with contextlib.redirect_stdout(io.StringIO()) as out:
                ragdoll.cmd_status(None)
            self.assertNotIn("update_available", json.loads(out.getvalue()))
        finally:
            ragdoll.APP_DIR = old

    def test_current_then_available_then_updated(self):
        self.assertEqual(ragdoll.do_update(self.app)["state"], "current")
        self.release("0.3.1", "Faster search")
        r = ragdoll.do_update(self.app, check_only=True)
        self.assertEqual((r["state"], r["current"], r["version"], r["notes"]),
                         ("available", "0.3.0", "0.3.1", ["Faster search"]))
        r = ragdoll.do_update(self.app)
        self.assertEqual(r["state"], "updated")
        self.assertEqual(self.head(), self.git(self.remote, "rev-parse", "HEAD"))
        self.assertEqual(ragdoll.update_state()["previous"]["version"], "0.3.0")
        with open(os.path.join(ragdoll.CFG.home, "logs", "update.log")) as f:
            self.assertIn("updated to 0.3.1", f.read())

    def test_failed_self_test_puts_old_version_back(self):
        before = self.head()
        self.release("0.3.1", "Broken")
        ragdoll.self_test = lambda repo: (False, "SyntaxError")
        r = ragdoll.do_update(self.app)
        self.assertEqual(r["state"], "failed")
        self.assertIn("put back", r["reason"])
        self.assertEqual(self.head(), before)
        self.assertEqual(self.git(self.app, "status", "--porcelain"), "")

    def test_refuses_local_changes_and_local_commits(self):
        self.release("0.3.1", "New")
        with open(os.path.join(self.app, "ragdoll.py"), "a") as f:
            f.write("# mine\n")
        r = ragdoll.do_update(self.app)
        self.assertEqual(r["state"], "refused")
        self.assertIn("changed files", r["reason"])
        self.commit(self.app, "Local")
        r = ragdoll.do_update(self.app)
        self.assertEqual(r["state"], "refused")
        self.assertIn("not on the remote", r["reason"])

    def test_refuses_while_another_command_runs(self):
        self.release("0.3.1", "New")
        d = os.path.join(ragdoll.CFG.home, "run")
        os.makedirs(d)
        marker = os.path.join(d, "999999-send.lock")
        f = open(marker, "a+")
        self.assertTrue(ragdoll.try_lock(f))
        r = ragdoll.do_update(self.app)
        self.assertEqual(r["state"], "refused")
        self.assertIn("send", r["reason"])
        ragdoll.unlock(f)
        f.close()
        self.assertEqual(ragdoll.busy_commands(), [])        # stale marker is cleaned up
        self.assertFalse(os.path.exists(marker))
        self.assertEqual(ragdoll.do_update(self.app)["state"], "updated")

    def test_rollback_and_skip(self):
        before = self.head()
        self.release("0.3.1", "New")
        self.assertEqual(ragdoll.do_update(self.app)["state"], "updated")
        new = self.head()
        r = ragdoll.do_rollback(self.app)
        self.assertEqual((r["state"], r["current"], r["was"]), ("rolled_back", "0.3.0", "0.3.1"))
        self.assertEqual(self.head(), before)
        self.assertEqual(ragdoll.update_state()["skip"], new)
        self.assertEqual(ragdoll.do_rollback(self.app)["state"], "refused")

    def test_no_rollback_to_old_hmail(self):
        os.rename(os.path.join(self.remote, "ragdoll.py"), os.path.join(self.remote, "hmail.py"))
        self.commit(self.remote, "Old name")
        self.git(self.app, "pull", "-q")
        self.assertEqual(ragdoll.version_at(self.app, "HEAD"), "0.3.0")      # read from hmail.py
        self.git(self.remote, "mv", "hmail.py", "ragdoll.py")
        self.release("0.4.0", "Rename")
        self.assertEqual(ragdoll.do_update(self.app)["state"], "updated")
        r = ragdoll.do_rollback(self.app)
        self.assertEqual(r["state"], "refused")
        self.assertIn("old hmail", r["reason"])

    def test_bad_remote_fails_quietly(self):
        os.environ["RAGDOLL_UPDATE_REMOTE"] = os.path.join(self.tmp, "nowhere")
        r = ragdoll.do_update(self.app)
        self.assertEqual(r["state"], "failed")
        self.assertIn("pull --ff-only", r["by_hand"])



class Rename(unittest.TestCase):
    """The first run after the rename from hmail moves the old config and data folders."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)

    def make(self, rel, text=""):
        p = os.path.join(self.home, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_moves_folders_and_fixes_paths(self):
        self.make("skills/ragdoll/sig.html", "<div>Me</div>")
        self.make(".local/share/hmail/index.db", "x")
        self.make(".config/hmail/config.json", json.dumps(
            {"user": "me@x.com", "data_dir": "~/.local/share/hmail", "signature": "~/skills/hmail/sig.html"}))
        path, over = ragdoll.move_old_setup(home=self.home)
        self.assertEqual(path, os.path.join(self.home, ".config", "ragdoll-mail", "config.json"))
        self.assertEqual(over, {})
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config", "hmail")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "share", "hmail")))
        self.assertTrue(os.path.exists(os.path.join(self.home, ".local", "share", "ragdoll-mail", "index.db")))
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual((cfg["user"], cfg["data_dir"], cfg["signature"]),
                         ("me@x.com", "~/.local/share/ragdoll-mail", "~/skills/ragdoll/sig.html"))
        self.assertEqual(ragdoll.move_old_setup(home=self.home), (path, {}))     # second run: nothing to do

    def test_default_data_dir_moves_without_rewrite(self):
        self.make(".local/share/hmail/index.db", "x")
        cfg = self.make(".config/ragdoll-mail/config.json", json.dumps({"user": "me@x.com"}))
        self.assertEqual(ragdoll.move_old_setup(home=self.home), (cfg, {}))
        self.assertTrue(os.path.exists(os.path.join(self.home, ".local", "share", "ragdoll-mail", "index.db")))
        with open(cfg, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"user": "me@x.com"})

    def test_folder_that_cannot_move_is_used_in_place(self):
        old = os.path.dirname(self.make(".local/share/hmail/index.db", "x"))
        self.make(".local/share/ragdoll-mail/other", "y")              # new one already there
        _, over = ragdoll.move_old_setup(home=self.home)
        self.assertEqual(over, {"data_dir": old})

    def test_old_env_names_still_work(self):
        old = {k: os.environ.pop(k, None) for k in ("RAGDOLL_CONFIG", "HMAIL_CONFIG")}
        try:
            os.environ["HMAIL_CONFIG"] = "/x/config.json"
            self.assertEqual(ragdoll.env("CONFIG"), "/x/config.json")
            os.environ["RAGDOLL_CONFIG"] = "/y/config.json"
            self.assertEqual(ragdoll.env("CONFIG"), "/y/config.json")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_old_import_name(self):
        import hmail
        self.assertIs(hmail, ragdoll)

class TextFixes(unittest.TestCase):
    """A base64 text cut mid-way, Tencent's entities in plain text, and the one-time repair of old rows."""
    TEXT = "Dear Ms. Linh, thank you for the order. We will ship the goods next week as agreed."

    def cut_mail(self, keep):
        b64 = base64.b64encode(self.TEXT.encode()).decode()[:keep]
        return email.message_from_bytes(
            ("From: a@b.c\r\nContent-Type: text/plain; charset=utf-8\r\n"
             "Content-Transfer-Encoding: base64\r\n\r\n" + b64).encode(), policy=policy.default)

    def test_base64_text_cut_one_character_too_far_is_read(self):
        msg = self.cut_mail(61)                 # 61 % 4 == 1: the email module gives it back undecoded
        self.assertEqual(ragdoll.b64_cut(msg), self.TEXT.encode()[:45])
        self.assertEqual(ragdoll.part_text(msg), self.TEXT[:45])
        self.assertTrue(ragdoll.body_text(msg).startswith("Dear Ms. Linh"))

    def test_base64_text_that_is_whole_is_left_alone(self):
        msg = self.cut_mail(60)
        self.assertIsNone(ragdoll.b64_cut(msg))
        self.assertEqual(ragdoll.part_text(msg), self.TEXT[:45])
        plain = email.message_from_bytes(b"Content-Type: text/plain\r\n\r\nabcde", policy=policy.default)
        self.assertIsNone(ragdoll.b64_cut(plain))

    def test_cut_inside_a_character_does_not_fail(self):
        b64 = base64.b64encode("订单已收到，谢谢。".encode()).decode()[:9]     # 6 bytes: two characters
        msg = email.message_from_bytes(
            ("Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: base64\r\n\r\n" + b64).encode(),
            policy=policy.default)
        self.assertEqual(ragdoll.part_text(msg), "订单")

    def test_entities_in_plain_text(self):
        self.assertEqual(ragdoll.plain_text("Hi John,&nbsp;price &gt; 100 &amp; rising"), "Hi John, price > 100 & rising")
        self.assertEqual(ragdoll.plain_text("use &lt;b&gt; for bold"), "use &lt;b&gt; for bold")
        self.assertEqual(ragdoll.plain_text("no entities here"), "no entities here")

    def test_old_rows_are_repaired_once(self):
        old_dir = ragdoll.CFG.d["data_dir"]
        ragdoll.CFG.d["data_dir"] = tempfile.mkdtemp()
        raw = base64.b64encode((self.TEXT * 2).encode()).decode()

        def add(c, uid, body):
            cur = c.execute(
                "insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,"
                "answered,has_body) values('INBOX',1,?,?,'','',1700000000,'a@b.c','me@example.com','','s','',?,1,0,0,1)",
                (uid, "<%d@x>" % uid, body))
            c.execute("insert into fts(rowid,subject,frm,to_,atts,body) values(?,'s','a@b.c','',\'\',?)",
                      (cur.lastrowid, body))

        def row(c, uid):
            return c.execute("select body, has_body from msgs where uid=?", (uid,)).fetchone()
        try:
            c = ragdoll.db()
            add(c, 1, raw)
            add(c, 2, "Hi John,&nbsp;see &gt; below")
            add(c, 3, "A normal text that stays as it is, with enough words to be longer than sixty characters.")
            c.execute("delete from meta where k='body_fix'")       # as an index from 0.8.0 is
            c.commit()
            c.close()
            c = ragdoll.db()
            self.assertEqual(tuple(row(c, 1)), ("", 0))            # the next sync reads it again
            self.assertEqual(tuple(row(c, 2)), ("Hi John, see > below", 1))
            self.assertEqual(row(c, 3)["has_body"], 1)
            self.assertTrue(row(c, 3)["body"].startswith("A normal text"))
            self.assertEqual(c.execute("select v from meta where k='body_fix'").fetchone()["v"], "2")
            self.assertTrue(c.execute("select 1 from fts where fts match 'below'").fetchone())
            add(c, 4, raw)
            add(c, 5, "later&nbsp;text")
            c.commit()
            c.close()
            c = ragdoll.db()                                        # the mark is there: nothing is touched
            self.assertEqual(tuple(row(c, 4)), (raw, 1))
            self.assertEqual(tuple(row(c, 5)), ("later&nbsp;text", 1))
            c.close()
        finally:
            shutil.rmtree(ragdoll.CFG.d["data_dir"], ignore_errors=True)
            ragdoll.CFG.d["data_dir"] = old_dir


BIG_STRUCTURE = (b'(("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL "7BIT" 60 2 NIL NIL NIL) '
                 b'("IMAGE" "PNG" ("NAME" "p.png") "<pic1@x>" NIL "BASE64" 300000 NIL ("ATTACHMENT" ("FILENAME" "p.png")) NIL) '
                 b'("APPLICATION" "PDF" ("NAME" "big.pdf") NIL NIL "BASE64" 400000 NIL ("ATTACHMENT" ("FILENAME" "big.pdf")) NIL) '
                 b'"MIXED" ("BOUNDARY" "B") NIL NIL)')
BIG_PARTS = {
    "HEADER": b"From: Linh <linh@cust.vn>\r\nTo: me@example.com\r\nSubject: Drawing\r\nMIME-Version: 1.0\r\n"
              b"X-Ragdoll-Part: 9\r\nContent-Type: multipart/mixed; boundary=\"B\"\r\n\r\n",
    "1.MIME": b"Content-Type: text/html; charset=utf-8\r\n\r\n",
    "1": b"<p>See the picture.</p><img src=\"cid:pic1@x\">",
    "2.MIME": b"Content-Type: image/png; name=\"p.png\"\r\nContent-ID: <pic1@x>\r\n"
              b"Content-Disposition: attachment; filename=\"p.png\"\r\nContent-Transfer-Encoding: base64\r\n\r\n",
    "2": b"iVBORw0KGgo=",
    # the sender's own X-Ragdoll-Part must not be taken for ours
    "3.MIME": b"Content-Type: application/pdf; name=\"big.pdf\"\r\nX-Ragdoll-Part: 1] BODY[\r\n"
              b"Content-Disposition: attachment; filename=\"big.pdf\"\r\nContent-Transfer-Encoding: base64\r\n\r\n",
    "3": b"JVBERi0xLjQ=",
}


class BigMailServer(FakeIMAP):
    """Answers FETCH for one mail (UID 7) from BIG_STRUCTURE and BIG_PARTS, the way imaplib hands it over."""
    def __init__(self, structure=BIG_STRUCTURE, parts=BIG_PARTS, blind=0):
        super().__init__(["INBOX"])
        self.structure, self.parts, self.blind, self.noops = structure, parts, blind, 0

    def noop(self):
        self.noops += 1
        self.blind = 0                  # now the connection sees the mail that just came in
        return "OK", [b""]

    def uid(self, cmd, *args):
        self.calls.append(("uid", cmd) + args)
        if cmd != "FETCH" or args[0] != "7" or self.blind:
            return "OK", [None]
        if "BODYSTRUCTURE" in args[1]:
            return "OK", [b"1 (UID 7 BODYSTRUCTURE " + self.structure + b")"]
        if args[1] == "(BODY.PEEK[])":
            return "OK", [(b"1 (UID 7 BODY[] {5}", b"whole"), b")"]
        data = []
        for k, name in enumerate(re.findall(r"BODY\.PEEK\[([^\]]+)\]", args[1])):
            lit = self.parts[name]
            data.append((b"%sBODY[%s] {%d}" % (b" " if k else b"1 (UID 7 ", name.encode(), len(lit)), lit))
        return "OK", data + [b")"]

    def fetches(self):
        return [c for c in self.calls if c[:2] == ("uid", "FETCH")]


class LightMail(unittest.TestCase):
    """A big mail without its big files, the single file fetched later, and a mail the connection has not seen yet."""

    def test_structure_is_read(self):
        bs = ragdoll.fetch_items([b"1 (UID 7 BODYSTRUCTURE " + BIG_STRUCTURE + b")"], 7)[b"BODYSTRUCTURE"]
        parts, multis = ragdoll.leaves(bs)
        self.assertEqual(multis, [""])
        self.assertEqual([p[:3] for p in parts], [("1", "text", "html"), ("2", "image", "png"), ("3", "application", "pdf")])
        self.assertEqual(parts[1][3:], (False, "base64", 300000, "pic1@x"))    # marked as a file: not "shown"
        self.assertEqual(parts[2][5:], (400000, ""))
        self.assertEqual(ragdoll.fetch_items([b"1 (UID 8 BODYSTRUCTURE " + BIG_STRUCTURE + b")"], 7), {})

    def test_parse_keeps_literals_and_quotes(self):
        got = ragdoll.imap_parse([(b'1 (UID 7 BODY[1.MIME] {5}', b"a (b)"), b' X "q \\"r\\"" NIL)'])
        self.assertEqual(got, [b"1", [b"UID", b"7", b"BODY[1.MIME]", b"a (b)", b"X", b'q "r"', None]])

    def test_single_part_mail_is_not_made_light(self):
        self.assertIsNone(ragdoll.leaves(ragdoll.imap_parse([b'("TEXT" "PLAIN" NIL NIL NIL "7BIT" 10 1)'])[0]))
        m = BigMailServer(structure=b'("TEXT" "PLAIN" NIL NIL NIL "7BIT" 10 1)')
        self.assertIsNone(ragdoll.fetch_light(m, "INBOX", 7))

    def test_big_file_is_left_out_and_the_picture_in_the_body_is_not(self):
        m = BigMailServer()
        raw = ragdoll.fetch_light(m, "INBOX", 7)
        msg = ragdoll.to_msg(raw)
        self.assertNotIn("X-Ragdoll-Part", msg)                     # the one the sender put in the mail header
        html, pic, pdf = msg.get_payload()
        self.assertIn("cid:pic1@x", ragdoll.part_text(html))
        # the body shows it, though it is marked as a file and over the size for files: it came with the mail
        self.assertEqual(pic.get_payload(decode=True), base64.b64decode("iVBORw0KGgo="))
        self.assertIsNone(pic["X-Ragdoll-Part"])
        self.assertEqual(pdf.get_all("X-Ragdoll-Part"), ["3"])      # ours only, not the sender's
        self.assertEqual(pdf["X-Ragdoll-Size"], str(int(400000 * 57 / 78)))
        self.assertEqual(ragdoll.fname(pdf), "big.pdf")
        self.assertFalse(pdf.get_payload().strip())
        asked = " ".join(c[3] for c in m.fetches())
        self.assertIn("BODY.PEEK[2]", asked)
        self.assertNotIn("BODY.PEEK[3]", asked)

    def test_picture_the_body_does_not_show_stays_out(self):
        parts = dict(BIG_PARTS, **{"1": b"<p>No picture here.</p>"})
        m = BigMailServer(parts=parts)
        html, pic, pdf = ragdoll.to_msg(ragdoll.fetch_light(m, "INBOX", 7)).get_payload()
        self.assertEqual(pic["X-Ragdoll-Part"], "2")
        self.assertNotIn("BODY.PEEK[2]", " ".join(c[3] for c in m.fetches()))

    def test_structure_that_cannot_be_read_falls_back_to_the_whole_mail(self):
        # a part with too few fields
        self.assertIsNone(ragdoll.fetch_light(BigMailServer(structure=b'(("TEXT") "MIXED")'), "INBOX", 7))
        # no boundary to build it with
        parts = dict(BIG_PARTS, HEADER=b"From: a@b.c\r\nContent-Type: multipart/mixed\r\n\r\n")
        self.assertIsNone(ragdoll.fetch_light(BigMailServer(parts=parts), "INBOX", 7))
        # the server gave no header at all
        self.assertIsNone(ragdoll.fetch_light(BigMailServer(parts=dict(BIG_PARTS, HEADER=b"")), "INBOX", 7))

        class Odd(BigMailServer):
            def uid(self, cmd, *args):
                if cmd == "FETCH" and "BODYSTRUCTURE" in args[1]:
                    return "OK", [b"1 (UID 7 BODYSTRUCTURE (((NIL NIL) NIL) 5))"]
                return super().uid(cmd, *args)
        self.assertIsNone(ragdoll.fetch_light(Odd(), "INBOX", 7))

    def test_mail_the_connection_has_not_seen_is_asked_for_again(self):
        m = BigMailServer(blind=1)
        self.assertEqual(ragdoll.fetch_raw(m, "INBOX", 7), b"whole")
        self.assertEqual((m.noops, len(m.fetches())), (1, 2))
        m = BigMailServer(blind=1)
        self.assertEqual(ragdoll.fetch_one(m, 7, "(UID BODYSTRUCTURE)")[b"UID"], b"7")
        self.assertEqual(m.noops, 1)
        m = BigMailServer(blind=1)
        self.assertTrue(ragdoll.fetch_light(m, "INBOX", 7))
        m = BigMailServer()
        self.assertEqual(ragdoll.fetch_raw(m, "INBOX", 7), b"whole")
        self.assertEqual(m.noops, 0)                                # the usual case costs nothing more

    def test_mail_that_is_gone_is_still_refused(self):
        m = BigMailServer()
        with self.assertRaises(SystemExit):
            ragdoll.fetch_raw(m, "INBOX", 8)
        self.assertEqual((m.noops, len(m.fetches())), (1, 2))       # asked once more, not for ever

    def test_one_part_is_fetched_with_its_headers(self):
        m = BigMailServer()
        raw = ragdoll.fetch_part_raw(m, "INBOX", 7, "3")
        self.assertNotIn(b"X-Ragdoll", raw)
        p = ragdoll.fetch_part(m, "INBOX", 7, "3")
        self.assertEqual((ragdoll.fname(p), ragdoll.part_bytes(p)), ("big.pdf", b"%PDF-1.4"))

    def test_part_number_must_be_a_part_number(self):
        for bad in ("1] BODY[", "", "1.", ".1", "1 2", "HEADER", "1\r\nA1 DELETE x", None, "1.a"):
            m = BigMailServer()
            with self.assertRaises(SystemExit, msg=repr(bad)):
                ragdoll.fetch_part_raw(m, "INBOX", 7, bad)
            self.assertEqual(m.calls, [], repr(bad))                # nothing reached the server
        for good in ("1", "2.1", "10.2.3"):
            self.assertTrue(ragdoll.SECTION_RE.fullmatch(good))

    def test_part_file_is_kept_beside_the_light_mail(self):
        light, part = ragdoll.light_path("INBOX", 1, 7), ragdoll.part_path("INBOX", 1, 7, "2.1")
        self.assertEqual(os.path.dirname(light), os.path.dirname(part))
        self.assertTrue(os.path.basename(part).startswith(os.path.basename(light)[:-len(".light.eml")] + ".part"))
        self.assertNotEqual(part, ragdoll.part_path("INBOX", 1, 7, "2"))


class HeldFlags(unittest.TestCase):
    """A sync asks the server for flags; a mark the app made a moment ago may not be there yet."""

    class Server(FakeIMAP):
        def uid(self, cmd, *args):
            self.calls.append(("uid", cmd) + args)
            if cmd == "SEARCH":
                return "OK", [b"1 2"]
            return "OK", [b"1 (UID 1 FLAGS ())", b"2 (UID 2 FLAGS (\\Flagged))"]

    def setUp(self):
        self.old_dir = ragdoll.CFG.d["data_dir"]
        ragdoll.CFG.d["data_dir"] = tempfile.mkdtemp()
        self.c = ragdoll.db()
        for uid in (1, 2):
            self.c.execute(
                "insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,"
                "answered,has_body) values('INBOX',1,?,?,'','',1700000000,'a@b.c','me@example.com','','s','','',1,0,0,1)",
                (uid, "<%d@x>" % uid))
        self.c.commit()

    def tearDown(self):
        self.c.close()
        shutil.rmtree(ragdoll.CFG.d["data_dir"], ignore_errors=True)
        ragdoll.CFG.d["data_dir"] = self.old_dir

    def flags(self):
        return [tuple(r) for r in self.c.execute("select seen, flagged from msgs order by uid")]

    def test_server_flags_win_when_nothing_is_held(self):
        ragdoll.sync_headers(self.Server(["INBOX"]), self.c, "INBOX")
        self.assertEqual(self.flags(), [(0, 0), (0, 1)])

    def test_mark_on_its_way_is_not_undone(self):
        asked = []

        def held(folder, since):
            asked.append((folder, since))
            return {1: {"seen": 1}, 2: {"flagged": 0}}
        ragdoll.sync_headers(self.Server(["INBOX"]), self.c, "INBOX", held=held)
        self.assertEqual(self.flags(), [(1, 0), (0, 0)])            # the rest still follows the server
        self.assertEqual(asked[0][0], "INBOX")
        self.assertLessEqual(asked[0][1], time.time())


if __name__ == "__main__":
    unittest.main()


class AppBridge(unittest.TestCase):
    """The ragdoll command made from the app, hand-offs to the app, send later, the index version."""

    def setUp(self):
        self.old = ragdoll.CFG.d["data_dir"]
        ragdoll.CFG.d["data_dir"] = tempfile.mkdtemp()
        self.home = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(ragdoll.CFG.d["data_dir"], ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)
        ragdoll.CFG.d["data_dir"] = self.old

    @unittest.skipIf(sys.platform == "win32", "the launcher and PATH are a POSIX shell's here")
    def test_install_cli_makes_launcher_and_path_once(self):
        r = ragdoll.install_cli(self.home)
        self.assertTrue(r["made"])
        path = os.path.join(self.home, ".local", "bin", "ragdoll")
        self.assertEqual(r["path"], path)
        self.assertTrue(os.access(path, os.X_OK))
        out = subprocess.run([path, "--version"], capture_output=True, text=True, env=dict(os.environ, HOME=self.home))
        self.assertIn(ragdoll.__version__, out.stdout)
        self.assertTrue(r["path_added"])
        with open(r["path_added"], encoding="utf-8") as f:
            self.assertEqual(f.read().count(".local/bin"), 1)
        again = ragdoll.install_cli(self.home)
        self.assertFalse(again["made"])
        self.assertIsNone(again["path_added"])          # already on the PATH: the profile is not touched twice

    @unittest.skipIf(sys.platform == "win32", "POSIX launcher")
    def test_install_cli_keeps_a_launcher_it_did_not_make(self):
        d = os.path.join(self.home, ".local", "bin")
        os.makedirs(d)
        with open(os.path.join(d, "ragdoll"), "w") as f:
            f.write("#!/bin/sh\nexec python3 -I /my/clone/ragdoll.py \"$@\"\n")
        r = ragdoll.install_cli(self.home)
        self.assertTrue(r["kept"])
        self.assertFalse(r["made"])
        with open(os.path.join(d, "ragdoll")) as f:
            self.assertIn("/my/clone/", f.read())

    def test_asks_are_read_once_and_old_ones_dropped(self):
        ragdoll.tell_app("open", "inbox:5", "Hello")
        ragdoll.tell_app("draft", "drafts:7", "Re: Hello")
        got = ragdoll.take_asks()
        self.assertEqual([(x["kind"], x["id"]) for x in got], [("open", "inbox:5"), ("draft", "drafts:7")])
        self.assertEqual(ragdoll.take_asks(), [])
        ragdoll.tell_app("open", "inbox:6")
        self.assertEqual(ragdoll.take_asks(max_age=-1), [])

    def test_parse_when(self):
        now = ragdoll.dt.datetime(2026, 11, 21, 10, 0, tzinfo=ragdoll.CFG.tz)
        self.assertEqual(ragdoll.parse_when("+2h", now), now + ragdoll.dt.timedelta(hours=2))
        self.assertEqual(ragdoll.parse_when("09:00", now).day, 22)        # 9:00 has passed: tomorrow
        self.assertEqual(ragdoll.parse_when("11:30", now).day, 21)
        self.assertEqual(ragdoll.parse_when("2026-12-01 08:15", now).hour, 8)
        with self.assertRaises(ValueError):
            ragdoll.parse_when("tomorrow", now)

    def run_cli(self, *argv):
        """Run one command here as the shell would: (exit code, stdout, stderr)."""
        out, err, code = io.StringIO(), io.StringIO(), 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                a = ragdoll.parser().parse_args(list(argv))
                a.fn(a)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    print(e.code, file=sys.stderr)
            except LookupError as e:
                code = 1
                print(e, file=sys.stderr)
        return code, out.getvalue(), err.getvalue()

    def test_schedule_needs_yes_and_a_draft(self):
        code, out, err = self.run_cli("schedule", "inbox:5", "--at", "+1h", "--yes")
        self.assertNotEqual(code, 0)
        code, out, err = self.run_cli("schedule", "drafts:9", "--at", "+1h")
        self.assertIn("--yes", err)
        self.assertEqual(ragdoll.sched_read(), [])
        code, out, err = self.run_cli("schedule", "drafts:9", "--at", "+1h", "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual([x["id"] for x in ragdoll.sched_read()], ["drafts:9"])
        self.assertGreater(ragdoll.sched_read()[0]["at"], time.time() + 3000)
        code, out, err = self.run_cli("schedule", "--list", "--json")
        self.assertEqual(json.loads(out)[0]["id"], "drafts:9")
        code, out, err = self.run_cli("schedule", "drafts:9", "--cancel")
        self.assertEqual(code, 0, err)
        self.assertEqual(ragdoll.sched_read(), [])

    def test_index_from_a_newer_version_is_refused(self):
        c = ragdoll.db()
        self.assertEqual(c.execute("select v from meta where k='schema'").fetchone()[0], str(ragdoll.SCHEMA_VERSION))
        c.execute("insert or replace into meta values('schema', ?)", (str(ragdoll.SCHEMA_VERSION + 1),))
        c.commit()
        c.close()
        with self.assertRaises(ragdoll.IndexTooNew):
            ragdoll.db()
        code, out, err = self.run_cli("status")
        self.assertNotEqual(code, 0)
        self.assertIn("newer Ragdoll Mail", err)


class PasswordFromShell(unittest.TestCase):
    """An app opened from the Dock does not get the variables the shell profile exports."""

    def setUp(self):
        self.saved = (ragdoll.FROZEN, ragdoll.keychain_get, ragdoll.subprocess.run, dict(ragdoll._SHELL_ENV),
                      ragdoll.CFG.d.get("password_env"))
        ragdoll.CFG.d["password_env"] = "RAGDOLL_TEST_PW_X"
        os.environ.pop("RAGDOLL_TEST_PW_X", None)
        ragdoll._SHELL_ENV.clear()
        ragdoll.keychain_get = lambda *a, **k: None
        self.calls = []

        def run(argv, **kw):
            self.calls.append(argv)
            out = "" if argv[0] == "launchctl" else "s3cret\n"
            return subprocess.CompletedProcess(argv, 0, stdout=out)
        ragdoll.subprocess.run = run

    def tearDown(self):
        ragdoll.FROZEN, ragdoll.keychain_get, ragdoll.subprocess.run, old, ragdoll.CFG.d["password_env"] = self.saved
        ragdoll._SHELL_ENV.clear()
        ragdoll._SHELL_ENV.update(old)

    def test_the_app_asks_the_login_shell_once(self):
        ragdoll.FROZEN = True
        self.assertEqual(ragdoll.find_password(), "s3cret")
        self.assertEqual(ragdoll.find_password(), "s3cret")
        shells = [c for c in self.calls if c[0] != "launchctl"]
        self.assertEqual(len(shells), 1)                         # asked once, then remembered
        self.assertEqual(shells[0][-1], "printenv RAGDOLL_TEST_PW_X")

    def test_a_terminal_does_not_ask_the_shell(self):
        ragdoll.FROZEN = False
        self.assertIsNone(ragdoll.find_password())
        self.assertEqual(self.calls, [])

    def test_odd_variable_names_are_never_put_in_a_command(self):
        self.assertIsNone(ragdoll.shell_env("X; rm -rf ~"))
        self.assertEqual(self.calls, [])
