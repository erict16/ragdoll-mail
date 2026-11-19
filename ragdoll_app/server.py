"""The small HTTP server the page talks to. It answers only requests that carry this run's token."""

import json
import os
import secrets
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .common import STATIC


# ------------------------------------------------------------------ HTTP server

TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
         ".json": "application/json", ".woff2": "font/woff2"}


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob: https: http:; font-src 'self' data:; connect-src 'self'; "
       "frame-src 'self' about: data:; media-src 'self' data:; object-src 'none'; base-uri 'none'; "
       "form-action 'none'")


def make_handler(backend, token):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "ragdoll"

        def log_message(self, *args):
            pass

        def host_ok(self):
            port = self.server.server_address[1]
            return self.headers.get("Host") in ("127.0.0.1:%d" % port, "localhost:%d" % port)

        def send(self, code, body, ctype="application/json; charset=utf-8", extra=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if self.close_connection:
                self.send_header("Connection", "close")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.host_ok():
                return self.send(403, b"forbidden", "text/plain")
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                path = "/index.html"
            full = os.path.realpath(os.path.join(STATIC, urllib.parse.unquote(path).lstrip("/")))
            if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
                return self.send(404, b"not found", "text/plain")
            with open(full, "rb") as f:
                body = f.read()
            ext = os.path.splitext(full)[1].lower()
            extra = [("Content-Security-Policy", CSP)] if ext == ".html" else []
            self.send(200, body, TYPES.get(ext, "application/octet-stream"), extra)

        def do_POST(self):
            # On a kept-alive connection an unread body would be parsed as the next request,
            # so every early answer either reads the body or closes the connection.
            try:
                n = max(0, int(self.headers.get("Content-Length") or 0))
            except ValueError:
                self.close_connection = True
                return self.send(400, b'{"ok":false,"error":"bad request"}')
            if not self.host_ok() or not secrets.compare_digest(self.headers.get("X-Token", ""), token):
                self.close_connection = True
                return self.send(403, b'{"ok":false,"error":"forbidden"}')
            if n > 200 * 1024 * 1024:
                self.close_connection = True
                return self.send(413, b'{"ok":false,"error":"That file is too big."}')
            data = self.rfile.read(n) if n else b""
            path = urllib.parse.urlparse(self.path).path
            if path == "/upload":
                name = urllib.parse.unquote(self.headers.get("X-Name", "file"))
                try:
                    out = {"ok": True, "data": backend.upload(name, data)}
                except OSError as e:
                    out = {"ok": False, "error": str(e)}
                return self.send(200, json.dumps(out, ensure_ascii=False).encode())
            if not path.startswith("/api/"):
                return self.send(404, b'{"ok":false,"error":"not found"}')
            try:
                args = json.loads(data or b"{}")
            except ValueError:
                return self.send(400, b'{"ok":false,"error":"bad request"}')
            code, out = backend.call(path[5:], args)
            self.send(code, json.dumps(out, ensure_ascii=False).encode())

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
