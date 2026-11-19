"""Starting the app: read the command line, start the server, open the window or the browser."""

import argparse
import contextlib
import os
import secrets
import shutil
import signal
import sys
import threading
import time
import webbrowser

import ragdoll as R
from .backend import Backend
from .common import __version__
from .desktop import APP, run_window
from .server import make_handler, Server


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ragdoll app", description="ragdoll-mail desktop app")
    ap.add_argument("--demo", action="store_true", help="a made-up mailbox; no account needed")
    ap.add_argument("--browser", action="store_true", help="open in the default browser, not a window")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version="ragdoll-mail " + __version__)
    a = ap.parse_args(argv)
    APP.argv = list(sys.argv[1:] if argv is None else argv)
    # a plain kill still closes the mailbox and removes the demo's temp folder
    with contextlib.suppress(ValueError, OSError):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    backend = Backend(demo=a.demo)
    token = os.environ.get("RAGDOLL_APP_TOKEN") or secrets.token_urlsafe(24)
    srv = Server(("127.0.0.1", a.port), make_handler(backend, token))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/#t=%s" % (srv.server_address[1], token)
    use_window = not a.browser
    if use_window:
        try:
            import webview  # noqa: F401
        except ImportError:
            use_window = False
            print("pywebview is not installed (pip install pywebview); opening the browser instead.",
                  file=sys.stderr)
    try:
        with R.running("app"):
            if use_window:
                run_window(url, R.CFG.home)
            else:
                print("ragdoll-mail is running at http://127.0.0.1:%d  (Ctrl+C stops it)" % srv.server_address[1])
                if not a.no_open:
                    webbrowser.open(url)
                while True:
                    time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        backend.close()
        srv.shutdown()
        if a.demo:
            shutil.rmtree(R.CFG.home, ignore_errors=True)
