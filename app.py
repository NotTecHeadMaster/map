#!/usr/bin/env python3
"""
Tactical Map — local dashboard server.

Usage
-----
  python app.py                 Start the server and open the dashboard
  python app.py --port 9000     Use a custom port
  python app.py --no-browser    Don't open the browser automatically

Startup file handling (checked on every launch)
-----------------------------------------------
  newmap.osm   -> replaces assets/map.osm
  newdata.json -> replaces data.json
  adddata.json -> merged into data.json (items appended), then deleted
"""

import argparse
import json
import random
import shutil
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Timer

# ─── Paths ──────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent
DATA = BASE / "data.json"
OSM  = BASE / "assets" / "map.osm"

NEW_MAP  = BASE / "newmap.osm"
NEW_DATA = BASE / "newdata.json"
ADD_DATA = BASE / "adddata.json"

HOST = "127.0.0.1"
KEYS = ("targets", "pins", "symbols")


# ════════════════════════════════════════════════════════════
#  DATA HELPERS
# ════════════════════════════════════════════════════════════
def _empty() -> dict:
    return {k: [] for k in KEYS}


def _load() -> dict:
    if DATA.exists():
        try:
            data = json.loads(DATA.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return _empty()


def _save(data: dict) -> None:
    DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _ensure_data() -> None:
    if not DATA.exists():
        _save(_empty())


def _gen_id() -> str:
    return f"{int(time.time() * 1000):x}-{random.randint(1000, 9999)}"


# ════════════════════════════════════════════════════════════
#  STARTUP FILE HANDLING
# ════════════════════════════════════════════════════════════
def replace_files() -> None:
    """newmap.osm -> assets/map.osm and newdata.json -> data.json."""
    for src, dst in ((NEW_MAP, OSM), (NEW_DATA, DATA)):
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            src.unlink()
            print(f"[startup] Replaced {dst.name} <- {src.name}")


def add_data() -> None:
    """Append the contents of adddata.json to data.json, then delete it."""
    if not ADD_DATA.exists():
        return
    try:
        extra = json.loads(ADD_DATA.read_text(encoding="utf-8"))
        if not isinstance(extra, dict):
            raise ValueError("top level must be an object")
        for k in KEYS:
            if not isinstance(extra.get(k, []), list):
                raise ValueError(f'"{k}" must be an array')
    except (json.JSONDecodeError, ValueError) as exc:
        # Leave the file in place so nothing is lost
        print(f"[startup] Skipped {ADD_DATA.name}: {exc}")
        return

    data = _load()
    added = 0
    for k in KEYS:
        items = data.setdefault(k, [])
        seen = {i.get("id") for i in items if isinstance(i, dict)}
        for item in extra.get(k, []):
            if not isinstance(item, dict):
                continue
            if not item.get("id"):
                item["id"] = _gen_id()
            if item["id"] in seen:
                continue
            items.append(item)
            seen.add(item["id"])
            added += 1

    _save(data)
    ADD_DATA.unlink()
    print(f"[startup] Added {added} item(s) from {ADD_DATA.name} to {DATA.name}")


# ════════════════════════════════════════════════════════════
#  HTTP SERVER
# ════════════════════════════════════════════════════════════
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE), **kwargs)

    # ── GET ─────────────────────────────────────────────────
    def do_GET(self):
        if self.path.startswith("/api/data"):
            self._send_data()
        else:
            super().do_GET()

    # ── POST ────────────────────────────────────────────────
    def do_POST(self):
        if self.path == "/api/data":
            self._receive_data()
        else:
            self.send_error(404)

    # ── API: send ────────────────────────────────────────────
    def _send_data(self):
        try:
            _ensure_data()
            payload = json.dumps(_load()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",  "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control",  "no-store")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            self.send_error(500, str(exc))

    # ── API: receive ─────────────────────────────────────────
    def _receive_data(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))

            if not isinstance(data, dict):
                raise ValueError("payload must be an object")
            for key in KEYS:
                if not isinstance(data.get(key, []), list):
                    raise ValueError(f'"{key}" must be an array')

            _save(data)
            resp, status = {"ok": True}, 200
        except Exception as exc:
            resp, status = {"ok": False, "error": str(exc)}, 400

        body = json.dumps(resp).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",  "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"  [{self.log_date_time_string()}] " + fmt % args)


def start_server(port: int = 8000, open_browser: bool = True) -> None:
    _ensure_data()
    server = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"

    print()
    print(f"  Tactical Map running at {url}")
    print(f"  OSM  : {OSM}")
    print(f"  Data : {DATA}")
    print("  Press Ctrl+C to stop.")
    print()

    if open_browser:
        Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopping…")
    finally:
        server.server_close()


# ════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(prog="app.py", description="Tactical Map server")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not open the browser automatically")
    args = parser.parse_args()

    replace_files()   # newmap.osm / newdata.json
    add_data()        # adddata.json (runs after newdata.json, so it merges into the new data)
    start_server(port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()