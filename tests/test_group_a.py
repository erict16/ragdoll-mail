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

    def test_ime_keys_are_left_alone(self):
        self.assertEqual(js('[{ isComposing: true }, { keyCode: 229 }, { key: "Enter", keyCode: 13 }, null].map(K.isIME)'),
                         [True, True, False, False])

    def test_every_key_handler_checks_the_input_method(self):
        import re
        with open(os.path.join(os.path.dirname(KIT), "app.js"), encoding="utf-8") as f:
            src = f.read()
        spots = [m.start() for m in re.finditer(r'"keydown"|onkeydown:', src)]
        self.assertGreater(len(spots), 8)
        for at in spots:
            near = src[at:at + 160]
            self.assertTrue("K.isIME(e)" in near or "onKey" in near, near)
        self.assertIn("if (K.isIME(e)) return;", src[src.index("function onKey(e)"):][:200])

    def test_single_keys_stop_at_an_open_compose(self):
        with open(os.path.join(os.path.dirname(KIT), "app.js"), encoding="utf-8") as f:
            src = f.read()
        body = src[src.index("function onKey(e)"):]
        block = body[body.index("if (S.compose) {"):]
        block = block[:block.index("\n  }\n")]
        self.assertTrue(block.rstrip().endswith("return;"), block)


class SendFlow(unittest.TestCase):
    """The page's send and save rules (#4, #5, #8), read from app.js."""
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(os.path.dirname(KIT), "app.js"), encoding="utf-8") as f:
            cls.src = f.read()

    def fn(self, name):
        s = self.src[self.src.index(name):]
        return s[:s.index("\n}\n")]

    def test_busy_before_the_first_wait(self):
        f = self.fn("async function sendCompose(")
        self.assertLess(f.index("lockCompose(c, true)"), f.index("await saving"))
        self.assertIn("if (!c || c.busy) return;", self.fn("async function discardCompose("))
        self.assertIn("if (!S.compose.busy) saveDraft()", self.src)
        self.assertIn("if (!c || c.busy) return;", self.fn("function saveDraft("))

    def test_words_typed_during_a_save_stay_unsaved(self):
        f = self.fn("function saveDraft(")
        self.assertIn("const edits = c.edits;", f)
        self.assertIn("if (c.edits === edits) c.dirty = false;", f)
        self.assertIn("c.edits = (c.edits || 0) + 1;", self.fn("function touched("))

    def test_no_close_while_uploading(self):
        self.assertIn('if (c.atts.some((a) => a.uploading)) { toast(t("att_wait")', self.fn("async function leaveCompose("))
        self.assertIn("if (S.compose === c) touched(c);", self.fn("async function uploadFiles("))

    def test_a_sent_mail_leaves_an_open_compose_alone(self):
        self.assertIn("if (S.thread && !S.compose) openThread(", self.fn("async function sendHeld("))


@unittest.skipUnless(NODE, "node is not installed")
class Addresses(unittest.TestCase):
    def test_commas_in_names(self):
        self.assertEqual(js('K.parseAddrs(\'"Wang, Li" <li@x.com>, Zhang <zhang@x.com>\')'),
                         [{"name": "Wang, Li", "addr": "li@x.com"}, {"name": "Zhang", "addr": "zhang@x.com"}])
        self.assertEqual(js('K.parseAddrs("Wang, Li <LI@x.com>; b@y.org")'),
                         [{"name": "Wang, Li", "addr": "li@x.com"}, {"name": "", "addr": "b@y.org"}])

    def test_full_width_separators(self):
        self.assertEqual(js('K.parseAddrs("a@x.com，b@y.com；c@z.com").map((p) => p.addr)'),
                         ["a@x.com", "b@y.com", "c@z.com"])

    def test_when_the_box_makes_a_chip(self):
        self.assertEqual(js('["a@x.com,", "a@x.com，", "Wang,", \'"Wang,\', "Wang, Li <li@x.com>;", "li.ming@hua", "<a,"]'
                            '.map(K.commitReady)'), [True, True, False, False, True, False, False])

    def test_autosave_does_not_take_the_box(self):
        with open(os.path.join(os.path.dirname(KIT), "app.js"), encoding="utf-8") as f:
            src = f.read()
        f = src[src.index("function composeState("):]
        f = f[:f.index("\n}\n")]
        self.assertNotIn('.value = ""', f)
        self.assertIn("!opts.auto || ADDR_RE.test(p.addr)", f)


def app_src():
    with open(os.path.join(os.path.dirname(KIT), "app.js"), encoding="utf-8") as f:
        return f.read()


