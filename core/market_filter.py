"""
NEXUS CAPITAL - Market filters for scanner
Categories blacklist, min/max days to resolution, keyword blacklist.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def _get_env_list(key: str, default: list[str]) -> list[str]:
    v = os.getenv(key)
    if not v:
        return default
    return [x.strip().lower() for x in v.split(",") if x.strip()]


def _get_env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    return int(v) if v else default


def get_categories_blacklist() -> list[str]:
    """Sport,Politique,Crypto,Finance,Autre - blacklisted = excluded."""
    return _get_env_list("AUTO_TRADE_CATEGORIES_BLACKLIST", [])


def get_min_days_resolution() -> int:
    return _get_env_int("AUTO_TRADE_MIN_DAYS_RESOLUTION", 0)


def get_max_days_resolution() -> int:
    return _get_env_int("AUTO_TRADE_MAX_DAYS_RESOLUTION", 365)


def get_min_market_volume() -> float:
    v = os.getenv("MIN_MARKET_VOLUME")
    return float(v) if v else 1000.0


def get_min_liquidity() -> float:
    v = os.getenv("MIN_LIQUIDITY")
    return float(v) if v else 100.0


def get_keywords_blacklist() -> list[str]:
    return _get_env_list("AUTO_TRADE_KEYWORDS_BLACKLIST", [])


def _days_to_resolution(market: dict[str, Any]) -> int | None:
    """Days until market resolution. None if unknown."""
    end = market.get("endDate") or market.get("end_date_iso") or market.get("end_date")
    if not end:
        return None
    try:
        if isinstance(end, (int, float)):
            dt = datetime.fromtimestamp(end, tz=timezone.utc)
        elif isinstance(end, str):
            dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            return None
        delta = dt - datetime.now(timezone.utc)
        return max(0, delta.days)
    except Exception:
        return None


def _market_category(market: dict[str, Any]) -> str:
    """Infer category from question/tags."""
    q = (market.get("question") or "").lower()
    tags = (market.get("tags") or []) + [market.get("groupItemTitle") or ""]
    combined = q + " " + " ".join(str(t).lower() for t in tags)
    if any(x in combined for x in ["sport", "football", "basketball", "nba", "nfl", "soccer", "match", "game"]):
        return "sport"
    if any(x in combined for x in ["politic", "election", "vote", "trump", "biden", "congress"]):
        return "politique"
    if any(x in combined for x in ["crypto", "btc", "bitcoin", "eth", "ethereum"]):
        return "crypto"
    if any(x in combined for x in ["stock", "fed", "interest rate", "inflation", "finance"]):
        return "finance"
    return "autre"


def passes_filter(market: dict[str, Any]) -> bool:
    """True if market passes all filters."""
    blacklist = get_categories_blacklist()
    if blacklist:
        cat = _market_category(market)
        if cat in blacklist:
            return False

    min_days = get_min_days_resolution()
    max_days = get_max_days_resolution()
    days = _days_to_resolution(market)
    if days is not None:
        if days < min_days or days > max_days:
            return False

    keywords = get_keywords_blacklist()
    if keywords:
        q = (market.get("question") or "").lower()
        if any(kw in q for kw in keywords):
            return False

    volume = float(market.get("volumeNum", market.get("volume", 0)) or 0)
    if volume < get_min_market_volume():
        return False

    liquidity = float(market.get("liquidityNum", market.get("liquidity", 0)) or 0)
    if liquidity < get_min_liquidity():
        return False

    return True
