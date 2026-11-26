"""Comprehensive tests for roadmap features #115-#124, Windows packaging, and Windows icon fix."""
import contextlib, io, json, mailbox, os, shutil, sys, tempfile, time, unittest
from email.message import EmailMessage
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll as R  # noqa: E402
import ragdoll_app as A  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def make_raw(frm="Alice <alice@example.com>", to="you@example.com", subj="Hello", body="Hi there",
             html=None, mid="<m1@example.com>", irt=None, list_hdr=False, ics=False):
    msg = EmailMessage()
    msg["From"] = frm
    msg["To"] = to
    msg["Subject"] = subj
    msg["Date"] = "Wed, 25 Nov 2026 10:00:00 +0800"
    msg["Message-ID"] = mid
    if irt:
        msg["In-Reply-To"] = irt
        msg["References"] = irt
    if list_hdr:
        msg["List-Unsubscribe"] = "<https://example.com/unsub>"
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    if ics:
        msg.add_attachment("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n", subtype="calendar", filename="invite.ics")
    return msg.as_bytes(policy=R.OUT_POLICY)


class MultiAccountTest(unittest.TestCase):
    """#115: Multi-account config loading, isolation, and CLI account selection."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cfg_path = os.path.join(self.tmp, "config.json")
        self.data_base = os.path.join(self.tmp, "data")
        cfg = {
            "data_dir": self.data_base,
            "default_account": "work",
            "accounts": [
                {"id": "work", "label": "Work", "user": "alice@work.example", "name": "Alice Work",
                 "imap": {"host": "imap.work.example", "port": 993},
                 "smtp": {"host": "smtp.work.example", "port": 465}},
                {"id": "personal", "label": "Personal", "user": "alice@home.example", "name": "Alice Home",
                 "imap": {"host": "imap.home.example", "port": 993},
                 "smtp": {"host": "smtp.home.example", "port": 465}},
            ],
        }
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def test_list_and_load_accounts(self):
        accs = R.list_accounts(self.cfg_path)
        self.assertEqual([a["id"] for a in accs], ["work", "personal"])
        self.assertTrue(accs[0]["is_default"])
        self.assertFalse(accs[1]["is_default"])
        c1 = R.load_config(self.cfg_path)
        self.assertEqual(c1.user, "alice@work.example")
        self.assertEqual(c1.home, self.data_base)
        c2 = R.load_config(self.cfg_path, account="personal")
        self.assertEqual(c2.user, "alice@home.example")
        self.assertIn("personal", c2.home)
        self.assertNotEqual(c1.home, c2.home)
        c3 = R.load_config(self.cfg_path, account="alice@home.example")
        self.assertEqual(c3.user, "alice@home.example")
        with self.assertRaises(LookupError):
            R.load_config(self.cfg_path, account="nonexistent")


class MarkdownAndThreadFullTest(unittest.TestCase):
    """#116: Stdlib html_to_markdown, read --markdown, thread --full --markdown."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old_cfg = R.CFG
        d = json.loads(json.dumps(R.DEFAULTS))
        d.update(user="you@example.com", name="Alex", data_dir=self.tmp)
        R.CFG = R.Cfg(d)
        self.addCleanup(setattr, R, "CFG", self.old_cfg)

    def test_html_to_markdown(self):
        h = ('<h1>Summary</h1><p>Hello <b>world</b> and <i>team</i>. '
             'See <a href="https://example.com/doc">the doc</a>.</p>'
             '<ul><li>First</li><li>Second</li></ul>'
             '<blockquote>Quoted line</blockquote>'
             '<table><tr><th>Item</th><th>Qty</th></tr><tr><td>Bolt</td><td>10</td></tr></table>')
        md = R.html_to_markdown(h)
        self.assertIn("# Summary", md)
        self.assertIn("**world**", md)
        self.assertIn("*team*", md)
        self.assertIn("[the doc](https://example.com/doc)", md)
        self.assertIn("- First", md)
        self.assertIn("> Quoted line", md)
        self.assertIn("| Bolt | 10 |", md)

    def test_thread_full_markdown_and_max_chars(self):
        c = R.db()
        raw1 = make_raw(subj="Order 42", body="Initial message body", html="<p>Initial <b>body</b></p>", mid="<t1@ex>")
        raw2 = make_raw(subj="Re: Order 42", body="Follow up reply body", html="<p>Follow <i>reply</i></p>", mid="<t2@ex>", irt="<t1@ex>")
        A.index_raw(c, "INBOX", 1, 10, raw1, 1000, 1, 0)
        A.index_raw(c, "Sent Messages", 1, 20, raw2, 2000, 1, 0)
        for f, u, raw in (("INBOX", 10, raw1), ("Sent Messages", 20, raw2)):
            R.cache_put(R.cache_path(f, 1, u), raw)
        buf = io.StringIO()
        args = R.parser().parse_args(["thread", "inbox:10", "--full", "--markdown", "--max-chars", "50", "--json", "--no-sync"])
        with contextlib.redirect_stdout(buf):
            R.cmd_thread(args)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data), 2)
        self.assertIn("**body**", data[0]["markdown"])
        self.assertIn("*reply*", data[1]["markdown"])


