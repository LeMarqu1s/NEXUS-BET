"""
NEXUS BET - Scalper
Scanner dédié aux marchés "Up or Down" (BTC/ETH) sur fenêtres < 30 minutes.
Suivi de position toutes les 60s avec alerte TP/SL.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("nexus.scalper")

GAMMA_URL      = "https://gamma-api.polymarket.com"
CLOB_URL       = "https://clob.polymarket.com"
SCAN_INTERVAL  = 30   # secondes entre chaque scan
MONITOR_INTERVAL = 60 # secondes entre chaque check de position
MAX_RESOLUTION_MINUTES = 30

SETTINGS_FILE  = Path(__file__).resolve().parent.parent / "scalp_settings.json"
DEFAULT_TP     = 0.20   # +20%
DEFAULT_SL     = 0.15   # -15%


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ScalpSignal:
    market_id:        str
    question:         str
    token_id_yes:     str
    token_id_no:      str
    yes_price:        float
    no_price:         float
    minutes_remaining: float
    end_ts:           float


@dataclass
class ScalpPosition:
    market_id:   str
    question:    str
    token_id:    str
    side:        str          # "YES" or "NO"
    entry_price: float
    tp_price:    float
    sl_price:    float
    size_usd:    float
    chat_ids:    list[str]
    opened_at:   float = field(default_factory=time.time)
    alerted:     bool  = False


# ── Settings TP/SL ────────────────────────────────────────────────────────────

def load_scalp_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"tp": DEFAULT_TP, "sl": DEFAULT_SL}


def save_scalp_settings(tp: float, sl: float) -> None:
    SETTINGS_FILE.write_text(
        json.dumps({"tp": tp, "sl": sl}, indent=2),
        encoding="utf-8",
    )


# ── Scalper ───────────────────────────────────────────────────────────────────

class ScalperTracker:
    def __init__(self) -> None:
        self.positions: dict[str, ScalpPosition] = {}   # token_id → position
        self._alerted_markets: set[str] = set()         # éviter les doublons d'alerte
        self._last_scan: float = 0.0
        self._market_cache: dict[str, dict] = {}        # market_id → raw market dict pour le sniper
        self._sniper: Optional["PolymarketSniper"] = None  # instance partagée

    def _get_sniper(self) -> "PolymarketSniper":
        if self._sniper is None:
            from core.sniper import PolymarketSniper
            self._sniper = PolymarketSniper()
        return self._sniper

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _fetch_markets(self) -> list[dict]:
        """Récupère les marchés actifs depuis Gamma API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(
                    f"{GAMMA_URL}/markets",
                    params={
                        "limit": 200,
                        "active": "true",
                        "closed": "false",
                        "order": "volume24hr",
                        "ascending": "false",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            log.warning("_fetch_markets: %s", e)
        return []

    def _minutes_remaining(self, market: dict) -> Optional[float]:
        """Retourne les minutes restantes avant résolution, ou None si inconnu."""
        from datetime import datetime, timezone
        end_date = market.get("endDate") or market.get("end_date_iso") or ""
        if not end_date:
            return None
        try:
            end_dt = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            delta = (end_dt - datetime.now(timezone.utc)).total_seconds() / 60
            return delta
        except Exception:
            return None

    def _extract_tokens(self, market: dict) -> tuple[str, str]:
        """Retourne (yes_token_id, no_token_id)."""
        tokens = market.get("clobTokenIds") or market.get("tokens") or []
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except Exception:
                return "", ""
        if len(tokens) < 2:
            return "", ""
        t0 = tokens[0]
        t1 = tokens[1]
        yes_id = (t0.get("token_id") if isinstance(t0, dict) else str(t0)) or ""
        no_id  = (t1.get("token_id") if isinstance(t1, dict) else str(t1)) or ""
        return yes_id, no_id

    def _get_prices(self, market: dict) -> tuple[float, float]:
        """Retourne (yes_price, no_price) depuis outcomePrices."""
        prices = market.get("outcomePrices") or '["0.5","0.5"]'
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except Exception:
                return 0.5, 0.5
        yes_p = float(prices[0]) if prices else 0.5
        no_p  = float(prices[1]) if len(prices) > 1 else (1 - yes_p)
        return yes_p, no_p

    async def _fetch_current_price(self, token_id: str) -> Optional[float]:
        """Récupère le prix actuel depuis le CLOB."""
        if not token_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(
                    f"{CLOB_URL}/last-trade-price",
                    params={"token_id": token_id},
                )
                if r.status_code == 200:
                    return float(r.json().get("price", 0)) or None
        except Exception:
            pass
        return None

    # ── Scan ─────────────────────────────────────────────────────────────────

    async def scan_cycle(self) -> list[ScalpSignal]:
        """Filtre les marchés 'Up or Down' avec résolution < 30 min."""
        markets = await self._fetch_markets()
        signals: list[ScalpSignal] = []

        for m in markets:
            question = m.get("question") or ""
            if "up or down" not in question.lower():
                continue

            minutes = self._minutes_remaining(m)
            if minutes is None or minutes <= 0 or minutes > MAX_RESOLUTION_MINUTES:
                continue

            market_id = str(m.get("conditionId") or m.get("id") or "")
            if market_id in self._alerted_markets:
                continue

            log.info("scalper: marché Up/Down trouvé — question=%r", question)

            yes_token, no_token = self._extract_tokens(m)
            if not yes_token:
                continue

            yes_price, no_price = self._get_prices(m)
            from datetime import datetime, timezone
            end_date = m.get("endDate") or ""
            try:
                end_dt = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
                end_ts = end_dt.timestamp()
            except Exception:
                end_ts = time.time() + minutes * 60

            signals.append(ScalpSignal(
                market_id=market_id,
                question=question,
                token_id_yes=yes_token,
                token_id_no=no_token,
                yes_price=yes_price,
                no_price=no_price,
                minutes_remaining=round(minutes, 1),
                end_ts=end_ts,
            ))
            self._market_cache[market_id] = m

        return signals

    # ── Position monitor ──────────────────────────────────────────────────────

    async def monitor_positions(self) -> None:
        """Vérifie TP/SL pour chaque position ouverte."""
        from monitoring.push_alerts import push_scalp_tp_alert, push_scalp_sl_alert
        closed: list[str] = []

        for token_id, pos in self.positions.items():
            current = await self._fetch_current_price(token_id)
            if current is None:
                continue

            log.debug("scalp monitor: %s side=%s entry=%.3f cur=%.3f tp=%.3f sl=%.3f",
                      pos.question[:30], pos.side, pos.entry_price, current, pos.tp_price, pos.sl_price)

            if current >= pos.tp_price:
                pnl_pct = (current - pos.entry_price) / pos.entry_price * 100
                log.info("scalp TP atteint: %s +%.1f%%", pos.question[:40], pnl_pct)
                try:
                    await push_scalp_tp_alert(pos, current, pnl_pct)
                except Exception as e:
                    log.error("push_scalp_tp_alert: %s", e)
                closed.append(token_id)

            elif current <= pos.sl_price:
                pnl_pct = (current - pos.entry_price) / pos.entry_price * 100
                log.info("scalp SL atteint: %s %.1f%%", pos.question[:40], pnl_pct)
                try:
                    await push_scalp_sl_alert(pos, current, pnl_pct)
                except Exception as e:
                    log.error("push_scalp_sl_alert: %s", e)
                closed.append(token_id)

            # Marché expiré → clôture forcée
            elif time.time() > pos.opened_at + MAX_RESOLUTION_MINUTES * 60:
                log.info("scalp expiré (temps max): %s", pos.question[:40])
                closed.append(token_id)

        for token_id in closed:
            self.positions.pop(token_id, None)

    def open_position(self, token_id: str, pos: ScalpPosition) -> None:
        self.positions[token_id] = pos

    def mark_alerted(self, market_id: str) -> None:
        self._alerted_markets.add(market_id)

    # ── Boucle principale ─────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        log.info("🔪 Scalper started — scan every %ds, monitor every %ds | max_resolution=%dmin",
                 SCAN_INTERVAL, MONITOR_INTERVAL, MAX_RESOLUTION_MINUTES)
        last_monitor = 0.0

        while True:
            try:
                # Scan
                signals = await self.scan_cycle()
                if signals:
                    log.info("scalper: %d marchés Up/Down détectés < %dmin", len(signals), MAX_RESOLUTION_MINUTES)
                    sniper = self._get_sniper()
                    from monitoring.push_alerts import push_scalp_signal
                    for sig in signals:
                        m = self._market_cache.get(sig.market_id, {})
                        sniper_fired = False
                        if m:
                            try:
                                sniper_sig = await sniper.monitor_market(m)
                                if sniper_sig:
                                    sniper_fired = True
                                    log.info("scalper+sniper confluence: %s %s",
                                             sig.question[:40], sniper_sig.signals)
                                    await sniper._on_signal_detected(sniper_sig)
                            except Exception as e:
                                log.error("sniper analysis: %s", e)
                        if not sniper_fired:
                            # Fallback : alerte manuelle (boutons YES/NO)
                            try:
                                await push_scalp_signal(sig)
                            except Exception as e:
                                log.error("push_scalp_signal: %s", e)
                        self.mark_alerted(sig.market_id)

                # Monitor positions
                if self.positions and time.time() - last_monitor >= MONITOR_INTERVAL:
                    await self.monitor_positions()
                    last_monitor = time.time()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("scalper loop error: %s", e)

            await asyncio.sleep(SCAN_INTERVAL)


# ── Point d'entrée ────────────────────────────────────────────────────────────

_tracker: Optional[ScalperTracker] = None


def get_tracker() -> ScalperTracker:
    """Retourne l'instance globale du scalper (pour les callbacks Telegram)."""
    global _tracker
    if _tracker is None:
        _tracker = ScalperTracker()
    return _tracker


async def run_scalper_forever() -> None:
    tracker = get_tracker()
    await tracker.run_forever()
