"""Offline tests for the 0.11 group C1 fixes: mail list, selection and search (demo mode, no network)."""
import json, os, shutil, subprocess, sys, time, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll_app as A  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
NODE = shutil.which("node")


class Paging(unittest.TestCase):
    """Search and folders give their results a page at a time, so nothing past the first page is out of reach."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = A.R.CFG                       # demo mode swaps the config; the CLI tests need it back
        cls.b = A.Backend(demo=True, demo_lang="en")
        inbox = A.R.CFG.folders["inbox"]
        now = int(time.time()) - 10 * 86400
        for k in range(620):
            raw = A.demo_message("inbox", now - k * 60, ("Paging Tester", "pager@example.org"),
                                 [("You", "you@example.com")], [], "Quotation %03d" % k,
                                 "Hello,\n\nquotation number %d attached.\n" % k, [],
                                 A.make_msgid(domain="example.org"), None, None)
            cls.b.demo_insert(inbox, raw, now - k * 60, 1, 0)

    @classmethod
    def tearDownClass(cls):
        cls.b.close()
        A.R.CFG = cls.cfg

    def pages(self, name, args, size):
        out, offset = [], 0
        while True:
            r = getattr(self.b, "api_" + name)(dict(args, limit=size, offset=offset))
            out += r["rows"]
            offset += len(r["rows"])
            if not r["more"]:
                return out

    def test_search_pages_reach_every_match(self):
        first = self.b.api_search({"q": "quotation"})
        self.assertEqual(len(first["rows"]), 200)
        self.assertTrue(first["more"])
        rows = self.pages("search", {"q": "quotation"}, 150)
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))           # no mail twice across pages
        self.assertGreaterEqual(len(ids), 620)
        self.assertEqual(sorted((r["ts"] for r in rows), reverse=True), [r["ts"] for r in rows])

    def test_search_offset_and_limit(self):
        a = self.b.api_search({"q": "quotation", "limit": 50})["rows"]
        b = self.b.api_search({"q": "quotation", "limit": 50, "offset": 50})["rows"]
        both = self.b.api_search({"q": "quotation", "limit": 100})["rows"]
        self.assertEqual([r["id"] for r in a + b], [r["id"] for r in both])
        self.assertEqual(len(self.b.api_search({"q": "quotation", "limit": 10 ** 6})["rows"]), 500)
        self.assertFalse(self.b.api_search({"q": "quotation", "offset": 10 ** 6})["more"])
        self.assertEqual(self.b.api_search({"q": ""}), {"rows": [], "more": False})

    def test_short_and_operator_search_pages(self):
        rows = self.pages("search", {"q": "from:pager@example.org"}, 200)
        self.assertEqual(len(rows), 620)
        rows = self.pages("search", {"q": "qu"}, 300)       # a short word goes through LIKE, not the index
        self.assertGreaterEqual(len(rows), 620)

    def test_folder_pages_cover_a_long_list(self):
        """A quiet refresh of 600+ rows asks in pages of 500: together they give every row once."""
        r = self.b.api_list({"folder": "inbox", "limit": 5000})
        self.assertEqual(len(r["rows"]), 500)
        self.assertTrue(r["more"])
        rows = self.pages("list", {"folder": "inbox"}, 500)
        self.assertEqual(len(rows), len({x["id"] for x in rows}))
        self.assertGreater(len(rows), 620)


@unittest.skipUnless(NODE, "node is not installed")
class ListLogic(unittest.TestCase):
    """The pure parts of app/app.js, run in node."""

    def js(self, code):
        with open(os.path.join(ROOT, "app", "app.js"), encoding="utf-8") as f:
            src = f.read()
        start, end = src.index("// ---- C1 pure: start"), src.index("// ---- C1 pure: end")
        out = subprocess.run([NODE, "-e", src[start:end] + "\nconsole.log(JSON.stringify((() => {" + code + "})()));"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_search_terms(self):
        self.assertEqual(self.js('return searchTerms(\'from:anna "price list" 报价 is:unread has:file to:"x y" in:sent\');'),
                         ["price list", "报价"])
        self.assertEqual(self.js("return searchTerms('  ');"), [])
        self.assertEqual(self.js("return searchTerms('a ab abc');"), ["abc", "ab", "a"])

    def test_split_hits(self):
        r = self.js("return splitHits('Price list and PRICE', termsRe(['price']));")
        self.assertEqual(r, [["", "Price"], [" list and ", "PRICE"], ["", ""]])
        r = self.js("return splitHits('请确认报价单的报价', termsRe(['报价']));")
        self.assertEqual(r, [["请确认", "报价"], ["单的", "报价"], ["", ""]])
        self.assertEqual(self.js("return splitHits('a.b*c', termsRe(['.b*']));"), [["a", ".b*"], ["c", ""]])
        self.assertIsNone(self.js("return termsRe([]);"))

    def test_highlight_escapes(self):
        self.assertEqual(self.js("return hlText('<b>Tom & 报价</b>', termsRe(['tom', '报价']));"),
                         "&lt;b&gt;<mark>Tom</mark> &amp; <mark>报价</mark>&lt;/b&gt;")
        self.assertEqual(self.js("return hlText('a <x>', null);"), "a &lt;x&gt;")

    def test_frame_keys_stay_in_the_mail(self):
        stay = self.js("""return [
          {key: 'ArrowDown'}, {key: 'ArrowUp'}, {key: ' '}, {key: 'PageDown'}, {key: 'End'},
          {key: 'a', metaKey: true}, {key: 'a', ctrlKey: true}, {key: 'c', metaKey: true},
          {key: 'j'}, {key: 'k'}, {key: 'e'}, {key: '#'}, {key: 'Escape'}, {key: 'k', metaKey: true}, {key: 'ArrowLeft'},
        ].map(frameKey);""")
        self.assertEqual(stay, ["down", "up", "page", "page", "end", "keep", "keep", "keep",
                                None, None, None, None, None, None, "keep"])

    def test_next_after_move(self):
        rows = "[{id:'a'},{id:'b'},{id:'c'},{id:'d'},{id:'e'}]"
        self.assertEqual(self.js("return nextAfter(%s, ['c'], 'c');" % rows), "d")
        self.assertEqual(self.js("return nextAfter(%s, ['e'], 'e');" % rows), "d")
        self.assertIsNone(self.js("return nextAfter(%s, ['b'], 'a');" % rows))      # the open mail did not move
        self.assertEqual(self.js("return nextAfter(%s, ['b','c','d'], null);" % rows), "e")
        self.assertEqual(self.js("return nextAfter(%s, ['d','e'], null);" % rows), "c")
        self.assertIsNone(self.js("return nextAfter([{id:'a'}], ['a'], 'a');"))

    def test_scroll_anchor(self):
        """After a refresh the row that was under the eye keeps its place, even when rows above it came or went."""
        r = self.js("return anchorShift({id: 'c', off: 12}, ['x', 'a', 'b', 'c', 'd'], {x: 0, a: 80, b: 160, c: 240, d: 320});")
        self.assertEqual(r, 228)
        r = self.js("return anchorShift({id: 'gone', after: ['d'], off: 5}, ['a', 'd'], {a: 0, d: 80});")
        self.assertEqual(r, 75)
        self.assertIsNone(self.js("return anchorShift(null, ['a'], {a: 0});"))


if __name__ == "__main__":
    unittest.main()
