"""Offline tests of the desktop app's local server, in demo mode (no account, no network)."""
import contextlib, http.client, io, json, os, queue, re, shutil, subprocess, sys, tempfile, threading, time, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll_app as A  # noqa: E402
REAL_OPEN_PATH = A.open_path      # the Files tests put a stand-in in its place

TOKEN = "test-token"


class AppServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = A.R.CFG                       # demo mode swaps the config; the CLI tests need it back
        cls.backend = A.Backend(demo=True)
        cls.srv = A.Server(("127.0.0.1", 0), A.make_handler(cls.backend, TOKEN))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.backend.close()
        cls.srv.shutdown()
        shutil.rmtree(A.R.CFG.home, ignore_errors=True)
        A.R.CFG = cls.cfg

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % self.port}
        h.update(headers or {})
        c.request(method, path, body, h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def api(self, name, args=None, token=TOKEN):
        code, data = self.req("POST", "/api/" + name, json.dumps(args or {}), {"X-Token": token})
        return code, json.loads(data)

    def test_page_and_assets(self):
        code, body = self.req("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"app.js", body)
        self.assertEqual(self.req("GET", "/style.css")[0], 200)

    def test_no_path_escape(self):
        self.assertEqual(self.req("GET", "/../ragdoll.py")[0], 404)
        self.assertEqual(self.req("GET", "/%2e%2e/ragdoll.py")[0], 404)

    def test_token_required(self):
        self.assertEqual(self.api("boot", token="wrong")[0], 403)
        self.assertEqual(self.api("boot", token="")[0], 403)

    def test_foreign_host_refused(self):
        code, _ = self.req("POST", "/api/boot", "{}", {"X-Token": TOKEN, "Host": "evil.example:80"})
        self.assertEqual(code, 403)

    def test_boot_and_list(self):
        code, out = self.api("boot")
        self.assertEqual(code, 200)
        self.assertTrue(out["ok"])
        self.assertTrue(out["data"]["demo"])
        code, out = self.api("list", {"folder": "inbox"})
        self.assertTrue(out["ok"])
        self.assertTrue(out["data"]["rows"])

    def test_refused_post_does_not_break_the_connection(self):
        # a refused POST must not leave its body behind for the next request on a kept-alive connection
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % self.port, "Content-Type": "application/json"}
        c.request("POST", "/api/boot", "{}", dict(h, **{"X-Token": "wrong"}))
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 403)
        c.request("POST", "/api/boot", "{}", dict(h, **{"X-Token": TOKEN}))
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertTrue(json.loads(r.read())["ok"])
        c.request("POST", "/api/boot", "{}", dict(h, **{"X-Token": TOKEN}))
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        r.read()
        c.close()

    def draft(self, subject):
        _, out = self.api("prepare_send", {"mode": "new", "to": [{"name": "", "addr": "pat@example.com"}],
                                           "subject": subject, "html": "<p>Hello Pat</p>", "atts": []})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["problems"], [])
        return out["data"]["id"]

    def test_scheduled_send(self):
        import time
        i = self.draft("Scheduled hello")
        at = int(time.time()) + 3600
        self.assertTrue(self.api("schedule", {"id": i, "at": at})[1]["ok"])
        rows = self.api("list", {"folder": "scheduled"})[1]["data"]["rows"]
        self.assertEqual([(r["id"], r["sched"]) for r in rows], [(i, at)])
        drafts = self.api("list", {"folder": "drafts"})[1]["data"]["rows"]
        self.assertEqual([r.get("sched") for r in drafts if r["id"] == i], [at])
        keys = [f["key"] for f in self.api("status")[1]["data"]["folders"]]
        self.assertIn("scheduled", keys)
        self.assertEqual(self.backend.send_due(now=at - 10), 0)
        self.assertEqual(self.backend.send_due(now=at + 1), 1)
        self.assertEqual(self.api("list", {"folder": "scheduled"})[1]["data"]["rows"], [])
        sent = self.api("list", {"folder": "sent"})[1]["data"]["rows"]
        self.assertIn("Scheduled hello", [r["subject"] for r in sent])

    def test_unschedule_keeps_the_draft(self):
        import time
        i = self.draft("Not yet")
        self.api("schedule", {"id": i, "at": int(time.time()) + 600})
        self.assertTrue(self.api("unschedule", {"id": i})[1]["ok"])
        self.assertEqual(self.api("list", {"folder": "scheduled"})[1]["data"]["rows"], [])
        self.assertEqual(self.backend.send_due(now=time.time() + 7200), 0)
        drafts = self.api("list", {"folder": "drafts"})[1]["data"]["rows"]
        self.assertIn(i, [r["id"] for r in drafts])
        self.api("delete_draft", {"id": i})

    def test_schedule_refuses_the_past(self):
        i = self.draft("Too late")
        _, out = self.api("schedule", {"id": i, "at": 1000})
        self.assertFalse(out["ok"])
        self.api("delete_draft", {"id": i})

    def test_failed_scheduled_send_is_kept_with_its_reason(self):
        import time
        i = self.draft("Gone")
        self.api("schedule", {"id": i, "at": int(time.time()) + 60})
        self.backend.demo_delete(i)            # the draft vanished (deleted in another mail app)
        self.assertEqual(self.backend.send_due(now=time.time() + 120), 0)
        left = [x for x in self.backend.sched_list() if x["id"] == i]
        self.assertTrue(left and left[0].get("error"))
        self.assertEqual(self.backend.send_due(now=time.time() + 240), 0)   # not tried again by itself
        self.api("unschedule", {"id": i})

    def test_prefs_are_checked(self):
        out = self.api("prefs", {"lang": "zh-Hant", "tz": "Asia/Taipei", "undo": 10})[1]["data"]
        self.assertEqual((out["lang"], out["tz"], out["undo"]), ("zh-Hant", "Asia/Taipei", 10))
        out = self.api("prefs", {"lang": "xx", "tz": "../../etc", "undo": 7})[1]["data"]
        self.assertEqual((out["lang"], out["tz"], out["undo"]), ("zh-Hant", "Asia/Taipei", 10))
        self.assertEqual(self.api("boot")[1]["data"]["prefs"]["lang"], "zh-Hant")
        self.api("prefs", {"lang": "system", "tz": "system", "undo": 5})

    def test_look_prefs_are_checked(self):
        out = self.api("prefs", {"font": "georgia", "font_size": 16, "text_size": 15, "fmt_bar": True})[1]["data"]
        self.assertEqual((out["font"], out["font_size"], out["text_size"], out["fmt_bar"]), ("georgia", 16, 15, True))
        out = self.api("prefs", {"font": "comic; x", "font_size": 99, "text_size": "15", "fmt_bar": "yes"})[1]["data"]
        self.assertEqual((out["font"], out["font_size"], out["text_size"], out["fmt_bar"]), ("georgia", 16, 15, True))
        self.api("prefs", {"font": "system", "font_size": 14, "text_size": 14, "fmt_bar": False})

    def test_folded_folders_pref_is_checked(self):
        out = self.api("prefs", {"folded": ["@mine", "Projects"]})[1]["data"]
        self.assertEqual(out["folded"], ["@mine", "Projects"])
        for bad in ("Projects", [1], [""], ["x" * 501], ["a"] * 501):
            self.assertEqual(self.api("prefs", {"folded": bad})[1]["data"]["folded"], ["@mine", "Projects"])
        self.api("prefs", {"folded": []})

    def test_prefs_widths_and_sidebar(self):
        out = self.api("prefs", {"list_width": 420, "side_width": 260, "side_hidden": True})[1]["data"]
        self.assertEqual((out["list_width"], out["side_width"], out["side_hidden"]), (420, 260, True))
        # not a whole number in range, or not a true/false: the saved value stays
        for bad in ({"list_width": "420px;color:red"}, {"list_width": 9999}, {"side_width": 1.5}, {"side_width": -3},
                    {"side_width": True}, {"side_width": "260"}, {"side_hidden": "yes"}):
            out = self.api("prefs", bad)[1]["data"]
            self.assertEqual((out["list_width"], out["side_width"], out["side_hidden"]), (420, 260, True))
        out = self.api("prefs", {"side_width": 0, "side_hidden": False})[1]["data"]
        self.assertEqual((out["side_width"], out["side_hidden"]), (0, False))

    def test_flagged_list_and_count(self):
        rows = self.api("list", {"folder": "inbox"})[1]["data"]["rows"]
        i = next(r["id"] for r in rows if not r["flagged"])

        def flagged():
            ids = [r["id"] for r in self.api("list", {"folder": "flagged"})[1]["data"]["rows"]]
            n = {f["key"]: f for f in self.api("status")[1]["data"]["folders"]}["flagged"]
            return ids, n
        before, _ = flagged()
        self.assertTrue(self.api("mark", {"ids": [i], "flag": "flagged", "on": True})[1]["ok"])
        after, _ = flagged()
        self.assertEqual(set(after) - set(before), {i})
        self.api("mark", {"ids": [i], "flag": "flagged", "on": False})
        self.assertNotIn(i, flagged()[0])

    def test_bad_input_gets_a_message(self):
        for name, args in (("mark", {"ids": 5}), ("mark", {"ids": [1, 2]}), ("move", {"to": "trash", "ids": {"a": 1}}),
                           ("list", {"folder": "inbox", "limit": "lots", "offset": 1e300}),
                           ("search", {"q": ["x"]}), ("contacts", {"q": 7}), ("schedule", {"id": "x", "at": 1e400})):
            code, out = self.api(name, args)
            self.assertIn(code, (200, 400, 500), name)
            self.assertIn("ok", out, name)
        code, out = self.req("POST", "/api/list", json.dumps([1, 2]), {"X-Token": TOKEN})
        self.assertEqual(code, 400)
        rows = self.api("list", {"folder": "inbox", "limit": "lots"})[1]["data"]["rows"]
        self.assertTrue(rows)

    def test_moved_draft_is_no_longer_scheduled(self):
        import time
        i = self.draft("Move me")
        self.api("schedule", {"id": i, "at": int(time.time()) + 600})
        self.assertTrue(self.api("move", {"ids": [i], "to": "trash"})[1]["ok"])
        self.assertNotIn(i, [x["id"] for x in self.backend.sched_list()])
        self.assertEqual(self.backend.send_due(now=time.time() + 7200), 0)

    def test_demo_ids_are_not_reused(self):
        a = self.draft("First")
        self.api("delete_draft", {"id": a})
        b = self.draft("Second")
        self.assertNotEqual(a, b)
        self.api("delete_draft", {"id": b})

    def test_unknown_call(self):
        code, out = self.api("nope")
        self.assertEqual(code, 404)
        self.assertFalse(out["ok"])

    def rows(self, folder, **more):
        return self.api("list", dict(more, folder=folder))[1]["data"]["rows"]

    def test_list_filters(self):
        every = self.rows("inbox")
        ids = lambda rows: [r["id"] for r in rows]
        self.assertEqual(ids(self.rows("inbox", unread=True)), ids([r for r in every if r["unread"]]))
        self.assertEqual(ids(self.rows("inbox", att=True)), ids([r for r in every if r["atts"]]))
        self.assertTrue(self.rows("inbox", unread=True) and self.rows("inbox", att=True))
        i = every[0]["id"]
        self.api("mark", {"ids": [i], "flag": "flagged", "on": True})
        self.assertIn(i, ids(self.rows("inbox", starred=True)))
        self.assertTrue(all(r["flagged"] for r in self.rows("inbox", starred=True)))
        self.api("mark", {"ids": [i], "flag": "flagged", "on": False})
        who = every[0]["from"]["addr"]
        one = self.rows("inbox", **{"from": who})
        self.assertEqual(ids(one), ids([r for r in every if r["from"]["addr"] == who]))
        both = self.rows("inbox", unread=True, **{"from": who})
        self.assertEqual(ids(both), ids([r for r in one if r["unread"]]))
        self.assertEqual(self.rows("inbox", **{"from": "100%_nobody"}), [])   # typed text is not a pattern

    def test_senders(self):
        people = self.api("senders", {"folder": "inbox"})[1]["data"]["people"]
        self.assertTrue(0 < len(people) <= 6)
        seen = {r["from"]["addr"] for r in self.rows("inbox")}
        self.assertTrue(all(p["addr"] in seen for p in people))
        self.assertNotIn(A.R.CFG.user, [p["addr"] for p in people])
        self.assertEqual(self.api("senders", {"folder": "scheduled"})[1]["data"]["people"], [])

    def test_junk_and_other_folders(self):
        fs = {f["key"]: f for f in self.api("status")[1]["data"]["folders"]}
        self.assertIn("junk", fs)
        self.assertTrue(self.rows("junk"))
        self.assertEqual({r["folder"] for r in self.rows("junk")}, {"junk"})
        self.assertEqual((fs["Projects"]["other"], fs["Projects"]["depth"], fs["Projects"]["label"]), (True, 0, "Projects"))
        self.assertEqual((fs["Projects/Acme"]["depth"], fs["Projects/Acme"]["label"]), (1, "Acme"))
        self.assertFalse(fs["inbox"].get("other"))

    def test_move_to_other_folder_and_junk(self):
        subject = "Moved around %d" % os.getpid()
        self.backend.demo_insert(A.R.CFG.folders["inbox"], A.demo_message(
            "inbox", 1790000000, ("Mover", "mover@example.com"), [A.ME], [], subject, "x", [],
            A.make_msgid(domain="example.com"), None, None), 1790000000, 1, 0)

        def where(folder):
            return [r["id"] for r in self.rows(folder) if r["subject"] == subject]
        for dest in ("Projects/Acme", "junk", "inbox"):
            src = next(f for f in ("inbox", "Projects/Acme", "junk") if where(f))
            self.assertTrue(self.api("move", {"ids": where(src), "to": dest})[1]["ok"])
            self.assertEqual(len(where(dest)), 1)
            self.assertEqual(where(src) if src != dest else [], [])
        self.assertTrue(where("inbox")[0].startswith("inbox:"))
        out = self.api("move", {"ids": where("inbox"), "to": "No such folder"})[1]
        self.assertFalse(out["ok"])
        self.assertEqual(len(where("inbox")), 1)
        self.api("move", {"ids": where("inbox"), "to": "trash"})

    def test_folder_tree(self):
        found = [("INBOX", ""), ("Sent Messages", "\\sent"), ("其他文件夹", "\\haschildren"),
                 ("其他文件夹/华明印尼", ""), ("其他文件夹/2025归档", ""), ("All Mail", "\\all"),
                 ("Gone", "\\noselect"), ("Clients.Acme", ""), ("flagged", "")]
        self.assertEqual(A.folder_tree(found, {"Sent Messages"}), [
            ("Clients.Acme", "Clients.Acme", 0), ("其他文件夹", "其他文件夹", 0),
            ("其他文件夹/2025归档", "2025归档", 1), ("其他文件夹/华明印尼", "华明印尼", 1)])

    def test_new_mail_is_news(self):
        before = self.api("status")[1]["data"]["news"]
        self.assertTrue(self.api("demo_mail")[1]["ok"])
        news = self.api("status", {"focus": True})[1]["data"]["news"]
        self.assertEqual(len(news), len(before) + 1)
        x = news[-1]
        self.assertEqual((x["subject"], x["from"]["addr"]), ("Delivery date for order 4502", "sofia.rossi@example.it"))
        self.assertGreater(x["n"], max([b["n"] for b in before], default=0))
        self.assertIn(x["id"], [r["id"] for r in self.rows("inbox", unread=True)])
        self.assertEqual(self.api("boot")[1]["data"]["news"], news)     # a page opened later does not repeat it

    def test_mail_put_back_is_not_news(self):
        i = self.rows("junk")[0]["id"]
        before = self.api("status")[1]["data"]["news"]
        self.api("move", {"ids": [i], "to": "inbox"})
        self.assertEqual(self.api("status")[1]["data"]["news"], before)

    def test_own_folders_made_renamed_deleted(self):
        keys = lambda: [f["key"] for f in self.api("status")[1]["data"]["folders"] if f.get("other")]
        err = lambda name, a: self.api(name, a)[1].get("error", "")
        self.assertEqual(self.api("folder_new", {"name": "  Tenders   2026 "})[1]["data"], {"key": "Tenders 2026"})
        self.assertIn("Tenders 2026", keys())
        self.assertIn("already a folder", err("folder_new", {"name": "tenders 2026"}))
        self.assertIn("Give the folder a name", err("folder_new", {"name": "  "}))
        self.assertIn("can't have / in it", err("folder_new", {"name": "a/b"}))
        self.assertIn("no longer on the server", err("folder_rename", {"key": "INBOX", "name": "x"}))
        self.assertIn("no longer on the server", err("folder_delete", {"key": "Trash"}))
        # the mail in a folder follows it to the new name
        i = self.rows("inbox")[-1]["id"]
        subject = self.rows("inbox")[-1]["subject"]
        self.api("move", {"ids": [i], "to": "Tenders 2026"})
        self.assertEqual(self.api("folder_rename", {"key": "Tenders 2026", "name": "Tenders"})[1]["data"], {"key": "Tenders"})
        self.assertNotIn("Tenders 2026", keys())
        got = self.rows("Tenders")
        self.assertEqual([r["subject"] for r in got], [subject])
        self.assertTrue(self.api("message", {"id": got[0]["id"]})[1]["ok"])
        # a folder with mail in it stays; an empty one goes
        self.assertIn("still has mail", err("folder_delete", {"key": "Tenders"}))
        self.assertIn("Tenders", keys())
        self.api("move", {"ids": [got[0]["id"]], "to": "inbox"})
        self.assertTrue(self.api("folder_delete", {"key": "Tenders"})[1]["ok"])
        self.assertNotIn("Tenders", keys())
        self.assertIn("folders inside", err("folder_delete", {"key": "Projects"}))
        # a folder inside another keeps its place when the outer one is renamed
        self.assertEqual(self.api("folder_rename", {"key": "Projects/Acme", "name": "Acme Ltd"})[1]["data"], {"key": "Projects/Acme Ltd"})
        self.api("folder_rename", {"key": "Projects", "name": "Work"})
        self.assertIn("Work/Acme Ltd", keys())
        self.api("folder_rename", {"key": "Work", "name": "Projects"})
        self.api("folder_rename", {"key": "Projects/Acme Ltd", "name": "Acme"})
        self.assertIn("Projects/Acme", keys())

    def test_new_folder_goes_beside_the_others(self):
        b = A.Backend.__new__(A.Backend)
        b.found = [("INBOX", ""), ("其他文件夹", "\\noselect \\haschildren"), ("其他文件夹/2025归档", "")]
        self.assertEqual(b.own_parent("/"), "其他文件夹")
        b.found = [("INBOX", ""), ("其他文件夹", "\\noselect \\haschildren")]
        self.assertEqual(b.own_parent("/"), "其他文件夹")
        b.found = [("INBOX", ""), ("Clients", ""), ("Clients/Acme", "")]
        self.assertEqual(b.own_parent("/"), "")

    def test_a_page_with_its_own_notices_is_noted(self):
        self.api("status", {"web_notice": True})
        self.assertLess(time.time() - self.backend.web_notice_at, 5)

    def test_a_change_from_the_cli_reaches_the_page(self):
        """Another connection (the CLI in a terminal) marks a mail answered: the next status call says so."""
        rev = self.api("status")[1]["data"]["rev"]
        self.assertEqual(self.api("status")[1]["data"]["rev"], rev)
        row = self.api("list", {"folder": "inbox"})[1]["data"]["rows"][-1]
        folder, uid = A.R.parse_id(row["id"])
        c = A.R.db()
        c.execute("update msgs set answered=1, seen=0 where folder=? and uid=?", (folder, uid))
        c.commit()
        c.close()
        st = self.api("status")[1]["data"]
        self.assertGreater(st["rev"], rev)
        again = [r for r in self.api("list", {"folder": "inbox"})[1]["data"]["rows"] if r["id"] == row["id"]][0]
        self.assertTrue(again["answered"])
        self.api("mark", {"ids": [row["id"]], "flag": "seen", "on": True})

    def test_counts_follow_what_the_app_does(self):
        before = {f["key"]: f for f in self.api("status")[1]["data"]["folders"]}
        row = [r for r in self.api("list", {"folder": "inbox"})[1]["data"]["rows"] if not r["unread"]][0]
        self.api("mark", {"ids": [row["id"]], "flag": "seen", "on": False})
        after = {f["key"]: f for f in self.api("status")[1]["data"]["folders"]}
        self.assertEqual(after["inbox"]["unread"], before["inbox"]["unread"] + 1)
        self.api("mark", {"ids": [row["id"]], "flag": "seen", "on": True})
        self.assertEqual({f["key"]: f for f in self.api("status")[1]["data"]["folders"]}["inbox"]["unread"],
                         before["inbox"]["unread"])

    def test_notify_pref_is_checked(self):
        self.assertIs(self.api("prefs", {"notify": False})[1]["data"]["notify"], False)
        self.assertIs(self.api("prefs", {"notify": "yes"})[1]["data"]["notify"], False)
        self.assertIs(self.api("prefs", {"notify": True})[1]["data"]["notify"], True)

    def test_notice_state_outside_the_mac_app(self):
        # only the built Mac app can ask macOS; anywhere else there is nothing to tell and nothing to open
        self.assertEqual(self.api("notice_state")[1]["data"]["state"], "")
        self.assertIs(self.api("notice_settings")[1]["data"]["ok"], False)
        self.assertEqual(A.mac_notice_state(), "")

    def test_a_mail_is_never_shrunk(self):
        # 0.8.1 zoomed a whole mail out when one picture or table was wider than the reader: 14px text became 10px
        js = open(os.path.join(os.path.dirname(A.__file__), "app", "app.js"), encoding="utf-8").read()
        self.assertNotIn("style.zoom", js)
        self.assertIn("img{max-width:100%!important", js)
        self.assertIn("minText(d);", js)

