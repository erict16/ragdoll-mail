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
            def __init__(self, host, port, timeout=None, **kw):
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
            def __init__(self, host, port_, timeout=None, **kw):
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


class BodyServer(Works):
    """Answers a body FETCH for each UID asked, except the ones in `gone`."""
    def __init__(self, gone=()):
        super().__init__()
        self.gone = set(gone)

    def uid(self, *args):
        self.calls.append(("uid",) + args)
        if args[0] == "FETCH" and "BODY.PEEK[]" in args[2]:
            out = []
            for k, u in enumerate(args[1].split(",")):
                if int(u) in self.gone:
                    continue
                lit = b"Subject: s\r\nContent-Type: text/plain\r\n\r\nbody of %s" % u.encode()
                out += [(b"%d (UID %s BODY[]<0> {%d}" % (k + 1, u.encode(), len(lit)), lit), b")"]
            return "OK", out
        return "OK", [b""]


class Bodies(OwnBackend):
    """#57: the first download of mail text: newest first, many per command, no sync work in between."""

    def setUp(self):
        super().setUp()
        b = self.b
        b.demo = False
        b.BODY_PAUSE = 0
        b.exec("update msgs set has_body=0, body='' where folder='INBOX'")
        self.uids = [r["uid"] for r in b.q("select uid from msgs where folder='INBOX' order by ts desc")]
        self.server = BodyServer()
        self.patch(A.R, "imap", lambda: self.server)
        self.patch(A.R.CFG, "sync_folders", ["INBOX"])

    def fetches(self):
        return [c for c in self.server.calls if c[:2] == ("uid", "FETCH")]

    def test_all_text_in_few_commands_newest_first(self):
        b = self.b
        b.body_folders = lambda: ["INBOX"]
        self.patch(A.R, "BODY_BATCH", 4)
        with b.dblock:
            b.fetch_bodies_now(b.c)
        self.assertEqual(b.q("select count(*) n from msgs where folder='INBOX' and has_body=0")[0]["n"], 0)
        asked = [int(u) for c in self.fetches() for u in c[2].split(",")]
        self.assertEqual(asked, self.uids)                          # newest first, each once
        self.assertEqual(len(self.fetches()), -(-len(self.uids) // 4))
        self.assertEqual(len([c for c in self.server.calls if c[0] == "select"]), 1)
        self.assertIn("body of", b.q("select body from msgs where folder='INBOX' and uid=?", (self.uids[0],))[0]["body"])

    def test_mail_the_server_does_not_give_is_not_asked_for_ever(self):
        b = self.b
        b.body_folders = lambda: ["INBOX"]
        self.server.gone = {self.uids[0]}
        with b.dblock:
            b.fetch_bodies_now(b.c)
        self.assertEqual(len(self.fetches()), 1)
        self.assertEqual([r["uid"] for r in b.q("select uid from msgs where folder='INBOX' and has_body=0")],
                         [self.uids[0]])

    def test_makes_way_for_the_user(self):
        b = self.b
        b.body_folders = lambda: ["INBOX"]
        b.BODY_QUIET = 0.3
        b.call("mark_all_read", {"folder": "nowhere"})                # anything the user does
        t = time.time()
        with b.dblock:
            b.fetch_bodies_now(b.c)
        self.assertGreater(time.time() - t, 0.25)
        b.active_at = 0
        b.call("status", {})                                        # a poll is not the user
        self.assertEqual(b.active_at, 0)

    def test_sync_pass_hands_bodies_to_the_worker(self):
        b, kicked = self.b, []
        b.start_bodies = lambda: kicked.append(1)
        self.patch(A.R, "sync_headers", lambda *a, **kw: 0)
        b.note_new = lambda *a: None
        real = b.note_folders

        def note_folders(m, c):
            real(m, c)
            b.stopping.set()
        b.note_folders = note_folders
        b.wake.set()
        b.sync_loop()
        self.assertEqual(kicked, [1])


def add_row(b, folder, uid, has_body=1):
    with b.dblock:
        cur = b.c.execute(
            "insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,"
            "answered,has_body) values(?,1,?,?,'','',1700000000,'a@b.c','me@example.com','','ghost','','',1,0,0,?)",
            (folder, uid, "<%s-%d@x>" % (folder, uid), has_body))
        b.c.execute("insert into fts(rowid,subject,frm,to_,atts,body) values(?,'ghost','','','','')", (cur.lastrowid,))
        b.c.execute("insert or replace into state values(?,1)", (folder,))
        b.c.commit()


class Listed(Works):
    def __init__(self, names):
        super().__init__()
        self.names = names

    def list(self):
        return "OK", [('(\\HasNoChildren) "/" "%s"' % R.mutf7(n)).encode() for n in self.names]


class GoneFolders(OwnBackend):
    """#48: a folder renamed or deleted elsewhere leaves no ghost mail and no busy sync."""

    def test_rows_of_a_folder_the_server_lost_go(self):
        b = self.b
        add_row(b, "华明印尼", 1)
        add_row(b, "Keep", 2)
        with b.dblock:
            b.note_folders(Listed(["INBOX", "Keep"]), b.c)
        self.assertEqual(b.q("select count(*) n from msgs where folder='华明印尼'")[0]["n"], 0)
        self.assertEqual(b.q("select count(*) n from state where folder='华明印尼'")[0]["n"], 0)
        self.assertEqual(b.q("select count(*) n from fts where subject='ghost'")[0]["n"], 1)
        self.assertEqual(b.q("select count(*) n from msgs where folder='Keep'")[0]["n"], 1)
        self.assertTrue(b.q("select count(*) n from msgs where folder='INBOX'")[0]["n"])

    def test_a_failed_list_removes_nothing(self):
        b = self.b
        add_row(b, "Keep", 2)
        for names in ([], ["Keep"]):            # nothing, or an answer without the inbox
            with b.dblock:
                b.note_folders(Listed(names), b.c)
        self.assertEqual(b.q("select count(*) n from msgs where folder='Keep'")[0]["n"], 1)

    def test_body_download_skips_a_folder_that_went(self):
        b = self.b
        b.demo, b.BODY_PAUSE = False, 0

        class Server(BodyServer):
            def select(self, name, readonly=True):
                self.calls.append(("select", name, readonly))
                return ("NO", [b"no such folder"]) if "Gone" in name else ("OK", [b"1"])
        server = Server()
        self.patch(A.R, "imap", lambda: server)
        add_row(b, "Gone", 1, has_body=0)
        add_row(b, "INBOX", 9001, has_body=0)
        b.body_folders = lambda: ["Gone", "INBOX"]
        with b.dblock:
            b.fetch_bodies_now(b.c)
        self.assertEqual(b.q("select has_body from msgs where folder='INBOX' and uid=9001")[0]["has_body"], 1)
        self.assertEqual(len([c for c in server.calls if c[0] == "select" and "Gone" in c[1]]), 1)

    def test_only_folders_on_the_server_get_their_text(self):
        b = self.b
        b.server_folders = ["INBOX", "Sent Messages"]
        self.assertEqual([f for f in b.body_folders() if f not in ("INBOX", "Sent Messages")], [])


class OwnFolders(OwnBackend):
    """#39: the owner's own folders are looked at on every pass; synced when their STATUS changed."""

    class Server(Listed):
        def __init__(self, names):
            super().__init__(names)
            self.st = {n: [3, 10, 1, 7] for n in names}

        def status(self, name, what):
            n = R.mutf7_decode(name.strip('"'))
            if n not in self.st:
                return "NO", [b"no"]
            v = self.st[n]
            return "OK", [b'"x" (MESSAGES %d UIDNEXT %d UNSEEN %d UIDVALIDITY %d)' % tuple(v)]

    def setUp(self):
        super().setUp()
        self.synced = []
        self.patch(A.R, "sync_headers", lambda m, c, f, **kw: self.synced.append(f) or 0)
        self.b.note_new = lambda c: None
        self.server = self.Server(["INBOX", "Sent Messages", "Drafts", "Junk", "华明印尼", "Projects"])
        self.patch(A.R.CFG, "sync_folders", ["INBOX", "Sent Messages", "Drafts"])
        self.b.others = lambda: [("华明印尼", "华明印尼", 0), ("Projects", "Projects", 0)]

    def run_pass(self):
        self.synced = []
        with self.b.dblock:
            self.b.sync_pass(self.server, self.b.c)
        return [f for f in self.synced if f in ("Junk", "华明印尼", "Projects")]

    def test_only_a_changed_folder_is_synced_between_full_passes(self):
        self.assertEqual(sorted(self.run_pass()), sorted(["Junk", "华明印尼", "Projects"]))     # the first pass: all
        self.assertEqual(self.run_pass(), [])                                   # nothing changed
        self.server.st["华明印尼"][1] = 11                                      # a server rule filed new mail
        self.assertEqual(self.run_pass(), ["华明印尼"])
        self.assertEqual(self.run_pass(), [])
        self.server.st["Projects"][2] = 0                                       # read on the phone
        self.assertEqual(self.run_pass(), ["Projects"])
        self.b.extra_at = time.time() - self.b.EXTRA_EVERY - 1                  # now and then: all again
        self.assertEqual(len(self.run_pass()), 3)

    def test_folder_without_status_is_synced_as_before(self):
        self.run_pass()
        del self.server.st["Projects"]
        self.assertEqual(self.run_pass(), ["Projects"])

    def test_status_parsing(self):
        self.assertEqual(A.folder_status(self.server, "华明印尼"), (3, 10, 1, 7))
        self.assertIsNone(A.folder_status(self.server, "nowhere"))
        self.assertIsNone(A.folder_status(FakeServer(), "INBOX"))               # no STATUS at all


class FlagServer:
    """A folder of `n` mails with flags kept here; CONDSTORE when `modseq` is given."""
    def __init__(self, n, unseen=(), modseq=None):
        self.uids = list(range(1, n + 1))
        self.flags = {u: ({"\\Seen"} if u not in set(unseen) else set()) for u in self.uids}
        self.modseq, self.changed = modseq, {}
        self.capabilities = ("IMAP4REV1",) + (("CONDSTORE",) if modseq is not None else ())
        self.calls, self.untagged_responses = [], {}

    def set(self, uid, *flags):
        self.flags[uid] = set(flags)
        if self.modseq is not None:
            self.modseq += 1
            self.changed[uid] = self.modseq

    def select(self, name, readonly=True):
        return "OK", [str(len(self.uids)).encode()]

    def response(self, code):
        return code, [b"1"]

    def status(self, name, what):
        return "OK", [b'"INBOX" (HIGHESTMODSEQ %d)' % self.modseq]

    def uid(self, cmd, *args):
        self.calls.append((cmd,) + args)
        if cmd == "SEARCH":
            key = args[-1]
            hit = {"ALL": lambda u: True, "UNSEEN": lambda u: "\\Seen" not in self.flags[u],
                   "FLAGGED": lambda u: "\\Flagged" in self.flags[u]}[key]
            return "OK", [" ".join(str(u) for u in self.uids if hit(u)).encode()]
        if cmd == "FETCH":
            want = self.uids if args[0] == "1:*" else [int(x) for x in args[0].split(",")]
            since = None
            if "CHANGEDSINCE" in args[1]:
                since = int(args[1].split("CHANGEDSINCE ")[1].rstrip(")"))
            out = []
            for k, u in enumerate(want, 1):
                if since is not None and self.changed.get(u, 0) <= since:
                    continue
                out.append(b"%d (UID %d FLAGS (%s))" % (k, u, " ".join(sorted(self.flags[u])).encode()))
            return "OK", out
        return "OK", [b""]


class OlderFlags(unittest.TestCase):
    """#47: read / unread of mail older than the newest 300 follows the server."""

    def setUp(self):
        import tempfile, shutil
        self.cfg = R.CFG
        R.CFG = R.Cfg(dict(R.DEFAULTS, user="me@example.com", data_dir=tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, R.CFG.home, True)
        self.addCleanup(setattr, R, "CFG", self.cfg)
        self.c = R.db()
        self.addCleanup(self.c.close)

    def fill(self, n):
        for u in range(1, n + 1):
            self.c.execute("insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,"
                           "flagged,answered,has_body) values('INBOX',1,?,?,'','',?,'a@b.c','','','s','','',0,0,0,1)",
                           (u, "<%d@x>" % u, 1700000000 + u))
        self.c.execute("insert or replace into state values('INBOX', 1)")
        self.c.commit()

    def unread(self):
        return self.c.execute("select count(*) from msgs where seen=0").fetchone()[0]

    def test_all_read_on_the_server_is_read_here(self):
        self.fill(1000)
        R.sync_headers(FlagServer(1000), self.c, "INBOX")
        self.assertEqual(self.unread(), 700)                    # the old way: only the newest 300
        R.sync_headers(FlagServer(1000), self.c, "INBOX", deep=True)
        self.assertEqual(self.unread(), 0)

    def test_unread_and_flagged_elsewhere(self):
        self.fill(1000)
        srv = FlagServer(1000)
        R.sync_headers(srv, self.c, "INBOX", deep=True)
        srv.set(5)                                              # marked unread on the phone
        srv.set(6, "\\Seen", "\\Flagged")
        R.sync_headers(srv, self.c, "INBOX", deep=True)
        got = {r[0]: (r[1], r[2]) for r in self.c.execute("select uid, seen, flagged from msgs where uid in (5,6,7)")}
        self.assertEqual(got, {5: (0, 0), 6: (1, 1), 7: (1, 0)})

    def test_held_mark_stays(self):
        self.fill(400)
        R.sync_headers(FlagServer(400, unseen=[3]), self.c, "INBOX", deep=True,
                       held=lambda f, since: {3: {"seen": 1}})
        self.assertEqual(self.c.execute("select seen from msgs where uid=3").fetchone()[0], 1)

    def test_answered_comes_in_by_the_sweep(self):
        self.fill(R.SWEEP + 800)
        srv = FlagServer(R.SWEEP + 800)
        srv.set(1, "\\Seen", "\\Answered")
        srv.set(R.SWEEP + 400, "\\Seen", "\\Answered")
        answered = lambda: [r[0] for r in self.c.execute("select uid from msgs where answered=1 order by uid")]
        R.sync_headers(srv, self.c, "INBOX", deep=True)
        self.assertEqual(answered(), [R.SWEEP + 400])           # the newest older ones first
        R.sync_headers(srv, self.c, "INBOX", deep=True)
        self.assertEqual(answered(), [1, R.SWEEP + 400])        # then the rest, in turn

    def test_condstore_asks_only_for_changes(self):
        self.fill(1000)
        srv = FlagServer(1000, modseq=100)
        R.sync_headers(srv, self.c, "INBOX", deep=True)         # the first pass: everything once
        self.assertEqual(self.unread(), 0)
        srv.calls.clear()
        srv.set(10)
        R.sync_headers(srv, self.c, "INBOX", deep=True)
        self.assertEqual(self.unread(), 1)
        self.assertFalse([c for c in srv.calls if c[0] == "SEARCH" and c[-1] != "ALL"])
        self.assertTrue([c for c in srv.calls if c[0] == "FETCH" and "CHANGEDSINCE 100" in c[2]])
        srv.calls.clear()
        R.sync_headers(srv, self.c, "INBOX", deep=True)         # nothing changed: nothing asked
        self.assertFalse([c for c in srv.calls if c[0] == "FETCH" and "CHANGEDSINCE" in c[2]])


class OtherSync(OwnBackend):
    """#53: while another process holds the index, the app does not say it synced."""

    def one_pass(self):
        b = self.b
        b.stopping.clear()
        b.start_bodies = lambda: b.stopping.set()
        b.wake.set()
        b.sync_loop()

    def test_busy_lock_is_not_a_sync(self):
        b = self.b
        self.patch(A.R, "imap", Works)
        b.sync_pass = lambda m, c: None
        with R.file_lock("headers", wait=False) as got:
            self.assertTrue(got)
            self.one_pass()
            self.assertIsNone(b.sync["last"])
            self.assertIsNone(b.sync["error"])
            b.lock_busy = time.time() - b.LOCK_WARN - 1          # held for minutes
            self.one_pass()
            self.assertEqual(b.sync["error"], A.BUSY_MSG)
            self.assertIsNone(b.sync["last"])
        self.one_pass()                                         # free again: a real sync
        self.assertIsNone(b.sync["error"])
        self.assertIsNotNone(b.sync["last"])
        self.assertIsNone(b.lock_busy)


class PlainErrors(OwnBackend):
    """#58: errors in plain words the page can translate; the server's raw text only as detail."""

    def test_sentences_and_kinds(self):
        cases = [
            (imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials"), "auth"),
            (SystemExit("RAGDOLL_PASSWORD is not set and no password is saved"), "config"),
            (SystemExit("no account configured: copy config.example.json"), "config"),
            (socket.gaierror(8, "nodename nor servname provided"), "offline"),
            (socket.timeout("timed out"), "offline"),
            (ConnectionRefusedError(61, "Connection refused"), "offline"),
            (OSError(51, "Network is unreachable"), "offline"),
            (imaplib.IMAP4.abort("socket error: EOF"), "offline"),
            (LookupError("cannot open folder 华明印尼: [b'Folder not exist']"), "server"),
            (SystemExit("no mail INBOX:123 (moved or deleted? run search again)"), "server"),
            (R.Refused("the server refused the move after 200 mails: [b'quota']", 200), "server"),
            (imaplib.IMAP4.error("[b'Mailbox is full']"), "server"),
        ]
        for e, kind in cases:
            msg, k, detail = A.explain(e)
            self.assertEqual(k, kind, msg)
            self.assertNotIn("[b'", msg)
            self.assertNotIn("run search again", msg)
        self.assertEqual(A.friendly(cases[8][0]), "Can't open the folder 华明印尼 on the server.")
        out = self.b.call("mark", {"ids": "INBOX:1", "flag": "nope"})[1]
        self.assertFalse(out["ok"])

    def test_call_gives_the_raw_text_as_detail(self):
        def boom(a):
            raise LookupError("cannot open folder X: [b'gone']")
        self.b.api_boom = boom
        out = self.b.call("boom", {})[1]
        self.assertEqual(out["error"], "Can't open the folder X on the server.")
        self.assertIn("[b'gone']", out["detail"])

    def test_mail_deleted_elsewhere_leaves_the_list(self):
        b = self.b
        b.demo = False
        i = self.ids()[0]
        b.imap = b.download = lambda fn: fn(FakeServer())
        self.patch(A.R, "fetch_raw", lambda m, f, u: A.R.die("no mail %s (moved or deleted? run search again)" % i))
        rev = b.rev
        with self.assertRaises(A.ApiError) as cm:
            b.raw(i)
        self.assertEqual(str(cm.exception), A.GONE_MSG)
        self.assertFalse(b.q("select 1 from msgs where folder=? and uid=?", A.R.parse_id(i)))
        self.assertGreater(b.rev, rev)

    def test_part_of_a_move_that_went_leaves_the_old_folder(self):
        b = self.b
        b.demo = False
        b.imap = lambda fn: fn(FakeServer())
        b.folders = lambda m: ["INBOX", "Archive", "Sent Messages"]
        self.patch(A.R.CFG, "folders", dict(A.R.CFG.folders, archive="Archive"))
        inbox = self.ids(seen=1)[:2]
        sent = [A.R.make_id("Sent Messages", r["uid"]) for r in b.q("select uid from msgs where folder='Sent Messages'")][:1]

        def move_uids(m, folder, uids, dest):
            if folder == "Sent Messages":
                raise A.R.Refused("the server refused the move after 0 mails: [b'no']", 0)
            raise A.R.Refused("the server refused the move after 1 mails: [b'no']", 1)
        self.patch(A.R, "move_uids", move_uids)
        out = b.call("move", {"ids": inbox + sent, "to": "archive"})[1]
        self.assertFalse(out["ok"])
        self.assertNotIn("[b'", out["error"])
        left = [A.R.make_id("INBOX", r["uid"]) for r in b.q("select uid from msgs where folder='INBOX'")]
        first = sorted(inbox, key=lambda x: A.R.parse_id(x)[1])[0]
        self.assertNotIn(first, left)                               # it went: not shown in the inbox any more
        self.assertIn(sorted(inbox, key=lambda x: A.R.parse_id(x)[1])[1], left)

    def test_setup_messages(self):
        self.assertEqual(self.b.call("test", {"user": "nope"})[1]["error"], "Enter a full email address.")


class StatusFields(OwnBackend):
    """#54: the status the page polls says what kind of problem, when it last synced, when it retries."""

    def run_pass(self, imap):
        b = self.b
        b.demo = False
        b.stopping.clear()
        self.patch(A.R, "imap", imap)
        b.start_bodies = lambda: None
        b.sync_pass = lambda m, c: b.stopping.set()
        b.wake.set()
        t = time.time()
        if imap is not Works:
            b.wake.set()
            threading.Timer(0.05, b.stopping.set).start()
            threading.Timer(0.08, b.wake.set).start()
        b.sync_loop()
        return t

    def fields(self):
        st = self.b.api_status({})
        return {k: st[k] for k in ("error_kind", "last_sync", "retry_at", "error_detail")}

    def failing(self, e):
        def imap():
            raise e
        return imap

    def test_kinds_from_real_failures(self):
        for e, kind in ((socket.gaierror(8, "nodename nor servname"), "offline"),
                        (ConnectionRefusedError(61, "refused"), "offline"),
                        (socket.timeout("timed out"), "offline"),
                        (imaplib.IMAP4.error("LOGIN failed: invalid password"), "auth"),
                        (SystemExit("RAGDOLL_PASSWORD is not set and no password is saved"), "config"),
                        (SystemExit("no account configured"), "config"),
                        (imaplib.IMAP4.error("[b'Server busy']"), "server")):
            self.b.clear_error()
            t = self.run_pass(self.failing(e))
            f = self.fields()
            self.assertEqual(f["error_kind"], kind, e)
            self.assertGreaterEqual(f["retry_at"], int(t))
            self.assertTrue(f["error_detail"])

    def test_retry_waits_longer_each_time(self):
        b = self.b
        waits = [b.note_error(OSError(51, "Network is unreachable")) for _ in range(7)]
        self.assertEqual(waits, [15, 30, 60, 120, 300, 300, 300])

    def test_good_sync_clears_it(self):
        self.run_pass(self.failing(OSError(51, "unreachable")))
        self.assertEqual(self.fields()["error_kind"], "offline")
        t = int(time.time())
        self.run_pass(Works)
        f = self.fields()
        self.assertEqual((f["error_kind"], f["retry_at"], f["error_detail"]), (None, None, None))
        self.assertGreaterEqual(f["last_sync"], t)

    def test_no_problem_no_fields(self):
        self.assertEqual(self.fields(), {"error_kind": None, "last_sync": None, "retry_at": None, "error_detail": None})


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BrokenConfig(OwnBackend):
    """#49: a typo in config.json does not stop the app; setup says so and keeps a copy of the file."""

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, R, "CONFIG_ERROR", None)
        self.path = os.path.join(self.home, "config.json")

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_load_config_survives_a_typo(self):
        for text in ('{"user": "a@b.c",}', '["not", "an", "object"]', '{"imap": "imap.example.com"}'):
            self.write(text)
            cfg = R.load_config(self.path)
            self.assertEqual(cfg.user, "")
            self.assertEqual(cfg.imap["port"], 993)
            self.assertEqual(R.CONFIG_ERROR["path"], self.path, text)
        self.write('{"user": "A@B.C"}')
        self.assertEqual(R.load_config(self.path).user, "a@b.c")
        self.assertIsNone(R.CONFIG_ERROR)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"user": "A@B.C"}')           # never written over

    def test_app_starts_with_a_broken_file(self):
        import subprocess
        self.write('{"user": "a@b.c",,}')
        env = dict(os.environ, HOME=self.home, RAGDOLL_CONFIG=self.path, RAGDOLL_PASSWORD="x", PYTHONUTF8="1")
        code = "import ragdoll_app as A; print(A.R.CONFIG_ERROR['path'])"
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, cwd=ROOT)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), self.path)
        cli = subprocess.run([sys.executable, "ragdoll.py", "sync"], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=30, cwd=ROOT)
        self.assertNotEqual(cli.returncode, 0)
        self.assertIn("can't be read", cli.stderr)
        self.assertNotIn("Traceback", cli.stderr)

    def test_boot_and_status_tell_the_page(self):
        b = self.b
        b.demo = False
        R.CONFIG_ERROR = {"path": self.path, "error": "Expecting property name: line 1 column 18"}
        boot = b.api_boot({})
        self.assertEqual(boot["config_error"]["path"], self.path)
        self.assertIn(self.path, b.made)                            # the page may show the file
        st = b.api_status({})
        self.assertEqual((st["error"], st["error_kind"]), (A.CONFIG_MSG, "config"))

    def test_setup_again_keeps_a_copy(self):
        self.write('{"user": "a@b.c",}')
        self.patch(A, "config_path", lambda: self.path)
        self.online()
        self.b.start_sync = lambda: None
        self.b.api_save_settings({"user": "you@example.com", "name": "Alex", "imap_host": "demo", "smtp_host": "demo"})
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["user"], "you@example.com")
        kept = [n for n in os.listdir(self.home) if n.startswith("config.json.broken-")]
        self.assertEqual(len(kept), 1)
        with open(os.path.join(self.home, kept[0]), encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"user": "a@b.c",}')

