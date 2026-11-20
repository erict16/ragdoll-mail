"""Edge cases found by stress testing. Offline: python -m unittest discover -s tests"""
import email, os, sqlite3, sys, tempfile, time, unittest
from email import policy
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll as R  # noqa: E402


def parse(raw):
    return email.message_from_bytes(raw, policy=policy.default)


def index(rows):
    """An in-memory index with rows of (msgid, irt, refs, subject, frm, body, ts)."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(R.SCHEMA)
    for k, (mid, irt, refs, subject, frm, body, ts) in enumerate(rows, 1):
        c.execute("insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,"
                  "answered,has_body) values('INBOX',1,?,?,?,?,?,?,'','',?,'',?,1,0,0,1)",
                  (k, mid, irt, refs, ts, frm, subject, body))
        c.execute("insert into fts(rowid,subject,frm,to_,atts,body) values(?,?,?,'','',?)", (k, subject, frm, body))
    return c


def ns(**k):
    d = dict(limit=50, folder=None, from_=None, to=None, since=None, until=None, unread=False, att=False)
    d.update(k)
    return SimpleNamespace(**d)


class Stress(unittest.TestCase):
    def setUp(self):
        self.old = R.CFG
        self.tmp = tempfile.mkdtemp()
        R.CFG = R.Cfg(dict(R.DEFAULTS, user="me@example.com", name="Me", utc_offset_hours=8,
                           signature_marks=["+1 555 0100"], require_cc=["boss@example.com"],
                           data_dir=os.path.join(self.tmp, "data")))

    def tearDown(self):
        R.CFG = self.old
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_thread_links_follow_new_and_deleted_mail(self):
        c = index([("<a@x>", "", "", "Quote", "A <a@x>", "", 1000),
                   ("<b@x>", "<a@x>", "<a@x>", "Re: Quote", "B <b@x>", "", 2000)])
        row = c.execute("select * from msgs where uid=1").fetchone()
        self.assertEqual([r["uid"] for r in R.thread_rows(c, row)], [1, 2])
        c.execute("insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,"
                  "answered,has_body) values('INBOX',1,3,'<c@x>','<b@x>','<a@x> <b@x>',3000,'','','','Other','','',1,0,0,1)")
        self.assertEqual([r["uid"] for r in R.thread_rows(c, row)], [1, 2, 3])
        c.execute("delete from msgs where uid=2")
        self.assertEqual([r["uid"] for r in R.thread_rows(c, row)], [1, 3])
        self.assertEqual(c.execute("select count(*) from links where id=2").fetchone()[0], 0)

    def test_read_commands_skip_the_server_right_after_a_sync(self):
        c = R.db()
        c.execute("insert or replace into meta values('last_sync', ?)", (str(int(time.time())),))
        c.commit()
        old = R.imap
        R.imap = lambda: self.fail("the server was asked again")
        try:
            R.quick_sync().close()
            c.execute("insert or replace into meta values('last_sync', ?)", (str(int(time.time()) - 600),))
            c.commit()
            with self.assertRaises(AssertionError):
                R.quick_sync()
        finally:
            R.imap = old
            c.close()

    def test_a_kept_mail_is_read_without_the_server(self):
        c = R.db()
        c.execute("insert into msgs(folder,uidv,uid,msgid,subject) values('INBOX',7,42,'<k@x>','kept')")
        c.commit()
        c.close()
        R.cache_put(R.cache_path("INBOX", 7, 42), b"Subject: kept\r\n\r\nhello")
        old = R.imap
        R.imap = lambda: self.fail("the server was asked")
        try:
            self.assertIn(b"hello", R.mail_raw("INBOX", 42))
        finally:
            R.imap = old

    def test_parse_id_rejects_bad_ids_cleanly(self):
        # these raised TypeError / ValueError / OverflowError, which the app does not catch
        for bad in (None, 5, True, ["inbox:1"], "inbox:", "inbox:abc", "inbox:1e3", "inbox:-1", "inbox:0",
                    "inbox:99999999999999999999", "inbox:١٢", ":5", "5"):
            with self.assertRaises(SystemExit, msg=repr(bad)):
                R.parse_id(bad)
        self.assertEqual(R.parse_id("inbox:9255"), (R.CFG.folder("inbox"), 9255))
        self.assertEqual(R.parse_id("inbox: 7"), (R.CFG.folder("inbox"), 7))

    def test_local_time_out_of_range(self):
        self.assertEqual(R.local_time(10 ** 13), "?")
        self.assertEqual(R.local_time(-10 ** 12), "?")
        self.assertRegex(R.local_time(0), r"^1970-01-01")

    def test_day_start_bad_date_is_a_message(self):
        for bad in ("2026-13-01", "yesterday", ""):
            with self.assertRaises(SystemExit):
                R.day_start(bad)
        self.assertIsInstance(R.day_start("2026-11-16"), int)

    def test_search_percent_and_underscore_are_literal(self):
        c = index([("<a@x>", "", "", "Price 50% off", "a@x.com", "body one", 1),
                    ("<b@x>", "", "", "Hello", "b_c@x.com", "body two", 2),
                    ("<c@x>", "", "", "Other", "c@x.com", "plain", 3)])
        subj = lambda rows: sorted(r["subject"] for r in rows)
        self.assertEqual(subj(R.search_rows(c, ["%"], ns())), ["Price 50% off"])
        self.assertEqual(subj(R.search_rows(c, ["_"], ns())), ["Hello"])
        self.assertEqual(subj(R.search_rows(c, ["\\"], ns())), [])
        self.assertEqual(subj(R.search_rows(c, [], ns(from_="%"))), [])
        self.assertEqual(subj(R.search_rows(c, [], ns(from_="b_c"))), ["Hello"])
        self.assertEqual(subj(R.search_rows(c, [], ns(to="_"))), [])

    def test_search_huge_word_is_fast(self):
        c = index([("<a@x>", "", "", "invoice", "a@x.com", "x" * 500, 1)])
        t = time.time()
        R.search_rows(c, ["x" * 1000000], ns())
        R.search_rows(c, ["a"] * 10000, ns())
        self.assertLess(time.time() - t, 2)

    def test_thread_without_message_ids_stays_alone(self):
        # a mail with no Message-ID used to collect every mail that is not a reply
        c = index([("", "", "", "Scan 1", "a@x.com", "", 1000),
                   ("<b@x>", "", "", "Lunch", "b@x.com", "", 1001),
                   ("<c@x>", "", "", "Quote", "c@x.com", "", 1002),
                   ("<d@x>", "<c@x>", "<c@x>", "Re: Quote", "d@x.com", "", 1003)])
        row = c.execute("select * from msgs where uid=1").fetchone()
        self.assertEqual([r["subject"] for r in R.thread_rows(c, row)], ["Scan 1"])
        row = c.execute("select * from msgs where uid=3").fetchone()
        self.assertEqual([r["subject"] for r in R.thread_rows(c, row)], ["Quote", "Re: Quote"])

    def test_thread_underscore_in_message_id_is_literal(self):
        c = index([("<a_1@x>", "", "", "One", "a@x.com", "", 1),
                   ("<z@x>", "", "<aX1@x>", "Two", "b@x.com", "", 2)])
        row = c.execute("select * from msgs where uid=1").fetchone()
        self.assertEqual([r["subject"] for r in R.thread_rows(c, row)], ["One"])

    def test_html_to_text_many_open_brackets_is_fast(self):
        t = time.time()
        self.assertEqual(len(R.html_to_text("<" * 200000)), 200000)
        self.assertEqual(R.html_to_text("a <b>bold</b> < c"), "a bold < c")
        self.assertLess(time.time() - t, 2)

    def test_table_check_broken_html_is_fast(self):
        t = time.time()
        R.table_problems("<table>" + "<td colspan=" * 20000, -1, False)
        R.table_problems("<table><tr><td>" * 5000, -1, False)
        self.assertLess(time.time() - t, 2)
        html = ('<table style="word-break:normal"><tr><td>a</td><td></td><td colspan="2">-</td></tr></table>')
        p = R.table_problems(html, -1, False)
        self.assertIn("a 4-column table has no fixed pixel width", p)
        self.assertTrue(any(x.startswith("1 blank") for x in p), p)

    def test_safe_name_long_name_fits_the_disk(self):
        for name in ("长" * 200 + ".pdf", "x" * 300 + ".docx", "y" * 300):
            n = R.safe_name(name)
            self.assertLessEqual(len(n.encode()), 200)
            self.assertEqual(os.path.splitext(n)[1], os.path.splitext(name)[1])
            p = R.unique_path(self.tmp, n, set())
            with open(p, "wb") as f:
                f.write(b"x")
        self.assertEqual(R.safe_name("a.pdf"), "a.pdf")

    def test_single_part_file_is_an_attachment(self):
        m = parse(b"Subject: scan\r\nContent-Type: application/pdf; name=\"scan.pdf\"\r\n"
                  b"Content-Disposition: attachment; filename=\"scan.pdf\"\r\nContent-Transfer-Encoding: base64\r\n\r\n"
                  b"JVBERg==\r\n")
        self.assertEqual([R.fname(p) for p in R.attachments(m)], ["scan.pdf"])
        self.assertEqual(R.attachments(parse(b"Subject: x\r\nContent-Type: text/plain\r\n\r\nhi")), [])
        fw = R.build_message("<p>fyi</p>", [("", "a@b.com")], [], "Fw: scan", m, "forward")
        self.assertEqual([R.fname(p) for p in R.attachments(fw)], ["scan.pdf"])

    def test_line_breaks_in_headers_do_not_break_the_draft(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        att = os.path.join(d, "new\nline.txt")
        try:
            with open(att, "wb") as f:
                f.write(b"x")
        except OSError:         # Windows: no line break allowed in a file name
            att = None
        m = R.build_message("<p>hi</p>", [("Ann\r\nBcc: evil@x.com", "ann@x.com")], [],
                            "line1\r\nBcc: evil@x.com", attach=[att] if att else [])
        back = parse(m.as_bytes(policy=R.OUT_POLICY))
        self.assertIsNone(back["Bcc"])
        self.assertEqual(R.hdr(back, "Subject"), "line1 Bcc: evil@x.com")
        if att:
            self.assertEqual([R.fname(p) for p in R.attachments(back)], ["new line.txt"])
        self.assertEqual(R.addrs(R.hdr(back, "To")), [("Ann Bcc: evil@x.com", "ann@x.com")])


if __name__ == "__main__":
    unittest.main()