def no_server():
    raise OSError("the tests have no mail server")


class FakeServer:
    """Stands in for the IMAP connection: keeps what was asked; says NO to a STORE of a uid in `refuse`."""
    def __init__(self, refuse=()):
        self.calls, self.refuse = [], set(refuse)

    def select(self, name, readonly=True):
        self.calls.append(("select", name, readonly))
        return "OK", [b"1"]

    def response(self, code):
        return code, [b"1"]

    def uid(self, *args):
        self.calls.append(("uid",) + args)
        if args[0] == "STORE" and self.refuse & set(args[1].split(",")):
            return "NO", [b"not allowed"]
        return "OK", [b""]

    def stores(self):
        return [c[1:] for c in self.calls if c[:2] == ("uid", "STORE")]

    def logout(self):
        pass


class FakeQueue:
    """Keeps the marks for the server instead of sending them."""
    unfinished_tasks = 0

    def __init__(self):
        self.jobs = []

    def put(self, job):
        self.jobs.append(job)


class Busy:
    """A background thread that looks alive, so no real one is started."""
    @staticmethod
    def is_alive():
        return True


class OwnBackend(unittest.TestCase):
    """Each test gets a demo mailbox of its own. `online()` makes the backend act as with an account,
    with a fake in place of the server."""
    def setUp(self):
        self.patch(A.R, "imap", no_server)      # whatever a test forgets to fake fails here, not on the network
        cfg = A.R.CFG                           # demo mode swaps the config; the other tests need it back
        self.b = A.Backend(demo=True)
        self.b.MARK_PAUSE = 0
        self.home = A.R.CFG.home
        self.err = io.StringIO()
        self.addCleanup(self.done, cfg)

    def done(self, cfg):
        self.b.close()
        with self.b.dblock:
            self.b.c.close()
        shutil.rmtree(self.home, ignore_errors=True)
        A.R.CFG = cfg

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def online(self, server=None, fail=()):
        """fail: for each connection use in turn, the error it raises (None = it works)."""
        b, fail = self.b, list(fail)
        b.demo = False
        self.server = server or FakeServer()
        self.uses = []

        def imap(fn):
            self.uses.append(1)
            e = fail.pop(0) if fail else None
            if e is not None:
                b.m = None
                raise e
            b.m = self.server
            return fn(self.server)
        b.imap = imap

    def hold_queue(self):
        self.b.flag_q, self.b.flag_thread = FakeQueue(), Busy
        return self.b.flag_q.jobs

    def run_queue(self):
        b = self.b
        b.flag_thread = threading.Thread(target=b.flag_loop, daemon=True)
        b.flag_thread.start()
        end = time.time() + 5
        while b.flag_q.unfinished_tasks and time.time() < end:
            time.sleep(0.01)
        self.assertEqual(b.flag_q.unfinished_tasks, 0)

    def unread(self, folder="INBOX"):
        return [r["uid"] for r in self.b.q("select uid from msgs where folder=? and seen=0 order by uid", (folder,))]

    def ids(self, folder="INBOX", seen=0):
        return [A.R.make_id(folder, r["uid"]) for r in
                self.b.q("select uid from msgs where folder=? and seen=? order by uid", (folder, seen))]

    def by_subject(self, subject, folder="INBOX"):
        r = self.b.q("select uid from msgs where folder=? and subject=?", (folder, subject))[0]
        return A.R.make_id(folder, r["uid"])


