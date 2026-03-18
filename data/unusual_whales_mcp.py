"""
NEXUS BET - Whale Tracker via Polymarket Public APIs
Replaces paid Unusual Whales API with free Polymarket Data API + Gamma API.
- Data API: large trades by wallet (no auth required)
- Gamma API: top markets by volume (no auth required)
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from config.settings import settings

KNOWN_WHALES: list[str] = [
    w.strip()
    for w in (getattr(settings, "WHALE_WALLETS", "") or "").split(",")
    if w.strip()
]

DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


class UnusualWhalesMCPClient:
    """Whale tracker backed by free Polymarket public APIs."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def get_smart_money_moves(
        self,
        symbol: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Fetch large trades from known whale wallets via Polymarket Data API.
        Falls back to top-volume market trades when no whale wallets configured.
        Each returned dict has: symbol, side/direction, size, wallet, timestamp.
        """
        client = self._get_client()
        results: list[dict[str, Any]] = []

        if KNOWN_WHALES:
            for wallet in KNOWN_WHALES[:10]:
                try:
                    resp = await client.get(
                        f"{DATA_API}/trades",
                        params={"funder": wallet, "size": min(limit, 50)},
                    )
                    resp.raise_for_status()
                    trades = resp.json()
                    if not isinstance(trades, list):
                        continue
                    for t in trades:
                        results.append({
                            "symbol": str(t.get("market", t.get("asset_id", "")))[:40],
                            "side": t.get("side", "BUY"),
                            "direction": t.get("side", "BUY"),
                            "size": float(t.get("size", 0)),
                            "price": float(t.get("price", 0)),
                            "wallet": wallet,
                            "timestamp": t.get("timestamp", t.get("created_at", "")),
                            "ticker": str(t.get("market", ""))[:20],
                        })
                except Exception:
                    continue
        else:
            try:
                resp = await client.get(
                    f"{GAMMA_API}/markets",
                    params={"order": "volumeNum", "ascending": "false", "limit": limit},
                )
                resp.raise_for_status()
                markets = resp.json()
                if not isinstance(markets, list):
                    return []
                for m in markets:
                    results.append({
                        "symbol": str(m.get("question", ""))[:40],
                        "side": "BUY",
                        "direction": "BUY",
                        "size": float(m.get("volumeNum", m.get("volume", 0)) or 0),
                        "price": 0,
                        "wallet": "",
                        "timestamp": m.get("endDate", ""),
                        "ticker": str(m.get("conditionId", m.get("id", "")))[:20],
                    })
            except Exception:
                return []

        return results[:limit]

    async def get_options_flow(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Polymarket equivalent: recent large trades across all markets."""
        return await self.get_smart_money_moves(symbol=symbol, limit=limit)

    async def get_dark_pool_activity(
        self,
        symbol: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """No direct dark pool equivalent on Polymarket; returns top volume markets."""
        client = self._get_client()
        try:
            resp = await client.get(
                f"{GAMMA_API}/markets",
                params={"order": "volumeNum", "ascending": "false", "limit": limit},
            )
            resp.raise_for_status()
            markets = resp.json()
            if not isinstance(markets, list):
                return []
            return [
                {
                    "symbol": str(m.get("question", ""))[:40],
                    "volume": float(m.get("volumeNum", m.get("volume", 0)) or 0),
                    "liquidity": float(m.get("liquidityNum", m.get("liquidity", 0)) or 0),
                    "ticker": str(m.get("conditionId", m.get("id", "")))[:20],
                }
                for m in markets
            ]
        except Exception:
            return []

    async def get_flow_for_ticker(self, ticker: str) -> list[dict[str, Any]]:
        """Get recent trades for a specific market condition ID."""
        client = self._get_client()
        try:
            resp = await client.get(
                f"{DATA_API}/trades",
                params={"market": ticker, "size": 20},
            )
            resp.raise_for_status()
            trades = resp.json()
            if not isinstance(trades, list):
                return []
            return [
                {
                    "symbol": ticker[:40],
                    "side": t.get("side", "BUY"),
                    "size": float(t.get("size", 0)),
                    "price": float(t.get("price", 0)),
                    "timestamp": t.get("timestamp", t.get("created_at", "")),
                }
                for t in trades
            ]
        except Exception:
            return []

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
