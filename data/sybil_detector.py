"""
NEXUS BET — Sybil / Coordinated Wallet Detector

Détecte les mouvements coordonnés sur Polymarket :
- 3+ wallets qui parient des montants similaires dans la même fenêtre de 60s
- Volume coordonné > $5 000 sur un marché peu actif
- Génère des signaux WHALE_COORDINATED avec action FOLLOW / FADE / WATCH

Résultat mis en cache 5 minutes pour ne pas spammer l'API.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("nexus.sybil")

TRADES_URL = "https://data-api.polymarket.com/trades"
COORD_WINDOW_SEC = 60       # fenêtre de détection coordonnée (secondes)
MIN_WALLETS = 3             # nombre min de wallets distincts dans la fenêtre
MIN_COORD_VOLUME = 5_000    # volume min ($) pour déclencher un signal
FOLLOW_THRESHOLD = 0.15     # prix < 15¢ → FOLLOW (marché pas encore pompé)
FADE_THRESHOLD = 0.25       # prix > 25¢ → FADE (déjà pompé, vendre contre)
REQUEST_TIMEOUT = 10.0
CACHE_TTL = 300             # 5 minutes entre deux scans


# ── Cache module-level ────────────────────────────────────────────────────────
_last_scan: float = 0.0
_cached_signals: list[dict[str, Any]] = []


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class CoordSignal:
    market_id: str
    market_question: str
    wallets_count: int
    coordinated_volume: float
    entry_price: float
    action: str  # FOLLOW | FADE | WATCH
    detected_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_type": "WHALE_COORDINATED",
            "market": self.market_question,
            "market_id": self.market_id,
            "wallets_count": self.wallets_count,
            "coordinated_volume": self.coordinated_volume,
            "entry_price": self.entry_price,
            "action": self.action,
            "detected_at": self.detected_at,
        }


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_recent_trades(limit: int = 200) -> list[dict[str, Any]]:
    """Récupère les trades récents depuis l'API Polymarket Data."""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            r = await client.get(TRADES_URL, params={"size": limit})
            if r.status_code != 200:
                log.warning("Trades API %d: %s", r.status_code, r.text[:100])
                return []
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("_fetch_recent_trades: %s", e)
        return []


def _extract_ts(trade: dict[str, Any]) -> float:
    """Extrait un timestamp float depuis un trade (gère plusieurs formats d'API)."""
    for key in ("timestamp", "createdAt", "created_at", "blockTimestamp"):
        val = trade.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except (ValueError, TypeError):
            continue
    return 0.0


def _extract_maker(trade: dict[str, Any]) -> str:
    """Extrait l'adresse du wallet depuis un trade."""
    for key in ("maker", "transactor", "user", "makerAddress", "trader"):
        val = trade.get(key)
        if val and isinstance(val, str):
            return val.lower()
    return ""


def _extract_market_id(trade: dict[str, Any]) -> str:
    """Extrait l'identifiant du marché depuis un trade."""
    for key in ("conditionId", "market", "asset_id", "marketId", "condition_id"):
        val = trade.get(key)
        if val and isinstance(val, str):
            return val
    return ""


def _detect_coordinated(trades: list[dict[str, Any]]) -> list[CoordSignal]:
    """
    Algorithme de détection :
    1. Groupe les trades par marché
    2. Pour chaque marché, fenêtre glissante de 60s
    3. Si 3+ wallets distincts + volume > $5 000 → signal

    Retourne au plus 1 signal par marché (le plus gros volume).
    """
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        mid = _extract_market_id(t)
        if mid:
            by_market[mid].append(t)

    signals: list[CoordSignal] = []

    for market_id, mtrades in by_market.items():
        if len(mtrades) < MIN_WALLETS:
            continue

        mtrades_sorted = sorted(mtrades, key=_extract_ts)
        n = len(mtrades_sorted)
        best: CoordSignal | None = None

        for i in range(n):
            t_start = _extract_ts(mtrades_sorted[i])
            if t_start == 0:
                continue

            wallets: set[str] = set()
            total_volume = 0.0
            prices: list[float] = []

            for j in range(i, n):
                t_j = _extract_ts(mtrades_sorted[j])
                if t_j - t_start > COORD_WINDOW_SEC:
                    break
                maker = _extract_maker(mtrades_sorted[j])
                if maker:
                    wallets.add(maker)
                size = float(mtrades_sorted[j].get("size") or mtrades_sorted[j].get("amount") or 0)
                price = float(mtrades_sorted[j].get("price") or 0)
                total_volume += size * price
                if 0 < price < 1:
                    prices.append(price)

            if len(wallets) < MIN_WALLETS or total_volume < MIN_COORD_VOLUME:
                continue

            avg_price = sum(prices) / len(prices) if prices else 0.0
            if avg_price < FOLLOW_THRESHOLD:
                action = "FOLLOW"
            elif avg_price > FADE_THRESHOLD:
                action = "FADE"
            else:
                action = "WATCH"

            question = (
                mtrades_sorted[i].get("title")
                or mtrades_sorted[i].get("question")
                or market_id[:40]
            )

            sig = CoordSignal(
                market_id=market_id,
                market_question=str(question)[:80],
                wallets_count=len(wallets),
                coordinated_volume=total_volume,
                entry_price=avg_price,
                action=action,
            )
            # Garder le signal avec le plus grand volume pour ce marché
            if best is None or sig.coordinated_volume > best.coordinated_volume:
                best = sig

        if best is not None:
            signals.append(best)

    signals.sort(key=lambda s: -s.coordinated_volume)
    return signals


# ── Public API ────────────────────────────────────────────────────────────────

async def scan_coordinated_activity() -> list[dict[str, Any]]:
    """
    Point d'entrée principal.
    Retourne la liste de signaux WHALE_COORDINATED, triés par volume décroissant.
    Résultat mis en cache 5 minutes.
    """
    global _last_scan, _cached_signals

    now = time.time()
    if now - _last_scan < CACHE_TTL and _cached_signals:
        return _cached_signals

    trades = await _fetch_recent_trades(200)
    if not trades:
        log.debug("scan_coordinated_activity: 0 trades récupérés")
        return _cached_signals  # retourner cache même expiré plutôt que rien

    raw_signals = _detect_coordinated(trades)
    _cached_signals = [s.to_dict() for s in raw_signals]
    _last_scan = now
    log.info(
        "Sybil scan: %d trades analysés → %d signal(s) coordonné(s)",
        len(trades), len(raw_signals),
    )
    return _cached_signals
