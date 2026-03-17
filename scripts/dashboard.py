#!/usr/bin/env python3
"""
NEXUS BET - Dashboard localhost
Affiche les signaux Polymarket via Gamma + CLOB API (httpx uniquement, pas de py_clob_client).
Usage: python scripts/dashboard.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from aiohttp import web

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"


async def fetch_markets(limit: int = 50) -> list[dict]:
    """Fetch markets from Gamma API (no auth)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{GAMMA_URL}/markets",
            params={"limit": limit, "active": "true", "closed": "false"},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("data", []) or []


async def fetch_order_book(token_id: str) -> dict | None:
    """Fetch order book from CLOB API (no auth)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{CLOB_URL}/book", params={"token_id": token_id})
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None


def _parse_json_field(val: str | list) -> list:
    """Parse clobTokenIds or outcomePrices JSON string."""
    if isinstance(val, list):
        return val
    if not val:
        return []
    try:
        out = json.loads(val)
        return out if isinstance(out, list) else []
    except Exception:
        return []


async def fetch_scan_data(limit: int = 30) -> dict:
    """Fetch markets + order books, compute signals (no py_clob_client)."""
    markets = await fetch_markets(limit=min(limit, 20))
    signals: list[dict] = []

    for market in markets[:20]:
        try:
            token_ids = _parse_json_field(market.get("clobTokenIds") or "[]")
            prices = _parse_json_field(market.get("outcomePrices") or "[]")
            if len(token_ids) < 2 or len(prices) < 2:
                continue

            question = (market.get("question") or "")[:80]
            market_id = str(market.get("conditionId", market.get("id", ""))) or ""

            obs = await asyncio.gather(
                fetch_order_book(token_ids[0]),
                fetch_order_book(token_ids[1]),
            )

            for i, (token_id, side) in enumerate([(token_ids[0], "YES"), (token_ids[1], "NO")]):
                if i >= len(prices):
                    continue
                try:
                    price_val = float(prices[i])
                except (TypeError, ValueError):
                    continue
                if price_val <= 0 or price_val >= 1:
                    continue

                ob = obs[i] if i < len(obs) else None
                if not ob:
                    signals.append({
                        "market_id": market_id,
                        "question": question,
                        "side": side,
                        "polymarket_price": price_val,
                        "edge_pct": 0,
                        "kelly_fraction": 0,
                        "model": "gamma",
                        "confidence": 0.5,
                    })
                    continue

                bids = ob.get("bids", []) or []
                asks = ob.get("asks", []) or []
                best_bid = float(bids[0]["price"]) if bids else price_val
                best_ask = float(asks[0]["price"]) if asks else price_val
                mid = (best_bid + best_ask) / 2 if (bids and asks) else price_val

                confidence = 0.5 + 0.2 * min(1.0, (len(bids) + len(asks)) / 10)
                if side == "YES":
                    edge_pct = (mid - price_val) / price_val if price_val > 0 else 0
                else:
                    mid_no = 1.0 - mid
                    pm_no = 1.0 - price_val
                    edge_pct = (mid_no - pm_no) / pm_no if pm_no > 0 else 0

                edge_pct = round(edge_pct * 100, 2)
                min_edge = 2.0
                if edge_pct < min_edge or confidence < 0.6:
                    continue

                b = (1.0 - price_val) / price_val if price_val > 0 else 1.0
                p = mid if side == "YES" else (1.0 - mid)
                kelly = max(0, min(0.25, (b * p - (1 - p)) / b)) if b > 0 else 0

                signals.append({
                    "market_id": market_id,
                    "question": question,
                    "side": side,
                    "polymarket_price": price_val,
                    "edge_pct": edge_pct,
                    "kelly_fraction": round(kelly, 4),
                    "model": "ncaa",
                    "confidence": round(confidence, 2),
                })
        except Exception:
            pass

    return {"signals": signals, "count": len(signals)}


async def api_scan(request: web.Request) -> web.Response:
    """GET /api/scan - retourne les données du scanner en JSON."""
    limit = int(request.query.get("limit", 30))
    data = await fetch_scan_data(limit=limit)
    return web.json_response(data)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>NEXUS BET - Scanner Polymarket</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; padding: 1.5rem; }
        header { margin-bottom: 1.5rem; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 1rem; }
        h1 { font-size: 1.5rem; font-weight: 600; }
        .badge { background: #334155; padding: 0.25rem 0.5rem; border-radius: 6px; font-size: 0.875rem; }
        button { background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 8px; cursor: pointer; font-weight: 500; }
        button:hover { background: #2563eb; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        .signals { display: grid; gap: 0.75rem; }
        .card { background: #1e293b; border-radius: 10px; padding: 1rem; border: 1px solid #334155; }
        .card .question { font-weight: 500; margin-bottom: 0.5rem; color: #f1f5f9; }
        .card .meta { display: flex; flex-wrap: wrap; gap: 0.75rem; font-size: 0.8125rem; color: #94a3b8; }
        .edge { color: #22c55e; font-weight: 600; }
        .no-signals { text-align: center; padding: 3rem; color: #64748b; }
        .error { color: #ef4444; background: #7f1d1d30; padding: 1rem; border-radius: 8px; margin-bottom: 1rem; }
    </style>
</head>
<body>
    <header>
        <h1>NEXUS BET - Scanner Polymarket</h1>
        <div style="display: flex; gap: 0.5rem; align-items: center;">
            <span class="badge" id="count">0 signaux</span>
            <button id="refresh" onclick="refresh()">Actualiser</button>
        </div>
    </header>
    <div id="error" class="error" style="display:none;"></div>
    <div id="signals" class="signals">
        <div class="no-signals">Chargement...</div>
    </div>
    <script>
        async function refresh() {
            const btn = document.getElementById('refresh');
            btn.disabled = true;
            document.getElementById('error').style.display = 'none';
            document.getElementById('signals').innerHTML = '<div class="no-signals">Chargement...</div>';
            try {
                const r = await fetch('/api/scan');
                const data = await r.json();
                if (!r.ok) throw new Error(data.message || 'Erreur API');
                render(data);
            } catch (e) {
                document.getElementById('error').textContent = e.message;
                document.getElementById('error').style.display = 'block';
                document.getElementById('signals').innerHTML = '<div class="no-signals">Erreur lors du chargement</div>';
            }
            btn.disabled = false;
        }
        function render(data) {
            const signals = data.signals || [];
            document.getElementById('count').textContent = signals.length + ' signaux';
            if (signals.length === 0) {
                document.getElementById('signals').innerHTML = '<div class="no-signals">Aucun signal détecté (edge &lt; 2%)</div>';
                return;
            }
            document.getElementById('signals').innerHTML = signals.map(s => `
                <div class="card">
                    <div class="question">${escapeHtml(s.question || s.market_id)}</div>
                    <div class="meta">
                        <span class="edge">Edge: ${s.edge_pct}%</span>
                        <span>${s.side}</span>
                        <span>Confiance: ${(s.confidence * 100).toFixed(0)}%</span>
                        <span>Kelly: ${(s.kelly_fraction * 100).toFixed(2)}%</span>
                        <span>Prix: ${(s.polymarket_price * 100).toFixed(1)}%</span>
                        <span>${s.model || ''}</span>
                    </div>
                </div>
            `).join('');
        }
        function escapeHtml(s) {
            const div = document.createElement('div');
            div.textContent = s || '';
            return div.innerHTML;
        }
        refresh();
        setInterval(refresh, 30000);
    </script>
</body>
</html>
"""


async def index(request: web.Request) -> web.Response:
    """GET / - dashboard HTML."""
    return web.Response(text=HTML_TEMPLATE, content_type="text/html")


async def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/scan", api_scan)
    return app


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = loop.run_until_complete(create_app())
    print("NEXUS BET Dashboard: http://127.0.0.1:8080")
    web.run_app(app, host="127.0.0.1", port=8080, print=lambda _: None)


if __name__ == "__main__":
    main()