class SettingsChange(OwnBackend):
    """#59: saving another account or server applies at once; the old one stops syncing."""

    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.home, "config.json")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"user": "you@example.com", "data_dir": self.home, "imap": {"host": "demo", "port": 993},
                       "smtp": {"host": "demo", "port": 465}}, f)
        self.patch(A, "config_path", lambda: self.path)
        self.addCleanup(setattr, R, "CONFIG_ERROR", None)
        self.online()
        self.b.start_sync = lambda: None
        self.b.sync_m, self.b.pre_m, self.b.body_m = Works(), Works(), Works()
        self.old = [self.b.sync_m, self.b.pre_m, self.b.body_m]

    def save(self, **kw):
        a = {"user": "you@example.com", "name": "Alex", "imap_host": "demo", "imap_port": 993,
             "smtp_host": "demo", "smtp_port": 465}
        a.update(kw)
        return self.b.api_save_settings(a)

    def count(self):
        return self.b.q("select count(*) n from msgs")[0]["n"]

    def test_same_account_changes_nothing(self):
        n, gen = self.count(), self.b.gen
        self.save(name="Alex Morgan")
        self.assertEqual((self.count(), self.b.gen), (n, gen))
        self.assertFalse(any(m.sock.down.is_set() for m in self.old))

    def test_other_server_reconnects_and_keeps_the_mail(self):
        n, gen = self.count(), self.b.gen
        self.save(imap_host="imap.other.example")
        self.assertEqual(self.b.gen, gen + 1)
        self.assertTrue(all(m.sock.down.is_set() for m in self.old))      # every loop's connection
        self.assertEqual(self.count(), n)
        self.assertTrue(self.b.redetect)                                   # saved without "Test connection"

    def test_other_account_starts_clean(self):
        b = self.b
        r = b.q("select * from msgs limit 1")[0]
        cached = R.cache_path(r["folder"], r["uidv"], r["uid"])
        R.cache_put(cached, b"old account's mail")
        b.exec("insert or replace into meta values('modseq:INBOX', '1 5')")
        self.save(user="other@example.org", imap_host="imap.example.org")
        self.assertEqual(self.count(), 0)
        self.assertFalse(os.path.exists(cached))
        self.assertFalse(b.q("select 1 from meta where k like 'modseq:%'"))
        self.assertEqual(R.CFG.user, "other@example.org")

    def test_folder_names_found_again(self):
        b = self.b
        self.save(user="other@example.org", imap_host="imap.example.org")
        b.found = [("INBOX", ""), ("已发送", "\\sent"), ("草稿箱", "\\drafts"), ("已删除", "\\trash")]
        b.use_detected(A.detect_folders(b.found))
        self.assertEqual(R.CFG.folders["sent"], "已发送")
        self.assertEqual(R.CFG.sync_folders, ["INBOX", "已发送", "草稿箱"])
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["folders"]["drafts"], "草稿箱")

    def test_pass_under_way_stops(self):
        b = self.b
        b.pass_gen = b.gen
        b.gen += 1
        b.note_folders = lambda m, c: None
        with self.assertRaises(A.Restart), b.dblock:
            b.sync_pass(Works(), b.c)

