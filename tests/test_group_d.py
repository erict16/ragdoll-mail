"""Offline tests of sync, connections, errors, settings and prefs (0.11 group D)."""
import contextlib, imaplib, io, json, os, socket, sys, threading, time, unittest, unittest.mock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll_app as A  # noqa: E402
from test_app import LIGHT, PART, FakeServer, OwnBackend  # noqa: E402

R = A.R


class Sock:
    """A socket that records its timeouts; shutdown() ends whatever waits on it."""
    def __init__(self):
        self.timeouts, self.down = [], threading.Event()

    def settimeout(self, t):
        self.timeouts.append(t)

    def gettimeout(self):
        return self.timeouts[-1] if self.timeouts else None

    def shutdown(self, how):
        self.down.set()


class Hangs(FakeServer):
    """A connection that died while the laptop slept: LIST waits until its socket is shut down."""
    def __init__(self):
        super().__init__()
        self.sock = Sock()
        self.listed = False

    def list(self):
        if not self.sock.down.wait(5):
            raise AssertionError("nobody cut the dead connection")
        raise imaplib.IMAP4.abort("socket error: EOF")

    def noop(self):
        return "OK", [b""]


class Works(FakeServer):
    def __init__(self):
        super().__init__()
        self.sock = Sock()
        self.listed = False

    def list(self):
        self.listed = True
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

    def noop(self):
        return "OK", [b""]


def hung_server(answer_login=True):
    """A local server that greets and signs in, then never answers again. Returns its port."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def run():
        conn, _ = srv.accept()
        conn.sendall(b"* OK ready\r\n")
        buf = b""
        while True:
            try:
                data = conn.recv(4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                tag, _, rest = line.partition(b" ")
                cmd = rest.split(b" ")[0].upper()
                if cmd == b"CAPABILITY":
                    conn.sendall(b"* CAPABILITY IMAP4rev1\r\n" + tag + b" OK done\r\n")
                elif cmd == b"LOGIN" and answer_login:
                    conn.sendall(tag + b" OK signed in\r\n")
                # anything else: silence, like a connection that died during sleep
        conn.close()
        srv.close()
    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1]


class Timeouts(unittest.TestCase):
    """#40: no read from the server waits for good."""

    def setUp(self):
        self.cfg = R.CFG
        R.CFG = R.Cfg(dict(R.DEFAULTS, user="me@example.com", imap={"host": "127.0.0.1", "port": 993}))
        self.addCleanup(setattr, R, "CFG", self.cfg)
        self.addCleanup(setattr, R, "password", R.password)
        R.password = lambda: "pw"

    def test_a_connection_keeps_a_read_timeout_after_login(self):
        made = []

        class Fake:
            def __init__(self, host, port, timeout=None):
                self.sock, self.capabilities = Sock(), ()
                made.append(self)

            def login(self, user, pw):
                pass

            def capability(self):
                return "OK", [b"IMAP4rev1"]
        with unittest.mock.patch.object(R.imaplib, "IMAP4_SSL", Fake):
            R.imap()
        self.assertEqual(made[0].sock.timeouts, [R.IMAP_TIMEOUT])
        self.assertTrue(0 < R.IMAP_TIMEOUT <= 120)

    def test_a_dead_connection_gives_up(self):
        port = hung_server()

        class Plain(imaplib.IMAP4):     # the same reads as IMAP4_SSL, without TLS
            def __init__(self, host, port_, timeout=None):
                super().__init__(host, port, timeout=timeout)
        with unittest.mock.patch.object(R.imaplib, "IMAP4_SSL", Plain), \
                unittest.mock.patch.object(R, "IMAP_TIMEOUT", 0.3):
            m = R.imap()
            t = time.time()
            with self.assertRaises((socket.timeout, TimeoutError, imaplib.IMAP4.abort)):
                m.noop()
            self.assertLess(time.time() - t, 3)
            m.shutdown()

    def test_patient_waits_longer_then_goes_back(self):
        m = Works()
        m.sock.settimeout(60)
        with R.patient(m):
            self.assertEqual(m.sock.gettimeout(), R.BIG_WAIT)
        self.assertEqual(m.sock.gettimeout(), 60)
        with R.patient(object()):           # no socket: nothing to change
            pass

    def test_a_failed_session_does_not_wait_on_logout(self):
        m = Works()
        with unittest.mock.patch.object(R, "imap", lambda: m), self.assertRaises(OSError):
            with R.session():
                raise OSError("gone")
        self.assertEqual(m.sock.timeouts[-1], 3)


class Watchdog(OwnBackend):
    """#40: a sync pass that hangs on a dead connection is cut off and goes on."""

    def test_stuck_pass_is_cut(self):
        b = self.b
        b.sync_m, b.pass_at = Works(), time.monotonic() - b.SYNC_STUCK - 1
        with contextlib.redirect_stderr(self.err):
            b.watch_tick()
        self.assertTrue(b.sync_m.sock.down.is_set())
        self.assertTrue(b.pass_cut)

    def test_fresh_pass_is_left_alone(self):
        b = self.b
        b.sync_m, b.pass_at = Works(), time.monotonic()
        b.watch_tick()
        self.assertFalse(b.sync_m.sock.down.is_set())

    def test_sync_goes_on_after_a_hang(self):
        b = self.b
        conns = [Hangs(), Works()]
        self.patch(A.R, "imap", lambda: conns.pop(0))
        self.patch(A.R, "sync_headers", lambda *a, **kw: 0)
        self.patch(A.R, "sync_bodies", lambda *a, **kw: 0)
        b.note_new = lambda *a: None
        b.SYNC_STUCK = 0.2
        done = threading.Event()
        real = b.note_folders

        def note_folders(m, c):
            real(m, c)
            done.set()
            b.stopping.set()
        b.note_folders = note_folders
        stop = threading.Event()
        self.addCleanup(stop.set)

        def watch():
            with contextlib.redirect_stderr(self.err):
                while not stop.wait(0.05):
                    b.watch_tick()
        threading.Thread(target=watch, daemon=True).start()
        b.wake.set()
        t = threading.Thread(target=b.sync_loop, daemon=True)
        t.start()
        self.assertTrue(done.wait(5))
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertIsNone(b.sync["error"])