class MarkAllRead(OwnBackend):
    def test_folder_becomes_read(self):
        n, junk = len(self.unread()), self.unread("Junk")
        self.assertGreater(n, 1)
        self.assertTrue(junk)
        rev = self.b.rev
        self.assertEqual(self.b.api_mark_all_read({"folder": "inbox"}), {"count": n})
        self.assertEqual(self.unread(), [])
        self.assertEqual(self.unread("Junk"), junk)                 # the other folders are not touched
        self.assertGreater(self.b.rev, rev)                         # the page hears about it
        self.assertEqual(self.b.api_mark_all_read({"folder": "inbox"}), {"count": 0})
        self.assertEqual(self.b.api_mark_all_read({}), {"count": 0})
        self.assertEqual(self.b.api_mark_all_read({"folder": "scheduled"}), {"count": 0})
        self.assertEqual(self.b.api_mark_all_read({"folder": "No such folder"}), {"count": 0})

    def test_own_folder_and_flagged_list(self):
        self.assertEqual(self.b.api_mark_all_read({"folder": "Projects/Acme"}), {"count": 1})
        self.assertEqual(self.unread("Projects/Acme"), [])
        n = len(self.unread())
        self.assertEqual(self.b.api_mark_all_read({"folder": "flagged"}), {"count": 1})    # the unread flagged one
        self.assertEqual(len(self.unread()), n - 1)

    def test_it_is_one_of_the_calls_the_page_can_make(self):
        n = len(self.unread())
        self.assertEqual(self.b.call("mark_all_read", {"folder": "inbox"}), (200, {"ok": True, "data": {"count": n}}))

    def test_server_hears_it_in_the_background(self):
        self.online()
        jobs = self.hold_queue()
        uids = self.unread()
        self.assertEqual(self.b.api_mark_all_read({"folder": "inbox"}), {"count": len(uids)})
        self.assertEqual(self.unread(), [])                         # read at once, before the server knows
        self.assertEqual((len(jobs), self.uses), (1, []))
        go, done, end = jobs[0]
        self.assertIsNone(done)                                     # nobody waits for it
        go(self.server)
        self.assertEqual(self.server.calls[0], ("select", '"INBOX"', False))
        (cmd, sent, how, flag), = self.server.stores()
        self.assertEqual((cmd, sorted(map(int, sent.split(","))), how, flag), ("STORE", uids, "+FLAGS.SILENT", "(\\Seen)"))
        # a sync that asks the server before it has them must not show them unread again
        self.assertEqual(self.b.held("INBOX", time.time()), {u: {"seen": 1} for u in uids})
        end(None)
        self.assertEqual(self.unread(), [])

    def test_mails_are_unread_again_when_the_server_cannot_be_told(self):
        self.online()
        jobs = self.hold_queue()
        uids = self.unread()
        self.b.api_mark_all_read({"folder": "inbox"})
        with contextlib.redirect_stderr(self.err):
            jobs[0][2](OSError("network is down"))
        self.assertEqual(self.unread(), uids)
        self.assertIn("did not reach the server", self.err.getvalue())
        self.assertEqual(self.b.held("INBOX", 0), {})

    def test_many_mails_go_in_pieces(self):
        with self.b.dblock:
            for uid in range(1000, 1650):
                self.b.c.execute("insert into msgs(folder,uidv,uid,msgid,ts,seen) values('INBOX',1,?,?,1700000000,0)",
                                 (uid, "<m%d@x>" % uid))
            self.b.c.commit()
        self.online()
        jobs = self.hold_queue()
        n = len(self.unread())
        self.assertEqual(self.b.api_mark_all_read({"folder": "inbox"}), {"count": n})
        self.assertEqual(self.unread(), [])
        jobs[0][0](self.server)
        sent = [len(c[1].split(",")) for c in self.server.stores()]
        self.assertEqual((sum(sent), max(sent)), (n, 200))


