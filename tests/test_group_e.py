"""Folders (0.11 group E): subfolders, moving a folder, renaming one with folders inside, deleting one with
mail in it, emptying Trash and Junk. Offline: the demo mailbox, and a fake IMAP server for the server side."""
import os, re, shutil, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll_app as A  # noqa: E402


def no_server():
    raise OSError("the tests have no mail server")


class OwnBackend(unittest.TestCase):
    """Each test gets a demo mailbox of its own; online() makes it act as with an account, `server` in
    place of the mail server."""
    def setUp(self):
        old_imap, cfg = A.R.imap, A.R.CFG     # demo mode swaps the config; the other tests need it back
        A.R.imap = no_server
        self.b = A.Backend(demo=True)
        self.home = A.R.CFG.home
        self.addCleanup(self.done, cfg, old_imap)

    def done(self, cfg, old_imap):
        self.b.close()
        with self.b.dblock:
            self.b.c.close()
        shutil.rmtree(self.home, ignore_errors=True)
        A.R.CFG, A.R.imap = cfg, old_imap

    def online(self, server):
        self.b.demo = False
        self.b.imap = lambda fn: fn(server)


def mail(b, folder, subject):
    """A demo mail put in `folder`; its id."""
    raw = A.demo_message("inbox", 1790000000, ("Sender", "sender@example.com"), [A.ME], [], subject, "x", [],
                         A.make_msgid(domain="example.com"), None, None)
    return A.R.make_id(folder, b.demo_insert(folder, raw, 1790000000, 1, 0))


class Demo(OwnBackend):
    """The same calls the page makes, on the demo mailbox."""
    def keys(self):
        return [n for n, _, _ in self.b.others()]

    def subjects(self, folder):
        return sorted(r["subject"] for r in self.b.q("select subject from msgs where folder=?", (folder,)))

    def err(self, name, a):
        with self.assertRaises(A.ApiError) as e:
            getattr(self.b, "api_" + name)(a)
        return str(e.exception)

    def test_delete_with_mail_goes_to_trash(self):
        self.b.found.append(("Projects/Acme/2026", ""))
        mail(self.b, "Projects/Acme/2026", "Deep mail")
        mail(self.b, "Projects", "Top mail")
        n = len(self.b.q("select 1 from msgs where folder in ('Projects', 'Projects/Acme', 'Projects/Acme/2026')"))
        self.assertEqual(self.b.api_folder_delete({"key": "Projects", "check": True}), {"mails": n, "folders": 2})
        self.assertIn("folders inside", self.err("folder_delete", {"key": "Projects"}))     # not without asking
        trash = len(self.subjects("Deleted Messages"))
        out = self.b.api_folder_delete({"key": "Projects", "trash": True})
        self.assertEqual(out["deleted"], ["Projects/Acme/2026", "Projects/Acme", "Projects"])
        self.assertFalse([k for k in self.keys() if k.startswith("Projects")])
        self.assertEqual(len(self.subjects("Deleted Messages")), trash + n)
        self.assertIn("Deep mail", self.subjects("Deleted Messages"))
        self.assertFalse(self.b.q("select 1 from msgs where folder like 'Projects%'"))
        # an empty one goes without the question
        self.b.found.append(("Empty", ""))
        self.assertEqual(self.b.api_folder_delete({"key": "Empty", "check": True}), {"mails": 0, "folders": 0})
        self.assertEqual(self.b.api_folder_delete({"key": "Empty"}), {"deleted": ["Empty"]})

    def test_empty_trash_and_junk(self):
        mail(self.b, "Deleted Messages", "Old one")
        n = len(self.subjects("Deleted Messages"))
        self.assertEqual(self.b.api_folder_empty({"key": "trash", "check": True}), {"count": n})
        self.assertEqual(len(self.subjects("Deleted Messages")), n)                  # asking deletes nothing
        self.assertEqual(self.b.api_folder_empty({"key": "trash"}), {"count": n})
        self.assertEqual(self.subjects("Deleted Messages"), [])
        self.assertTrue(self.subjects("Junk"))
        self.b.api_folder_empty({"key": "junk"})
        self.assertEqual(self.subjects("Junk"), [])
        self.assertTrue(self.subjects("INBOX"))                          # nothing else touched
        self.assertIn("can't empty", self.err("folder_empty", {"key": "inbox"}))
        self.assertIn("can't empty", self.err("folder_empty", {"key": "Projects"}))
        counts = {f["key"]: f for f in self.b.count_folders()}
        self.assertEqual((counts["trash"]["total"], counts["junk"]["total"]), (0, 0))


