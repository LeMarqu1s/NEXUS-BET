"""
NEXUS BET - Price Feed
Prix temps réel Binance (API publique, sans clé).
Stratégie : référence = prix BTC à l'ouverture du marché (via klines 1min).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

log = logging.getLogger("nexus.price_feed")

BINANCE_URL = "https://api.binance.com"
CACHE_TTL   = 8.0   # secondes

_price_cache:  dict[str, tuple[float, float]] = {}   # symbol → (price, ts)
_ref_cache:    dict[str, tuple[float, float]] = {}   # question_key → (ref_price, ts)


async def get_binance_price(symbol: str = "BTCUSDT") -> Optional[float]:
    """Prix actuel Binance avec cache 8s."""
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
                return price
    except Exception as e:
        log.debug("get_binance_price %s: %s", symbol, e)
    return None


def _parse_market_start_ts(question: str) -> Optional[float]:
    """
    Parse la question Polymarket pour extraire le timestamp UTC du début du marché.
    Format : "Bitcoin Up or Down - March 31, 9:50PM-9:55PM ET"
             "Bitcoin Up or Down - April 1, 3:00AM-3:05AM ET"
    Retourne un Unix timestamp UTC ou None.
    ET = EDT (UTC-4) d'avril à novembre, EST (UTC-5) le reste.
    """
    # Pattern : "Month DD, H:MM(AM|PM)"
    m = re.search(r'(\w+)\s+(\d{1,2}),\s*(\d{1,2}:\d{2})\s*(AM|PM)', question, re.IGNORECASE)
    if not m:
        return None
    month_str, day_str, time_str, ampm = m.group(1), m.group(2), m.group(3), m.group(4).upper()
    year = datetime.now(timezone.utc).year
    try:
        dt = datetime.strptime(
            f"{month_str} {day_str} {year} {time_str} {ampm}",
            "%B %d %Y %I:%M %p",
        )
        # EDT (UTC-4) en vigueur d'avril à novembre
        month_num = dt.month
        offset = -4 if 4 <= month_num <= 10 else -5
        dt_utc = dt.replace(tzinfo=timezone(timedelta(hours=offset)))
        ts = dt_utc.timestamp()
        # Sanity check : le timestamp doit être récent (< 24h dans le passé)
        if time.time() - ts > 86400:
            ts += 365 * 86400  # essayer l'année suivante
        return ts
    except Exception as e:
        log.debug("_parse_market_start_ts: %s", e)
    return None


async def get_reference_price(question: str, symbol: str = "BTCUSDT") -> Optional[float]:
    """
    Récupère le prix BTC de référence (prix à l'ouverture du marché).
    Utilise les klines Binance 1-minute au timestamp de début du marché.
    Cache par question pour éviter les appels répétés.
    """
    cache_key = f"{symbol}:{question[:40]}"
    cached = _ref_cache.get(cache_key)
    if cached and time.time() - cached[1] < 300:   # cache 5min
        return cached[0]

    start_ts = _parse_market_start_ts(question)
    if not start_ts:
        log.debug("get_reference_price: impossible de parser la date dans %r", question[:60])
        return None

    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(
                f"{BINANCE_URL}/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": "1m",
                    "startTime": int(start_ts * 1000),
                    "limit": 1,
                },
            )
            if r.status_code == 200:
                klines = r.json()
                if klines and isinstance(klines, list) and len(klines[0]) > 1:
                    ref = float(klines[0][1])   # open price du chandelier
                    _ref_cache[cache_key] = (ref, time.time())
                    log.debug("get_reference_price %s @ %s = %.2f", symbol, question[22:40], ref)
                    return ref
    except Exception as e:
        log.debug("get_reference_price klines: %s", e)
    return None


def get_symbol_from_question(question: str) -> str:
    """Retourne 'ETHUSDT' ou 'BTCUSDT' selon la question."""
    if "ETH" in question.upper() or "ETHEREUM" in question.upper():
        return "ETHUSDT"
    return "BTCUSDT"
