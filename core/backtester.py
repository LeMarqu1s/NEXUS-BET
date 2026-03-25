"""
NEXUS BET - Backtester
Rejoue les conditions sniper sur l'historique des prix Polymarket
et calcule les stats : win rate, return moyen, Sharpe, meilleur/pire trade.

Endpoint CLOB : GET /prices-history?market={token_id}&fidelity=1
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

log = logging.getLogger("nexus.backtester")

CLOB_URL   = "https://clob.polymarket.com"
GAMMA_URL  = "https://gamma-api.polymarket.com"
TP_PCT     = 0.40   # +40%
SL_PCT     = 0.25   # -25%
MOMENTUM_THRESHOLD = 0.05
VOLUME_MULTIPLIER  = 3.0


# ── Résultat d'un trade simulé ────────────────────────────────────────────────

@dataclass
class SimTrade:
    entry_price: float
    exit_price: float
    pnl_pct: float           # % de retour sur le trade
    hold_minutes: int
    exit_reason: str         # "TP", "SL", "END"
    signals: list[str] = field(default_factory=list)


@dataclass
class BacktestResult:
    market_id: str
    question: str
    days: int
    total_signals: int
    trades: list[SimTrade]

    @property
    def win_rate(self) -> float:
        wins = sum(1 for t in self.trades if t.pnl_pct > 0)
        return (wins / len(self.trades) * 100) if self.trades else 0.0

    @property
    def avg_return(self) -> float:
        return (sum(t.pnl_pct for t in self.trades) / len(self.trades)) if self.trades else 0.0

    @property
    def avg_hold_minutes(self) -> float:
        return (sum(t.hold_minutes for t in self.trades) / len(self.trades)) if self.trades else 0.0

    @property
    def best_trade(self) -> Optional[SimTrade]:
        return max(self.trades, key=lambda t: t.pnl_pct) if self.trades else None

    @property
    def worst_trade(self) -> Optional[SimTrade]:
        return min(self.trades, key=lambda t: t.pnl_pct) if self.trades else None

    @property
    def sharpe(self) -> float:
        """Sharpe annualisé simplifié (returns quotidiens)."""
        if len(self.trades) < 2:
            return 0.0
        returns = [t.pnl_pct for t in self.trades]
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        std = math.sqrt(variance)
        return (mean / std * math.sqrt(252)) if std > 0 else 0.0

    def to_telegram(self) -> str:
        """Formate le résultat pour Telegram (HTML)."""
        import html
        L = "━━━━━━━━━━━━━━━"
        safe_q = html.escape(self.question[:55])
        if not self.trades:
            return (
                f"<b>📊 BACKTEST</b>\n{L}\n"
                f"<b>{safe_q}</b>\n\n"
                f"<code>Aucun signal détecté sur {self.days}j\n"
                f"({self.total_signals} candles analysées)</code>"
            )
        best  = self.best_trade
        worst = self.worst_trade
        avg_ret_sign = "+" if self.avg_return >= 0 else ""
        return (
            f"<b>📊 BACKTEST — {self.days}j</b>\n{L}\n"
            f"<b>{safe_q}</b>\n\n"
            f"<code>"
            f"TRADES     {len(self.trades)}\n"
            f"WIN RATE   {self.win_rate:.0f}%\n"
            f"AVG RETURN {avg_ret_sign}{self.avg_return:.1f}%\n"
            f"AVG HOLD   {self.avg_hold_minutes:.0f} min\n"
            f"SHARPE     {self.sharpe:.2f}\n"
            f"BEST       +{best.pnl_pct:.1f}%\n"
            f"WORST      {worst.pnl_pct:.1f}%"
            f"</code>\n{L}\n"
            f"<i>Candles : {self.total_signals} | TP +{TP_PCT*100:.0f}% | SL -{SL_PCT*100:.0f}%</i>"
        )


# ── Fetchers ─────────────────────────────────────────────────────────────────

async def _find_token_id(market_slug: str) -> tuple[str, str, str]:
    """
    Cherche un marché par slug/ID/question partielle.
    Retourne (market_id, token_id, question).
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            # Essai direct par conditionId
            r = await c.get(f"{GAMMA_URL}/markets/{market_slug}")
            if r.status_code == 200:
                m = r.json()
                if isinstance(m, list):
                    m = m[0]
                q = str(m.get("question") or market_slug)
                tokens = m.get("clobTokenIds") or m.get("tokens") or []
                if isinstance(tokens, str):
                    import json
                    tokens = json.loads(tokens)
                yes_tok = tokens[0] if tokens else {}
                tok_id = (yes_tok.get("token_id") if isinstance(yes_tok, dict) else str(yes_tok)) or ""
                return market_slug, tok_id, q

            # Recherche textuelle
            r2 = await c.get(
                f"{GAMMA_URL}/markets",
                params={"limit": 5, "q": market_slug, "active": "true"},
            )
            if r2.status_code == 200:
                data = r2.json()
                markets = data if isinstance(data, list) else data.get("data", [])
                if markets:
                    m = markets[0]
                    mid = str(m.get("conditionId") or m.get("id") or "")
                    q = str(m.get("question") or market_slug)
                    tokens = m.get("clobTokenIds") or m.get("tokens") or []
                    if isinstance(tokens, str):
                        import json
                        tokens = json.loads(tokens)
                    yes_tok = tokens[0] if tokens else {}
                    tok_id = (yes_tok.get("token_id") if isinstance(yes_tok, dict) else str(yes_tok)) or ""
                    return mid, tok_id, q
    except Exception as e:
        log.warning("_find_token_id(%s): %s", market_slug, e)
    return market_slug, "", market_slug


