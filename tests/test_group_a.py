"""Offline tests for writing mail and keys (0.11 group A): the draft HTML the editor gets, the page's own
helpers in app/compose-kit.js (run in node when it is there), signatures, undo of moves, a pending send."""
import json, os, shutil, subprocess, sys, time, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import ragdoll_app as A  # noqa: E402
from test_app import OwnBackend  # noqa: E402

KIT = os.path.join(os.path.dirname(__file__), "..", "app", "compose-kit.js")
NODE = shutil.which("node")


def js(expr):
    """The value of a JavaScript expression with the kit loaded as K (JSON round trip)."""
    code = "import * as K from %s; console.log(JSON.stringify(await (async () => (%s))()));" % (
        json.dumps("file://" + os.path.abspath(KIT)), expr)
    out = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=20)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


HOSTILE = ('<html><head><style>body{display:none}</style></head><body>'
           '<p onclick="x()">Hi</p><img src=x/onerror=alert(1)><img src="x"/onerror=alert(2)>'
           '<img src="cid:none" onload="y()"><script>alert(3)</script><svg><g onload="z()"></g></svg>'
           '<a href="javascript:alert(4)">a</a><a href=" jav&#x09;ascript:alert(5)">b</a>'
           '<div style="position:fixed;top:0;color:red">c</div><iframe src="https://x"></iframe>'
           '<form action="/api/send"><input value=1>d</form><span class="pane" id="search">e</span>'
           '<!-- note --><font color="red" size="2" onmouseover="q()">f</font>'
           '<img src="https://example.com/a.png" alt="ok"><a href="mailto:a@b.co">m</a></body></html>')


class EditorHTML(unittest.TestCase):
    def test_hostile_mail_html_is_cleaned(self):
        out = A.editor_html(A.page_html(HOSTILE, {}))
        low = out.lower()
        for bad in ("onerror", "onclick", "onload", "onmouseover", "<script", "<style", "<svg", "<iframe",
                    "<form", "<input", "javascript", "position", "class=", "id=", "<!--", "alert(3)"):
            self.assertNotIn(bad, low, bad)
        for good in ("<p>Hi</p>", 'color: red', '<font color="red" size="2">f</font>',
                     '<img src="https://example.com/a.png" alt="ok">', 'href="mailto:a@b.co"', ">e<"):
            self.assertIn(good, out)

    def test_entities_and_quotes_stay_text(self):
        out = A.editor_html('<p title="a&quot;b">1 &lt; 2 &amp; &lt;img src=x onerror=y&gt;</p>')
        self.assertEqual(out, '<p title="a&quot;b">1 &lt; 2 &amp; &lt;img src=x onerror=y&gt;</p>')

    def test_unclosed_tags_are_closed(self):
        self.assertEqual(A.editor_html("<div><b>x"), "<div><b>x</b></div>")
        self.assertEqual(A.editor_html("a<br/>b<hr>"), "a<br>b<hr>")

    def test_our_own_wrapper_survives(self):
        html = ('<div data-rd-body="1" style="font-family:Arial, \'Times New Roman\';font-size:14px">'
                '<p style="margin:0 0 10px">x</p><img src="data:image/png;base64,AAAA"></div>')
        out = A.editor_html(html)
        self.assertIn('data-rd-body="1"', out)
        self.assertIn("font-family: Arial, &#x27;Times New Roman&#x27;; font-size: 14px", out)
        self.assertIn('src="data:image/png;base64,AAAA"', out)
        self.assertNotIn("data:image/svg", A.editor_html('<img src="data:image/svg+xml,<svg onload=x()>">'))

    def test_style_urls(self):
        self.assertEqual(A.clean_style("background:url(javascript:x);color:red"), "color: red")
        self.assertEqual(A.clean_style("background:url('data:image/png;base64,AA');x:1"),
                         "background: url('data:image/png;base64,AA'); x: 1")
        self.assertEqual(A.clean_style("width:expression(alert(1))"), "")


class DraftFromElsewhere(OwnBackend):
    def draft(self, html):
        raw = ("From: you@example.com\r\nTo: a@example.org\r\nSubject: Outside\r\nMessage-ID: <out-1@x>\r\n"
               "Content-Type: text/html; charset=utf-8\r\n\r\n" + html).encode()
        uid = self.b.demo_insert(A.R.CFG.folders["drafts"], raw, int(time.time()), 1, 0)
        return A.R.make_id(A.R.CFG.folders["drafts"], uid)

    def test_compose_gets_clean_html(self):
        out = self.b.api_compose({"mode": "draft", "id": self.draft(HOSTILE)})
        self.assertNotIn("onerror", out["html"])
        self.assertNotIn("<style", out["html"])
        self.assertIn("<p>Hi</p>", out["html"])

    def test_saved_state_is_cleaned_too(self):
        i = self.draft("<p>x</p>")
        st = {"mode": "new", "to": [{"name": "", "addr": "a@example.org"}], "cc": [], "bcc": [], "subject": "S",
              "html": '<p>ok</p><img src=x onerror="alert(1)">', "atts": [], "use_signature": False, "replace": i}
        i2 = self.b.api_save_draft(st)["id"]
        out = self.b.api_compose({"mode": "draft", "id": i2})
        self.assertIn("<p>ok</p>", out["html"])
        self.assertNotIn("onerror", out["html"])


@unittest.skipUnless(NODE, "node is not installed")
class Kit(unittest.TestCase):
    def test_safe_urls(self):
        self.assertEqual(js('["https://a", "mailto:x@y.z", " java\\tscript:x", "data:text/html,x", "file:///a", "#top"]'
                            '.map((u) => K.safeURL(u, "href"))'), [True, True, False, False, False, True])
        self.assertEqual(js('["https://a/b.png", "cid:x", "data:image/png;base64,A", "data:image/svg+xml,x", '
                            '"blob:https://a/1", "webkit-fake-url://x/y.png", "file:///C:/a.png"]'
                            '.map((u) => K.safeURL(u, "src"))'), [True, True, True, False, False, False, False])

    def test_clean_style(self):
        self.assertEqual(js('K.cleanStyle("position: fixed; color: red; z-index: 9; background: url(javascript:x)")'),
                         "color: red")
        self.assertEqual(js('K.cleanStyle("background-image: url(data:image/png;base64,AA;); width: 2px")'),
                         "background-image: url(data:image/png;base64,AA;); width: 2px")


@unittest.skipUnless(NODE, "node is not installed")
class Keys(unittest.TestCase):
    def test_mod_is_cmd_on_mac_and_ctrl_elsewhere(self):
        got = js('[true, false].map((mac) => [{ metaKey: true }, { ctrlKey: true }, { metaKey: true, ctrlKey: true }]'
                 '.map((e) => K.modOf(mac)(e)))')
        self.assertEqual(got, [[True, False, False], [False, True, False]])

    def test_sync_shortcut_is_wired(self):
        with open(os.path.join(os.path.dirname(KIT), "app.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('e.key.toLowerCase() === "r") || e.key === "F5") { e.preventDefault(); syncNow()', src)
        self.assertIn('[MOD + "R", "sync_now"]', src)
        # no shortcut takes Ctrl on a Mac any more
        self.assertNotIn("const mod = e.metaKey || e.ctrlKey", src)