class Paragraphs(OwnBackend):
    def test_paragraph_gap_goes_out_with_the_mail(self):
        html = ('<div data-rd-body="1" style="font-size:14px"><p style="margin:0 0 11px">One</p>'
                '<p style="margin:0 0 11px">Two<br>Three</p></div>')
        st = {"mode": "new", "to": [{"name": "", "addr": "a@example.org"}], "cc": [], "bcc": [], "subject": "P",
              "html": html, "atts": [], "use_signature": False}
        _, body = A.R.bodies(self.b.build(st))
        self.assertIn('<p style="margin:0 0 11px">One</p>', body)
        self.assertIn("Two<br>Three", body)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_gap_follows_the_text_size(self):
        self.assertEqual(js("[12, 14, 18].map(K.paraGap)"), [9, 11, 14])
        src = app_src()
        self.assertIn('document.execCommand("defaultParagraphSeparator", false, "p")', src)
        self.assertIn('=== ed) document.execCommand("formatBlock", false, "p");', src)
        self.assertIn("function outHTML(html)", src)


@unittest.skipUnless(NODE, "node is not installed")
class Paste(unittest.TestCase):
    def test_dark_theme_colours_go(self):
        self.assertEqual(js('K.cleanStyle("color: #fff; background: #1e1e1e; font-weight: bold", { paste: true })'),
                         "font-weight: bold")
        self.assertEqual(js('K.cleanStyle("color: rgb(30, 30, 30); background-color: yellow", { paste: true })'),
                         "color: rgb(30, 30, 30); background-color: yellow")
        self.assertEqual(js('K.cleanStyle("color: #fff; background: #1e1e1e")'), "color: #fff; background: #1e1e1e")
        self.assertEqual(js('["white", "#eee", "rgba(255,255,255,.9)", "#000", "windowtext", "var(--x)"].map(K.lightText)'),
                         [True, True, True, False, False, False])

    def test_paste_prefers_the_html_and_drops_local_pictures(self):
        src = app_src()
        f = src[src.index("async function onPaste("):]
        f = f[:f.index("\n}\n")]
        self.assertLess(f.index("if (html) {"), f.index("for (const src of await Promise.all(imgs.map(readURL)))"))
        self.assertIn("K.sanitizeBody(doc.body, { paste: true })", f)
        self.assertIn("file|blob|webkit-fake-url", src)


@unittest.skipUnless(NODE, "node is not installed")
class Sizes(unittest.TestCase):
    def test_menu_sizes_map_to_browser_sizes(self):
        self.assertEqual(js("[12, 14, 18, 24].map(K.sizeKey)"), ["2", "3", "5", "6"])
        src = app_src()
        self.assertNotIn('font[size=\'7\']', src)
        self.assertIn('e.code === "Digit7"', src)
        self.assertIn("f.style.fontSize = px + \"px\"", src)


class HeldSend(OwnBackend):
    """The undo pause after Send lives in the backend too (#50)."""
    def draft(self, subject="Held"):
        st = {"mode": "new", "to": [{"name": "", "addr": "a@example.org"}], "cc": [], "bcc": [], "subject": subject,
              "html": "<p>x</p>", "atts": [], "use_signature": False}
        return self.b.api_prepare_send({**st, "force": True})["id"]

    def sent(self, subject):
        return bool(self.b.q("select 1 from msgs where folder=? and subject=?", (A.R.CFG.folders["sent"], subject)))

    def test_send_wait_sends_once(self):
        i = self.draft()
        self.assertTrue(self.b.api_send({"id": i, "delay": 30})["held"])
        self.assertEqual(self.b.send_state(), (1, 0))
        self.assertFalse(self.sent("Held"))
        self.assertTrue(self.b.api_send_wait({"id": i})["sent"])
        self.assertTrue(self.sent("Held"))
        self.assertEqual(self.b.send_state(), (0, 0))
        self.assertIsNone(self.b.run_held(i))       # the timer finds nothing left to send

    def test_undo_keeps_the_draft(self):
        i = self.draft()
        self.b.api_send({"id": i, "delay": 30})
        self.assertTrue(self.b.api_send_cancel({"id": i})["cancelled"])
        self.assertEqual(self.b.send_state(), (0, 0))
        self.assertFalse(self.sent("Held"))
        self.b.row(i)                                # still in Drafts

    def test_a_closed_page_does_not_drop_it(self):
        self.patch(self.b, "SEND_GRACE", 0)
        i = self.draft("Page gone")
        self.b.api_send({"id": i, "delay": 0.2})
        end = time.time() + 5
        while not self.sent("Page gone") and time.time() < end:
            time.sleep(0.05)
        self.assertTrue(self.sent("Page gone"))
        self.assertFalse(self.b.api_send_cancel({"id": i})["cancelled"])    # too late to undo

    def test_closing_asks_the_page_then_waits(self):
        calls = []
        self.patch(A, "WINDOW", A.SimpleNamespace(w=None, backend=self.b, quit_ok=False, asked=0))
        self.patch(A, "page_call", calls.append)
        self.patch(A, "close_window", lambda: calls.append("closed"))
        self.assertTrue(A.window_closing())                  # nothing on its way: it just closes
        i = self.draft("Closing")
        self.b.api_send({"id": i, "delay": 30})
        self.assertFalse(A.window_closing())                 # held: the page asks
        self.assertEqual(calls, ["window.ragdollClosing && window.ragdollClosing()"])
        self.b.api_close_asked({"open": True})
        self.assertFalse(A.window_closing())                 # the question shows again, still open
        self.assertFalse(self.sent("Closing"))
        A.WINDOW.asked = 1                                    # a page that never showed it: send, then close
        self.assertFalse(A.window_closing())
        end = time.time() + 5
        while "closed" not in calls and time.time() < end:
            time.sleep(0.05)
        self.assertTrue(self.sent("Closing"))
        self.assertTrue(A.WINDOW.quit_ok)
        self.assertTrue(A.window_closing())

    def test_page_hands_the_pause_to_the_backend(self):
        src = app_src()
        self.assertIn('api("send", { id, delay: wait / 1000 })', src)
        self.assertIn('api(wait ? "send_wait" : "send", { id })', src)
        self.assertIn("window.ragdollClosing = () =>", src)


