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

    def test_unknown_call(self):
        code, out = self.api("nope")
        self.assertEqual(code, 404)
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
