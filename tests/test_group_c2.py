"""Offline tests for the reading pane, appearance, theme, problem notice and window fixes of 0.11 (group C2)."""
import json, os, re, shutil, subprocess, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll as R  # noqa: E402
import ragdoll_app as A  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


# (text, where the quoted history starts: the line it starts on, or None)
QUOTE_CASES = [
    ("Shipment ready.\nFrom: Shanghai\nTo: Singapore\nETD 3 Dec", None),
    ("Your trip\nFrom: Shanghai\nTo: Singapore\nDate: 3 Dec\nSeat 12A", None),
    ("发件人: 上海\n收件人: 新加坡\n", None),
    ("Noted.\n\nFrom: Tan Eric\nSent: Monday, 3 November 2026 10:00\nTo: Li Wei\nSubject: RE: Order\n\nold", 2),
    ("Noted.\n\nFrom: a@b.com\nDate: 3 Nov 2026\nTo: c@d.com\n\nold", 2),
    ("Noted.\nFrom: Tan Eric\nTo: Li Wei\nSubject: Order\nold", 1),
    ("好的。\n\n发件人：张三\n发送时间：2026年11月3日 10:00\n收件人：李四\n主题：订单\n\n旧", 2),
    ("OK\n________________________________\nFrom: Tan Eric\nold", 1),
    ("OK\n\n-----Original Message-----\nFrom: x\n", 2),
    ("OK\n\nOn Mon, 3 Nov 2026 at 10:00, Tan Eric <e@x.com> wrote:\n> old", 2),
    ("Danke\n\nVon: Max\nGesendet: Montag\nAn: Eva\nBetreff: Termin\n", 2),
    ("Merci\n\nDe : Jean\nEnvoyé : lundi\nÀ : Marie\nObjet : RDV\n", 2),
    # the mail's own From/To lines, then the real history: only the history is folded
    ("Ready.\nFrom: Shanghai\nTo: Singapore\nETD 3 Dec\nFrom: Tan Eric <e@x.com>\nSent: Monday\nTo: Li\nSubject: RE: x", 4),
    ("Ready.\nFrom: Shanghai\nTo: Singapore\n\nSubject to change.\nDate: 3 Dec", None),
]