class UndoMove(OwnBackend):
    """Cmd+Z after a move reached the server (#25)."""
    def inbox_id(self):
        r = self.b.q("select uid, msgid, subject from msgs where folder='INBOX' and msgid != '' limit 1")[0]
        return A.R.make_id("INBOX", r["uid"]), r["subject"]

    def test_moved_back_in_the_demo(self):
        i, subject = self.inbox_id()
        out = self.b.api_move({"ids": [i], "to": "trash"})
        trash = A.R.CFG.folders["trash"]
        self.assertTrue(self.b.q("select 1 from msgs where folder=? and subject=?", (trash, subject)))
        self.assertEqual(self.b.api_unmove({"token": out["undo"]})["moved"], 1)
        self.assertTrue(self.b.q("select 1 from msgs where folder='INBOX' and subject=?", (subject,)))
        self.assertFalse(self.b.q("select 1 from msgs where folder=? and subject=?", (trash, subject)))
        with self.assertRaises(A.ApiError):
            self.b.api_unmove({"token": out["undo"]})      # once only

    def test_only_the_last_ten_are_kept(self):
        tokens = []
        for _ in range(12):
            i, _s = self.inbox_id()
            tokens.append(self.b.api_move({"ids": [i], "to": "archive"})["undo"])
        self.assertEqual(len(self.b.undo_moves), 10)
        with self.assertRaises(A.ApiError):
            self.b.api_unmove({"token": tokens[0]})

    def test_on_the_server_it_is_found_by_message_id(self):
        i, _ = self.inbox_id()
        mid = self.b.q("select msgid from msgs where folder='INBOX' and uid=?", (int(i.split(":")[1]),))[0]["msgid"]
        self.online()
        found = []

        class Srv(type(self.server)):
            def uid(s, *args):
                s.calls.append(("uid",) + args)
                if args[0] == "SEARCH":
                    found.append(args)
                    return "OK", [b"77"]
                return "OK", [b""]
        self.server = Srv()
        self.b.imap = lambda fn: fn(self.server)
        self.b.folders = lambda m: [A.R.CFG.folders["trash"], "INBOX"]
        self.patch(A.R, "has_cap", lambda m, c: True)
        self.patch(A.R, "use", lambda m, f, write=False: None)
        out = self.b.api_move({"ids": [i], "to": "trash"})
        self.assertEqual(self.b.api_unmove({"token": out["undo"]})["moved"], 1)
        self.assertEqual(found[0][1:3], ("HEADER", "Message-ID"))
        self.assertIn(mid.strip('"'), found[0][3])
        moves = [c for c in self.server.calls if c[:2] == ("uid", "MOVE")]
        self.assertEqual(moves[-1][2:], ("77", A.R.q("INBOX")))

    def test_page_takes_cmd_z_outside_text(self):
        src = app_src()
        self.assertIn('e.key.toLowerCase() === "z" && !typing(e)) { e.preventDefault(); undoMove(); return; }', src)
        k = src.index("function onKey(e)")
        self.assertLess(src.index("if (S.compose) {", k), src.index('=== "z" && !typing(e)', k))