class Prefs(OwnBackend):
    """#61: changes made at the same moment are all kept."""

    def test_changes_at_once_lose_nothing(self):
        b = self.b
        b.api_prefs({"lang": "zh-Hans", "theme": "dark"})
        sizes = [12, 13, 14, 15, 16, 18, 20, 14]
        for _ in range(5):
            go = threading.Barrier(len(sizes) + 1)

            def one(n):
                go.wait()
                b.call("prefs", {"text_size": n})
            ts = [threading.Thread(target=one, args=(n,)) for n in sizes]
            for t in ts:
                t.start()
            reader = []
            go.wait()
            for _ in range(20):
                reader.append(b.prefs().get("lang"))        # a reader never sees half a file
            for t in ts:
                t.join(5)
            self.assertEqual(set(reader), {"zh-Hans"})
            p = b.prefs()
            self.assertEqual((p["lang"], p["theme"]), ("zh-Hans", "dark"))
            self.assertIn(p["text_size"], sizes)
        self.assertFalse([n for n in os.listdir(self.home) if n.endswith(".tmp")])

    def test_a_file_that_is_not_an_object_counts_as_empty(self):
        with open(os.path.join(self.home, "app.json"), "w", encoding="utf-8") as f:
            f.write("[1, 2]")
        self.assertEqual(self.b.prefs(), {})
        self.assertEqual(self.b.api_prefs({"lang": "de"})["lang"], "de")

