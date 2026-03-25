"""
NEXUS BET - Sniper Bot (pure math, no AI agents for signal detection).
Détecte 4 patterns en temps réel :
  1. Volume spike  (>3x moyenne 10min)
  2. Price momentum (>5% en 2min)
  3. Spread anomaly (>8% sur marché liquide)
  4. Whale entry   (>$10k en une transaction)

AI agents : post-trade analysis uniquement (rapports hebdomadaires).
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

log = logging.getLogger("nexus.sniper")

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"
SCAN_INTERVAL = 10          # secondes
HISTORY_WINDOW = 60         # nb de points conservés (~10min @ 10s)
VOLUME_SPIKE_MULTIPLIER = 3.0
MOMENTUM_THRESHOLD = 0.05   # 5%
MOMENTUM_WINDOW_POINTS = 12 # 2min / 10s = 12 points
SPREAD_THRESHOLD = 0.08     # 8%
WHALE_THRESHOLD_USD = 10_000


# ── Dataclass signal ──────────────────────────────────────────────────────────

@dataclass
class SniperSignal:
    market_id: str
    question: str
    token_id: str
    price: float
    signals: list[str]
    entry_price: float
    target_price: float   # +40%
    stop_price: float     # -25%
    confidence: float     # 0.25 – 1.0  (nb conditions / 4)
    timestamp: float = field(default_factory=time.time)


# ── Sniper ────────────────────────────────────────────────────────────────────

class PolymarketSniper:
    """Détecte des opportunités de trading par analyse mathématique pure."""

    def __init__(self) -> None:
        # token_id → deque de (timestamp, price)
        self.price_history: dict[str, deque] = {}
        # token_id → deque de (timestamp, volume)
        self.volume_history: dict[str, deque] = {}
        # token_id → entry_price (positions actives)
        self.active_positions: dict[str, float] = {}
        # token_id → timestamp dernière alerte (évite les doublons)
        self._last_alert: dict[str, float] = {}
        self._alert_cooldown = 120  # secondes entre deux alertes sur le même token

    # ── Historique ────────────────────────────────────────────────────────────

    def _update_history(self, token_id: str, price: float, volume: float = 0.0) -> None:
        now = time.time()
        if token_id not in self.price_history:
            self.price_history[token_id] = deque(maxlen=HISTORY_WINDOW)
            self.volume_history[token_id] = deque(maxlen=HISTORY_WINDOW)
        self.price_history[token_id].append((now, price))
        self.volume_history[token_id].append((now, volume))

    # ── Conditions mathématiques ──────────────────────────────────────────────

    def _volume_spike(self, token_id: str, multiplier: float = VOLUME_SPIKE_MULTIPLIER) -> bool:
        """Retourne True si le dernier volume > multiplier × moyenne historique."""
        history = self.volume_history.get(token_id)
        if not history or len(history) < 3:
            return False
        vols = [v for _, v in history]
        current = vols[-1]
        avg = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else 0
        return avg > 0 and current > avg * multiplier

    def _price_momentum(self, token_id: str, minutes: int = 2) -> float:
        """Retourne le % de variation de prix sur les `minutes` dernières minutes."""
        history = self.price_history.get(token_id)
        if not history or len(history) < 2:
            return 0.0
        now = time.time()
        cutoff = now - minutes * 60
        past_prices = [p for ts, p in history if ts >= cutoff]
        if len(past_prices) < 2:
            # Utilise les MOMENTUM_WINDOW_POINTS derniers points
            pts = list(history)
            if len(pts) < 2:
                return 0.0
            ref = pts[max(0, len(pts) - MOMENTUM_WINDOW_POINTS)][1]
            current = pts[-1][1]
        else:
            ref = past_prices[0]
            current = past_prices[-1]
        if ref <= 0:
            return 0.0
        return (current - ref) / ref

    def _calculate_spread(self, market: dict) -> float:
        """Estime le spread bid-ask depuis les outcomePrices YES/NO."""
        try:
            prices = market.get("outcomePrices") or []
            if isinstance(prices, str):
                import json
                prices = json.loads(prices)
            if len(prices) >= 2:
                yes = float(prices[0])
                no = float(prices[1])
                # YES + NO devrait ≈ 1.0 ; l'écart par rapport à 1.0 est le spread implicite
                return abs(1.0 - (yes + no))
        except (ValueError, TypeError, IndexError):
            pass
        return 0.0

    async def _detect_whale_entry(self, token_id: str) -> Optional[dict]:
        """
        Interroge /data/trades sur le CLOB pour détecter une transaction > WHALE_THRESHOLD_USD.
        Retourne {"size": float} si une whale est détectée, None sinon.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(
                    f"{CLOB_URL}/data/trades",
                    params={"token_id": token_id, "limit": "20"},
                )
                if r.status_code != 200:
                    return None
                trades = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
            now = time.time()
            for trade in trades or []:
                ts = float(trade.get("timestamp") or trade.get("created_at") or 0)
                # Ne considère que les trades des 2 dernières minutes
                if ts and now - ts > 120:
                    continue
                price = float(trade.get("price") or 0)
                size = float(trade.get("size") or trade.get("amount") or 0)
                size_usd = size * price if price > 0 else size
                if size_usd >= WHALE_THRESHOLD_USD:
                    log.info("Whale detected: token=%s size_usd=$%.0f", token_id[:16], size_usd)
                    return {"size": size_usd}
        except Exception as e:
            log.debug("_detect_whale_entry(%s): %s", token_id[:16], e)
        return None

    # ── Analyse d'un marché ───────────────────────────────────────────────────

    async def monitor_market(self, market: dict) -> Optional[SniperSignal]:
        """Analyse un marché et retourne un SniperSignal si ≥1 condition est remplie."""
        try:
            # Extraction du token YES
            tokens = market.get("clobTokenIds") or market.get("tokens") or []
            if isinstance(tokens, str):
                import json
                try:
                    tokens = json.loads(tokens)
                except Exception:
                    tokens = []
            if not tokens:
                return None
            yes_token = tokens[0]
            token_id: str = (
                yes_token.get("token_id") if isinstance(yes_token, dict) else str(yes_token)
            )
            if not token_id:
                return None

            prices = market.get("outcomePrices") or ["0.5"]
            if isinstance(prices, str):
                import json
                try:
                    prices = json.loads(prices)
                except Exception:
                    prices = ["0.5"]
            price = float(prices[0]) if prices else 0.5
            volume = float(market.get("volume24hr") or market.get("volume") or 0)

            self._update_history(token_id, price, volume)

            # Cooldown : on n'alerte pas deux fois en moins de 2min sur le même token
            if time.time() - self._last_alert.get(token_id, 0) < self._alert_cooldown:
                return None

            signals: list[str] = []

            # 1. Volume spike
            if self._volume_spike(token_id):
                signals.append("VOLUME_SPIKE")

            # 2. Price momentum
            momentum = self._price_momentum(token_id, minutes=2)
            if abs(momentum) > MOMENTUM_THRESHOLD:
                sign = "+" if momentum > 0 else "-"
                signals.append(f"MOMENTUM_{sign}{abs(momentum) * 100:.1f}%")

            # 3. Spread anomaly (uniquement marchés liquides)
            liquidity = float(market.get("liquidity") or market.get("liquidityNum") or 0)
            if liquidity > 10_000:
                spread = self._calculate_spread(market)
                if spread > SPREAD_THRESHOLD:
                    signals.append(f"SPREAD_{spread * 100:.1f}%")

            # 4. Whale entry
            whale = await self._detect_whale_entry(token_id)
            if whale:
                signals.append(f"WHALE_${whale['size']:,.0f}")

            if not signals:
                return None

            self._last_alert[token_id] = time.time()
            market_id = str(market.get("conditionId") or market.get("id") or token_id)
            question = html.escape(str(market.get("question") or market_id)[:80])

            return SniperSignal(
                market_id=market_id,
                question=question,
                token_id=token_id,
                price=price,
                signals=signals,
                entry_price=price,
                target_price=round(price * 1.40, 4),
                stop_price=round(price * 0.75, 4),
                confidence=round(len(signals) / 4, 2),
            )
        except Exception as e:
            log.debug("monitor_market error: %s", e)
            return None

    # ── Fetch marchés ─────────────────────────────────────────────────────────

    async def _fetch_markets(self) -> list[dict[str, Any]]:
        """Récupère les marchés actifs depuis Gamma API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(
                    f"{GAMMA_URL}/markets",
                    params={
                        "limit": 200,
                        "active": "true",
                        "closed": "false",
                        "archived": "false",
                        "order": "volume24hr",
                        "ascending": "false",
                    },
                )
                r.raise_for_status()
                data = r.json()
                return data if isinstance(data, list) else data.get("data", []) or []
        except Exception as e:
            log.warning("_fetch_markets: %s", e)
            return []

    # ── Signal detected ───────────────────────────────────────────────────────

    async def _on_signal_detected(self, signal: SniperSignal) -> None:
        """AUTO_SNIPE=true → exécute l'ordre PUIS notifie.
           AUTO_SNIPE=false → push alerte avec bouton SNIPE."""
        auto_snipe = os.getenv("AUTO_SNIPE", "false").lower() == "true"
        if auto_snipe:
            # 1. Exécuter immédiatement
            order_id = await self._execute_entry(signal)
            # 2. Notifier "exécuté"
            try:
                from monitoring.push_alerts import push_auto_snipe_notification
                await push_auto_snipe_notification(signal, order_id)
            except Exception as e:
                log.error("push_auto_snipe_notification failed: %s", e)
        else:
            # Envoyer l'alerte avec bouton SNIPE / PASS
            try:
                from monitoring.push_alerts import push_sniper_alert
                await push_sniper_alert(signal)
            except Exception as e:
                log.error("push_sniper_alert failed: %s", e)

    async def _execute_entry(self, signal: SniperSignal) -> str | None:
        """Exécute l'entrée automatique (AUTO_SNIPE=true). Retourne order_id ou None."""
        try:
            from config.settings import settings as _s
            from execution.order_manager import OrderManager, OrderConfig
            cap = getattr(_s, "POLYMARKET_CAPITAL_USD", 1000.0)
            size_usd = round(cap * signal.confidence * 0.10, 1)  # max 10% × confidence
            size_usd = max(1.0, size_usd)
            om = OrderManager()
            cfg = OrderConfig(
                market_id=signal.market_id,
                outcome="YES",
                side="BUY",
                size_usd=size_usd,
                limit_price=signal.entry_price,
                take_profit_pct=0.40,
                stop_loss_pct=0.25,
            )
            order_id = await om.place_limit_order(cfg)
            if order_id:
                self.active_positions[signal.token_id] = signal.entry_price
                log.info("AUTO_SNIPE order placed: %s size=$%.0f", order_id, size_usd)
            else:
                log.warning("AUTO_SNIPE: order failed for %s", signal.market_id[:20])
            return order_id
        except Exception as e:
            log.error("_execute_entry: %s", e)
            return None

    # ── Boucle principale ─────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Boucle principale du sniper — scan toutes les 10 secondes."""
        log.info("🎯 Sniper started — scanning every %ds | VOLUME_SPIKE x%.0f | MOMENTUM >%.0f%% | SPREAD >%.0f%% | WHALE >$%.0f",
                 SCAN_INTERVAL, VOLUME_SPIKE_MULTIPLIER, MOMENTUM_THRESHOLD * 100,
                 SPREAD_THRESHOLD * 100, WHALE_THRESHOLD_USD)
        while True:
            try:
                markets = await self._fetch_markets()
                if not markets:
                    log.debug("Sniper: no markets returned")
                else:
                    tasks = [self.monitor_market(m) for m in markets]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    fired = 0
                    for result in results:
                        if isinstance(result, SniperSignal):
                            await self._on_signal_detected(result)
                            fired += 1
                    if fired:
                        log.info("Sniper: %d signal(s) fired on %d markets", fired, len(markets))
                    else:
                        log.debug("Sniper: 0 signals on %d markets", len(markets))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("Sniper loop error: %s", e)
            await asyncio.sleep(SCAN_INTERVAL)
