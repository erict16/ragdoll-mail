"""Offline tests: python -m unittest discover -s tests"""
import email, os, shutil, sqlite3, subprocess, sys, tempfile, unittest
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
                b'("IMAGE" "PNG" ("NAME" "A71D6834@7680436B.0A0FF86A00000000.png") NIL) '
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
    def build(self, body="<div>Dear Linh,</div><div>Noted, thank you.</div>", **kw):
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


def parse(raw):
    return email.message_from_bytes(raw, policy=policy.default)


def built(msg):
    return parse(msg.as_bytes(policy=hmail.OUT_POLICY))


class Charsets(unittest.TestCase):
    """16th Nov 2026: 赵珺 labelled GB2312 became 赵�B in the To line of a reply."""

    def test_gb2312_label_with_gbk_character(self):
        m = parse(b"From: =?GB2312?B?1dSsQg==?= <rose@x.cn>\r\nTo: me@example.com\r\nSubject: s\r\n\r\nx\r\n")
        self.assertEqual(hmail.hdr(m, "From"), "赵珺 <rose@x.cn>")
        to, _ = hmail.reply_recipients(m, False, "me@example.com")
        self.assertEqual(to, [("赵珺", "rose@x.cn")])
        self.assertIn("赵珺", hmail.quote_block(m))

    def test_gb2312_body(self):
        m = parse(b"From: a@b.c\r\nSubject: s\r\nContent-Type: text/plain; charset=gb2312\r\n"
                  b"Content-Transfer-Encoding: 8bit\r\n\r\n" + "赵珺你好".encode("gbk") + b"\r\n")
        self.assertEqual(hmail.body_text(m), "赵珺你好")

    def test_raw_8bit_gbk_headers_and_filename(self):
        raw = (b"From: " + "赵珺".encode("gbk") + b" <z@x.cn>\r\nSubject: " + "报价".encode("gbk") +
               b"\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=\"B\"\r\n\r\n--B\r\n"
               b"Content-Type: text/plain; charset=utf-8\r\n\r\nhi\r\n--B\r\nContent-Type: application/pdf\r\n"
               b"Content-Disposition: attachment; filename=\"" + "报价.pdf".encode("gbk") + b"\"\r\n\r\nx\r\n--B--\r\n")
        m = parse(raw)
        self.assertEqual(hmail.hdr(m, "From"), "赵珺 <z@x.cn>")
        self.assertEqual(hmail.hdr(m, "Subject"), "报价")
        self.assertEqual([hmail.fname(p) for p in hmail.attachments(m)], ["报价.pdf"])

    def test_big5(self):
        m = parse(b"From: a@b.c\r\nSubject: =?big5?B?" + __import__("base64").b64encode("碁€".encode("cp950")) +
                  b"?=\r\n\r\nx\r\n")
        self.assertEqual(hmail.hdr(m, "Subject"), "碁€")

    def test_unknown_charset_does_not_crash(self):
        m = parse(b"From: a@b.c\r\nSubject: s\r\nContent-Type: text/plain; charset=unknown-8bit\r\n\r\n"
                  + "Chào anh".encode("utf-8") + b"\r\n")
        self.assertEqual(hmail.body_text(m), "Chào anh")

    def test_vietnamese_nfc(self):
        decomposed = "Trả lời: Order 1"
        self.assertEqual(hmail.bare_subject(decomposed), "order 1")

    def test_broken_name_falls_back_to_bare_address(self):
        to, cc = hmail.clean_recipients([("赵�B", "rose@x.cn")], [], set())
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
        plain, html = hmail.bodies(m)
        self.assertIn("OUTER TEXT", plain)
        self.assertEqual(html, "")
        self.assertEqual([hmail.fname(p) for p in hmail.attachments(m)], ["fwd.eml"])
        self.assertIn(b"inner.pdf", hmail.part_bytes(hmail.attachments(m)[0]))

    def test_forward_keeps_the_eml(self):
        msg = hmail.build_message("<div>pls</div>", [("", "x@y.z")], [], "Fw: s", parse(self.RAW), "forward",
                                  signature_html=SIG)
        self.assertEqual([hmail.fname(p) for p in hmail.attachments(built(msg))], ["fwd.eml"])

    def test_pdf_with_content_id_is_a_file(self):
        raw = ORIG.replace(b"--B--", b"--B\r\nContent-Type: application/pdf; name=\"spec.pdf\"\r\n"
                           b"Content-ID: <p1>\r\nContent-Transfer-Encoding: base64\r\n\r\nJVBERg==\r\n--B--")
        msg = hmail.build_message("<div>pls</div>", [("", "x@y.z")], [], "Fw: x", parse(raw), "forward",
                                  signature_html=SIG)
        self.assertEqual([hmail.fname(p) for p in hmail.attachments(built(msg))], ["spec.pdf"])