def part(headers, body):
    return R.to_msg(headers.encode() + b"\r\n\r\n" + body)


class NoCharset(unittest.TestCase):
    """#46: a text part without a charset (or with the wrong one) is read right."""

    def test_utf8_without_charset(self):
        self.assertEqual(R.part_text(part("Content-Type: text/plain", "报价单 PO-1234".encode())), "报价单 PO-1234")

    def test_gb2312_html_with_only_a_meta_charset(self):
        html = '<html><head><meta http-equiv="Content-Type" content="text/html; charset=gb2312"></head>' \
               '<body>报价 附件</body></html>'
        got = R.part_text(part("Content-Type: text/html", html.encode("gb2312")))
        self.assertIn("报价 附件", got)
        self.assertNotIn("�", got)

    def test_gbk_without_meta(self):
        self.assertEqual(R.part_text(part("Content-Type: text/plain", "陈喆 您好".encode("gbk"))), "陈喆 您好")

    def test_labelled_utf8_but_gbk(self):
        self.assertEqual(R.part_text(part("Content-Type: text/plain; charset=utf-8", "您好".encode("gbk"))), "您好")

    def test_big5_shift_jis_euc_kr(self):
        self.assertEqual(R.decode_text("請見附件".encode("big5"), "big5"), "請見附件")
        self.assertEqual(R.decode_text("見積書".encode("shift_jis"), "shift_jis"), "見積書")
        self.assertEqual(R.decode_text("見積書です".encode("shift_jis"), None).count("�"), 0)     # some reading, never "�"
        self.assertEqual(R.decode_text("견적서".encode("euc-kr"), "euc-kr"), "견적서")

    def test_western_without_charset(self):
        self.assertEqual(R.part_text(part("Content-Type: text/plain", "Caf\xe9 au lait, r\xe9sum\xe9".encode("latin-1"))),
                         "Café au lait, résumé")
        self.assertEqual(R.part_text(part("Content-Type: text/plain", "“quoted”".encode("cp1252"))),
                         "“quoted”")

    def test_cut_in_the_middle_of_a_character(self):
        raw = "报价单".encode()[:-1]                       # the index reads only the start of a mail
        self.assertEqual(R.part_text(part("Content-Type: text/plain; charset=utf-8", raw)), "报价")

    def test_base64_and_qp(self):
        import base64 as b64
        body = b64.b64encode("请查收报价".encode())
        self.assertEqual(R.part_text(part("Content-Type: text/plain\r\nContent-Transfer-Encoding: base64", body)),
                         "请查收报价")
        qp = b"=E8=AF=B7=E6=9F=A5=E6=94=B6"
        self.assertEqual(R.part_text(part("Content-Type: text/plain\r\nContent-Transfer-Encoding: quoted-printable", qp)),
                         "请查收")

    def test_garbled_rows_are_fetched_again(self):
        import tempfile, shutil
        cfg = R.CFG
        R.CFG = R.Cfg(dict(R.DEFAULTS, data_dir=tempfile.mkdtemp()))
        self.addCleanup(setattr, R, "CFG", cfg)
        self.addCleanup(shutil.rmtree, R.CFG.home, True)
        c = R.db()
        c.execute("delete from meta where k='charset_fix2'")
        c.execute("insert into msgs(folder,uidv,uid,msgid,ts,frm,subject,body,seen,flagged,answered,has_body) "
                  "values('INBOX',1,1,'<a@x>',1,'a','s','���',1,0,0,1)")
        c.commit()
        c.close()
        c = R.db()
        self.assertEqual(tuple(c.execute("select body, has_body from msgs").fetchone()), ("", 0))
        c.close()