class Wake(OwnBackend):
    """#56: after sleep the kept connections are dead; the app connects again and looks for mail at once."""

    def test_time_jump_is_a_wake(self):
        b = self.b
        b.m, b.sync_m, b.pre_m = Works(), Works(), Works()
        with contextlib.redirect_stderr(self.err):
            b.watch_tick(mono=100, wall=1000)
            b.watch_tick(mono=102, wall=1002)          # an ordinary look
            self.assertFalse(b.wake.is_set() or b.woke_at)
            b.watch_tick(mono=104, wall=1900)          # macOS: the wall clock ran on in sleep
        self.assertTrue(b.wake.is_set())
        self.assertTrue(all(m.sock.down.is_set() for m in (b.m, b.sync_m, b.pre_m)))

    def test_long_gap_is_a_wake_too(self):
        b = self.b
        b.sync_m = Works()
        with contextlib.redirect_stderr(self.err):
            b.watch_tick(mono=100, wall=1000)
            b.watch_tick(mono=700, wall=1600)          # Windows: both clocks ran, the app did not
        self.assertTrue(b.wake.is_set() and b.sync_m.sock.down.is_set())

    def test_idle_connection_is_asked_briefly(self):
        class Dead(Works):
            def noop(self):
                raise socket.timeout("timed out")
        live, dead = Works(), Dead()
        self.assertTrue(A.still_there(dead, time.time(), 120))      # used a moment ago: not asked
        self.assertTrue(A.still_there(live, 0, 120))
        self.assertEqual(live.sock.timeouts, [6, 120])
        self.assertFalse(A.still_there(dead, 0, 120))
        self.assertEqual(dead.sock.timeouts[-1], 120)

    def test_sync_drops_a_dead_kept_connection(self):
        b = self.b

        class Dead(Works):
            def list(self):
                raise AssertionError("the dead connection was used")

            def noop(self):
                raise imaplib.IMAP4.abort("EOF")
        b.sync_m, b.sync_used = Dead(), 0
        fresh = Works()
        self.patch(A.R, "imap", lambda: fresh)
        self.patch(A.R, "sync_headers", lambda *a, **kw: 0)
        self.patch(A.R, "sync_bodies", lambda *a, **kw: 0)
        b.note_new = lambda *a: None
        real = b.note_folders

        def note_folders(m, c):
            real(m, c)
            b.stopping.set()
        b.note_folders = note_folders
        b.wake.set()
        b.sync_loop()
        self.assertTrue(fresh.listed)
        self.assertIsNone(b.sync["error"])


class Downloads(OwnBackend):
    """#55: a big file downloads on its own connection; other mail and marks do not wait for it."""

    def setUp(self):
        super().setUp()
        self.b.demo = False
        self.made = []

        def imap():
            m = Works()
            self.made.append(m)
            return m
        self.patch(A.R, "imap", imap)
        self.down = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.down, True)
        self.patch(A, "downloads_dir", lambda: self.down)

    def test_a_mark_goes_through_while_a_file_downloads(self):
        b, going, release = self.b, threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def fetch_part_raw(m, folder, uid, sec):
            going.set()
            release.wait(5)
            return PART
        self.patch(A.R, "fetch_part_raw", fetch_part_raw)
        b.view = lambda i: (LIGHT, True)
        i = self.ids(seen=1)[0]
        out = {}
        t = threading.Thread(target=lambda: out.update(b.api_attachment({"id": i, "i": 0, "action": "save"})))
        t.start()
        self.assertTrue(going.wait(5))
        started = time.time()
        b.set_flag([self.ids()[0]], "seen", True)          # waits for the server to have it
        self.assertLess(time.time() - started, 2)
        self.assertEqual(len(self.made), 2)                  # one connection each
        self.assertIsNot(b.m, b.dm)
        release.set()
        t.join(5)
        self.assertEqual(out["name"], "big.pdf")

    def test_big_whole_mail_downloads_aside_small_one_on_the_main_connection(self):
        b, used = self.b, []
        b.imap = lambda fn: used.append("main") or fn(Works())
        b.download = lambda fn: used.append("download") or fn(Works())
        self.patch(A.R, "fetch_raw", lambda m, f, u: b"Subject: x\r\n\r\nhi")
        small, big = self.ids()[:2]
        b.exec("update msgs set size=? where folder=? and uid=?", (R.LIGHT_MIN + 1, *R.parse_id(big)))
        b.exec("update msgs set size=? where folder=? and uid=?", (1000, *R.parse_id(small)))
        b.raw(small)
        b.raw(big)
        self.assertEqual(used, ["main", "download"])

    def test_idle_download_connection_is_let_go(self):
        b = self.b
        b.download(lambda m: None)
        self.assertIsNotNone(b.dm)
        b.dm_used = time.time() - b.DOWNLOAD_IDLE - 1
        b.watch_tick()
        self.assertIsNone(b.dm)


if __name__ == "__main__":
    unittest.main()
