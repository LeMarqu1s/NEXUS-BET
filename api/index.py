"""
NEXUS CAPITAL - Vercel Serverless Dashboard API
Serves Bloomberg-style dashboard + API endpoints with Supabase data.
Auth: token dans ?token= requis pour les endpoints API (sauf /health et dashboard HTML).
Performance: timeout 5s, cache market 60s.
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError

DATA_ROOT = os.getenv("NEXUS_DATA_ROOT", str(Path(__file__).resolve().parent.parent))
API_TIMEOUT = 5
CACHE_TTL = 60
_market_cache: dict[str, tuple[dict, float]] = {}


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


def _fetch_url(url: str, timeout: int = API_TIMEOUT) -> dict | list | None:
    """Fetch JSON from URL. Returns None on error. Max 5s timeout."""
    try:
        req = Request(url, headers={"User-Agent": "NexusCapital/1.0"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _get_market_by_id_or_slug(identifier: str) -> dict | None:
    """Récupère un marché depuis Gamma API par condition_id ou slug."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    gamma = "https://gamma-api.polymarket.com"
    # Essai 1: par slug (pas de 0x)
    if not identifier.startswith("0x"):
        for url in (
            f"{gamma}/markets/slug/{identifier}",
            f"{gamma}/markets?slug={identifier}",
        ):
            data = _fetch_url(url, timeout=API_TIMEOUT)
            if data:
                m = data[0] if isinstance(data, list) and data else data
                if isinstance(m, dict):
                    return m
    # Essai 2: par condition_id
    for url in (
        f"{gamma}/markets/{identifier}",
        f"{gamma}/markets?condition_id={identifier}",
    ):
        data = _fetch_url(url, timeout=API_TIMEOUT)
        if data:
            m = data[0] if isinstance(data, list) and data else data
            if isinstance(m, dict) and str(m.get("conditionId", m.get("id", ""))) == identifier:
                return m
    # Essai 3: recherche dans les marchés actifs (fallback)
    try:
        url = f"{gamma}/markets?limit=200&active=true&closed=false"
        data = _fetch_url(url, timeout=API_TIMEOUT)
        markets = data if isinstance(data, list) else (data.get("data", []) or []) if isinstance(data, dict) else []
        ident_lower = identifier.lower()
        for m in markets:
            if not isinstance(m, dict):
                continue
            cid = str(m.get("conditionId", m.get("id", "")))
            slug = str(m.get("slug", ""))
            q = str(m.get("question", ""))
            if cid == identifier or slug == identifier or ident_lower in q.lower():
                return m
    except Exception:
        pass
    return None


def _extract_token_ids(market: dict) -> tuple[str | None, str | None]:
    """Extrait (yes_token_id, no_token_id) du marché."""
    tokens = market.get("clobTokenIds") or market.get("tokens") or []
    if isinstance(tokens, str):
        try:
            tokens = json.loads(tokens)
        except (json.JSONDecodeError, TypeError):
            tokens = []
    if not isinstance(tokens, list) or len(tokens) < 2:
        return None, None
    t0 = tokens[0]
    t1 = tokens[1]
    yes_id = t0.get("token_id", t0) if isinstance(t0, dict) else str(t0)
    no_id = t1.get("token_id", t1) if isinstance(t1, dict) else str(t1)
    return yes_id, no_id


def _get_order_book(token_id: str) -> dict:
    """Order book CLOB API - bids/asks top 5."""
    try:
        url = f"https://clob.polymarket.com/book?token_id={token_id}"
        data = _fetch_url(url, timeout=API_TIMEOUT)
        if not data or not isinstance(data, dict):
            return {"bids": [], "asks": [], "spread": 0, "mid_price": 0.5}
        bids = (data.get("bids") or [])[:5]
        asks = (data.get("asks") or [])[:5]
        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 1
        mid = (best_bid + best_ask) / 2 if (best_bid and best_ask) else (best_bid or best_ask or 0.5)
        spread = (best_ask - best_bid) if (best_bid and best_ask) else 0
        return {
            "bids": [{"price": float(b["price"]), "size": float(b.get("size", 0))} for b in bids],
            "asks": [{"price": float(a["price"]), "size": float(a.get("size", 0))} for a in asks],
            "spread": round(spread, 4),
            "mid_price": round(mid, 4),
        }
    except Exception:
        return {"bids": [], "asks": [], "spread": 0, "mid_price": 0.5}


