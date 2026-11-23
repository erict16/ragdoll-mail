# PyInstaller build for the desktop app:  pyinstaller ragdoll-mail.spec
# macOS gives "dist/Ragdoll Mail.app"; Windows gives "dist/Ragdoll Mail.exe" (one file, no console)
# and "dist/ragdoll.exe" (the command line, with a console).
import re
import sys

VERSION = re.search(r'^__version__ = "([^"]+)"', open("ragdoll.py", encoding="utf-8").read(), re.M).group(1)
# PyInstaller turns it into .icns / .ico (needs Pillow). macOS gets its own icon on Apple's
# 1024 grid (824 px tile, room for the shadow); Windows keeps the full-size one.
ICON = "assets/icon-mac.png" if sys.platform == "darwin" else "assets/icon.png"

# Windows has no time zone database of its own: invite times need the tzdata package's files
TZ = []
if sys.platform == "win32":
    from PyInstaller.utils.hooks import collect_data_files
    TZ = collect_data_files("tzdata")

a = Analysis(["ragdoll_app.py"], datas=[("app", "app")] + TZ,
             hiddenimports=["ragdoll"] + (["UserNotifications"] if sys.platform == "darwin" else []) + (["tzdata"] if sys.platform == "win32" else []),
             excludes=["tkinter", "unittest", "pydoc"])
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ragdoll-mail", console=False, icon=ICON)
    coll = COLLECT(exe, a.binaries, a.datas, name="ragdoll-mail")
    app = BUNDLE(coll, name="Ragdoll Mail.app", icon=ICON, bundle_identifier="io.github.erict16.ragdoll-mail",
                 info_plist={"CFBundleName": "Ragdoll Mail", "CFBundleDisplayName": "Ragdoll Mail",
                             "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                             "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0",
                             "NSRequiresAquaSystemAppearance": False})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="Ragdoll Mail", console=False, icon=ICON)
    # A window program has no console, so the ragdoll command is its own small
    # console program beside it. On the Mac the app's own program is the command: <app> cli ...
    c = Analysis(["ragdoll.py"], excludes=["tkinter", "unittest", "pydoc", "webview"])
    cli = EXE(PYZ(c.pure), c.scripts, c.binaries, c.datas, [], name="ragdoll", console=True, icon=ICON)
