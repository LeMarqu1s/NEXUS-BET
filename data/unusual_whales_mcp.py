"""
NEXUS BET - Unusual Whales MCP Smart Money Client
Client for Unusual Whales API for options flow & smart money data.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional
import httpx

from config.settings import settings


class UnusualWhalesMCPClient:
    """Async client for Unusual Whales API (MCP / REST)."""

    BASE_URL = "https://api.unusualwhales.com/api"

    def __init__(self) -> None:
        self.api_key = settings.UNUSUAL_WHALES_API_KEY
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def get_options_flow(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch unusual options flow data."""
        if not self.api_key:
            return []
        try:
            client = self._get_client()
            params: dict[str, Any] = {"limit": limit}
            if symbol:
                params["symbol"] = symbol
            resp = await client.get("/options/flow", params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "data" in data:
                return data["data"] if isinstance(data["data"], list) else []
            return []
        except Exception:
            return []

    async def get_smart_money_moves(
        self,
        symbol: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch smart money / whale activity."""
        if not self.api_key:
            return []
        try:
            client = self._get_client()
            params: dict[str, Any] = {"limit": limit}
            if symbol:
                params["symbol"] = symbol
            resp = await client.get("/smart-money/moves", params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "data" in data:
                return data["data"] if isinstance(data["data"], list) else []
            return []
        except Exception:
            return []

    async def get_dark_pool_activity(
        self,
        symbol: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch dark pool activity."""
        if not self.api_key:
            return []
        try:
            client = self._get_client()
            params: dict[str, Any] = {"limit": limit}
            if symbol:
                params["symbol"] = symbol
            resp = await client.get("/dark-pool", params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "data" in data:
                return data["data"] if isinstance(data["data"], list) else []
            return []
        except Exception:
            return []

    async def get_flow_for_ticker(self, ticker: str) -> list[dict[str, Any]]:
        """Get options flow for a specific ticker (e.g. NCAA, BTC)."""
        return await self.get_options_flow(symbol=ticker, limit=20)

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
