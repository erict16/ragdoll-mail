"""Open the real app window on the demo mailbox and click through it (tests/ui_smoke.js).

    python tests/ui_smoke.py

Needs pywebview. Prints each step; the exit code is 1 when a step fails or the page reports an error.
Not part of `python -m unittest`: it needs a screen.
"""
import json, os, shutil, sys, threading, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll_app as A  # noqa: E402

JS = open(os.path.join(os.path.dirname(__file__), "ui_smoke.js"), encoding="utf-8").read()
out = {"result": None}


def drive():
    w = None
    try:
        end = time.time() + 30
        while time.time() < end and (A.desktop.WINDOW.w is None or not A.desktop.WINDOW.w.evaluate_js("!!document.querySelector('#rows .row')")):
            time.sleep(0.3)
        w = A.desktop.WINDOW.w
        w.evaluate_js(JS)
        end = time.time() + 90
        while time.time() < end and not out["result"]:
            time.sleep(0.5)
            out["result"] = json.loads(w.evaluate_js("JSON.stringify(window.__smoke || null)") or "null")
    finally:
        if w is not None:
            w.destroy()


def main():
    backend = A.Backend(demo=True)
    srv = A.Server(("127.0.0.1", 0), A.make_handler(backend, "smoke"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=drive, daemon=True).start()
    try:
        A.run_window("http://127.0.0.1:%d/#t=smoke" % srv.server_address[1], A.R.CFG.home)
    finally:
        backend.close()
        srv.shutdown()
        shutil.rmtree(A.R.CFG.home, ignore_errors=True)
    r = out["result"] or {"ok": False, "steps": [], "errors": ["the page gave no result"]}
    print("\n".join(r["steps"] + r["errors"]))
    print("UI smoke test: %s" % ("passed" if r["ok"] else "FAILED"))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