class TemplatesAliasesSearchTest(unittest.TestCase):
    """#117 Templates, #118 Search operators, #120 Aliases/Reply-To, #121 People vs Newsletters, #122-#124."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old_cfg = R.CFG
        d = json.loads(json.dumps(R.DEFAULTS))
        d.update(user="you@example.com", name="Alex", data_dir=self.tmp,
                 aliases=["Sales <sales@example.com>"], reply_to="support@example.com")
        R.CFG = R.Cfg(d)
        self.addCleanup(setattr, R, "CFG", self.old_cfg)

    def test_templates_and_render(self):
        R.save_templates([{"name": "quote", "subject": "Quote for {{po}}", "body": "Hi {{name}}, total is {{amount}}.", "html": False}])
        loaded = R.load_templates()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(R.render_template(loaded[0]["body"], {"name": "Jane", "amount": "$500"}), "Hi Jane, total is $500.")
        # Unfilled variables remain intact so pre-send check catches them
        self.assertIn("{{amount}}", R.render_template(loaded[0]["body"], {"name": "Jane"}))

    def test_aliases_and_reply_to(self):
        msg = R.build_message("<p>Hi</p>", [("Bob", "bob@example.com")], [], "Hi",
                              from_addr="sales@example.com", reply_to="custom@example.com")
        self.assertIn("sales@example.com", msg["From"])
        self.assertIn("Sales", msg["From"])
        self.assertEqual(msg["Reply-To"], "custom@example.com")
        msg_def = R.build_message("<p>Hi</p>", [("Bob", "bob@example.com")], [], "Hi")
        self.assertEqual(msg_def["Reply-To"], "support@example.com")
        with self.assertRaises(SystemExit):
            R.build_message("<p>Hi</p>", [("Bob", "bob@example.com")], [], "Hi", from_addr="spoof@evil.com")

    def test_search_operators_and_people_vs_newsletters(self):
        c = R.db()
        A.index_raw(c, "INBOX", 1, 1, make_raw(frm="Jane <jane@acme.com>", subj="Q4 Invoice", body="See attached", mid="<s1@ex>", ics=True), 1764000000, 0, 0, 1)
        A.index_raw(c, "INBOX", 1, 2, make_raw(frm="News <news@acme.com>", subj="Weekly Digest", body="Promo deal", mid="<s2@ex>", list_hdr=True), 1764100000, 1, 0, 0)
        spec = R.parse_search_query('from:acme is:people has:invite -Promo')
        ns = SimpleNamespace(limit=20, offset=0, **spec)
        rows = R.search_rows(c, spec["words"], ns)
        self.assertEqual([r["uid"] for r in rows], [1])
        spec2 = R.parse_search_query("is:newsletter")
        rows2 = R.search_rows(c, [], SimpleNamespace(limit=20, offset=0, **spec2))
        self.assertEqual([r["uid"] for r in rows2], [2])
        spec3 = R.parse_search_query("is:starred filename:.ics")
        rows3 = R.search_rows(c, [], SimpleNamespace(limit=20, offset=0, **spec3))
        self.assertEqual([r["uid"] for r in rows3], [1])

    def test_dry_run_and_export(self):
        c = R.db()
        raw = make_raw(subj="Export Me", body="Hello export", mid="<exp1@ex>")
        A.index_raw(c, "INBOX", 1, 7, raw, 1764000000, 0, 0)
        R.cache_put(R.cache_path("INBOX", 1, 7), raw)
        # --dry-run mark & archive do not require IMAP or mutate DB
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.cmd_mark(R.parser().parse_args(["mark", "inbox:7", "--read", "--dry-run", "--json"]))
        self.assertTrue(json.loads(buf.getvalue())["dry_run"])
        self.assertEqual(c.execute("select seen from msgs where uid=7").fetchone()[0], 0)
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            R.cmd_move(R.parser().parse_args(["archive", "inbox:7", "--dry-run", "--json"]))
        self.assertEqual(json.loads(buf2.getvalue())["count"], 1)
        # export to .eml dir and .mbox
        out_dir = os.path.join(self.tmp, "emls")
        mbox_file = os.path.join(self.tmp, "out.mbox")
        buf3 = io.StringIO()
        with contextlib.redirect_stdout(buf3):
            R.cmd_export(R.parser().parse_args(["export", "inbox:7", "--out", out_dir, "--mbox", mbox_file, "--json"]))
        res = json.loads(buf3.getvalue())
        self.assertEqual(res["exported"], 1)
        self.assertTrue(any(f.endswith(".eml") for f in os.listdir(out_dir)))
        mb = mailbox.mbox(mbox_file)
        try:
            self.assertEqual(len(mb), 1)
        finally:
            mb.close()

    def test_remind_and_mute_cli(self):
        c = R.db()
        A.index_raw(c, "INBOX", 1, 5, make_raw(subj="Follow up", mid="<r5@ex>"), 1764000000, 0, 0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.cmd_remind(R.parser().parse_args(["remind", "inbox:5", "--at", "+2h", "--if-no-reply", "--json"]))
        self.assertEqual(json.loads(buf.getvalue())["kind"], "followup")
        self.assertEqual(len(R.remind_read()), 1)
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            R.cmd_mute(R.parser().parse_args(["mute", "inbox:5", "--json"]))
        self.assertTrue(json.loads(buf2.getvalue())["muted"])
        self.assertTrue(R.is_thread_muted(R.muted_read(), irt="<r5@ex>", subject="Re: Follow up"))
        with contextlib.redirect_stdout(io.StringIO()):
            R.cmd_mute(R.parser().parse_args(["mute", "inbox:5", "--unmute", "--json"]))
        self.assertFalse(R.is_thread_muted(R.muted_read(), irt="<r5@ex>", subject="Re: Follow up"))


class DemoBackendRoadmapTest(unittest.TestCase):
    """End-to-end backend tests in demo mode for #117-#124."""
    def setUp(self):
        self.b = A.Backend(demo=True, demo_lang="en")
        self.addCleanup(self.b.close)

    def test_demo_backend_apis(self):
        boot = self.b.api_boot({})
        self.assertIn("accounts", boot)
        self.assertIn("aliases", boot)
        # People vs Newsletters filter
        people = self.b.api_list({"folder": "inbox", "kind": "people"})["rows"]
        news = self.b.api_list({"folder": "inbox", "kind": "newsletters"})["rows"]
        self.assertTrue(len(people) > 0)
        self.assertTrue(len(news) > 0)
        self.assertTrue(all(not r["is_list"] for r in people))
        self.assertTrue(all(r["is_list"] for r in news))
        # Saved searches pref
        p = self.b.api_prefs({"saved_searches": [{"name": "Quotes", "q": "quote has:attachment"}]})
        self.assertEqual(len(p["saved_searches"]), 1)
        # Templates API
        t = self.b.api_save_templates({"templates": [{"name": "Followup", "subject": "Checking in", "body": "Hi {{name}}", "html": False}]})
        self.assertEqual(t["templates"][0]["name"], "Followup")
        self.assertEqual(len(self.b.api_templates({})["templates"]), 1)
        # Search operators
        res = self.b.api_search({"q": "has:invite"})["rows"]
        self.assertTrue(len(res) >= 1)
        with self.assertRaises(A.ApiError):
            self.b.api_search({"q": "since:not-a-date"})
        # Snooze & unsnooze
        first_id = people[0]["id"]
        self.b.api_snooze({"id": first_id, "at": int(time.time()) + 3600})
        snoozed = self.b.api_list({"folder": "snoozed"})["rows"]
        self.assertEqual(len(snoozed), 1)
        # Simulate snooze due -> moves back to inbox and emits reminder notice
        items = R.remind_read()
        items[0]["at"] = int(time.time()) - 10
        R.remind_write(items)
        fired = self.b.process_reminders()
        self.assertEqual(fired, 1)
        self.assertEqual(len(self.b.rem_due), 1)
        # Mute & unmute
        target_id = people[1]["id"]
        mres = self.b.api_mute({"id": target_id})
        self.assertTrue(mres["muted"])
        self.assertEqual(len(self.b.api_muted({})["muted"]), 1)
        self.b.api_unmute({"id": target_id})
        self.assertEqual(len(self.b.api_muted({})["muted"]), 0)


class PackagingAndHygieneTest(unittest.TestCase):
    def _read(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            return f.read()

    def test_inno_setup_script_and_ci(self):
        iss = self._read("packaging", "windows", "ragdoll-mail.iss")
        self.assertIn("PrivilegesRequired=lowest", iss)
        self.assertIn("UninstallFilesDir={localappdata}\\RagdollMail\\Uninstall", iss)
        self.assertIn("Ragdoll Mail.exe", iss)
        self.assertIn("ragdoll.exe", iss)
        wf = self._read(".github", "workflows", "build.yml")
        self.assertIn("concurrency:", wf)
        self.assertIn("ragdoll-mail-windows-setup.exe", wf)

    def test_windows_icon_is_not_png(self):
        src = self._read("ragdoll_app.py")
        self.assertIn('logo.ico" if sys.platform == "win32"', src)

    def test_version_consistency(self):
        pyproj = self._read("pyproject.toml")
        self.assertIn('version = "%s"' % R.__version__, pyproj)


if __name__ == "__main__":
    unittest.main()
