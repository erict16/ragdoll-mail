"""Offline tests: python -m unittest discover -s tests"""
import contextlib, email, io, json, os, shutil, sqlite3, subprocess, sys, tempfile, unittest
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

if __name__ == "__main__":
    unittest.main()