class MarksOnTheirWay(OwnBackend):
    """Read and flag marks: the index first, the server in the background, and what happens when it fails."""

    def test_mail_that_does_not_open_stays_unread(self):
        i = self.ids()[0]
        self.b.demo_raw.pop(A.R.parse_id(i))
        n = len(self.unread())
        with self.assertRaises(A.ApiError):
            self.b.api_message({"id": i})
        self.assertEqual(len(self.unread()), n)
        self.assertTrue(self.b.api_message({"id": self.ids()[1]})["subject"])     # one that opens is read
        self.assertEqual(len(self.unread()), n - 1)
        self.b.api_message({"id": self.ids()[1], "mark": False})    # a look that is not a read
        self.assertEqual(len(self.unread()), n - 1)

    def test_server_is_told_only_after_the_mail_opened(self):
        self.online()
        jobs = self.hold_queue()
        i, n = self.ids()[0], len(self.unread())
        f, uid = A.R.parse_id(i)

        def broken(i):
            self.assertEqual(len(self.unread()), n - 1)            # shown read while it loads
            raise OSError("connection lost")
        self.b.build_message = broken
        with self.assertRaises(OSError):
            self.b.api_message({"id": i})
        self.assertEqual((jobs, len(self.unread())), ([], n))
        self.assertEqual(self.b.held(f, 0), {})
        self.b.build_message = lambda i: {"id": i, "html": ""}
        self.b.api_message({"id": i})
        self.assertEqual((len(jobs), len(self.unread())), (1, n - 1))
        self.assertEqual(self.b.held(f, time.time()), {uid: {"seen": 1}})
        self.b.api_message({"id": i})                               # read already: nothing more to tell
        self.assertEqual(len(jobs), 1)

    def test_failed_mark_is_tried_once_more(self):
        self.online(fail=[ConnectionResetError("dropped")])
        i = self.ids()[0]
        f, uid = A.R.parse_id(i)
        self.b.set_flag([i], "seen", True)                          # waits for the server; no error comes back
        self.assertEqual(len(self.uses), 2)
        self.assertEqual(self.server.stores(), [("STORE", str(uid), "+FLAGS.SILENT", "(\\Seen)")])
        self.assertNotIn(uid, self.unread())

    def test_mark_that_fails_twice_is_undone(self):
        self.online(fail=[ConnectionResetError("dropped"), OSError("still down")])
        i = self.ids()[0]
        uid = A.R.parse_id(i)[1]
        with self.assertRaises(OSError):
            self.b.set_flag([i], "seen", True)
        self.assertIn(uid, self.unread())
        self.online(fail=[OSError("down"), OSError("down")])
        with contextlib.redirect_stderr(self.err):
            self.b.set_flag([i], "flagged", True, wait=False)       # shown at once ...
            self.run_queue()
        self.assertEqual(self.b.row(i)["flagged"], 0)               # ... and taken back
        self.assertEqual(len(self.uses), 2)
        self.assertEqual(self.b.held("INBOX", 0), {})

    def test_server_down_fails_the_waiting_marks_at_once(self):
        self.online(fail=[OSError("down")] * 9)
        self.hold_queue()
        self.b.flag_q = queue.Queue()
        ids = self.ids()[:3]
        for i in ids:
            self.b.set_flag([i], "flagged", True, wait=False)
        self.assertEqual([self.b.row(i)["flagged"] for i in ids], [1, 1, 1])
        with contextlib.redirect_stderr(self.err):
            self.run_queue()
        self.assertEqual(len(self.uses), 2)                         # the first mark twice; the others not at all
        self.assertEqual([self.b.row(i)["flagged"] for i in ids], [0, 0, 0])

    def test_one_refused_mark_does_not_fail_the_others(self):
        ids = self.ids()[:3]
        self.online(FakeServer(refuse=[str(A.R.parse_id(ids[0])[1])]))
        self.hold_queue()
        self.b.flag_q = queue.Queue()
        for i in ids:
            self.b.set_flag([i], "flagged", True, wait=False)
        with contextlib.redirect_stderr(self.err):
            self.run_queue()
        self.assertEqual([self.b.row(i)["flagged"] for i in ids], [0, 1, 1])
        self.assertIn("refused", self.err.getvalue())

    def test_folder_that_is_gone_is_not_asked_twice(self):
        class Gone(FakeServer):
            def select(self, name, readonly=True):
                return "NO", [b"no such folder"]
        self.online(Gone())
        i = self.ids()[0]
        with self.assertRaises(LookupError):
            self.b.set_flag([i], "seen", True)
        self.assertEqual(len(self.uses), 1)
        self.assertIn(A.R.parse_id(i)[1], self.unread())

    def test_waiting_for_a_mark_ends(self):
        self.online()
        self.hold_queue()
        self.b.flag_q = queue.Queue()                               # nothing takes the mark from the queue
        self.b.MARK_WAIT = 0.05
        i = self.ids()[0]
        with self.assertRaises(TimeoutError) as cm:
            self.b.set_flag([i], "seen", True)
        self.assertIn("did not answer in time", A.friendly(cm.exception))
        self.run_queue()                                            # nobody waits for it: it is not sent
        self.assertEqual((self.uses, self.server.stores()), ([], []))
        self.assertIn(A.R.parse_id(i)[1], self.unread())
        self.assertEqual(self.b.held("INBOX", 0), {})

    def test_quit_waits_for_marks_on_their_way(self):
        self.online()
        real = self.b.imap

        def slow(fn):
            time.sleep(0.3)
            return real(fn)
        self.b.imap = slow
        i = self.ids()[0]
        self.b.set_flag([i], "seen", True, wait=False)
        t = time.time()
        self.b.close()
        self.assertEqual(len(self.server.stores()), 1)
        self.assertLess(time.time() - t, 3)

    def test_quit_does_not_wait_for_ever(self):
        self.assertLessEqual(self.b.QUIT_WAIT, 5)
        self.online()
        stuck = threading.Event()
        self.addCleanup(stuck.set)
        self.b.imap = lambda fn: stuck.wait(30)
        self.b.QUIT_WAIT = 0.3
        self.b.set_flag([self.ids()[0]], "seen", True, wait=False)
        t = time.time()
        self.b.close()
        self.assertTrue(0.25 < time.time() - t < 2, time.time() - t)

    def test_sync_keeps_a_mark_the_server_does_not_have_yet(self):
        b, by = self.b, {"INBOX": [5, 6]}
        now = time.time()
        b.hold(by, "seen", True)
        self.assertEqual(b.held("INBOX", now), {5: {"seen": 1}, 6: {"seen": 1}})
        self.assertEqual(b.held("Sent Messages", now), {})
        b.hold({"INBOX": [5]}, "seen", False)                       # marked again before the first arrived
        b.settle(by, "seen", True)
        self.assertEqual(b.held("INBOX", time.time() + 60), {5: {"seen": 0}})     # 6 is with the server
        self.assertEqual(b.held("INBOX", now), {5: {"seen": 0}, 6: {"seen": 1}})  # this sync asked before that
        b.settle({"INBOX": [5]}, "seen", False)                     # given up: the server's flag counts again
        self.assertEqual(b.held("INBOX", now), {6: {"seen": 1}})
        b.marks[("INBOX", 6, "seen")][2] = now - 1000
        self.assertEqual((b.held("INBOX", 0), b.marks), ({}, {}))  # long done: forgotten

    def test_sync_is_given_the_marks(self):
        got = []

        def sync_headers(m, c, folder, **kw):
            got.append((folder, kw["held"](folder, time.time())))
            self.b.stopping.set()               # one pass is enough
            return []
        self.patch(A.R, "imap", FakeServer)
        self.patch(A.R, "sync_headers", sync_headers)
        self.patch(A.R, "sync_bodies", lambda *a, **kw: None)
        self.b.note_folders = self.b.note_new = lambda *a: None
        self.b.hold({"INBOX": [5]}, "seen", True)
        self.b.wake.set()
        self.b.sync_loop()
        self.assertEqual(got[0], ("INBOX", {5: {"seen": 1}}))


