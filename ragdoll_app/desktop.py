"""The parts that talk to the operating system: the window, its title bar colours, desktop
notifications, the unread number on the taskbar or Dock icon, and starting the app again."""

import contextlib
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
from types import SimpleNamespace

import ragdoll as R
from .common import FROZEN, HERE, STATIC


APP = SimpleNamespace(argv=[])


def relaunch():
    """Open the app again as a new process, then close this one (after an update)."""
    cmd = [sys.executable] if FROZEN else [sys.executable, "-m", "ragdoll_app"]
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, cwd=HERE)
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000 | 0x00000200       # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd + list(APP.argv), **kw)

    def stop():
        if WINDOW.w is not None:
            WINDOW.w.destroy()
        else:
            import _thread
            _thread.interrupt_main()
    threading.Timer(0.4, stop).start()


# ------------------------------------------------------------------ window

def system_dark():
    try:
        if sys.platform == "darwin":
            r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True,
                               timeout=5)
            return "dark" in r.stdout.lower()
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        pass
    return False


WINDOW = SimpleNamespace(w=None, hwnd=0, tokens=[], own=False, proc=None)


def mac_clear_titlebar(w):
    """macOS 26 paints the title bar container opaque even when it is 'transparent'; clear it."""
    try:
        box = w.standardWindowButton_(0).superview().superview()       # NSTitlebarContainerView
    except Exception:
        return
    import warnings
    warnings.filterwarnings("ignore", message="PyObjCPointer created")
    stack = [box]
    while stack:
        v = stack.pop()
        layer = v.layer()
        if layer is not None and layer.backgroundColor() is not None and "Widget" not in v.className():
            layer.setBackgroundColor_(None)
        stack.extend(v.subviews())


def mac_titlebar(window):
    """Content runs under the title bar; an empty unified toolbar centres the traffic lights in the app's top bar."""
    try:
        import AppKit
        from PyObjCTools import AppHelper
    except ImportError:
        return

    def go():
        w = window.native
        if w is None:
            return
        w.setStyleMask_(w.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
        w.setTitlebarAppearsTransparent_(True)
        w.setTitleVisibility_(AppKit.NSWindowTitleHidden)
        w.setMovableByWindowBackground_(False)
        if w.toolbar() is None:
            bar = AppKit.NSToolbar.alloc().initWithIdentifier_("ragdoll-mail")
            bar.setShowsBaselineSeparator_(False)
            w.setToolbar_(bar)
            w.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnified)
        mac_clear_titlebar(w)
        if not WINDOW.tokens:
            nc = AppKit.NSNotificationCenter.defaultCenter()

            def watch(name, fn):
                WINDOW.tokens.append(nc.addObserverForName_object_queue_usingBlock_(
                    getattr(AppKit, name, name), w, None, lambda _n: fn()))

            def toolbar(visible):
                if w.toolbar() is not None:
                    w.toolbar().setVisible_(visible)        # full screen has no traffic lights to make room for
                mac_clear_titlebar(w)
            for name in ("NSWindowDidBecomeKeyNotification", "NSWindowDidResignKeyNotification",
                         "NSWindowDidEndLiveResizeNotification", "NSWindowDidChangeScreenNotification"):
                watch(name, lambda: mac_clear_titlebar(w))
            watch("NSWindowWillEnterFullScreenNotification", lambda: toolbar(False))
            watch("NSWindowDidExitFullScreenNotification", lambda: toolbar(True))
    AppHelper.callAfter(go)


def win_one_piece(window):
    """Windows: take the system title bar away. The page runs to the top edge and draws its own three buttons.
    Unlike pywebview's frameless mode, the window keeps its resize border, shadow, round corners and snapping."""
    import ctypes
    from ctypes import wintypes
    from System import Action
    form = window.native
    if form is None or WINDOW.own:
        return
    u, c = ctypes.windll.user32, ctypes.windll.comctl32
    result = ctypes.c_ssize_t
    kind = ctypes.WINFUNCTYPE(result, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                              ctypes.c_size_t, ctypes.c_size_t)
    c.DefSubclassProc.restype = result
    c.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    c.SetWindowSubclass.argtypes = [wintypes.HWND, kind, ctypes.c_size_t, ctypes.c_size_t]
    for fn in (u.IsZoomed, u.GetDpiForWindow):
        fn.argtypes = [wintypes.HWND]
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]

    def proc(h, msg, wp, lp, _id, _data):
        if msg == 0x0083 and wp:                    # WM_NCCALCSIZE: how much of the window is the page's
            try:
                r = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT))
                top = r[0].top
                res = c.DefSubclassProc(h, msg, wp, lp)
                if u.IsZoomed(h):                   # a maximised window hangs over the screen edge by its border
                    dpi = u.GetDpiForWindow(h) or 96
                    top += u.GetSystemMetricsForDpi(33, dpi) + u.GetSystemMetricsForDpi(92, dpi)
                r[0].top = top                      # all of the top: no title bar
                return res
            except Exception:                       # noqa: BLE001 - never let the window procedure fail
                pass
        return c.DefSubclassProc(h, msg, wp, lp)

    def go():
        try:
            if WINDOW.own:
                return
            hwnd = int(form.Handle.ToInt64())
            WINDOW.proc = kind(proc)                # kept, or Python would free it under Windows' feet
            if c.SetWindowSubclass(hwnd, WINDOW.proc, 1, 0):
                WINDOW.own = True
                u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)   # frame changed
        except Exception:
            traceback.print_exc(file=sys.stderr)
    try:
        form.BeginInvoke(Action(go))
    except Exception:                               # noqa: BLE001 - no window handle yet: the next call makes it
        pass


