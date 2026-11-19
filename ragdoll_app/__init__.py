"""ragdoll-mail desktop app: a window over ragdoll's mailbox and search index.

    ragdoll app                 open the app (pywebview window, else the default browser)
    python -m ragdoll_app --demo --browser
                                a made-up mailbox in the browser, no account needed

The page (app/) talks to a small HTTP server on 127.0.0.1. The server answers only requests
that carry this run's random token, and only for the 127.0.0.1 host name (no DNS rebinding).

Where things are:
    launch.py      the command line; starts the server and the window
    server.py      the HTTP server the page talks to
    backend.py     Backend, the object behind the page; it inherits one class per feature:
                   folders.py  sync.py  updates.py  status.py  reading.py  compose.py
                   sendlater.py  invites.py  snooze.py  templates.py  settings.py  demo.py
    message.py     raw mail -> safe HTML for the page, rows for the index
    desktop.py     window, notifications, taskbar badge (everything that touches the OS)
    common.py      paths, the error type, small helpers
"""
import os
import sys

for _s in ("stdout", "stderr"):          # a windowed (PyInstaller) build has no console
    if getattr(sys, _s) is None:
        setattr(sys, _s, open(os.devnull, "w", encoding="utf-8"))

import ragdoll as R  # noqa: E402,F401
from . import (  # noqa: E402,F401
    common, compose, demo, desktop, folders, invites, message, reading, sendlater, server, settings, snooze,
    status, sync, templates, updates,
)
from .backend import Backend  # noqa: E402,F401
from .common import ApiError, __version__  # noqa: E402,F401
from .desktop import run_window  # noqa: E402,F401
from .launch import main  # noqa: E402,F401
from .server import Server, make_handler  # noqa: E402,F401
