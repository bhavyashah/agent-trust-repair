"""Chat panel for the reimbursement demo.

    python agent/panel.py [--url URL] [--email-delay 20] [--headless] [--reset] [--before | --script]

Opens the panel at http://localhost:8790 in your normal browser (use it with
your screen reader). The agent's own browser window opens beside it.
"""
import argparse, json, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from agent import Agent, SITE_URL, reset_demo, FILES

PAGE = (Path(__file__).parent / "panel.html").read_text(encoding="utf-8")
EVENTS, LOCK = [], threading.Lock()


def emit(kind, text="", meta=None):
    with LOCK:
        EVENTS.append({"id": len(EVENTS) + 1, "kind": kind, "text": text, "meta": meta or {}})
    if kind not in ("busy", "idle"):
        print(f"[{kind}] {text}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = PAGE.replace("{{MODE}}", MODE).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/events"):
            after = int(self.path.split("after=")[-1]) if "after=" in self.path else 0
            with LOCK:
                items = [e for e in EVENTS if e["id"] > after]
            self._json({"events": items, "busy": AGENT.busy})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/message" and data.get("text", "").strip():
            AGENT.send("person", data["text"].strip())
        elif self.path == "/api/confirm":
            AGENT.send("confirm", bool(data.get("ok")))
        elif self.path == "/api/email-now":
            if AGENT.last_submission:
                AGENT.send("email", AGENT.last_submission)
            else:
                emit("notice", "Nothing has been submitted yet, so there is no email to deliver.")
        elif self.path in ("/api/new", "/api/reset"):
            AGENT.send(self.path.rsplit("/", 1)[-1])
        self._json({"ok": True})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=SITE_URL)
    ap.add_argument("--email-delay", type=int, default=20, help="seconds before the outcome email arrives; -1 = only by button")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--reset", action="store_true", help="restore the Receipts folder and forget preferences first")
    ap.add_argument("--before", action="store_true", help="show the original recovery behavior (default: the improved 'after' one)")
    ap.add_argument("--script", action="store_true", help="scripted trust repair after the rejection email (same beats every run)")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    if args.reset or not any(FILES.glob("*.jpeg")):
        reset_demo()
    MODE = "before" if args.before else "scripted" if args.script else "after"
    print(f"Recovery: {MODE}", flush=True)
    AGENT = Agent(emit, headless=args.headless, url=args.url, email_delay=args.email_delay, mode=MODE)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}/"
    print("Chat panel:", url, flush=True)
    if not args.no_open:
        webbrowser.open(url)
    server.serve_forever()
