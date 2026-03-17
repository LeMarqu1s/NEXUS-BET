#!/usr/bin/env python3
"""
NEXUS CAPITAL - Dashboard HTTP Server (port 3000)
Simple dashboard for status, signals, positions.
"""
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'\"").strip()
            if k and v:
                os.environ.setdefault(k, v)

PORT = 3000


def _load_json(path: Path, default: dict | list) -> dict | list:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main():
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
    except ImportError:
        print("http.server not available")
        return 1

    root = Path(__file__).resolve().parent.parent

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/" or self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                data = {
                    "status": "ok",
                    "dashboard": "NEXUS CAPITAL",
                    "port": PORT,
                }
                self.wfile.write(json.dumps(data, indent=2).encode())
                return
            if self.path == "/api/signals":
                p = root / "paperclip_pending_signals.json"
                data = _load_json(p, {"signals": []})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data, indent=2).encode())
                return
            if self.path == "/api/yield":
                p = root / "defi_yield_state.json"
                data = _load_json(p, {})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data, indent=2).encode())
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format, *args):
            print(f"[Dashboard] {args[0]}")

    server = HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    print(f"NEXUS CAPITAL Dashboard running on http://localhost:{PORT}")
    print("Endpoints: /health, /api/signals, /api/yield")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
