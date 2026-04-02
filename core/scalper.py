"""
NEXUS BET - Scalper
Scanner dédié aux marchés "Up or Down" (BTC/ETH) sur fenêtres < 30 minutes.
Stratégie principale : lag Binance → Polymarket.
  Référence = prix BTC à l'ouverture du marché (klines Binance 1min).
  Si BTC s'est éloigné de la référence mais Poly n'a pas encore ajusté → trade.
Suivi de position 60s avec alerte TP/SL + auto-ajustement.
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

GAMMA_URL        = "https://gamma-api.polymarket.com"
CLOB_URL         = "https://clob.polymarket.com"
SCAN_INTERVAL    = 30
MONITOR_INTERVAL = 60
MAX_RESOLUTION_MINUTES = 30

SETTINGS_FILE  = Path(__file__).resolve().parent.parent / "scalp_settings.json"
HISTORY_FILE   = Path(__file__).resolve().parent.parent / "scalp_history.json"
CAPITAL_FILE   = Path(__file__).resolve().parent.parent / "scalp_capital.json"
DEFAULT_TP     = 0.20
DEFAULT_SL     = 0.15

DRIFT_THRESHOLD  = 0.004   # 0.4% drift minimum pour déclencher
POLY_LAG_MAX_YES = 0.68    # drift>0 mais YES < 68% → lag → BUY YES
POLY_LAG_MIN_YES = 0.32    # drift<0 mais YES > 32% → lag → BUY NO
AUTO_ADJUST_EVERY = 10

# ── Gestion du capital avec réinvestissement ──────────────────────────────────
KELLY_FRACTION   = 0.05    # 5% du capital par trade
REINVEST_RATIO   = 0.80    # 80% des profits réinvestis
WITHDRAW_RATIO   = 0.20    # 20% des profits retirés (non-réinvestis)
MIN_TRADE_USD    = 5.0     # taille minimale
MAX_TRADE_USD    = 200.0   # plafond de sécurité par trade


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ScalpSignal:
    market_id:         str
    question:          str
    token_id_yes:      str
    token_id_no:       str
    yes_price:         float
    no_price:          float
    minutes_remaining: float
    end_ts:            float


@dataclass
class ScalpPosition:
    market_id:   str
    question:    str
    token_id:    str
    side:        str
    entry_price: float
    tp_price:    float
    sl_price:    float
    size_usd:    float
    chat_ids:    list[str]
    opened_at:   float = field(default_factory=time.time)
    alerted:     bool  = False
    order_id:    str   = ""
    signal_type: str   = "manual"


# ── Settings ──────────────────────────────────────────────────────────────────

def load_scalp_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"tp": DEFAULT_TP, "sl": DEFAULT_SL}


def save_scalp_settings(tp: float, sl: float) -> None:
    SETTINGS_FILE.write_text(json.dumps({"tp": tp, "sl": sl}, indent=2), encoding="utf-8")


# ── Historique ────────────────────────────────────────────────────────────────

def load_scalp_history() -> list[dict]:
    try:
        if HISTORY_FILE.exists():
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def save_scalp_history(history: list[dict]) -> None:
    try:
        HISTORY_FILE.write_text(json.dumps(history[-200:], indent=2), encoding="utf-8")
    except Exception as e:
        log.debug("save_scalp_history: %s", e)


# ── Capital avec réinvestissement ─────────────────────────────────────────────

def load_scalp_capital() -> dict:
    try:
        if CAPITAL_FILE.exists():
            return json.loads(CAPITAL_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    base = float(os.getenv("POLYMARKET_CAPITAL_USD", "500"))
    return {"capital": base, "total_withdrawn": 0.0, "total_reinvested": 0.0}


def save_scalp_capital(data: dict) -> None:
    try:
        CAPITAL_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        log.debug("save_scalp_capital: %s", e)


def compute_trade_size(capital: float) -> float:
    """Taille du trade = KELLY_FRACTION × capital, entre MIN et MAX."""
    size = capital * KELLY_FRACTION
    return round(max(MIN_TRADE_USD, min(size, MAX_TRADE_USD)), 2)


# ── ScalperTracker ────────────────────────────────────────────────────────────

class ScalperTracker:
    def __init__(self) -> None:
        self.positions: dict[str, ScalpPosition] = {}
        self._alerted_markets: set[str] = set()
        self._last_scan: float = 0.0
        self._market_cache: dict[str, dict] = {}
        self._sniper: Optional["PolymarketSniper"] = None
        self._trade_history: list[dict] = load_scalp_history()
        self._capital_data: dict = load_scalp_capital()
        log.info("scalp capital: %.2f USDC (retiré: %.2f | réinvesti: %.2f)",
                 self._capital_data["capital"],
                 self._capital_data["total_withdrawn"],
                 self._capital_data["total_reinvested"])

    def _get_sniper(self) -> "PolymarketSniper":
        if self._sniper is None:
            from core.sniper import PolymarketSniper
            self._sniper = PolymarketSniper()
        return self._sniper

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _fetch_markets(self) -> list[dict]:
        """
        Récupère les marchés crypto scalp-able via l'endpoint /events.
        Retourne une liste de dicts compatibles avec scan_cycle (chaque dict
        représente un sub-market extrait de son event parent).
        """
        SCALP_KEYWORDS = ("up or down", "bitcoin above", "btc above",
                          "ethereum above", "bitcoin price on", "ethereum price on",
                          "btc 5 minute", "bitcoin 5 minute")
        results: list[dict] = []
        seen_ids: set[str] = set()
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(
                    f"{GAMMA_URL}/events",
                    params={"limit": 300, "active": "true", "closed": "false",
                            "order": "volume24hr", "ascending": "false"},
                )
                if r.status_code != 200:
                    return []
                events = r.json()
                if isinstance(events, dict):
                    events = events.get("data", [])
                for event in events:
                    title = (event.get("title") or "").lower()
                    if not any(kw in title for kw in SCALP_KEYWORDS):
                        continue
                    sub_markets = event.get("markets") or []
                    for m in sub_markets:
                        mid = str(m.get("conditionId") or m.get("id") or "")
                        if not mid or mid in seen_ids:
                            continue
                        # Injecter endDate du parent si absent du sub-market
                        if not m.get("endDate") and event.get("endDate"):
                            m = dict(m)
                            m["endDate"] = event["endDate"]
                        seen_ids.add(mid)
                        results.append(m)
        except Exception as e:
            log.warning("_fetch_markets: %s", e)
        log.debug("_fetch_markets: %d sub-marchés crypto extraits", len(results))
        return results

    def _minutes_remaining(self, market: dict) -> Optional[float]:
        from datetime import datetime, timezone
        end_date = market.get("endDate") or market.get("end_date_iso") or ""
        if not end_date:
            return None
        try:
            end_dt = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            return (end_dt - datetime.now(timezone.utc)).total_seconds() / 60
        except Exception:
            return None

    def _extract_tokens(self, market: dict) -> tuple[str, str]:
        tokens = market.get("clobTokenIds") or market.get("tokens") or []
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except Exception:
                return "", ""
        if len(tokens) < 2:
            return "", ""
        t0, t1 = tokens[0], tokens[1]
        yes_id = (t0.get("token_id") if isinstance(t0, dict) else str(t0)) or ""
        no_id  = (t1.get("token_id") if isinstance(t1, dict) else str(t1)) or ""
        return yes_id, no_id

    def _get_prices(self, market: dict) -> tuple[float, float]:
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
        if not token_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{CLOB_URL}/last-trade-price", params={"token_id": token_id})
                if r.status_code == 200:
                    return float(r.json().get("price", 0)) or None
        except Exception:
            pass
        return None

    # ── Stratégie : lag Binance → Polymarket ──────────────────────────────────

    async def _compute_drift_signal(self, sig: ScalpSignal) -> Optional[tuple[str, str]]:
        """
        Compare le prix Binance actuel au prix de référence (ouverture du marché).
        Retourne (direction, label) ou None si pas de lag détectable.
        """
        from core.price_feed import get_binance_price, get_reference_price, get_symbol_from_question
        symbol    = get_symbol_from_question(sig.question)
        ref_price = await get_reference_price(sig.question, symbol)
        if not ref_price:
            return None

        btc_price = await get_binance_price(symbol)
        if not btc_price:
            return None

        drift = (btc_price - ref_price) / ref_price
        log.info("scalper drift: %s btc=%.2f ref=%.2f drift=%+.3f%% poly_yes=%.2f",
                 symbol, btc_price, ref_price, drift * 100, sig.yes_price)

        if drift > DRIFT_THRESHOLD and sig.yes_price < POLY_LAG_MAX_YES:
            return "YES", f"DRIFT_+{drift*100:.2f}%"
        if drift < -DRIFT_THRESHOLD and sig.yes_price > POLY_LAG_MIN_YES:
            return "NO", f"DRIFT_{drift*100:.2f}%"
        return None

    async def _auto_execute_scalp(
        self, sig: ScalpSignal, direction: str, signal_type: str
    ) -> Optional[str]:
        """Exécute un trade scalp automatiquement. Retourne l'order_id ou None."""
        from execution.order_manager import OrderManager, OrderConfig
        cfg      = load_scalp_settings()
        size_usd = compute_trade_size(self._capital_data["capital"])
        token_id    = sig.token_id_yes if direction == "YES" else sig.token_id_no
        entry_price = sig.yes_price    if direction == "YES" else sig.no_price
        order_cfg = OrderConfig(
            market_id=sig.market_id, outcome=direction, side="BUY",
            size_usd=size_usd, limit_price=entry_price,
            take_profit_pct=cfg["tp"], stop_loss_pct=cfg["sl"],
        )
        order_id = await OrderManager().place_limit_order(order_cfg)
        if order_id:
            pos = ScalpPosition(
                market_id=sig.market_id, question=sig.question,
                token_id=token_id, side=direction, entry_price=entry_price,
                tp_price=round(entry_price * (1 + cfg["tp"]), 4),
                sl_price=round(entry_price * (1 - cfg["sl"]), 4),
                size_usd=size_usd, chat_ids=[], order_id=order_id,
                signal_type=signal_type,
            )
            self.open_position(token_id, pos)
            log.info("scalp auto-exec: %s %s @ %.3f [%s]",
                     direction, sig.question[:35], entry_price, signal_type)
        return order_id

    # ── Tracking & auto-ajustement ────────────────────────────────────────────

    def _record_trade_result(self, pos: ScalpPosition, exit_price: float, exit_reason: str) -> None:
        if pos.entry_price <= 0:
            log.warning("entry_price invalide pour %s, trade ignoré", pos.question[:40])
            return
        pnl_usd = round((exit_price - pos.entry_price) / pos.entry_price * pos.size_usd, 4)
        # Compounding : réinvestir 80% des profits, retirer 20%
        cap = self._capital_data
        if pnl_usd > 0:
            reinvest  = round(pnl_usd * REINVEST_RATIO, 4)
            withdrawn = round(pnl_usd * WITHDRAW_RATIO, 4)
            cap["capital"]          = round(cap["capital"] + reinvest, 4)
            cap["total_reinvested"] = round(cap.get("total_reinvested", 0) + reinvest, 4)
            cap["total_withdrawn"]  = round(cap.get("total_withdrawn", 0) + withdrawn, 4)
            log.info("scalp compounding: +%.2f USDC | capital=%.2f | retiré cumulé=%.2f",
                     reinvest, cap["capital"], cap["total_withdrawn"])
        elif pnl_usd < 0:
            cap["capital"] = round(max(cap["capital"] + pnl_usd, 0), 4)
            log.info("scalp perte: %.2f USDC | capital restant=%.2f", pnl_usd, cap["capital"])
        save_scalp_capital(cap)
        self._trade_history.append({
            "ts": time.time(), "question": pos.question[:60],
            "side": pos.side, "entry": pos.entry_price, "exit": exit_price,
            "pnl_usd": pnl_usd, "exit_reason": exit_reason,
            "signal_type": pos.signal_type,
            "capital_after": cap["capital"],
        })
        save_scalp_history(self._trade_history)
        self._auto_adjust_settings()

    def _auto_adjust_settings(self) -> None:
        closed = self._trade_history
        if len(closed) < AUTO_ADJUST_EVERY or len(closed) % AUTO_ADJUST_EVERY != 0:
            return
        last_n   = closed[-AUTO_ADJUST_EVERY:]
        win_rate = sum(1 for t in last_n if t.get("pnl_usd", 0) > 0) / len(last_n)
        cfg      = load_scalp_settings()
        tp, sl   = cfg["tp"], cfg["sl"]
        old_tp   = tp
        if win_rate > 0.65:
            tp = round(min(tp + 0.02, 0.35), 2)
        elif win_rate < 0.45:
            tp = round(max(tp - 0.02, 0.10), 2)
        if tp != old_tp:
            save_scalp_settings(tp, sl)
            log.info("scalp auto-adjust: win_rate=%.0f%% TP %.0f%%→%.0f%%",
                     win_rate * 100, old_tp * 100, tp * 100)

    def get_stats(self, days: int = 7) -> dict:
        cutoff = time.time() - days * 86400
        recent = [t for t in self._trade_history if t.get("ts", 0) > cutoff]
        if not recent:
            return {"trades": 0, "win_rate": 0, "total_pnl": 0.0,
                    "best": None, "worst": None, "by_signal": {}}
        wins      = sum(1 for t in recent if t.get("pnl_usd", 0) > 0)
        total_pnl = sum(t.get("pnl_usd", 0) for t in recent)
        by_signal: dict[str, dict] = {}
        for t in recent:
            e = by_signal.setdefault(t.get("signal_type", "manual"), {"count": 0, "wins": 0})
            e["count"] += 1
            if t.get("pnl_usd", 0) > 0:
                e["wins"] += 1
        return {
            "trades": len(recent),
            "win_rate": round(wins / len(recent) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "best":  max(recent, key=lambda t: t.get("pnl_usd", 0)),
            "worst": min(recent, key=lambda t: t.get("pnl_usd", 0)),
            "by_signal": by_signal,
            "capital": self._capital_data["capital"],
            "total_withdrawn": self._capital_data.get("total_withdrawn", 0.0),
            "total_reinvested": self._capital_data.get("total_reinvested", 0.0),
            "next_trade_size": compute_trade_size(self._capital_data["capital"]),
        }

    # ── Scan ─────────────────────────────────────────────────────────────────

    async def scan_cycle(self) -> list[ScalpSignal]:
        markets = await self._fetch_markets()
        signals: list[ScalpSignal] = []
        for m in markets:
            question = m.get("question") or ""
            q_lower = question.lower()
            # Crypto only — exclure S&P, indices, sports, etc.
            is_crypto  = any(kw in q_lower for kw in ("bitcoin", "btc", "ethereum", "eth", "crypto"))
            if not is_crypto:
                continue
            # Accepter : up/down court terme, above/price journalier crypto
            is_updown  = "up or down" in q_lower
            is_above   = any(kw in q_lower for kw in ("bitcoin above", "ethereum above", "btc above"))
            is_range   = any(kw in q_lower for kw in ("bitcoin price on", "ethereum price on"))
            if not (is_updown or is_above or is_range):
                continue
            minutes = self._minutes_remaining(m)
            if minutes is None or minutes <= 0:
                continue
            # Fenêtre courte pour up/down 5-15min, large pour journaliers
            max_mins = MAX_RESOLUTION_MINUTES if is_updown and minutes <= 60 else 480
            if minutes > max_mins:
                continue
            market_id = str(m.get("conditionId") or m.get("id") or "")
            if market_id in self._alerted_markets:
                continue
            yes_token, no_token = self._extract_tokens(m)
            if not yes_token:
                continue
            yes_price, no_price = self._get_prices(m)
            from datetime import datetime, timezone
            end_date = m.get("endDate") or ""
            try:
                end_ts = datetime.fromisoformat(str(end_date).replace("Z", "+00:00")).timestamp()
            except Exception:
                end_ts = time.time() + minutes * 60
            signals.append(ScalpSignal(
                market_id=market_id, question=question,
                token_id_yes=yes_token, token_id_no=no_token,
                yes_price=yes_price, no_price=no_price,
                minutes_remaining=round(minutes, 1), end_ts=end_ts,
            ))
            self._market_cache[market_id] = m
        return signals

    # ── Position monitor ──────────────────────────────────────────────────────

    async def monitor_positions(self) -> None:
        from monitoring.push_alerts import push_scalp_tp_alert, push_scalp_sl_alert
        closed: list[str] = []
        for token_id, pos in self.positions.items():
            current = await self._fetch_current_price(token_id)
            if current is None:
                continue
            if pos.entry_price <= 0:
                closed.append(token_id)
                continue
            if current >= pos.tp_price:
                pnl_pct = (current - pos.entry_price) / pos.entry_price * 100
                log.info("scalp TP atteint: %s +%.1f%%", pos.question[:40], pnl_pct)
                self._record_trade_result(pos, current, "TP")
                try:
                    await push_scalp_tp_alert(pos, current, pnl_pct)
                except Exception as e:
                    log.error("push_scalp_tp_alert: %s", e)
                closed.append(token_id)
            elif current <= pos.sl_price:
                pnl_pct = (current - pos.entry_price) / pos.entry_price * 100
                log.info("scalp SL atteint: %s %.1f%%", pos.question[:40], pnl_pct)
                self._record_trade_result(pos, current, "SL")
                try:
                    await push_scalp_sl_alert(pos, current, pnl_pct)
                except Exception as e:
                    log.error("push_scalp_sl_alert: %s", e)
                closed.append(token_id)
            elif time.time() > pos.opened_at + MAX_RESOLUTION_MINUTES * 60:
                log.info("scalp expiré: %s", pos.question[:40])
                self._record_trade_result(pos, pos.entry_price, "EXPIRED")
                closed.append(token_id)
        for token_id in closed:
            self.positions.pop(token_id, None)

    def open_position(self, token_id: str, pos: ScalpPosition) -> None:
        self.positions[token_id] = pos

    def mark_alerted(self, market_id: str) -> None:
        self._alerted_markets.add(market_id)

    # ── Boucle principale ─────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        log.info(
            "🔪 Scalper started — scan every %ds | drift_threshold=%.1f%% | max_resolution=%dmin",
            SCAN_INTERVAL, DRIFT_THRESHOLD * 100, MAX_RESOLUTION_MINUTES,
        )
        last_monitor = 0.0
        auto_snipe   = os.getenv("AUTO_SNIPE", "false").lower() == "true"

        while True:
            try:
                signals = await self.scan_cycle()
                if signals:
                    log.info("scalper: %d marchés Up/Down détectés < %dmin",
                             len(signals), MAX_RESOLUTION_MINUTES)
                    from monitoring.push_alerts import push_scalp_executed
                    for sig in signals:
                        direction, label = None, "DEFAULT"

                        # Priorité 1 : drift Binance
                        if auto_snipe:
                            try:
                                drift = await self._compute_drift_signal(sig)
                                if drift:
                                    direction, label = drift
                            except Exception as e:
                                log.error("drift signal: %s", e)

                        # Priorité 2 : meilleur prix disponible (NO si yes_price < 0.20)
                        if direction is None:
                            direction = "NO" if sig.yes_price < 0.20 else "YES"
                            label = "BEST_PRICE"

                        # Auto-exécution systématique
                        try:
                            order_id = await self._auto_execute_scalp(sig, direction, label)
                            if order_id:
                                cfg      = load_scalp_settings()
                                cfg["size_usd"] = compute_trade_size(self._capital_data["capital"])
                                entry    = sig.yes_price if direction == "YES" else sig.no_price
                                await push_scalp_executed(sig, direction, entry, order_id, cfg)
                        except Exception as e:
                            log.error("auto_execute: %s", e)

                        self.mark_alerted(sig.market_id)
                        await asyncio.sleep(2)  # anti-flood entre signaux

                else:
                    log.debug("scalper: 0 marchés actifs (hors horaires ou pas encore créés)")

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
    global _tracker
    if _tracker is None:
        _tracker = ScalperTracker()
    return _tracker


async def run_scalper_forever() -> None:
    await get_tracker().run_forever()
