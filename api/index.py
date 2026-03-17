"""
NEXUS CAPITAL - Vercel Serverless Dashboard API
Public endpoints: /, /api, /api/signals, /api/yield, /api/wallet
"""
import json
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

# Data root: Vercel serverless has limited filesystem; use env or default
DATA_ROOT = os.getenv("NEXUS_DATA_ROOT", str(Path(__file__).resolve().parent.parent))


def _load_json(path: str, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _get_wallet_value():
    relayer = os.getenv("RELAYER_API_KEY_ADDRESS")
    if not relayer:
        return {"value": 0, "user": ""}
    try:
        with urlopen(
            f"https://data-api.polymarket.com/value?user={relayer}",
            timeout=10,
        ) as r:
            arr = json.loads(r.read().decode())
            if isinstance(arr, list) and arr:
                return arr[0]
            if isinstance(arr, dict):
                return arr
    except (URLError, json.JSONDecodeError, OSError):
        pass
    return {"value": 0, "user": relayer}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/api", "/api/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "dashboard": "NEXUS CAPITAL",
                "endpoints": ["/api/signals", "/api/yield", "/api/wallet"],
            }, indent=2).encode())
            return
        if path == "/api/signals":
            p = Path(DATA_ROOT) / "paperclip_pending_signals.json"
            data = _load_json(str(p), {"signals": []})
            self._json_response(data)
            return
        if path == "/api/yield":
            p = Path(DATA_ROOT) / "defi_yield_state.json"
            data = _load_json(str(p), {})
            self._json_response(data)
            return
        if path == "/api/wallet":
            self._json_response(_get_wallet_value())
            return
        self.send_response(404)
        self.end_headers()

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
