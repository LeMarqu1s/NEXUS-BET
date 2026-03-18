"""
NEXUS CAPITAL - Vercel Serverless Dashboard API
Serves Bloomberg-style dashboard + API endpoints with Supabase data.
"""
import json
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

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


def _supabase_fetch(table: str, limit: int = 50, extra: str = ""):
    """Fetch from Supabase. Returns list or empty list on error."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return []
    try:
        order_col = "created_at" if table != "positions" else "opened_at"
        q = f"{url.rstrip('/')}/rest/v1/{table}?order={order_col}.desc&limit={limit}{extra}"
        req = __import__("urllib.request").request.Request(
            q,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception:
        return []


def _get_track_record():
    """Compute track record stats from Supabase trades table."""
    trades = _supabase_fetch("trades", limit=10000)
    if not trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_edge": 0,
            "best_trade": 0,
            "worst_trade": 0,
            "depuis": None,
        }
    pnls = []
    edges = []
    dates = []
    for t in trades:
        p = float(t.get("pnl") or t.get("pnl_usd") or 0)
        pnls.append(p)
        e = t.get("edge_pct")
        if e is not None:
            edges.append(float(e))
        created = t.get("created_at")
        if created:
            dates.append(created)
    winning = sum(1 for p in pnls if p > 0)
    total = len(trades)
    return {
        "total_trades": total,
        "winning_trades": winning,
        "win_rate": round(winning / total * 100, 1) if total else 0,
        "total_pnl": round(sum(pnls), 2),
        "avg_edge": round(sum(edges) / len(edges), 2) if edges else 0,
        "best_trade": round(max(pnls), 2) if pnls else 0,
        "worst_trade": round(min(pnls), 2) if pnls else 0,
        "depuis": min(dates) if dates else None,
    }


def _get_market_types():
    """Stats des signaux par type depuis paperclip_pending_signals.json."""
    p = Path(DATA_ROOT) / "paperclip_pending_signals.json"
    data = _load_json(str(p), {"signals": []})
    signals = data.get("signals", []) if isinstance(data, dict) else data or []
    by_type = {"binary": [], "multi_outcome": [], "scalar": []}
    for s in signals:
        mt = str(s.get("market_type", "binary")).lower().replace("-", "_")
        if mt not in by_type:
            by_type[mt] = []
        edge = float(s.get("edge_pct", 0))
        by_type[mt].append(edge)
    return {
        "binary": {"count": len(by_type["binary"]), "avg_edge": round(sum(by_type["binary"]) / len(by_type["binary"]), 2) if by_type["binary"] else 0},
        "multi_outcome": {"count": len(by_type["multi_outcome"]), "avg_edge": round(sum(by_type["multi_outcome"]) / len(by_type["multi_outcome"]), 2) if by_type["multi_outcome"] else 0},
        "scalar": {"count": len(by_type["scalar"]), "avg_edge": round(sum(by_type["scalar"]) / len(by_type["scalar"]), 2) if by_type["scalar"] else 0},
    }


def _get_dashboard_html():
    p = Path(__file__).resolve().parent / "dashboard.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "<!DOCTYPE html><html><body><h1>NEXUS CAPITAL</h1><p>Dashboard not found.</p></body></html>"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        # Serve dashboard UI at / and /dashboard
        if path in ("/", "/dashboard", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(_get_dashboard_html().encode("utf-8"))
            return
        if path == "/health":
            self._json_response({"status": "ok", "dashboard": "NEXUS CAPITAL"})
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
        if path == "/api/positions":
            rows = _supabase_fetch("positions", 100, "&status=eq.OPEN")
            self._json_response(rows)
            return
        if path == "/api/trades":
            rows = _supabase_fetch("trades", 50)
            self._json_response(rows)
            return
        if path == "/api/debates":
            rows = _supabase_fetch("debates", 30)
            debates = [{"agent": r.get("role"), "vote": r.get("vote"), "message": r.get("content"), "content": r.get("content")} for r in rows]
            self._json_response({"debates": debates})
            return
        if path == "/api/track-record":
            self._json_response(_get_track_record())
            return
        if path == "/api/market-types":
            self._json_response(_get_market_types())
            return
        self.send_response(404)
        self.end_headers()

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