LIGHT = (b"From: Linh <linh@cust.vn>\r\nTo: you@example.com\r\nSubject: Drawing\r\nMIME-Version: 1.0\r\n"
         b"Content-Type: multipart/mixed; boundary=\"B\"\r\n\r\n"
         b"--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nSee the drawing.\r\n"
         b"--B\r\nContent-Type: application/pdf; name=\"big.pdf\"\r\n"
         b"Content-Disposition: attachment; filename=\"big.pdf\"\r\nContent-Transfer-Encoding: base64\r\n"
         b"X-Ragdoll-Part: 2\r\nX-Ragdoll-Size: 292307\r\n\r\n\r\n--B--\r\n")
PART = (b"Content-Type: application/pdf; name=\"big.pdf\"\r\nContent-Disposition: attachment; filename=\"big.pdf\"\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\nJVBERi0xLjQ=")


class Files(OwnBackend):
    """Files of a mail: saved one by one or all, and the big ones a light mail left on the server."""

    def setUp(self):
        super().setUp()
        self.down = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.down, True)
        self.patch(A, "downloads_dir", lambda: self.down)
        self.opened = []
        self.patch(A, "open_path", lambda path, reveal=False: self.opened.append((path, reveal)))

    def light(self):
        """The backend with an account, and a mail that opens light: its PDF is still on the server."""
        self.online()
        self.asked = []

        def fetch_part_raw(m, folder, uid, sec):
            self.asked.append((folder, uid, sec))
            return PART
        self.patch(A.R, "fetch_part_raw", fetch_part_raw)
        self.b.view = lambda i: (LIGHT, True)
        i = self.ids(seen=1)[0]
        r = self.b.row(i)
        return i, (r["folder"], r["uidv"], r["uid"])

    def test_only_our_own_light_mail_names_a_part(self):
        part = lambda headers, body=b"": A.R.to_msg(b"Content-Type: application/pdf\r\n" + headers + b"\r\n" + body)
        ours = part(b"X-Ragdoll-Part: 2.1\r\n")
        self.assertEqual(A.left_out(ours, True), "2.1")
        self.assertIsNone(A.left_out(ours, False))                  # a mail somebody sent can carry the header too
        self.assertIsNone(A.left_out(part(b""), True))
        self.assertIsNone(A.left_out(part(b"X-Ragdoll-Part: 2\r\n", b"JVBERi0xLjQ="), True))    # the file is here
        for bad in (b"1] BODY[", b"HEADER", b"1.", b"2 3", b"-1", b"1.a"):
            self.assertIsNone(A.left_out(part(b"X-Ragdoll-Part: " + bad + b"\r\n"), True), bad)

    def test_header_in_a_mail_somebody_sent_is_not_followed(self):
        i, _ = self.light()
        self.b.view = lambda i: (LIGHT, False)                      # the same bytes, but as they came in
        self.assertEqual(self.b.build_message(i)["atts"][0]["size"], 0)
        out = self.b.api_attachment({"id": i, "i": 0, "action": "save"})
        self.assertEqual((self.asked, self.uses), ([], []))         # the server was not asked for "part 2"
        self.assertEqual(os.path.getsize(out["path"]), 0)

    def test_big_file_is_fetched_once_and_kept(self):
        i, key = self.light()
        self.assertEqual(self.b.build_message(i)["atts"],
                         [{"i": 0, "name": "big.pdf", "size": 292307, "type": "application/pdf"}])
        self.assertEqual(self.asked, [])                            # showing the mail does not fetch the file
        out = self.b.api_attachment({"id": i, "i": 0, "action": "save"})
        self.assertEqual(out, {"path": os.path.join(self.down, "big.pdf"), "name": "big.pdf"})
        with open(out["path"], "rb") as f:
            self.assertEqual(f.read(), b"%PDF-1.4")
        self.assertEqual(self.asked, [(key[0], key[2], "2")])
        kept = A.R.part_path(*key, "2")
        with open(kept, "rb") as f:
            self.assertEqual(f.read(), PART)
        again = self.b.api_attachment({"id": i, "i": 0, "action": "save"})
        self.assertEqual(again["name"], "big (2).pdf")              # the first one is not written over
        opened = self.b.api_attachment({"id": i, "i": 0, "action": "open"})
        self.assertEqual(self.opened, [(opened["path"], False)])
        self.assertEqual(self.b.api_save_all({"id": i})["count"], 1)
        self.assertEqual(len(self.asked), 1)                        # all from the kept file
        self.assertFalse(self.b.call("attachment", {"id": i, "i": 5, "action": "save"})[1]["ok"])

    def test_kept_file_goes_when_its_light_mail_goes(self):
        i, key = self.light()
        light, kept = A.R.light_path(*key), A.R.part_path(*key, "2")
        A.R.cache_put(light, LIGHT)
        self.b.api_attachment({"id": i, "i": 0, "action": "save"})
        self.b.prune_cache()
        self.assertTrue(os.path.exists(light) and os.path.exists(kept))
        old = time.time() - 100 * 86400
        os.utime(light, (old, old))                                 # not opened for a long time
        self.b.prune_cache()
        self.assertFalse(os.path.exists(light) or os.path.exists(kept))
        whole = A.R.cache_path(*key)                                # a whole mail has no such files to lose
        A.R.cache_put(whole, b"x")
        self.b.prune_cache()
        self.assertTrue(os.path.exists(whole))

    def test_opening_a_file_twice_opens_the_same_copy(self):
        i = self.by_subject("Quote for PO-1234")
        one = self.b.api_attachment({"id": i, "i": 1, "action": "open"})
        with open(one["path"], "ab") as f:
            f.write(b"changed")                         # the user worked in it
        two = self.b.api_attachment({"id": i, "i": 1, "action": "open"})
        self.assertEqual(one["path"], two["path"])      # Excel opens no second workbook of the same name
        with open(two["path"], "rb") as f:
            self.assertTrue(f.read().endswith(b"changed"))
        self.assertEqual(self.opened, [(one["path"], False)] * 2)
        self.assertFalse([n for n in os.listdir(os.path.dirname(one["path"])) if n.endswith(".part")])

    def test_the_name_picks_the_file_when_the_list_moved(self):
        i = self.by_subject("Quote for PO-1234")
        out = self.b.api_attachment({"id": i, "i": 0, "name": "Delivery_schedule.xlsx", "action": "open"})
        self.assertEqual(out["name"], "Delivery_schedule.xlsx")
        out = self.b.api_attachment({"id": i, "i": 7, "name": "Quote_PO-1234_signed.pdf", "action": "open"})
        self.assertEqual(out["name"], "Quote_PO-1234_signed.pdf")
        self.assertFalse(self.b.call("attachment", {"id": i, "i": 0, "name": "gone.pdf", "action": "open"})[1]["ok"])

    def test_a_file_no_app_opens_says_so(self):
        if sys.platform != "darwin":
            self.skipTest("macOS open")
        self.patch(A.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b"No application knows how to open it."))
        with self.assertRaises(A.ApiError) as e:
            REAL_OPEN_PATH("/tmp/x.weird")
        self.assertIn("No application", str(e.exception))

    def test_all_files_are_saved_to_downloads(self):
        i = self.by_subject("Quote for PO-1234")
        names = ["Quote_PO-1234_signed.pdf", "Delivery_schedule.xlsx"]
        out = self.b.call("save_all", {"id": i})[1]
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"], {"count": 2, "path": os.path.join(self.down, names[1]), "folder": self.down})
        self.assertEqual(sorted(os.listdir(self.down)), sorted(names))
        one = self.b.api_attachment({"id": i, "i": 0, "action": "save"})     # the same file as "save" gives
        with open(one["path"], "rb") as a, open(os.path.join(self.down, names[0]), "rb") as b:
            self.assertEqual(a.read(), b.read())
        out = self.b.api_save_all({"id": i})
        self.assertEqual(out["path"], os.path.join(self.down, "Delivery_schedule (2).xlsx"))
        self.assertEqual(sorted(os.listdir(self.down)), sorted(
            names + ["Quote_PO-1234_signed (2).pdf", "Quote_PO-1234_signed (3).pdf", "Delivery_schedule (2).xlsx"]))
        self.b.api_reveal({"path": out["path"]})                    # the page may show what was saved
        self.assertEqual(self.opened, [(out["path"], True)])
        self.assertEqual(self.unread().count(A.R.parse_id(i)[1]), 1)    # saving is not reading

    def test_mail_without_files(self):
        out = self.b.api_save_all({"id": self.by_subject("Lunch on Thursday?")})
        self.assertEqual(out, {"count": 0, "path": self.down, "folder": self.down})
        self.assertEqual(os.listdir(self.down), [])
        self.b.api_reveal({"path": out["path"]})
        self.assertFalse(self.b.call("save_all", {"id": "inbox:99999"})[1]["ok"])


