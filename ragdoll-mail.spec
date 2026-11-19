# PyInstaller build for the desktop app:  pyinstaller ragdoll-mail.spec
# macOS gives dist/ragdoll-mail.app, Windows gives dist/ragdoll-mail.exe (one file, no console).
import re
import sys

VERSION = re.search(r'^__version__ = "([^"]+)"', open("ragdoll.py", encoding="utf-8").read(), re.M).group(1)
# PyInstaller turns the picture into .icns / .ico (needs Pillow). The Windows one is the same drawing with the
# empty margin cut off (as Windows icons are drawn), so it is as big as its neighbours on the desktop and taskbar.
ICON = "assets/icon-win.png" if sys.platform == "win32" else "assets/icon.png"

# Left out to keep the download small. None of it runs in the app: build tools that cffi names but only
# uses to compile, process pools, async servers bottle can drive, archive formats, FTP, test helpers.
# After changing this list, build and run  dist/ragdoll-mail --demo  once: a missing module shows at start.
EXCLUDES = ["tkinter", "unittest", "pydoc", "doctest", "pdb", "setuptools", "pkg_resources",
            "multiprocessing", "asyncio", "xmlrpc", "ftplib", "tarfile", "bz2", "lzma", "_pydecimal",
            "statistics", "fractions"]

a = Analysis(["ragdoll_app/__main__.py"], pathex=["."], datas=[("app", "app")], hiddenimports=["ragdoll"],
             excludes=EXCLUDES)


def wanted(entry):
    """Drop the Android part and the API notes that pywebview and pythonnet ship. Keep every WebView2 loader
    (win-x64, win-x86, win-arm64): pywebview picks by the computer, not by this build, so an ARM PC needs its own."""
    return not entry[0].endswith((".jar", "Python.Runtime.xml"))


a.binaries = [x for x in a.binaries if wanted(x)]
a.datas = [x for x in a.datas if wanted(x)]
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ragdoll-mail", console=False, icon=ICON)
    coll = COLLECT(exe, a.binaries, a.datas, name="ragdoll-mail")
    app = BUNDLE(coll, name="ragdoll-mail.app", icon=ICON, bundle_identifier="io.github.erict16.ragdoll-mail",
                 info_plist={"CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                             "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0",
                             "NSRequiresAquaSystemAppearance": False})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="ragdoll-mail", console=False, icon=ICON)