class Server:
    """A fake IMAP server with folders and mail: what LIST, STATUS, SELECT, SEARCH, MOVE, STORE, EXPUNGE,
    CREATE, RENAME and DELETE do, with "." or "/" between a folder and the ones inside it. Names travel
    in modified UTF-7, as on the wire."""
    def __init__(self, folders, sep="/", caps=("MOVE", "UIDPLUS")):
        self.sep, self.capabilities, self.calls = sep, caps, []
        self.box = {A.R.mutf7(n): dict(u) for n, u in folders.items()}     # name on the wire -> {uid: flags}
        self.sel = None

    @staticmethod
    def name(q):
        return q[1:-1].replace('\\"', '"').replace("\\\\", "\\") if q.startswith('"') else q

    def list(self, ref=None, pat=None):
        if pat == '""':
            return "OK", [('(\\Noselect) "%s" ""' % self.sep).encode()]
        return "OK", [('() "%s" "%s"' % (self.sep, n)).encode() for n in self.box]

    def status(self, q, what):
        n = self.name(q)
        if n not in self.box:
            return "NO", [b"no such folder"]
        return "OK", [('"%s" (MESSAGES %d)' % (n, len(self.box[n]))).encode()]

    def select(self, q, readonly=True):
        n = self.name(q)
        self.calls.append(("select", A.R.mutf7_decode(n), readonly))
        if n not in self.box:
            return "NO", [b"no such folder"]
        self.sel = n
        return "OK", [str(len(self.box[n])).encode()]

    def response(self, code):
        return code, [b"7"]

    def uid(self, cmd, *args):
        self.calls.append(("uid", cmd) + args)
        box = self.box[self.sel]
        if cmd == "SEARCH":
            return "OK", [" ".join(map(str, sorted(box))).encode()]
        uids = [int(x) for x in args[0].split(",")]
        if cmd == "STORE":
            for u in uids:
                box[u] = box.get(u, "") + "\\Deleted"
            return "OK", [b""]
        if cmd == "EXPUNGE":
            for u in uids:
                if "\\Deleted" in box.get(u, ""):
                    del box[u]
            return "OK", [b""]
        if cmd == "MOVE":
            dest = self.box[self.name(args[1])]
            for u in uids:
                dest[max(dest, default=0) + 1] = box.pop(u)
            return "OK", [b""]
        return "NO", [b"?"]

    def expunge(self):
        box = self.box[self.sel]
        for u in [u for u, f in box.items() if "\\Deleted" in f]:
            del box[u]
        return "OK", [b""]

    def create(self, q):
        self.box[self.name(q)] = {}
        return "OK", [b""]

    def rename(self, a, b):
        a, b = self.name(a), self.name(b)
        for n in list(self.box):
            if n == a or n.startswith(a + self.sep):
                self.box[b + n[len(a):]] = self.box.pop(n)
        return "OK", [b""]

    def delete(self, q):
        n = self.name(q)
        if any(x.startswith(n + self.sep) for x in self.box):
            return "NO", [b"has children"]
        self.box.pop(n)
        return "OK", [b""]

    def subscribe(self, q):
        self.calls.append(("subscribe", A.R.mutf7_decode(self.name(q))))
        return "OK", [b""]

    def unsubscribe(self, q):
        self.calls.append(("unsubscribe", A.R.mutf7_decode(self.name(q))))
        return "OK", [b""]

    def folders(self):
        return sorted(A.R.mutf7_decode(n) for n in self.box)

    def count(self, n):
        return len(self.box[A.R.mutf7(n)])