class QuoteHistory(unittest.TestCase):
    """#52: a line starting with "From:" is quoted history only at the head of a real header block."""

    def test_python_rules(self):
        for text, line in QUOTE_CASES:
            with self.subTest(text=text):
                self.assertEqual(R.quote_line(text.split("\n")), -1 if line is None else line)

    def test_new_text_keeps_a_mail_that_says_from(self):
        text = "Shipment ready.\nFrom: Shanghai\nTo: Singapore\nETD 3 Dec"
        self.assertEqual(R.new_text(text), text)
        self.assertEqual(R.new_text("Noted.\n\nFrom: A\nSent: today\nTo: B\nSubject: x\nold"), "Noted.")

    def test_plain_mail_is_not_folded_at_from(self):
        html = A.plain_html("Shipment ready.\nFrom: Shanghai\nTo: Singapore\nETD 3 Dec")
        self.assertNotIn("rd-quote", html)
        self.assertIn("ETD 3 Dec", html)
        html = A.plain_html("Noted.\n\nFrom: A\nSent: today\nTo: B\nSubject: x\nold")
        self.assertIn('<div class="rd-plain rd-quote">From: A', html)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_page_has_the_same_rules(self):
        js = read("app", "app.js")
        start, end = js.index("const QUOTE_SEP ="), js.index("// a mail's text as the lines a reader sees")
        cases = [[t.split("\n"), -1 if n is None else n] for t, n in QUOTE_CASES]
        script = js[start:end] + "\nconst cases = " + json.dumps(cases) + ";\n" + \
            "console.log(JSON.stringify(cases.map(([l, n]) => quoteLine(l) === n)));"
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), [True] * len(cases))
        self.assertNotIn("QUOTE_TEXT", js)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_html_mail_is_read_as_lines(self):
        js = read("app", "app.js")
        start, end = js.index("const QUOTE_SEP ="), js.index("const frames = new Set()")
        # a few elements are enough for textLines: tag, class, children, text
        dom = """
const T = (s) => ({ nodeType: 3, nodeValue: s });
const h = (tag, cls, ...kids) => {
  const e = { nodeType: 1, tagName: tag, classList: { contains: (c) => c === cls }, firstChild: null };
  kids = kids.map((k) => typeof k === "string" ? T(k) : k);
  kids.forEach((k, i) => { k.nextSibling = kids[i + 1] || null; });
  e.firstChild = kids[0] || null;
  return e;
};
const run = (root) => { const L = textLines(root); const i = quoteLine(L.map((l) => l.text));
  return i < 0 ? null : (L.slice(i).find((l) => l.node).node.nodeValue || L.slice(i).find((l) => l.node).node.tagName); };
console.log(JSON.stringify([
  run(h("DIV", "", h("P", "", "Shipment ready"), h("P", "", "From: Shanghai", h("BR"), "To: Singapore"), h("P", "", "ETD"))),
  run(h("DIV", "", h("DIV", "", "Thanks"), h("DIV", "", h("P", "", h("B", "", "From:"), " Tan Eric", h("BR"),
      h("B", "", "Sent:"), " Monday", h("BR"), h("B", "", "To:"), " Li", h("BR"), h("B", "", "Subject:"), " RE: x")), h("P", "", "old"))),
  run(h("DIV", "", h("DIV", "", "OK"), h("HR"), h("DIV", "", h("B", "", "From:"), " Tan"), h("DIV", "", "old"))),
  run(h("DIV", "", h("DIV", "rd-plain", "a\\nFrom: x\\nTo: y\\nz"))),
  run(h("DIV", "", "From:\\n   Tan Eric", h("BR"), "Sent: today")),
]));"""
        out = subprocess.run(["node", "-e", js[start:end] + dom], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), [None, "From:", "HR", None, "From:\n   Tan Eric"])


class Frames(unittest.TestCase):
    def test_wide_mail_frame_makes_room_for_its_scrollbar(self):
        # #64: the frame is the content's height plus the sideways scrollbar's, so the last line is not under it
        js = read("app", "app.js")
        fit = js[js.index("const fit = () => {"):js.index("st.fit = fit;")]
        self.assertIn("view.innerHeight - d.documentElement.clientHeight", fit)
        self.assertRegex(fit, r"const h = Math\.ceil\(.*\+ bar\);")
        self.assertIn("overflow-x:auto;overflow-y:hidden", js)


def css_rule(css, selector):
    m = re.search(r"(?m)^" + re.escape(selector) + r" \{([^}]*)\}", css)
    return m.group(1) if m else ""


def dark_tokens(css):
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", "".join(re.findall(r':root\[data-theme="dark"\] \{([^}]*)\}', css))))


class Segmented(unittest.TestCase):
    """#27: concentric corners, a picked item that shows in dark mode, a thumb that slides."""

    def test_corners_are_concentric(self):
        css = read("app", "style.css")
        seg = css_rule(css, ".seg")
        outer = int(re.search(r"border-radius: (\d+)px", seg).group(1))
        inset = int(re.search(r"padding: (\d+)px", seg).group(1)) + int(re.search(r"border: (\d+)px", seg).group(1))
        for sel in (".seg button", ".seg-thumb"):
            self.assertIn("border-radius: %dpx" % (outer - inset), css_rule(css, sel), sel)

    def test_picked_item_is_lighter_than_the_track_in_dark(self):
        tok = dark_tokens(read("app", "style.css"))
        lum = lambda h: sum(int(h.strip()[i:i + 2], 16) for i in (1, 3, 5)) / 3      # noqa: E731
        self.assertGreater(lum(tok["--seg-on"]) - lum(tok["--sunk"]), 16)

    def test_every_segmented_control_is_made_in_one_place(self):
        js = read("app", "app.js")
        self.assertEqual(js.count('el("div", { class: "seg"'), 1)
        self.assertIn("function segmented(", js)
        self.assertGreaterEqual(js.count("segmented("), 6)


if __name__ == "__main__":
    unittest.main()