class NoCcRule(OwnBackend):
    """The "always Cc" rule belongs to the command line: the app neither shows, applies nor changes it."""
    BOSS = "boss@example.com"

    def setUp(self):
        super().setUp()
        A.R.CFG.d["require_cc"] = [self.BOSS]

    def test_settings_do_not_show_it(self):
        self.assertEqual(A.R.CFG.require_cc, [self.BOSS])
        self.assertNotIn("require_cc", self.b.api_settings({}))
        self.assertNotIn(self.BOSS, json.dumps(self.b.api_boot({})))

    def test_new_mail_and_reply_are_not_filled_with_it(self):
        self.assertEqual(self.b.api_compose({"mode": "new"})["cc"], [])
        for mode in ("reply", "replyall", "forward"):
            out = self.b.api_compose({"mode": mode, "id": self.by_subject("Lunch on Thursday?")})
            self.assertNotIn(self.BOSS, json.dumps(out["to"] + out["cc"] + out["bcc"]), mode)

    def test_send_check_does_not_ask_for_it(self):
        msg = A.R.to_msg(b"From: you@example.com\r\nTo: a@example.org\r\nSubject: Hi\r\n"
                         b"Content-Type: text/html; charset=utf-8\r\n\r\n<p>Hello</p>")
        self.assertTrue(any(self.BOSS in p for p in A.R.check_message(msg, False)))     # the command line still does
        self.assertFalse(any(self.BOSS in p for p in A.app_problems(msg, False)))

    def test_saving_settings_leaves_it_in_the_file(self):
        path = os.path.join(self.home, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"user": "you@example.com", "data_dir": self.home, "require_cc": [self.BOSS],
                       "imap": {"host": "demo", "port": 993}, "smtp": {"host": "demo", "port": 465}}, f)
        self.patch(A, "config_path", lambda: path)
        self.online()
        self.b.start_sync = lambda: None

        def saved():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        self.b.api_save_settings({"account": False, "signature": "<p>Alex</p>"})
        self.assertEqual(saved()["require_cc"], [self.BOSS])
        # a page that still sends the field changes nothing either
        self.b.api_save_settings({"user": "you@example.com", "name": "Alex", "imap_host": "demo", "imap_port": 993,
                                  "smtp_host": "demo", "smtp_port": 465, "require_cc": []})
        self.assertEqual((saved()["require_cc"], saved()["name"]), ([self.BOSS], "Alex"))
        self.b.api_save_settings({"account": False, "require_cc": ["other@example.com"]})
        self.assertEqual(saved()["require_cc"], [self.BOSS])
        self.assertEqual(A.R.CFG.require_cc, [self.BOSS])           # and the command line goes on using it


