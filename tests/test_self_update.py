"""Offline tests of the app updating itself (#76): pick the release file, download and check it,
unpack it, and the helper that swaps the files after the app quits (run for real on this system)."""
import contextlib, hashlib, http.server, io, json, os, shutil, subprocess, sys, tempfile, threading, time
import types, unittest, unittest.mock, zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll_app as A  # noqa: E402

WIN = sys.platform == "win32"


def read(path, mode="r", **kw):
    with open(path, mode, **kw) as f:
        return f.read()


def release(version="0.13.0", assets=None):
    return {"tag_name": "v" + version, "html_url": "https://example.invalid/r",
            "assets": assets if assets is not None else [
                {"name": "ragdoll-mail-mac.dmg", "browser_download_url": "https://example.invalid/m.dmg", "size": 10},
                {"name": "ragdoll-mail-windows.zip", "browser_download_url": "https://example.invalid/w.zip", "size": 20,
                 "digest": "sha256:" + "0" * 64}]}


def win_zip(files=None):
    files = files if files is not None else {"Ragdoll Mail.exe": b"MZnew-app", "ragdoll.exe": b"MZnew-cli"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    return buf.getvalue()


class Serve:
    """A local web server that hands out one file (the stand-in release download)."""
    def __init__(self, body, length=None):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(h):
                h.send_response(200)
                h.send_header("Content-Length", str(length if length is not None else len(body)))
                h.end_headers()
                with contextlib.suppress(OSError):
                    h.wfile.write(body)

            def log_message(h, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/file" % self.srv.server_address[1]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()


class Pieces(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_picks_the_file_for_this_system(self):
        self.assertEqual(A.pick_asset(release(), "darwin")["url"], "https://example.invalid/m.dmg")
        w = A.pick_asset(release(), "win32")
        self.assertEqual((w["size"], w["digest"][:7]), (20, "sha256:"))
        self.assertIsNone(A.pick_asset(release(), "linux"))
        self.assertIsNone(A.pick_asset(release(assets=[]), "win32"))

    def test_only_the_downloaded_app_updates_itself(self):
        with unittest.mock.patch.object(A, "FROZEN", False):
            self.assertIsNone(A.app_target())
        with unittest.mock.patch.object(A, "FROZEN", True), unittest.mock.patch.object(A, "brew_cask", lambda: True):
            self.assertIsNone(A.app_target())
        with unittest.mock.patch.object(A, "FROZEN", True), \
                unittest.mock.patch.object(A.sys, "platform", "win32"), \
                unittest.mock.patch.object(A.sys, "executable", r"C:\Users\x\AppData\Local\Microsoft\WinGet\Packages\erict16.RagdollMail_abc\Ragdoll Mail.exe"):
            self.assertTrue(A.winget_install())
            self.assertIsNone(A.app_target())
        with unittest.mock.patch.object(A, "FROZEN", True), unittest.mock.patch.object(A, "brew_cask", lambda: False), \
                unittest.mock.patch.object(A.sys, "platform", "darwin"), \
                unittest.mock.patch.object(A.sys, "executable", "/Applications/Ragdoll Mail.app/Contents/MacOS/ragdoll-mail"):
            self.assertTrue(A.app_target().replace(os.sep, "/").endswith("/Applications/Ragdoll Mail.app"))

    def test_a_folder_it_cannot_write_in_is_said_before_anything_starts(self):
        with unittest.mock.patch.object(A.sys, "platform", "win32" if WIN else "darwin"):
            self.assertIsNone(A.install_blocker(self.dir) if WIN else A.install_blocker(os.path.join(self.dir, "X.app")))
            gone = os.path.join(self.dir, "missing", "deeper")
            self.assertIn("can't replace itself", A.install_blocker(gone if WIN else os.path.join(gone, "X.app")))
        with unittest.mock.patch.object(A.sys, "platform", "darwin"):
            self.assertEqual(A.install_blocker("/Volumes/Ragdoll Mail/Ragdoll Mail.app"), A.INSTALL_MOVE_MSG)
            self.assertEqual(A.install_blocker("/private/var/folders/x/AppTranslocation/y/d/Ragdoll Mail.app"),
                             A.INSTALL_MOVE_MSG)

    def test_download_checks_size_and_sha256(self):
        body = b"x" * 600000
        dest = os.path.join(self.dir, "f")
        with Serve(body) as s:
            seen = []
            A.download({"url": s.url, "size": len(body), "digest": "sha256:" + hashlib.sha256(body).hexdigest()},
                       dest, lambda got, total: seen.append((got, total)))
            self.assertEqual(read(dest, "rb"), body)
            self.assertEqual(seen[-1], (len(body), len(body)))
            with self.assertRaises(A.ApiError) as cm:
                A.download({"url": s.url, "size": len(body), "digest": "sha256:" + "1" * 64}, dest)
            self.assertEqual(str(cm.exception), A.INSTALL_BAD_MSG)
            with self.assertRaises(A.ApiError) as cm:
                A.download({"url": s.url, "size": len(body) + 1, "digest": ""}, dest)
            self.assertEqual(str(cm.exception), A.INSTALL_FAIL_MSG)

    def test_a_cut_off_download_is_refused(self):
        with Serve(b"x" * 1000, length=5000) as s:
            with self.assertRaises(A.ApiError) as cm:
                A.download({"url": s.url, "size": 0, "digest": ""}, os.path.join(self.dir, "f"))
        self.assertEqual(str(cm.exception), A.INSTALL_FAIL_MSG)

    def test_offline(self):
        with self.assertRaises(A.ApiError) as cm:
            A.download({"url": "http://127.0.0.1:9/none", "size": 1, "digest": ""}, os.path.join(self.dir, "f"))
        self.assertEqual(str(cm.exception), A.INSTALL_FAIL_MSG)

    def stage(self, data):
        z, new = os.path.join(self.dir, "w.zip"), os.path.join(self.dir, "new")
        shutil.rmtree(new, True)
        os.makedirs(new)
        with open(z, "wb") as f:
            f.write(data)
        A.stage_windows(z, new)
        return sorted(os.listdir(new))

    def test_windows_zip_unpacks(self):
        self.assertEqual(self.stage(win_zip()), ["Ragdoll Mail.exe", "ragdoll.exe"])

    def test_windows_zip_refused(self):
        for bad in (b"not a zip", win_zip({"ragdoll.exe": b"MZ"}), win_zip({"Ragdoll Mail.exe": b"MZ", "../evil.exe": b"MZ"}),
                    win_zip({"Ragdoll Mail.exe": b"MZ", "sub/x.exe": b"MZ"}), win_zip({"Ragdoll Mail.exe": b"PK not a program"})):
            with self.assertRaises(A.ApiError) as cm:
                self.stage(bad)
            self.assertEqual(str(cm.exception), A.INSTALL_BAD_MSG)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "evil.exe")))

    def test_result_after_the_restart(self):
        path = os.path.join(self.dir, "update-result.json")

        def write(to, why=None, at=None):
            with open(path, "w") as f:
                json.dump({"from": "0.12.0", "to": to, "at": at or int(time.time())}, f)
            if why:
                with open(path + ".error", "w", encoding="utf-8-sig") as f:
                    f.write(why + "\n")
        write("0.13.0")
        self.assertEqual(A.update_result(self.dir, "0.13.0"), {"to": "0.13.0", "from": "0.12.0", "ok": True, "error": ""})
        self.assertIsNone(A.update_result(self.dir, "0.13.0"))          # said once
        write("0.13.0", "ragdoll.exe is in use. Close it and update again.")
        r = A.update_result(self.dir, "0.12.0")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "ragdoll.exe is in use. Close it and update again.")
        self.assertFalse(os.path.exists(path + ".error"))
        write("0.13.0")                                     # the old one is back with no reason left
        self.assertEqual(A.update_result(self.dir, "0.12.0")["error"], "The new version did not start.")
        write("0.13.0", at=1)
        self.assertIsNone(A.update_result(self.dir, "0.12.0"))