@unittest.skipUnless(__import__("shutil").which("node"), "needs node to read app/i18n.js")
class Translations(unittest.TestCase):
    """#65: every language has every string English has; every message the page translates has its string."""

    @classmethod
    def setUpClass(cls):
        import subprocess
        js = ("const { LANGS } = await import(%s);"
              "console.log(JSON.stringify(Object.fromEntries(Object.entries(LANGS).map(([k, v]) => [k, Object.keys(v)]))));"
              % json.dumps("file://" + os.path.join(ROOT, "app", "i18n.js")))
        out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        cls.keys = json.loads(out.stdout)

    def test_no_language_misses_a_key(self):
        en = set(self.keys["en"])
        for lang in ("zh-Hans", "zh-Hant", "ja", "ko", "es", "fr", "de"):
            self.assertEqual(sorted(en - set(self.keys[lang])), [], lang)

    def test_every_message_key_exists(self):
        import re
        with open(os.path.join(ROOT, "app", "app.js"), encoding="utf-8") as f:
            js = f.read()
        start = js.index("const MSGS = [")
        end = js.index("function tr(msg)")
        used = set(re.findall(r'/[a-z]*, "([a-z_0-9]+)"\]', js[start:end]))
        self.assertGreater(len(used), 20)
        self.assertEqual(sorted(used - set(self.keys["en"])), [])

if __name__ == "__main__":
    unittest.main()
