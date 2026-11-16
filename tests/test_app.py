"""Offline tests of the desktop app's local server, in demo mode (no account, no network)."""
import http.client, json, os, shutil, sys, threading, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll_app as A  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