def backend():
    b = types.SimpleNamespace(update=None, update_at=0.0, demo=False, update_asset=None, update_staged=None,
                              update_lock=threading.Lock(), update_note=None, send_state=lambda: (0, 0))
    for name in ("check_update", "api_install_update", "api_restart_update", "api_update_note_seen"):
        setattr(b, name, getattr(A.Backend, name).__get__(b))
    return b


class InApp(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.target = os.path.join(self.home, "app")
        os.makedirs(self.target)
        for p in (unittest.mock.patch.object(A, "FROZEN", True),
                  unittest.mock.patch.object(A, "__version__", "0.12.0"),
                  unittest.mock.patch.object(A, "brew_cask", lambda: False),
                  unittest.mock.patch.object(A, "winget_install", lambda: False),
                  unittest.mock.patch.object(A, "app_target", lambda: self.target),
                  unittest.mock.patch.object(A.sys, "platform", "win32"),
                  unittest.mock.patch.object(A.R.CFG, "d", dict(A.R.CFG.d, data_dir=self.home))):
            p.start()
            self.addCleanup(p.stop)

    def check(self, b, rel):
        body = json.dumps(rel).encode()
        ans = unittest.mock.MagicMock(__enter__=lambda s: io.BytesIO(body), __exit__=lambda *a: False)
        with unittest.mock.patch.object(A.urllib.request, "urlopen", lambda *a, **k: ans):
            b.check_update()

    def test_download_then_restart(self):
        data = win_zip()
        b = backend()
        with Serve(data) as s:
            self.check(b, release(assets=[{"name": "ragdoll-mail-windows.zip", "browser_download_url": s.url,
                                           "size": len(data), "digest": "sha256:" + hashlib.sha256(data).hexdigest()}]))
            self.assertTrue(b.update["install"])
            out = b.api_install_update({})
        self.assertEqual(out["update"]["step"], "ready")
        work = os.path.join(self.home, "update")
        self.assertEqual(sorted(os.listdir(os.path.join(work, "new"))), ["Ragdoll Mail.exe", "ragdoll.exe"])
        self.assertFalse(os.path.exists(os.path.join(work, "ragdoll-mail-windows.zip")))
        self.check(b, release())                       # a later check keeps the ready download
        self.assertEqual(b.update["step"], "ready")
        calls = []
        with unittest.mock.patch.object(A, "start_helper", lambda *a: calls.append(a)), \
                unittest.mock.patch.object(A, "quit_app", lambda: calls.append("quit")):
            b.api_restart_update({})
            time.sleep(0.1)
        self.assertEqual(calls[0], ("win32", work, self.target, "0.12.0", "0.13.0"))
        self.assertEqual(calls[1], "quit")

    def test_a_failed_download_leaves_the_update_to_try_again(self):
        b = backend()
        with Serve(b"short", length=100) as s:
            self.check(b, release(assets=[{"name": "ragdoll-mail-windows.zip", "browser_download_url": s.url, "size": 100}]))
            with self.assertRaises(A.ApiError):
                b.api_install_update({})
        self.assertNotIn("step", b.update)
        self.assertTrue(b.update["install"])
        with self.assertRaises(A.ApiError):
            b.api_restart_update({})

    def test_no_restart_while_mail_goes_out(self):
        b = backend()
        b.update, b.update_staged = {"version": "0.13.0", "step": "ready"}, ("w", "t")
        b.send_state = lambda: (1, 0)
        with unittest.mock.patch.object(A, "start_helper") as h:
            with self.assertRaises(A.ApiError) as cm:
                b.api_restart_update({})
        self.assertEqual(str(cm.exception), A.INSTALL_BUSY_MSG)
        h.assert_not_called()

    def test_copies_that_cannot_update_themselves(self):
        b = backend()
        with unittest.mock.patch.object(A, "app_target", lambda: None):
            self.check(b, release())
        self.assertNotIn("install", b.update)
        with self.assertRaises(A.ApiError):
            b.api_install_update({})
        with unittest.mock.patch.object(A, "winget_install", lambda: True), \
                unittest.mock.patch.object(A, "app_target", lambda: None):
            self.check(b, release())
        self.assertEqual(b.update["command"], A.WINGET_UPGRADE)

    def test_the_note_is_said_once(self):
        b = backend()
        b.update_note = {"ok": True}
        b.api_update_note_seen({})
        self.assertIsNone(b.update_note)


class Helper(unittest.TestCase):
    """The real helper script, on stand-in apps: the swap, and the way back when the new one won't run."""
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.work = os.path.join(self.home, "update")
        self.new = os.path.join(self.work, "new")
        os.makedirs(self.new)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="\n") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def run_helper(self, target, launch=None):
        gone = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])   # the app, quitting
        p = A.start_helper(sys.platform if WIN else "darwin", self.work, target, "0.12.0", "0.13.0",
                           wait=3, launch=launch, pids=[gone.pid])
        gone.wait()
        p.wait(timeout=90)
        r = os.path.join(self.home, "update-result.json")
        with open(r) as f:
            self.assertEqual(json.load(f)["to"], "0.13.0")
        return read(r + ".error", encoding="utf-8-sig").strip() if os.path.exists(r + ".error") else None

    def windows(self, new_app):
        target = os.path.join(self.home, "Ragdoll Mail")
        self.write(os.path.join(target, "app.cmd"), "@exit /b 0\r\n")
        self.write(os.path.join(target, "ragdoll.exe"), "old cli")
        self.write(os.path.join(target, "notes.txt"), "the user's own file")
        self.write(os.path.join(self.new, "app.cmd"), new_app)
        self.write(os.path.join(self.new, "ragdoll.exe"), "new cli")
        return target, self.run_helper(target, launch="app.cmd")

    @unittest.skipUnless(WIN, "Windows helper")
    def test_windows_swap(self):
        target, why = self.windows("@ping -n 6 127.0.0.1 >nul\r\n")       # keeps running
        self.assertIsNone(why)
        self.assertIn("ping", read(os.path.join(target, "app.cmd")))
        self.assertEqual(read(os.path.join(target, "ragdoll.exe")), "new cli")
        self.assertEqual(read(os.path.join(target, "notes.txt")), "the user's own file")
        prev = os.path.join(self.home, "previous")
        self.assertEqual(read(os.path.join(prev, "ragdoll.exe")), "old cli")
        self.assertIn("exit /b 0", read(os.path.join(prev, "app.cmd")))

    @unittest.skipUnless(WIN, "Windows helper")
    def test_windows_way_back(self):
        target, why = self.windows("@exit /b 1\r\n")                        # stops at once
        self.assertEqual(why, "The new version did not start.")
        self.assertIn("exit /b 0", read(os.path.join(target, "app.cmd")))
        self.assertEqual(read(os.path.join(target, "ragdoll.exe")), "old cli")

    def mac(self, new_bin):
        target = os.path.join(self.home, "Applications", "Ragdoll Mail.app")
        self.write(os.path.join(target, "Contents", "MacOS", "ragdoll-mail"), "exit 0\n")
        self.write(os.path.join(self.new, "Ragdoll Mail.app", "Contents", "MacOS", "ragdoll-mail"), new_bin)
        launch = os.path.join(self.home, "launch.sh")            # stands in for open(1)
        self.write(launch, '#!/bin/sh\n/bin/sh "$1/Contents/MacOS/ragdoll-mail" >/dev/null 2>&1 &\n')
        return target, self.run_helper(target, launch=launch)

    @unittest.skipIf(WIN or not shutil.which("pgrep"), "Mac helper")
    def test_mac_swap(self):
        target, why = self.mac("sleep 6\n")
        self.assertIsNone(why)
        self.assertIn("sleep", read(os.path.join(target, "Contents", "MacOS", "ragdoll-mail")))
        prev = os.path.join(self.home, "previous", "Ragdoll Mail.app", "Contents", "MacOS", "ragdoll-mail")
        self.assertEqual(read(prev), "exit 0\n")

    @unittest.skipIf(WIN or not shutil.which("pgrep"), "Mac helper")
    def test_mac_way_back(self):
        target, why = self.mac("exit 1\n")
        self.assertEqual(why, "The new version did not start.")
        self.assertEqual(read(os.path.join(target, "Contents", "MacOS", "ragdoll-mail")), "exit 0\n")


if __name__ == "__main__":
    unittest.main()
