"""
NEXUS BET - Price Feed
Prix temps réel Binance (API publique, sans clé).
Utilisé par le scalper pour détecter le lag Polymarket vs prix réels.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

import httpx

log = logging.getLogger("nexus.price_feed")

BINANCE_URL  = "https://api.binance.com"
CACHE_TTL    = 8.0  # secondes — rafraîchi tous les ~8s pour rester frais

_price_cache: dict[str, tuple[float, float]] = {}  # symbol → (price, ts)


async def get_binance_price(symbol: str = "BTCUSDT") -> Optional[float]:
    """Prix actuel depuis Binance avec cache 8s."""
    cached = _price_cache.get(symbol)
    if cached and time.time() - cached[1] < CACHE_TTL:
        return cached[0]
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(
                f"{BINANCE_URL}/api/v3/ticker/price",
                params={"symbol": symbol},
            )
            if r.status_code == 200:
                price = float(r.json()["price"])
                _price_cache[symbol] = (price, time.time())
                log.debug("Binance %s = %.2f", symbol, price)
                return price
    except Exception as e:
        log.debug("get_binance_price %s: %s", symbol, e)
    return None


def extract_reference_price(question: str) -> Optional[float]:
    """
    Extrait le prix de référence depuis la question du marché.
    Supporte les formats Polymarket :
      "Will BTC go Up or Down from $83,450?"        → 83450.0
      "BTC Up or Down 5 Minutes? $83.5K"            → 83500.0
      "Will BTC be above $83,000 at 3:05 PM?"       → 83000.0
      "Bitcoin Up or Down from 83450"               → 83450.0
    """
    q = question.replace(",", "")

    # $XX.XK  (ex: $83.5K → 83500)
    m = re.search(r'\$\s*([\d]+\.?\d*)\s*[kK]\b', q)
    if m:
        return float(m.group(1)) * 1000

    # $XXXXX.XX  (ex: $83450.50)
    m = re.search(r'\$\s*([\d]+\.?\d*)', q)
    if m:
        val = float(m.group(1))
        if val > 100:
            return val

    # Nombre sans $ mais > 1000 (dernier recours)
    m = re.search(r'\b([\d]{4,6}\.?\d*)\b', q)
    if m:
        val = float(m.group(1))
        if val > 100:
            return val

    return None


def get_symbol_from_question(question: str) -> str:
    """Retourne 'ETHUSDT' ou 'BTCUSDT' selon la question."""
    if "ETH" in question.upper():
        return "ETHUSDT"
    return "BTCUSDT"