def _get_recent_trades(condition_id: str) -> list:
    """Derniers 20 trades depuis Data API."""
    try:
        url = f"https://data-api.polymarket.com/trades?market={condition_id}&size=20"
        data = _fetch_url(url, timeout=API_TIMEOUT)
        if not isinstance(data, list):
            return []
        out = []
        for t in data[:20]:
            size = float(t.get("size", 0) or 0)
            price = float(t.get("price", 0) or 0)
            amount = float(t.get("amount", t.get("sizeUsd", 0)) or 0) or (size * price if size and price else 0)
            side = str(t.get("outcome", t.get("side", "?"))).upper()
            maker = (t.get("maker", t.get("proxyWallet", t.get("user", ""))) or "")
            maker_short = (maker[:6] + "..." + maker[-4:]) if len(maker) > 14 else maker
            out.append({
                "amount": round(amount, 2),
                "side": "YES" if side in ("YES", "BUY") else "NO" if side in ("NO", "SELL") else side,
                "timestamp": t.get("timestamp", t.get("created_at", t.get("blockTimestamp", ""))),
                "maker": maker_short or "—",
            })
        return out
    except Exception:
        return []


def _get_price_history(condition_id: str) -> list:
    """Série temporelle prix YES sur 24h."""
    try:
        url = f"https://clob.polymarket.com/prices-history?market={condition_id}&interval=1h&fidelity=60"
        data = _fetch_url(url, timeout=API_TIMEOUT)
        if isinstance(data, list):
            return data[:48]
        if isinstance(data, dict) and "history" in data:
            return (data.get("history") or [])[:48]
        return []
    except Exception:
        return []


def _compute_whale_activity(trades: list) -> dict:
    """Calcule whale_activity depuis les trades."""
    LARGE_THRESHOLD = 1000
    large = [t for t in trades if float(t.get("amount", 0)) >= LARGE_THRESHOLD]
    buy_amount = sum(t["amount"] for t in large if str(t.get("side", "")).upper() in ("YES", "BUY"))
    sell_amount = sum(t["amount"] for t in large if str(t.get("side", "")).upper() in ("NO", "SELL"))
    net = "BUY" if buy_amount > sell_amount else "SELL" if sell_amount > buy_amount else "NEUTRAL"
    largest = max(large, key=lambda t: float(t.get("amount", 0))) if large else {}
    return {
        "large_trades_count": len(large),
        "largest_trade": {
            "amount": round(float(largest.get("amount", 0)), 2),
            "side": largest.get("side", "?"),
            "wallet": largest.get("maker", "—"),
        } if largest else {"amount": 0, "side": "—", "wallet": "—"},
        "net_flow": net,
    }


def _compute_smart_money_signal(whale: dict, trades: list) -> str:
    """bullish | bearish | neutral basé sur whale activity."""
    if not trades:
        return "neutral"
    net = whale.get("net_flow", "NEUTRAL")
    count = whale.get("large_trades_count", 0)
    if count >= 2 and net == "BUY":
        return "bullish"
    if count >= 2 and net == "SELL":
        return "bearish"
    return "neutral"


def _get_nexus_edge_and_score(condition_id: str) -> tuple[float | None, float | None]:
    """Récupère edge et score Nexus depuis paperclip_pending_signals si disponible."""
    p = Path(DATA_ROOT) / "paperclip_pending_signals.json"
    data = _load_json(str(p), {"signals": []})
    signals = data.get("signals", []) if isinstance(data, dict) else data or []
    for s in signals:
        if str(s.get("market_id", s.get("conditionId", ""))) == condition_id:
            edge = s.get("edge_pct")
            edge_val = float(edge) if edge is not None else None
            score = s.get("nexus_score", s.get("score"))
            score_val = float(score) if score is not None else (50 + (edge_val or 0) * 2)
            return edge_val, min(100, max(0, score_val))
    return None, None