class DockBadge(OwnBackend):
    def test_unread_count_goes_to_the_dock(self):
        shown = []
        self.patch(A, "dock_badge", lambda n: shown.append(n) or True)
        n = len(self.unread())
        self.b.folder_counts()
        self.b.folder_counts()
        self.assertEqual(shown, [n])                                # asked once, not on every look
        self.b.set_flag([self.ids()[0]], "seen", True)
        self.b.folder_counts()
        self.assertEqual(shown, [n, n - 1])
        self.b.api_mark_all_read({"folder": "inbox"})
        self.b.folder_counts()
        self.assertEqual(shown[-1], 0)
        self.b.api_mark_all_read({"folder": "junk"})                # another folder's count is not the badge
        self.b.folder_counts()
        self.assertEqual(shown, [n, n - 1, 0])

    def test_nothing_is_shown_without_a_window_of_ours(self):
        self.assertIsNone(A.WINDOW.w)                               # as in the browser
        self.assertIs(A.dock_badge(3), False)
        self.b.folder_counts()
        self.assertIsNone(self.b.badge_n)                           # so it is shown once there is one




class GuessServers(OwnBackend):
    def test_known_domains_bring_their_port(self):
        self.assertEqual(self.b.api_guess_servers({"user": "a@icloud.com"})["smtp_port"], 587)
        self.assertEqual(self.b.api_guess_servers({"user": "a@qq.com"}),
                         {"imap_host": "imap.qq.com", "smtp_host": "smtp.qq.com", "smtp_port": 465})

    def test_company_domain_asks_who_receives_its_mail(self):
        asked = []
        self.patch(A.R, "servers_from_mx", lambda d: asked.append(d) or
                   {"imap_host": "imap.exmail.qq.com", "smtp_host": "smtp.exmail.qq.com", "smtp_port": 465})
        self.b.demo = False
        self.assertEqual(self.b.api_guess_servers({"user": "eric@company.com"})["imap_host"], "imap.exmail.qq.com")
        self.assertEqual(asked, ["company.com"])
        self.patch(A.R, "servers_from_mx", lambda d: None)
        self.assertEqual(self.b.api_guess_servers({"user": "eric@company.com"})["imap_host"], "imap.company.com")

