"""Offline tests of secure connections and the update check (0.11.1, #76)."""
import io, json, os, ssl, sys, types, unittest, unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll_app as A  # noqa: E402

R = A.R


class TlsContext(unittest.TestCase):
    def setUp(self):
        R._TLS.clear()
        self.addCleanup(R._TLS.clear)

    def test_checks_the_certificate_and_name(self):
        ctx = R.tls_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertIs(R.tls_context(), ctx)       # made once

    def test_off_when_the_settings_say_so(self):
        with unittest.mock.patch.dict(R.CFG.d, {"tls_verify": False}):
            self.assertEqual(R.tls_context().verify_mode, ssl.CERT_NONE)

    def test_roots_from_the_keychain_when_openssl_has_none(self):
        """The frozen Mac app: OpenSSL's folder does not exist, so the keychain's roots are loaded."""
        loaded = []
        real = ssl.create_default_context

        def empty():
            ctx = real()
            ctx.load_verify_locations = lambda cadata=None, **kw: loaded.append(cadata)
            ctx.cert_store_stats = lambda: {"x509_ca": 0}
            return ctx
        with unittest.mock.patch.object(R.ssl, "create_default_context", empty), \
                unittest.mock.patch.object(R, "_default_ca_found", lambda: False), \
                unittest.mock.patch.object(R.sys, "platform", "darwin"), \
                unittest.mock.patch.object(R, "mac_roots", lambda: "-----BEGIN CERTIFICATE-----x"):
            R.tls_context()
        self.assertEqual(loaded, ["-----BEGIN CERTIFICATE-----x"])

    def test_imap_and_smtp_get_the_context(self):
        seen = {}

        class Imap:
            def __init__(self, host, port, ssl_context=None, timeout=None):
                seen["imap"] = ssl_context
                raise OSError("stop")

        class Smtp:
            def __init__(self, host, port, timeout=None, context=None, **kw):
                seen["smtp"] = context
                raise OSError("stop")
        with unittest.mock.patch.object(R, "need_account", lambda: None), \
                unittest.mock.patch.object(type(R.CFG), "imap", {"host": "imap.example.invalid", "port": 993}, create=True), \
                unittest.mock.patch.object(R.imaplib, "IMAP4_SSL", Imap), \
                unittest.mock.patch.object(R.smtplib, "SMTP_SSL", Smtp):
            with self.assertRaises(BaseException):
                R.imap()
            with self.assertRaises(BaseException):
                R.smtp_open("smtp.example.invalid", 465, 5)
        self.assertIs(seen.get("imap"), R.tls_context())
        self.assertIs(seen.get("smtp"), R.tls_context())


def backend():
    b = types.SimpleNamespace(update=None, update_at=0.0, demo=False)
    for name in ("check_update", "api_check_update"):
        setattr(b, name, getattr(A.Backend, name).__get__(b))
    return b


def answer(tag):
    body = json.dumps({"tag_name": tag, "html_url": "https://example.invalid/r/" + tag}).encode()
    return unittest.mock.MagicMock(__enter__=lambda s: io.BytesIO(body), __exit__=lambda *a: False)


class UpdateCheck(unittest.TestCase):
    def run_check(self, tag=None, error=None, manual=False, brew=False, b=None):
        b = b or backend()
        fake = unittest.mock.Mock(side_effect=error) if error else unittest.mock.Mock(return_value=answer(tag))
        with unittest.mock.patch.object(A, "FROZEN", True), \
                unittest.mock.patch.object(A.urllib.request, "urlopen", fake), \
                unittest.mock.patch.object(A, "brew_cask", lambda: brew), \
                unittest.mock.patch.object(A, "__version__", "0.11.0"):
            out = b.api_check_update({}) if manual else b.check_update()
        return b, out, fake

    def test_newer(self):
        b, _, fake = self.run_check("v0.11.1")
        self.assertEqual(b.update, {"version": "0.11.1", "url": "https://example.invalid/r/v0.11.1"})
        self.assertIn("context", fake.call_args.kwargs)
        self.assertGreater(b.update_at, 0)

    def test_same_or_older(self):
        for tag in ("v0.11.0", "v0.10.0"):
            b, _, _ = self.run_check(tag)
            self.assertIsNone(b.update)

    def test_a_later_check_clears_an_old_notice(self):
        b = backend()
        b.update = {"version": "0.11.1"}
        self.run_check("v0.11.0", b=b)
        self.assertIsNone(b.update)

    def test_homebrew_gets_the_brew_command(self):
        b, _, _ = self.run_check("v0.12.0", brew=True)
        self.assertEqual(b.update["command"], "brew upgrade --cask ragdoll-mail")

    def test_quiet_check_says_nothing_offline(self):
        b, out, _ = self.run_check(error=OSError("offline"))
        self.assertIsNone(out)
        self.assertEqual(b.update_at, 0.0)

    def test_manual_check(self):
        _, out, _ = self.run_check("v0.11.1", manual=True)
        self.assertEqual(out["update"]["version"], "0.11.1")
        self.assertEqual(out["version"], "0.11.0")
        with self.assertRaises(A.ApiError) as cm:
            self.run_check(error=OSError("offline"), manual=True)
        self.assertEqual(str(cm.exception), A.UPDATE_FAIL_MSG)

    def test_checks_again_after_twelve_hours_and_after_sleep(self):
        calls = []
        b = types.SimpleNamespace(update_at=0.0)
        b.check_update = lambda: (calls.append(1), setattr(b, "update_at", clock["wall"]))
        clock = {"wall": 1000.0, "mono": 0.0}
        steps = iter([A.UPDATE_TICK, A.UPDATE_EVERY, A.UPDATE_TICK + 3600, None])

        def sleep(s):
            if s == 30:
                return
            step = next(steps)
            if step is None:
                raise StopIteration
            clock["wall"] += step
            clock["mono"] += A.UPDATE_TICK      # asleep: the monotonic clock stands still
        with unittest.mock.patch.object(A.time, "time", lambda: clock["wall"]), \
                unittest.mock.patch.object(A.time, "monotonic", lambda: clock["mono"]), \
                unittest.mock.patch.object(A.time, "sleep", sleep):
            with self.assertRaises(StopIteration):
                A.Backend.update_loop(b)
        # at start; not after 5 minutes; after 12 hours; after waking from an hour's sleep
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