async def _fetch_price_history(token_id: str, days: int) -> list[dict[str, Any]]:
    """
    Récupère l'historique de prix depuis le CLOB Polymarket.
    GET /prices-history?market={token_id}&fidelity=1
    Retourne une liste de {"t": timestamp, "p": price}.
    """
    if not token_id:
        return []
    try:
        # fidelity=1 = candles 1 minute
        start_ts = int(time.time()) - days * 86400
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(
                f"{CLOB_URL}/prices-history",
                params={"market": token_id, "fidelity": "1", "startTs": str(start_ts)},
            )
            if r.status_code == 200:
                data = r.json()
                history = data.get("history") or data if isinstance(data, list) else []
                return history
    except Exception as e:
        log.warning("_fetch_price_history(%s): %s", token_id[:16], e)
    return []


# ── Détection des signaux sur candles historiques ─────────────────────────────

def _detect_signals(prices: list[float], idx: int) -> list[str]:
    """Applique les conditions sniper sur une fenêtre glissante à l'index idx."""
    signals = []
    window = 12   # 12 candles = 2min @ 1m
    history = 60  # 60 candles = 10min @ 1m

    if idx < max(window, 3):
        return signals

    current = prices[idx]
    prev_window = prices[max(0, idx - window):idx]
    prev_history = prices[max(0, idx - history):idx]

    # 1. Momentum (>5% sur les 2 dernières minutes)
    if prev_window:
        ref = prev_window[0]
        if ref > 0:
            momentum = (current - ref) / ref
            if abs(momentum) > MOMENTUM_THRESHOLD:
                sign = "+" if momentum > 0 else "-"
                signals.append(f"MOMENTUM_{sign}{abs(momentum)*100:.1f}%")

    # 2. Volume spike : simulé via volatilité (écart absolu > 3× la moyenne)
    if len(prev_history) >= 3:
        diffs = [abs(prev_history[i] - prev_history[i-1]) for i in range(1, len(prev_history))]
        if diffs:
            avg_diff = sum(diffs) / len(diffs)
            cur_diff = abs(current - prices[idx - 1]) if idx >= 1 else 0
            if avg_diff > 0 and cur_diff > VOLUME_MULTIPLIER * avg_diff:
                signals.append("VOLUME_SPIKE")

    return signals


# ── Simulation ────────────────────────────────────────────────────────────────

def _simulate_trade(prices: list[float], entry_idx: int, signals: list[str]) -> SimTrade:
    """
    Simule un trade depuis entry_idx jusqu'au TP, SL ou fin des données.
    Retourne un SimTrade.
    """
    entry_price = prices[entry_idx]
    tp_price = entry_price * (1 + TP_PCT)
    sl_price = entry_price * (1 - SL_PCT)

    for i in range(entry_idx + 1, len(prices)):
        p = prices[i]
        hold = i - entry_idx
        if p >= tp_price:
            return SimTrade(entry_price, p, TP_PCT * 100, hold, "TP", signals)
        if p <= sl_price:
            return SimTrade(entry_price, p, -SL_PCT * 100, hold, "SL", signals)

    # Fin des données → exit au dernier prix connu
    last = prices[-1]
    pnl = (last - entry_price) / entry_price * 100 if entry_price > 0 else 0
    return SimTrade(entry_price, last, pnl, len(prices) - entry_idx - 1, "END", signals)


# ── Point d'entrée public ─────────────────────────────────────────────────────

async def run_backtest(market_slug: str, days: int = 7) -> BacktestResult:
    """
    Lance le backtest complet sur un marché Polymarket.
    market_slug : conditionId, ID ou mot-clé de recherche.
    days        : nombre de jours d'historique (défaut 7).
    """
    days = max(1, min(days, 30))  # cap à 30 jours
    market_id, token_id, question = await _find_token_id(market_slug)

    if not token_id:
        return BacktestResult(market_id, question, days, 0, [])

    raw = await _fetch_price_history(token_id, days)
    if not raw:
        return BacktestResult(market_id, question, days, 0, [])

    # Extrait les prix dans l'ordre chronologique
    try:
        sorted_raw = sorted(raw, key=lambda c: c.get("t") or c.get("ts") or 0)
        prices = [float(c.get("p") or c.get("price") or 0) for c in sorted_raw]
        prices = [p for p in prices if 0 < p <= 1.0]
    except Exception as e:
        log.warning("run_backtest price parse: %s", e)
        return BacktestResult(market_id, question, days, 0, [])

    trades: list[SimTrade] = []
    in_trade = False
    exit_idx = 0

    for i in range(len(prices)):
        if in_trade and i <= exit_idx:
            continue
        in_trade = False

        signals = _detect_signals(prices, i)
        if signals:
            trade = _simulate_trade(prices, i, signals)
            trades.append(trade)
            in_trade = True
            exit_idx = i + trade.hold_minutes  # ne re-entre pas avant la fin du trade

    return BacktestResult(
        market_id=market_id,
        question=question,
        days=days,
        total_signals=len(prices),
        trades=trades,
    )