if __name__ == "__main__":
    unittest.main()


class HandOffs(OwnBackend):
    def test_asks_reach_the_page_once(self):
        R = A.R
        rev = self.b.rev
        R.tell_app("draft", "drafts:3", "Re: Quote")
        R.tell_app("open", "inbox:5", "Hello")
        fronted = []
        old = A.bring_front
        A.bring_front = lambda: fronted.append(1)
        try:
            self.b.take_asks()
            self.b.take_asks()          # nothing new the second time
        finally:
            A.bring_front = old
        asks = self.b.api_status({})["asks"]
        self.assertEqual([(x["kind"], x["id"], x["n"]) for x in asks], [("draft", "drafts:3", 1), ("open", "inbox:5", 2)])
        self.assertEqual(fronted, [1])  # only "open" brings the window to the front
        self.assertGreater(self.b.rev, rev)
        self.assertIn("asks", self.b.api_boot({}))

    def test_cli_install_is_refused_in_the_demo(self):
        with self.assertRaises(A.ApiError):
            self.b.api_install_cli({})
        self.assertIn("installed", self.b.api_cli_state({}))


class ListsAndInvites(unittest.TestCase):
    """Unsubscribe headers and meeting invitations, read from the mail itself."""

    def msg(self, headers="", body=""):
        return A.R.to_msg((headers + "From: a@b.c\r\nSubject: x\r\n\r\n" + body).encode())

    def test_one_click_needs_https_and_the_post_header(self):
        u = A.list_unsub(self.msg("List-Unsubscribe: <mailto:u@l.com?subject=bye>, <https://l.com/u?x=1>\r\n"
                                  "List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n"))
        self.assertEqual(u, {"url": "https://l.com/u?x=1", "mailto": "mailto:u@l.com?subject=bye", "one_click": True})
        u = A.list_unsub(self.msg("List-Unsubscribe: <https://l.com/u>\r\n"))
        self.assertFalse(u["one_click"])
        self.assertIsNone(A.list_unsub(self.msg()))
        self.assertIsNone(A.list_unsub(self.msg("List-Unsubscribe: <ftp://x>\r\n")))

    def test_invite(self):
        ics = ("BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\nDTSTART;TZID=China Standard Time:20261125T140000\r\n"
               "DTEND;TZID=China Standard Time:20261125T150000\r\nSUMMARY:Review\\, Q4\r\nLOCATION:Room 3\r\n"
               " A\r\nORGANIZER;CN=\"Li, Ming\":mailto:li@x.cn\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        m = self.msg("MIME-Version: 1.0\r\nContent-Type: text/calendar; method=REQUEST; charset=utf-8\r\n", ics)
        v = A.invite_of(m)
        self.assertEqual((v["title"], v["where"], v["organizer"], v["all_day"], v["cancelled"]),
                         ("Review, Q4", "Room 3A", "Li, Ming", False, False))
        self.assertEqual(v["start"], 1795586400)            # 06:00 UTC: 14:00 in Shanghai
        self.assertEqual(v["end"] - v["start"], 3600)
        self.assertTrue(A.invite_of(A.R.to_msg(m.as_bytes().replace(b"METHOD:REQUEST", b"METHOD:CANCEL")))["cancelled"])
        self.assertIsNone(A.invite_of(self.msg(body="hello")))

    def test_times(self):
        self.assertEqual(A.ics_time("20261125T060000Z", {}), (1795586400, False))
        self.assertTrue(A.ics_time("20261125", {"VALUE": "DATE"})[1])
        self.assertEqual(A.ics_time("nonsense", {}), (None, False))

    def test_demo_has_both(self):
        cfg = A.R.CFG                           # demo mode swaps the config; the CLI tests need it back
        try:
            for lang, title, sub in (("en", "Product training", "Product training next Wednesday"),
                                     ("zh", "产品培训", "下周培训安排")):
                b = A.Backend(demo=True, demo_lang=lang)
                rows = b.api_list({"folder": "inbox"})["rows"]
                gh = next(r for r in rows if r["subject"].startswith("[ragdoll-mail]"))
                tr = next(r for r in rows if r["subject"] == sub)
                self.assertTrue(b.api_message({"id": gh["id"]})["unsub"]["one_click"])
                self.assertEqual(b.api_unsubscribe({"id": gh["id"]}), {"done": True})
                self.assertEqual(b.api_message({"id": tr["id"]})["invite"]["title"], title)
                self.assertTrue(b.api_open_invite({"id": tr["id"]})["path"].endswith(".ics"))
        finally:
            A.R.CFG = cfg

    def test_demo_is_one_language(self):
        """The English demo has no Chinese mail and the Chinese one no English mail, so a video shows one."""
        han = re.compile(r"[\u4e00-\u9fff]")
        for k, (_f, _a, frm, _to, _cc, subj, body, atts, *_r) in enumerate(A.DEMO):
            self.assertFalse(han.search(frm[0] + subj + body + "".join(n for n, _ in atts)), subj)
        for _f, _a, frm, _to, _cc, subj, body, *_r in A.DEMO_ZH:
            self.assertTrue(han.search(subj) or subj.startswith("[ragdoll-mail]"), subj)
            self.assertTrue(han.search(body), subj)
        self.assertEqual(A.demo_lang("zh"), "zh")
        self.assertIn(A.demo_lang(), ("en", "zh"))