class Safety(unittest.TestCase):
    def test_replace_only_takes_drafts(self):
        with self.assertRaises(SystemExit):
            hmail.drafts_only("inbox:9255", "--replace")
        self.assertEqual(hmail.drafts_only("drafts:3", "--replace"), ("Drafts", 3))

    def test_parse_people(self):
        self.assertEqual(hmail.parse_people('"Tan, Eric" <Eric@X.com>; b@c.d'), [("Tan, Eric", "eric@x.com"),
                                                                                ("", "b@c.d")])
        with self.assertRaises(SystemExit):
            hmail.parse_people("not an address")

    def test_check_catches_garble_placeholder_and_missing_attachment(self):
        msg = hmail.build_message("<div>Dear [Name],</div><div>Please find attached 赵�B.</div>",
                                  [("", "linh@cust.vn")], [("", "boss@example.com")], "Re: x", orig(), "reply",
                                  signature_html=SIG)
        problems = " ".join(hmail.check_message(built(msg), reply=False))
        self.assertIn("garbled", problems)
        self.assertIn("[Name]", problems)
        self.assertIn("mentions an attachment", problems)
        self.assertNotIn("mentions an attachment",
                         " ".join(hmail.check_message(built(msg), reply=True, attach_ok=True)))

    def test_long_to_line_folds(self):
        to = [("", "person%02d@example-company.com.vn" % i) for i in range(40)]
        raw = hmail.build_message("<div>x</div>", to, [], "Re: x", signature_html=SIG).as_bytes(policy=hmail.OUT_POLICY)
        self.assertLessEqual(max(len(x) for x in raw.split(b"\r\n")), 998)

    def test_references_fall_back_to_in_reply_to(self):
        o = parse(ORIG.replace(b"References: <root@cust.vn>\r\n", b"In-Reply-To: <root@cust.vn>\r\n"))
        m = built(hmail.build_message("<div>x</div>", [("", "a@b.c")], [], "Re: x", o, "reply", signature_html=SIG))
        self.assertEqual(m["References"], "<root@cust.vn> <abc@cust.vn>")

    def test_quote_strips_foreign_charset_meta_and_utc_date(self):
        o = parse(ORIG.replace(b"<p>Please", b"<html><head><meta charset=gb2312></head><body><p>Please")
                  .replace(b"+0800", b"-0000"))
        q = hmail.quote_block(o)
        self.assertNotIn("gb2312", q.lower())
        self.assertIn("16:10", q)        # 08:10 UTC shown as 16:10 at +08

    def test_bodystructure_continuation_charset_and_cut_names(self):
        blob = (b'("APPLICATION" "PDF" ("NAME" "COMMERCIAL INVOICE ES26-006.pd") NIL NIL "BASE64" 1 NIL '
                b'("ATTACHMENT" ("FILENAME" "COMMERCIAL INVOICE ES26-006.pdf"))) '
                b'("APPLICATION" "PDF" NIL NIL NIL "BASE64" 1 NIL ("ATTACHMENT" ("filename*0*" "utf-8\'\'%E6%8A%A5" '
                b'"filename*1*" "%E4%BB%B7.pdf"))) '
                b'("APPLICATION" "PDF" NIL NIL NIL "BASE64" 1 NIL ("ATTACHMENT" ("FILENAME*" "gb2312\'\'%D5%D4%ACB.pdf")))')
        self.assertEqual(hmail.bs_names(blob), ["COMMERCIAL INVOICE ES26-006.pdf", "报价.pdf", "赵珺.pdf"])

    def test_already_sent_log(self):
        import tempfile
        old = hmail.CFG.d["data_dir"]
        hmail.CFG.d["data_dir"] = tempfile.mkdtemp()
        try:
            self.assertIsNone(hmail.already_sent("<a@b>"))
            hmail.log_sent("<a@b>", "Re: x")
            self.assertTrue(hmail.already_sent("<a@b>"))
            self.assertIsNone(hmail.already_sent("<c@b>"))
        finally:
            hmail.CFG.d["data_dir"] = old

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
                               b"Message-ID: <E7A71F8638388FB7+1794.47644@huaming.com>\r\n\r\n"), b")"]
        self.assertTrue(hmail.in_folder(M(), "Sent Messages", "<1794.47644@huaming.com>"))
        self.assertFalse(hmail.in_folder(M(), "Sent Messages", "<94.47644@huaming.com>x"))

    def test_safe_unique_names(self):
        used = set()
        self.assertEqual(hmail.safe_name("CON.pdf"), "_CON.pdf")
        a = hmail.unique_path("d", "image.png", used)
        b = hmail.unique_path("d", "image.png", used)
        self.assertNotEqual(a, b)
        self.assertTrue(b.endswith("image (2).png"))