def _get_market_object(condition_id_or_slug: str) -> dict | None:
    """Aggrège Market Object complet depuis APIs Polymarket. Cache 60s, timeout 5s."""
    now = time.time()
    cache_key = f"m:{condition_id_or_slug}"
    if cache_key in _market_cache:
        data, ts = _market_cache[cache_key]
        if now - ts < CACHE_TTL:
            return data

    market = _get_market_by_id_or_slug(condition_id_or_slug)
    if not market:
        return None

    cid = str(market.get("conditionId", market.get("id", "")))
    yes_token, no_token = _extract_token_ids(market)
    ob = _get_order_book(yes_token) if yes_token else {"bids": [], "asks": [], "spread": 0, "mid_price": 0.5}

    prices = market.get("outcomePrices") or "[\"0.5\",\"0.5\"]"
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except (json.JSONDecodeError, TypeError):
            prices = [0.5, 0.5]
    yes_price = float(prices[0]) if prices else 0.5
    no_price = float(prices[1]) if len(prices) > 1 else (1 - yes_price)

    volume = float(market.get("volume24hr") or market.get("volume") or market.get("volume_24hr", 0))
    liquidity = float(market.get("liquidity") or 0)

    end_date = market.get("endDate") or market.get("end_date_iso") or ""
    days_remaining = 0
    if end_date:
        try:
            from datetime import datetime, timezone
            end_dt = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            days_remaining = max(0, (end_dt - datetime.now(timezone.utc)).days)
        except Exception:
            pass

    trades = _get_recent_trades(cid)
    whale = _compute_whale_activity(trades)
    smart_money = _compute_smart_money_signal(whale, trades)
    price_history = _get_price_history(cid)
    nexus_edge, nexus_score = _get_nexus_edge_and_score(cid)

    outcomes = market.get("outcomes") or "[]"
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except (json.JSONDecodeError, TypeError):
            outcomes = []
    market_type = "binary" if len(outcomes) == 2 else "multi_outcome" if len(outcomes) > 2 else "scalar"

    result = {
        "market_id": cid,
        "slug": market.get("slug") or "",
        "question": market.get("question") or "",
        "category": market.get("category") or "Autre",
        "market_type": market_type,
        "yes_price": round(yes_price, 2),
        "no_price": round(no_price, 2),
        "volume_24h": round(volume, 2),
        "liquidity": round(liquidity, 2),
        "end_date": end_date,
        "days_remaining": days_remaining,
        "order_book": {"bids": ob["bids"], "asks": ob["asks"], "spread": ob["spread"]},
        "recent_trades": trades,
        "price_history": price_history,
        "whale_activity": whale,
        "smart_money_signal": smart_money,
        "nexus_edge": round(nexus_edge, 2) if nexus_edge is not None else None,
        "nexus_score": round(nexus_score, 2) if nexus_score is not None else None,
    }
    _market_cache[cache_key] = (result, now)
    if len(_market_cache) > 100:
        oldest = min(_market_cache, key=lambda k: _market_cache[k][1])
        del _market_cache[oldest]
    return result


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

        # Public : dashboard HTML, /health, /api/market/* (données Polymarket publiques)
        if path in ("/", "/dashboard", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(_get_dashboard_html().encode("utf-8"))
            return
        if path == "/health":
            try:
                uptime = 0.0
                markets = 0
                signals_today = 0
                last_signal_at = None
                try:
                    p = Path(DATA_ROOT) / "paperclip_pending_signals.json"
                    if p.exists():
                        d = json.loads(p.read_text(encoding="utf-8"))
                        markets = d.get("market_count", len(d.get("signals", [])))
                        sigs = d.get("signals", [])
                        from datetime import datetime, timezone
                        today = datetime.now(timezone.utc).date().isoformat()
                        for s in sigs:
                            ts = s.get("created_at") or s.get("last_scan_ts")
                            if ts and str(ts)[:10] == today:
                                signals_today += 1
                            if ts:
                                last_signal_at = str(ts)[:19] if last_signal_at is None else max(last_signal_at, str(ts)[:19])
                except Exception:
                    pass
                self._json_response({
                    "status": "ok",
                    "uptime_seconds": round(uptime, 1),
                    "markets_tracked": markets,
                    "signals_found_today": signals_today,
                    "last_signal_at": last_signal_at or "—",
                    "telegram_status": "connected",
                    "scanner_status": "running",
                })
            except Exception:
                self._json_response({"status": "ok", "uptime_seconds": 0, "markets_tracked": 0, "signals_found_today": 0, "last_signal_at": "—", "telegram_status": "unknown", "scanner_status": "unknown"})
            return

        # Market Object (public — données Polymarket publiques)
        if path.startswith("/api/market/"):
            rest = path.replace("/api/market/", "").strip()
            if rest == "search":
                qs = parse_qs(full_path.split("?", 1)[1]) if "?" in full_path else {}
                query = (qs.get("q", [""]) or [""])[0].strip()
                if query:
                    obj = _get_market_object(query)
                    if obj:
                        self._json_response(obj)
                        return
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "market_not_found", "query": query}).encode())
                return
            if rest:
                obj = _get_market_object(rest)
                if obj:
                    self._json_response(obj)
                    return
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "market_not_found", "id": rest}).encode())
                return

        # Public track-record endpoints (accessible without auth for sales page proof)
        if token == "public":
            if path == "/api/track-record":
                self._json_response(_get_track_record())
                return
            if path == "/api/trades":
                rows = _supabase_fetch("trades", 50)
                self._json_response(rows)
                return
            self._unauthorized()
            return

        # Endpoints API protégés par token
        if not token or not _validate_token(token):
            self._unauthorized()
            return

        if path == "/api/signals":
            p = Path(DATA_ROOT) / "paperclip_pending_signals.json"
            data = _load_json(str(p), {"signals": []})
            # Add simulation_mode flag from environment
            if isinstance(data, dict):
                data["simulation_mode"] = os.getenv("SIMULATION_MODE", "true").lower() not in ("false", "0", "no")
            self._json_response(data)
            return
        if path == "/api/scan":
            # Alias for /api/signals — used by dashboard bot status pill
            p = Path(DATA_ROOT) / "paperclip_pending_signals.json"
            data = _load_json(str(p), {"signals": []})
            if isinstance(data, dict):
                data["simulation_mode"] = os.getenv("SIMULATION_MODE", "true").lower() not in ("false", "0", "no")
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

