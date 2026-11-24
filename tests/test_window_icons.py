"""Offline tests for the app icon picker and the Windows window without a title bar."""
import os, re, shutil, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll as R  # noqa: E402
import ragdoll_app as A  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


class Icons(unittest.TestCase):
    def test_every_icon_has_its_files(self):
        self.assertEqual(sorted(A.APP_ICONS), ["classic", "painted"])
        for files in A.APP_ICONS.values():
            for f in files:
                self.assertTrue(os.path.exists(os.path.join(A.STATIC, f)), f)
        for side in ("icon-painted.png", "icon-painted-mac.png"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "assets", side)), side)

    def test_icon_file_for_this_system(self):
        f = A.app_icon_file("painted")
        want = {"darwin": "logo-painted-mac.png", "win32": "logo-painted.ico"}.get(sys.platform, "logo-painted.png")
        self.assertEqual(os.path.basename(f), want)
        self.assertEqual(A.app_icon_file("nonsense"), A.app_icon_file("classic"))
        if sys.platform == "win32":     # pywebview on Windows takes only an .ico (a .png stopped the app)
            self.assertTrue(A.app_icon_file("classic").endswith(".ico"))

    def test_page_offers_both(self):
        js = read("app", "app.js")
        for k, (page, _mac, _ico) in A.APP_ICONS.items():
            self.assertIn('["%s", "%s"' % (k, page), js)
        self.assertIn('api("prefs", { icon: k })', js)
        self.assertNotIn('src="logo.png"', js.replace('<link rel="icon" href="logo.png">', ""))


class IconPref(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = R.CFG
        cls.backend = A.Backend(demo=True)

    @classmethod
    def tearDownClass(cls):
        cls.backend.close()
        shutil.rmtree(A.R.CFG.home, ignore_errors=True)
        A.R.CFG = cls.cfg

    def test_only_known_icons_are_kept(self):
        self.assertEqual(self.backend.api_prefs({"icon": "painted"})["icon"], "painted")
        self.assertEqual(self.backend.api_prefs({"icon": "../../evil"})["icon"], "painted")
        self.assertEqual(self.backend.api_prefs({"icon": "classic"})["icon"], "classic")


class WindowsFrame(unittest.TestCase):
    def test_no_window_answers_plainly(self):
        hwnd = A.WINDOW.hwnd
        A.WINDOW.hwnd = 0
        try:
            self.assertEqual(A.win_do("state"), {"max": False, "frameless": False})
            self.assertEqual(A.win_do("close"), {"max": False, "frameless": False})
        finally:
            A.WINDOW.hwnd = hwnd

    def test_page_draws_the_buttons(self):
        html, js, css = read("app", "index.html"), read("app", "app.js"), read("app", "style.css")
        self.assertIn('id="win-ctl"', html)
        self.assertIn("async function winFrame()", js)
        for what in ('"min"', '"max"', '"close"', '"drag"'):
            self.assertIn(what, js)
        self.assertRegex(css, r"\.win-btn\.close:hover \{[^}]*#c42b1c")
        self.assertIn(".frameless .toolbar", css)

    def test_strings_in_every_language(self):
        src = read("app", "i18n.js")
        block = src[src.index("const MORE_H_WINDOW = {"):src.index("for (const [k, v] of Object.entries(MORE_H_WINDOW))")]
        langs = dict(re.findall(r'^  "([\w-]+)": \{(.*)\},?$', block, re.M))
        self.assertEqual(sorted(langs), sorted(["en", "zh-Hans", "zh-Hant", "ja", "ko", "es", "fr", "de"]))
        keys = {k: set(re.findall(r"(\w+): \"", v)) for k, v in langs.items()}
        for lang, ks in keys.items():
            self.assertEqual(ks, keys["en"], lang)
        self.assertEqual(keys["en"], {"win_min", "win_max", "win_restore", "win_close", "app_icon", "icon_classic", "icon_painted"})


if __name__ == "__main__":
    unittest.main()