def window_do(what):
    """What the page asks of its window on Windows: state, min, max, close, and drag / top, which hand a move
    or a resize from the top edge to Windows itself (so snapping to the screen edges works as usual)."""
    w = WINDOW.w
    if what == "state":
        full = False
        if w is not None and sys.platform == "win32" and WINDOW.own:
            import ctypes
            full = bool(ctypes.windll.user32.IsZoomed(ctypes.c_void_p(win_hwnd(w))))
        return {"own": bool(WINDOW.own), "max": full}
    if w is None or sys.platform != "win32" or not WINDOW.own:
        return {}
    import ctypes
    from ctypes import wintypes
    from System import Action
    hwnd = win_hwnd(w)
    u = ctypes.windll.user32
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.IsZoomed.argtypes = [wintypes.HWND]
    u.PostMessageW.argtypes = u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    def go():
        if what == "min":
            u.ShowWindow(hwnd, 6)
        elif what == "max":
            u.ShowWindow(hwnd, 9 if u.IsZoomed(hwnd) else 3)
        elif what == "close":
            u.PostMessageW(hwnd, 0x0010, 0, 0)          # WM_CLOSE, as the system's own button sends
        elif u.GetAsyncKeyState(0x02 if u.GetSystemMetrics(23) else 0x01) & 0x8000:
            # the mouse button is still down: a press on the title bar (2) or the top border (12)
            u.ReleaseCapture()
            u.SendMessageW(hwnd, 0x00A1, 2 if what == "drag" else 12, 0)
    w.native.BeginInvoke(Action(go))
    return {}


def win_hwnd(window):
    try:
        return int(window.native.Handle.ToInt64())
    except Exception:
        try:
            import ctypes
            return ctypes.windll.user32.FindWindowW(None, "ragdoll-mail") or 0
        except Exception:
            return 0


def hex_ref(c):
    """'#RRGGBB' -> Windows COLORREF (0x00BBGGRR)."""
    c = (c or "").lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        return None
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return r | g << 8 | b << 16


def window_theme(dark, bg=None, text=None):
    """Match the native title bar to the app theme (it can differ from the system's)."""
    w = WINDOW.w
    if w is None:
        return
    if sys.platform == "darwin":
        try:
            import AppKit
            from PyObjCTools import AppHelper
        except ImportError:
            return

        def go():
            nw = w.native
            if nw is None:
                return
            nw.setAppearance_(AppKit.NSAppearance.appearanceNamed_(
                AppKit.NSAppearanceNameDarkAqua if dark else AppKit.NSAppearanceNameAqua))
            ref = (bg or "").lstrip("#")
            if re.fullmatch(r"[0-9a-fA-F]{6}", ref):
                nw.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
                    int(ref[0:2], 16) / 255, int(ref[2:4], 16) / 255, int(ref[4:6], 16) / 255, 1.0))
            mac_clear_titlebar(nw)
        AppHelper.callAfter(go)
    elif sys.platform == "win32":
        import ctypes
        hwnd = WINDOW.hwnd or win_hwnd(w)
        WINDOW.hwnd = hwnd
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi

        def put(attr, value):
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
        if put(20, 1 if dark else 0):                    # DWMWA_USE_IMMERSIVE_DARK_MODE
            put(19, 1 if dark else 0)                    # same, Windows 10 before 20H1
        for attr, colour in ((35, bg), (36, text)):      # caption colour, caption text (Windows 11)
            ref = hex_ref(colour)
            if ref is not None:
                put(attr, ref)


# ------------------------------------------------------------------ desktop notifications