class Signatures(OwnBackend):
    """Several signatures, a default for new mail and one for replies and forwards (#23)."""
    def lunch(self):
        r = self.b.q("select uid from msgs where folder='INBOX' and subject=?", ("Lunch on Thursday?",))
        return A.R.make_id("INBOX", r[0]["uid"]) if r else None

    def test_compose_starts_with_the_default_for_its_mode(self):
        new = self.b.api_compose({"mode": "new"})
        self.assertEqual(new["sig_id"], "full")
        self.assertEqual([x["id"] for x in new["signatures"]], ["full", "short"])
        i = self.lunch() or A.R.make_id("INBOX", self.b.q("select uid from msgs where folder='INBOX' limit 1")[0]["uid"])
        for mode in ("reply", "forward"):
            out = self.b.api_compose({"mode": mode, "id": i})
            self.assertEqual(out["sig_id"], "short", mode)
            self.assertNotIn("Sales Engineer", out["signature"])

    def test_the_picked_one_goes_out_and_comes_back(self):
        st = {"mode": "new", "to": [{"name": "", "addr": "a@example.org"}], "cc": [], "bcc": [], "subject": "Sig",
              "html": "<p>x</p>", "atts": [], "use_signature": True, "sig_id": "short"}
        _, body = A.R.bodies(self.b.build(st))
        self.assertNotIn("Sales Engineer", body)
        _, body = A.R.bodies(self.b.build({**st, "sig_id": "full"}))
        self.assertIn("Sales Engineer", body)
        i = self.b.api_save_draft(st)["id"]
        self.assertEqual(self.b.api_compose({"mode": "draft", "id": i})["sig_id"], "short")

    def test_saving_the_list(self):
        out = self.b.api_save_signatures({"signatures": [{"id": "a", "name": " EN ", "html": "<p>A</p>"},
                                                         {"id": "a", "name": "ZH", "html": "<p>B</p>"}],
                                          "sig_new": "a", "sig_reply": "nope"})
        self.assertEqual([x["name"] for x in out["signatures"]], ["EN", "ZH"])
        self.assertEqual(len({x["id"] for x in out["signatures"]}), 2)       # a repeated id gets its own
        self.assertEqual((out["sig_new"], out["sig_reply"]), ("a", ""))
        self.assertEqual(self.b.api_compose({"mode": "reply", "id": self.lunch()})["signature"], "")
        self.assertEqual(self.b.api_compose({"mode": "new"})["signature"], "<p>A</p>")

    def test_one_old_signature_file_becomes_the_list(self):
        path = os.path.join(self.home, "config.json")
        sig = os.path.join(self.home, "signature.html")
        with open(sig, "w", encoding="utf-8") as f:
            f.write("<p>Old</p>")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"user": "you@example.com", "data_dir": self.home, "signature": sig}, f)
        for k in ("signatures", "signature_new", "signature_reply"):
            A.R.CFG.d.pop(k, None)
        A.R.CFG.d["signature"] = sig
        self.assertEqual(self.b.api_signatures({}), {"signatures": [{"id": "1", "name": "", "html": "<p>Old</p>"}],
                                                     "sig_new": "1", "sig_reply": "1"})
        self.b.demo = False
        self.patch(A, "config_path", lambda: path)
        self.b.api_save_signatures({"signatures": [{"id": "1", "name": "", "html": "<p>Old</p>"},
                                                   {"id": "2", "name": "Short", "html": "<p>S</p>"}],
                                    "sig_new": "2", "sig_reply": "1"})
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual((saved["signature_new"], saved["signature_reply"]), ("2", "1"))
        with open(os.path.expanduser(saved["signature"]), encoding="utf-8") as f:
            self.assertEqual(f.read(), "<p>S</p>")          # the ragdoll command uses the new-mail one

    def test_page_switches_and_keeps_the_pick(self):
        src = app_src()
        self.assertIn("function sigBox(c)", src)
        self.assertIn("sig_id: c.sig_id", src)
        self.assertIn('api("save_signatures"', src)


class ForwardMarker(OwnBackend):
    def test_a_forward_draft_keeps_its_marker(self):
        orig = self.b.q("select msgid from msgs where msgid != '' limit 1")[0]["msgid"]
        st = {"mode": "draft", "to": [{"name": "", "addr": "a@example.org"}], "cc": [], "bcc": [], "subject": "Fw",
              "html": "<p>x</p>", "atts": [], "use_signature": False, "fwd": orig}
        self.assertEqual(A.R.hdr(self.b.build(st), A.R.FWD_HEADER).strip(), orig)
        self.assertIn("fwd: c.fwd", app_src())
