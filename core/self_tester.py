"""
NEXUS BET - Self-Tester
Simule 10 signaux aléatoires sur données réelles et compare vs performance passée.
Détecte les dérives de stratégie avant qu'elles coûtent de l'argent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("nexus.self_tester")

_ROOT = Path(__file__).resolve().parent.parent
GAMMA_URL = "https://gamma-api.polymarket.com"
N_SIGNALS = 10


# ── Fetch marchés actifs ───────────────────────────────────────────────────────

async def _fetch_active_markets(n: int = 50) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f"{GAMMA_URL}/markets",
                params={"active": "true", "closed": "false", "limit": str(n),
                        "order": "volume24hr", "ascending": "false"},
            )
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else data.get("data", []) or []
    except Exception as e:
        log.debug("_fetch_active_markets: %s", e)
    return []


# ── Simuler un signal sur un marché ──────────────────────────────────────────

def _simulate_signal(market: dict, strategy_cfg: dict) -> dict | None:
    """
    Applique la stratégie courante à un marché et retourne un signal simulé ou None.
    """
    try:
        prices_raw = market.get("outcomePrices")
        if isinstance(prices_raw, str):
            prices_raw = json.loads(prices_raw)
        if not isinstance(prices_raw, list) or len(prices_raw) < 2:
            return None
        yes_price = float(prices_raw[0])
        no_price  = float(prices_raw[1])
        if yes_price <= 0.01 or yes_price >= 0.99:
            return None

        # Applique les seuils de stratégie
        min_edge   = strategy_cfg.get("MIN_EDGE_THRESHOLD", 5.0)
        # Calcul de l'edge : écart entre fair value implicite et prix de marché
        # Pour un marché binaire : fair value = 0.5 (si 50/50), edge = abs(price - 0.5)
        implied_edge = abs(yes_price - 0.5) * 200  # % edge
        if implied_edge < min_edge:
            return None

        side = "YES" if yes_price < 0.5 else "NO"
        price = yes_price if side == "YES" else no_price

        return {
            "market_id": market.get("conditionId") or market.get("id") or "",
            "question": (market.get("question") or "")[:60],
            "side": side,
            "entry_price": price,
            "edge_pct": round(implied_edge, 2),
            "simulated": True,
        }
    except Exception:
        return None


# ── Calcule le P&L attendu ────────────────────────────────────────────────────

def _expected_pnl(signals: list[dict], win_rate: float, avg_return: float) -> float:
    """P&L attendu sur N signaux avec le taux de gain et retour moyen."""
    n = len(signals)
    if n == 0:
        return 0.0
    wins   = n * (win_rate / 100)
    losses = n - wins
    avg_loss = 0.025  # SL ~2.5%
    per_trade_capital = 10.0  # $10/signal (paper)
    return round(wins * per_trade_capital * (avg_return / 100) - losses * per_trade_capital * avg_loss, 2)


# ── Self-test principal ────────────────────────────────────────────────────────

async def run_selftest() -> dict[str, Any]:
    """
    Lance le self-test :
    1. Fetch N marchés actifs aléatoires
    2. Applique la stratégie courante
    3. Calcule P&L attendu
    4. Compare vs performance paper réelle
    Retourne un dict avec métriques et status.
    """
    started = time.time()

    # Charger la config optimiseur
    cfg_file = _ROOT / "logs" / "optimizer_config.json"
    strategy_cfg: dict = {}
    if cfg_file.exists():
        try:
            strategy_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Récupérer la performance réelle depuis paper portfolio
    actual_win_rate = 0.0
    actual_avg_return = 15.0
    try:
        from monitoring.paper_portfolio import get_paper_summary
        pp = get_paper_summary()
        actual_win_rate   = float(pp.get("win_rate") or 0)
        closed = pp.get("closed_trades") or []
        if closed:
            returns = [float(t.get("pnl_pct") or 0) for t in closed if float(t.get("pnl_pct") or 0) > 0]
            actual_avg_return = round(sum(returns) / len(returns), 1) if returns else 15.0
    except Exception:
        pass

    # Fetch marchés
    all_markets = await _fetch_active_markets(50)
    if not all_markets:
        return {"error": "Impossible de récupérer les marchés Polymarket", "duration_s": 0}

    # Sélectionner 10 marchés aléatoires
    sample = random.sample(all_markets, min(N_SIGNALS, len(all_markets)))

    # Simuler les signaux
    signals = [sig for m in sample if (sig := _simulate_signal(m, strategy_cfg)) is not None]

    # P&L attendu avec les paramètres de stratégie actuels
    expected = _expected_pnl(signals, actual_win_rate or 50.0, actual_avg_return)

    # Détecter une dérive : si la stratégie simule trop peu ou trop de signaux
    hit_rate = len(signals) / len(sample) * 100
    drift_flag = ""
    if hit_rate < 10:
        drift_flag = "⚠️ Seuils trop élevés — peu de signaux générés"
    elif hit_rate > 80:
        drift_flag = "⚠️ Seuils trop bas — trop de signaux (risque overtrading)"

    duration = round(time.time() - started, 1)
    return {
        "markets_tested": len(sample),
        "signals_generated": len(signals),
        "hit_rate_pct": round(hit_rate, 1),
        "expected_pnl_usd": expected,
        "actual_win_rate": actual_win_rate,
        "actual_avg_return": actual_avg_return,
        "drift_flag": drift_flag,
        "duration_s": duration,
        "top_signals": signals[:3],
        "strategy_cfg": {k: strategy_cfg.get(k) for k in
                         ("MOMENTUM_THRESHOLD", "VOLUME_SPIKE_MULTIPLIER",
                          "SPREAD_THRESHOLD", "WHALE_THRESHOLD_USD") if k in strategy_cfg},
    }


def selftest_to_telegram(result: dict) -> str:
    """Formate le résultat du self-test pour Telegram."""
    L = "━━━━━━━━━━━━━━━"
    if "error" in result:
        return f"🧪 <b>SELF-TEST</b>\n{L}\n<code>❌ {result['error']}</code>"

    drift = result.get("drift_flag", "")
    drift_line = f"\n{drift}" if drift else "\n✅ Stratégie dans les paramètres normaux"

    top_sigs = ""
    for s in result.get("top_signals", []):
        q = (s.get("question") or "?")[:38]
        top_sigs += f"  • {q}\n    {s['side']} edge {s['edge_pct']:+.1f}%\n"

    return (
        f"🧪 <b>SELF-TEST TERMINÉ</b>\n{L}\n"
        f"<code>"
        f"🎯 Marchés testés  {result['markets_tested']}\n"
        f"⚡ Signaux générés {result['signals_generated']}\n"
        f"📊 Hit rate        {result['hit_rate_pct']:.0f}%\n"
        f"💰 P&L attendu     ${result['expected_pnl_usd']:+.2f}\n"
        f"📈 Win rate réel   {str(int(result['actual_win_rate'])) + '%' if result['actual_win_rate'] > 0 else 'N/A'}\n"
        f"⏱️ Durée           {result['duration_s']}s"
        f"</code>\n{drift_line}\n"
        + (f"{L}\n<i>Top signaux :\n{top_sigs}</i>" if top_sigs else "")
    )


# ── Boucle horaire ────────────────────────────────────────────────────────────

async def run_self_tester_loop() -> None:
    """Boucle horaire : self-test automatique, log résultats."""
    log.info("Self-tester démarré — test automatique toutes les heures")
    await asyncio.sleep(120)  # 2min après démarrage
    while True:
        try:
            result = await run_selftest()
            log.info(
                "Self-test: %d signaux / %d marchés | hit=%.0f%% | P&L attendu $%.2f%s",
                result.get("signals_generated", 0),
                result.get("markets_tested", 0),
                result.get("hit_rate_pct", 0),
                result.get("expected_pnl_usd", 0),
                f" | DRIFT: {result['drift_flag']}" if result.get("drift_flag") else "",
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Self-tester error: %s", e)
        await asyncio.sleep(3600)  # 1h