NOTE = SimpleNamespace(icon=None, on_click=None, mac_delegate=None)


def window_focused():
    """True when the app window is the one in front (then the list already shows the new mail)."""
    w = WINDOW.w
    if w is None:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            hwnd = WINDOW.hwnd or win_hwnd(w)
            return bool(hwnd) and ctypes.windll.user32.GetForegroundWindow() == hwnd
        if sys.platform == "darwin":
            import AppKit
            return bool(AppKit.NSApplication.sharedApplication().isActive())
    except Exception:
        pass
    return False


def window_front():
    w = WINDOW.w
    if w is None:
        return
    try:
        if sys.platform == "win32":
            import System.Windows.Forms as WF
            from System import Action
            form = w.native

            def go():
                if form.WindowState == WF.FormWindowState.Minimized:
                    form.WindowState = WF.FormWindowState.Normal
                form.Show()
                form.Activate()
            form.BeginInvoke(Action(go))
        elif sys.platform == "darwin":
            import AppKit
            from PyObjCTools import AppHelper

            def go():
                AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                nw = w.native
                if nw is not None:
                    if nw.isMiniaturized():
                        nw.deminiaturize_(None)
                    nw.makeKeyAndOrderFront_(None)
            AppHelper.callAfter(go)
        else:
            w.restore()
    except Exception:
        traceback.print_exc(file=sys.stderr)


def desktop_notify(title, text, on_click):
    """One system notification. A click on it calls on_click (Windows, and macOS in the .app)."""
    title, text = R.one_line(title)[:63], R.one_line(text)[:200]
    NOTE.on_click = on_click
    try:
        if sys.platform == "win32":
            win_notify(title, text)
        elif sys.platform == "darwin":
            mac_notify(title, text)
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "ragdoll-mail", title, text])
    except Exception:
        traceback.print_exc(file=sys.stderr)


def note_clicked(*_):
    fn = NOTE.on_click
    if fn is not None:
        fn()


def win_notify(title, text):
    """A balloon from the app's tray icon; Windows 10 and 11 show it as a notification."""
    form = getattr(WINDOW.w, "native", None)
    if form is None:
        return
    import System.Drawing as SD
    import System.Windows.Forms as WF
    from System import Action

    def go():
        if NOTE.icon is None:
            ni = WF.NotifyIcon()
            png = os.path.join(STATIC, "logo.png")
            ni.Icon = SD.Icon.FromHandle(SD.Bitmap(png).GetHicon()) if os.path.exists(png) else SD.SystemIcons.Application
            ni.Text = "ragdoll-mail"
            ni.BalloonTipClicked += note_clicked
            ni.MouseClick += lambda *_: window_front()
            NOTE.icon = ni
        ni = NOTE.icon
        ni.Visible = True
        ni.BalloonTipTitle = title
        ni.BalloonTipText = text or title
        ni.ShowBalloonTip(10000)
    form.BeginInvoke(Action(go))


def win_notify_close(*_):
    if NOTE.icon is not None:
        with contextlib.suppress(Exception):
            NOTE.icon.Visible = False
            NOTE.icon.Dispose()
        NOTE.icon = None


def mac_notify(title, text):
    center = None
    try:
        import Foundation
        from PyObjCTools import AppHelper
        center = Foundation.NSUserNotificationCenter.defaultUserNotificationCenter()   # None outside an .app
    except Exception:
        pass
    if center is None:
        # from source: AppleScript's notification (a click on it opens Script Editor, not the app)
        subprocess.Popen(["osascript", "-e", "on run argv", "-e",
                          "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run",
                          title, text])
        return

    def go():
        if NOTE.mac_delegate is None:
            class RagdollNoteDelegate(Foundation.NSObject):
                def userNotificationCenter_didActivateNotification_(self, _center, _note):
                    note_clicked()
            NOTE.mac_delegate = RagdollNoteDelegate.alloc().init()
            center.setDelegate_(NOTE.mac_delegate)
        n = Foundation.NSUserNotification.alloc().init()
        n.setTitle_(title)
        n.setInformativeText_(text)
        center.deliverNotification_(n)
    AppHelper.callAfter(go)


# ------------------------------------------------------------------ unread count on the app icon

BADGE = SimpleNamespace(n=None, shown=None, taskbar=None, icon=0)


def set_badge(n):
    """The number of unread Inbox mails on the Dock icon (macOS) or the taskbar button (Windows)."""
    BADGE.n = n
    if WINDOW.w is None or n == BADGE.shown:
        return
    try:
        if sys.platform == "darwin":
            import AppKit
            from PyObjCTools import AppHelper

            def go():
                AppKit.NSApplication.sharedApplication().dockTile().setBadgeLabel_(badge_text(n) or None)
                BADGE.shown = n
            AppHelper.callAfter(go)
        elif sys.platform == "win32":
            win_badge(n)
    except Exception:
        traceback.print_exc(file=sys.stderr)