class Index(unittest.TestCase):
    def test_trigram_search_chinese(self):
        c = sqlite3.connect(":memory:")
        c.execute("create virtual table fts using fts5(x, tokenize='trigram')")
        c.execute("insert into fts values('回复： Fw: E-W260084-088 越南MEE 夏洁平')")
        self.assertEqual(c.execute("select count(*) from fts where fts match '\"越南MEE\"'").fetchone()[0], 1)


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
        self.old = (hmail.CFG, os.environ.get("HMAIL_UPDATE_REMOTE"), hmail.self_test)
        hmail.CFG = hmail.Cfg(dict(hmail.DEFAULTS, data_dir=os.path.join(self.tmp, "data")))
        os.environ["HMAIL_UPDATE_REMOTE"] = self.remote
        hmail.self_test = lambda repo: (True, "")

    def tearDown(self):
        hmail.CFG, remote, hmail.self_test = self.old
        if remote is None:
            os.environ.pop("HMAIL_UPDATE_REMOTE", None)
        else:
            os.environ["HMAIL_UPDATE_REMOTE"] = remote

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                              check=True, capture_output=True, text=True).stdout.strip()

    def write_version(self, v):
        with open(os.path.join(self.remote, "hmail.py"), "w") as f:
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
        self.assertEqual(hmail.do_update(self.app)["state"], "current")
        self.release("0.3.1", "Faster search")
        r = hmail.do_update(self.app, check_only=True)
        self.assertEqual((r["state"], r["current"], r["version"], r["notes"]),
                         ("available", "0.3.0", "0.3.1", ["Faster search"]))
        r = hmail.do_update(self.app)
        self.assertEqual(r["state"], "updated")
        self.assertEqual(self.head(), self.git(self.remote, "rev-parse", "HEAD"))
        self.assertEqual(hmail.update_state()["previous"]["version"], "0.3.0")
        with open(os.path.join(hmail.CFG.home, "logs", "update.log")) as f:
            self.assertIn("updated to 0.3.1", f.read())

    def test_failed_self_test_puts_old_version_back(self):
        before = self.head()
        self.release("0.3.1", "Broken")
        hmail.self_test = lambda repo: (False, "SyntaxError")
        r = hmail.do_update(self.app)
        self.assertEqual(r["state"], "failed")
        self.assertIn("put back", r["reason"])
        self.assertEqual(self.head(), before)
        self.assertEqual(self.git(self.app, "status", "--porcelain"), "")

    def test_refuses_local_changes_and_local_commits(self):
        self.release("0.3.1", "New")
        with open(os.path.join(self.app, "hmail.py"), "a") as f:
            f.write("# mine\n")
        r = hmail.do_update(self.app)
        self.assertEqual(r["state"], "refused")
        self.assertIn("changed files", r["reason"])
        self.commit(self.app, "Local")
        r = hmail.do_update(self.app)
        self.assertEqual(r["state"], "refused")
        self.assertIn("not on the remote", r["reason"])

    def test_refuses_while_another_command_runs(self):
        self.release("0.3.1", "New")
        d = os.path.join(hmail.CFG.home, "run")
        os.makedirs(d)
        marker = os.path.join(d, "999999-send.lock")
        f = open(marker, "a+")
        self.assertTrue(hmail.try_lock(f))
        r = hmail.do_update(self.app)
        self.assertEqual(r["state"], "refused")
        self.assertIn("send", r["reason"])
        hmail.unlock(f)
        f.close()
        self.assertEqual(hmail.busy_commands(), [])        # stale marker is cleaned up
        self.assertFalse(os.path.exists(marker))
        self.assertEqual(hmail.do_update(self.app)["state"], "updated")

    def test_rollback_and_skip(self):
        before = self.head()
        self.release("0.3.1", "New")
        self.assertEqual(hmail.do_update(self.app)["state"], "updated")
        new = self.head()
        r = hmail.do_rollback(self.app)
        self.assertEqual((r["state"], r["current"], r["was"]), ("rolled_back", "0.3.0", "0.3.1"))
        self.assertEqual(self.head(), before)
        self.assertEqual(hmail.update_state()["skip"], new)
        self.assertEqual(hmail.do_rollback(self.app)["state"], "refused")

    def test_bad_remote_fails_quietly(self):
        os.environ["HMAIL_UPDATE_REMOTE"] = os.path.join(self.tmp, "nowhere")
        r = hmail.do_update(self.app)
        self.assertEqual(r["state"], "failed")
        self.assertIn("pull --ff-only", r["by_hand"])


if __name__ == "__main__":
    unittest.main()
