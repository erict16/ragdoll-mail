# PyInstaller build for the desktop app:  pyinstaller ragdoll-mail.spec
# macOS gives dist/ragdoll-mail.app, Windows gives dist/ragdoll-mail.exe (one file, no console).
import re
import sys

VERSION = re.search(r'^__version__ = "([^"]+)"', open("ragdoll.py", encoding="utf-8").read(), re.M).group(1)
# PyInstaller turns it into .icns / .ico (needs Pillow). macOS gets its own icon on Apple's
# 1024 grid (824 px tile, room for the shadow); Windows keeps the full-size one.
ICON = "assets/icon-mac.png" if sys.platform == "darwin" else "assets/icon.png"

a = Analysis(["ragdoll_app.py"], datas=[("app", "app")], hiddenimports=["ragdoll"] + (["UserNotifications"] if sys.platform == "darwin" else []),
             excludes=["tkinter", "unittest", "pydoc"])
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