def badge_text(n):
    return "" if not n else str(n) if n < 100 else "99+"


def win_badge(n):
    """A small red circle with the number, laid over the taskbar button (ITaskbarList3.SetOverlayIcon)."""
    form = getattr(WINDOW.w, "native", None)
    if form is None:
        return
    import ctypes
    from ctypes import wintypes
    import System.Drawing as SD
    from System import Action

    def taskbar():
        class GUID(ctypes.Structure):
            _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]
        ole = ctypes.windll.ole32
        clsid, iid = GUID(), GUID()
        ole.CLSIDFromString(ctypes.c_wchar_p("{56FDF344-FD6D-11D0-958A-006097C9A090}"), ctypes.byref(clsid))
        ole.CLSIDFromString(ctypes.c_wchar_p("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"), ctypes.byref(iid))
        p = ctypes.c_void_p()
        if ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(p)) or not p:
            return None
        vt = ctypes.cast(ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vt[3])(p)                               # HrInit
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.HWND, wintypes.HICON, wintypes.LPCWSTR)(vt[18])
        return lambda hwnd, icon, text: fn(p, hwnd, icon, text)                                   # SetOverlayIcon

    def draw(text):
        bmp = SD.Bitmap(32, 32)
        g = SD.Graphics.FromImage(bmp)
        g.SmoothingMode = SD.Drawing2D.SmoothingMode.AntiAlias
        g.TextRenderingHint = SD.Text.TextRenderingHint.AntiAlias
        g.Clear(SD.Color.Transparent)
        g.FillEllipse(SD.SolidBrush(SD.Color.FromArgb(255, 221, 58, 58)), 0, 0, 31, 31)
        font = SD.Font("Segoe UI", {1: 23.0, 2: 18.0}.get(len(text), 13.0), SD.FontStyle.Bold, SD.GraphicsUnit.Pixel)
        fmt = SD.StringFormat()
        fmt.Alignment = fmt.LineAlignment = SD.StringAlignment.Center
        g.DrawString(text, font, SD.Brushes.White, SD.RectangleF(0.0, 1.0, 32.0, 32.0), fmt)
        g.Dispose()
        return int(bmp.GetHicon().ToInt64())

    def go():
        try:
            if BADGE.taskbar is None:
                BADGE.taskbar = taskbar() or False
            if not BADGE.taskbar:
                return
            hwnd = int(form.Handle.ToInt64())
            text = badge_text(n)
            icon = draw(text) if text else 0
            if BADGE.taskbar(hwnd, icon or None, text or None) == 0:
                BADGE.shown = n
            if BADGE.icon:
                ctypes.windll.user32.DestroyIcon(ctypes.c_void_p(BADGE.icon))
            BADGE.icon = icon
        except Exception:
            traceback.print_exc(file=sys.stderr)
    form.BeginInvoke(Action(go))


def run_window(url, home):
    import webview
    if sys.platform == "win32":
        # the page starts window moves itself (app/js/window.js); pywebview's own dragging would fight it
        webview.settings["DRAG_REGION_SELECTOR"] = ".pywebview-drag-off"
    dark = system_dark()
    w = webview.create_window("ragdoll-mail", url, width=1280, height=820, min_size=(880, 560),
                              background_color="#191919" if dark else "#FFFFFF", text_select=True)
    WINDOW.w = w
    if sys.platform == "darwin":
        w.events.before_show += lambda: mac_titlebar(w)
        w.events.shown += lambda: mac_titlebar(w)
    elif sys.platform == "win32":
        w.events.shown += lambda: window_theme(dark, "#191919" if dark else "#FFFFFF",
                                               "#E8E8E6" if dark else "#191919")
    # the taskbar button exists only once the window is up: put the count on it then
    w.events.shown += lambda: threading.Timer(1.0, lambda: (setattr(BADGE, "shown", None), set_badge(BADGE.n))).start()
    if sys.platform == "win32":
        w.events.closing += win_notify_close
        w.events.before_show += lambda: win_one_piece(w)
        w.events.shown += lambda: win_one_piece(w)
    icon = os.path.join(STATIC, "logo.png")
    if sys.platform == "win32":
        icon = None             # Windows wants an .ico here (a .png stops the window); the .exe carries its own
    webview.start(private_mode=False, storage_path=os.path.join(home, "webview"),
                  icon=icon if icon and os.path.exists(icon) else None)
