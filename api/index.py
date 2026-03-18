"""
NEXUS CAPITAL - Vercel Serverless Dashboard API
Serves Bloomberg-style dashboard + API endpoints with Supabase data.
Auth: token dans ?token= requis pour les endpoints API (sauf /health et dashboard HTML).
"""
import json
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError

DATA_ROOT = os.getenv("NEXUS_DATA_ROOT", str(Path(__file__).resolve().parent.parent))


def _get_query_token(path: str) -> str | None:
    """Extrait ?token=XXX de l'URL."""
    if "?" not in path:
        return None
    qs = path.split("?", 1)[1]
    params = parse_qs(qs)
    tokens = params.get("token", [])
    return tokens[0].strip() if tokens else None


def _validate_token(token: str) -> bool:
    """Vérifie token dans Supabase users : is_active et (expires_at null ou > now)."""
    if not token or len(token) < 6:
        return False
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return False
    try:
        req = Request(
            f"{url}/rest/v1/users?access_token=eq.{token}&select=is_active,expires_at",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
            },
            method="GET",
        )
        with urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        if not data or not isinstance(data, list):
            return False
        row = data[0]
        if not row.get("is_active", False):
            return False
        exp = row.get("expires_at")
        if exp:
            from datetime import datetime, timezone
            try:
                if isinstance(exp, str):
                    exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                else:
                    exp_dt = exp
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp_dt:
                    return False
            except Exception:
                return False
        return True
    except Exception:
        return False


def _load_json(path: str, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _get_wallet_value():
    """Retourne {"value": X, "user": Y} pour le dashboard."""
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
                row = arr[0]
                return {"value": float(row.get("value", row.get("usdc", 0))), "user": row.get("user", relayer)}
            if isinstance(arr, dict):
                v = arr.get("value", arr.get("usdc", 0))
                return {"value": float(v), "user": arr.get("user", relayer)}
    except (URLError, json.JSONDecodeError, OSError):
        pass
    return {"value": 0, "user": relayer}


def _supabase_fetch(table: str, limit: int = 50, extra: str = ""):
    """Fetch from Supabase. Returns list or empty list on error."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")
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


def _get_top_markets():
    """Top 5 marchés par volume 24h depuis Gamma API Polymarket."""
    try:
        url = "https://gamma-api.polymarket.com/markets?limit=5&active=true&closed=false&archived=false&order=volume24hr&ascending=false"
        with urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
        markets = data if isinstance(data, list) else data.get("data", []) or []
        return [
            {
                "question": (m.get("question") or "")[:60],
                "volume24hr": float(m.get("volume24hr") or m.get("volume") or m.get("volume_24hr", 0)),
                "outcomePrices": m.get("outcomePrices") or ["0.5", "0.5"],
                "conditionId": m.get("conditionId") or m.get("id"),
            }
            for m in markets[:5]
        ]
    except Exception:
        return []


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
    def _unauthorized(self):
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(
            json.dumps({"error": "unauthorized", "message": "Accès requis"}).encode()
        )

    def do_GET(self):
        path = self.path.split("?")[0]
        full_path = self.path
        token = _get_query_token(full_path)

        # Public : dashboard HTML et /health
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

        # Endpoints API protégés par token
        if not token or not _validate_token(token):
            self._unauthorized()
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
            debates = [{"agent": r.get("role"), "vote": r.get("vote"), "message": r.get("content"), "content": r.get("content"), "created_at": r.get("created_at")} for r in rows]
            self._json_response({"debates": debates})
            return
        if path == "/api/track-record":
            self._json_response(_get_track_record())
            return
        if path == "/api/market-types":
            self._json_response(_get_market_types())
            return
        if path == "/api/top-markets":
            self._json_response(_get_top_markets())
            return
        self.send_response(404)
        self.end_headers()

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