class OnServer(OwnBackend):
    """The same calls with an account: what reaches the server, and what the index keeps."""
    def start(self, sep="/", caps=("MOVE", "UIDPLUS")):
        s = sep
        self.srv = Server({"INBOX": {1: ""}, "Sent Messages": {}, "Drafts": {}, "Deleted Messages": {9: ""},
                           "Junk": {3: "", 4: "\\Seen"}, "其他文件夹": {},
                           "其他文件夹" + s + "华明印尼": {1: "", 2: ""}, "其他文件夹" + s + "华明印尼" + s + "2025": {5: ""},
                           "其他文件夹" + s + "归档": {}}, sep, caps)
        self.online(self.srv)
        self.b.found = A.list_folders(self.srv)
        A.R.CFG.folders.update({"inbox": "INBOX", "sent": "Sent Messages", "drafts": "Drafts",
                                "trash": "Deleted Messages", "junk": "Junk"})
        A.R.CFG.sync_folders = ["INBOX", "Sent Messages", "Drafts"]
        with self.b.dblock:
            self.b.c.execute("delete from msgs")
            self.b.c.execute("delete from fts")
            self.b.c.execute("delete from state")
            self.b.c.commit()
        for f, uids in (("其他文件夹" + s + "华明印尼", (1, 2)), ("其他文件夹" + s + "华明印尼" + s + "2025", (5,)),
                        ("Deleted Messages", (9,)), ("Junk", (3, 4))):
            for u in uids:
                raw = A.demo_message("inbox", 1790000000, ("Sender", "s@example.com"), [A.ME], [], "%s %d" % (f, u), "x", [],
                                     A.make_msgid(domain="example.com"), None, None)
                with self.b.dblock:
                    A.index_raw(self.b.c, f, 7, u, raw, 1790000000, 1, 0)
                    self.b.c.commit()
        return s

    def rows(self, folder):
        return sorted(r["uid"] for r in self.b.q("select uid from msgs where folder=?", (folder,)))

    def test_delete_folder_with_mail(self):
        s = self.start()
        key = "其他文件夹/华明印尼"
        self.assertEqual(self.b.api_folder_delete({"key": key, "check": True}), {"mails": 3, "folders": 1})
        with self.assertRaises(A.ApiError):
            self.b.api_folder_delete({"key": key})
        self.assertEqual(self.srv.count(key), 2)          # nothing happened without trash
        out = self.b.api_folder_delete({"key": key, "trash": True})
        self.assertEqual(out["deleted"], [key + s + "2025", key])
        self.assertEqual(self.srv.count("Deleted Messages"), 4)                 # moved, never deleted for good
        self.assertNotIn(key, self.srv.folders())
        self.assertNotIn(key + "/2025", self.srv.folders())
        self.assertEqual((self.rows(key), self.rows(key + "/2025")), ([], []))
        self.assertFalse([c for c in self.srv.calls if c[:2] == ("uid", "STORE")])

    def test_empty_trash_in_batches(self):
        self.start()
        self.srv.box["Deleted Messages"] = {u: "" for u in range(1, 1203)}
        self.assertEqual(self.b.api_folder_empty({"key": "trash", "check": True}), {"count": 1202})
        self.assertEqual(self.srv.count("Deleted Messages"), 1202)
        self.assertEqual(self.b.api_folder_empty({"key": "trash"}), {"count": 1202})
        self.assertEqual(self.srv.count("Deleted Messages"), 0)
        stores = [c for c in self.srv.calls if c[:2] == ("uid", "STORE")]
        self.assertEqual([len(c[2].split(",")) for c in stores], [500, 500, 202])
        self.assertEqual(self.rows("Deleted Messages"), [])
        self.assertEqual(self.rows("Junk"), [3, 4])                             # the other folders are untouched
        self.assertEqual(self.srv.count("INBOX"), 1)

    def test_empty_junk_without_uidplus(self):
        self.start(caps=("MOVE",))
        self.assertEqual(self.b.api_folder_empty({"key": "junk"}), {"count": 2})
        self.assertEqual(self.srv.count("Junk"), 0)
        self.assertEqual(self.rows("Junk"), [])
        self.assertFalse([c for c in self.srv.calls if c[:2] == ("uid", "EXPUNGE")])


if __name__ == "__main__":
    unittest.main()
