"""
NEXUS BET - Polymarket CLOB API Client
Async client for Polymarket Central Limit Order Book.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional
from decimal import Decimal
import httpx
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, ApiCreds
from py_clob_client.order_builder.constants import BUY

from config.settings import settings


class PolymarketClient:
    """Async Polymarket CLOB API client wrapper."""

    def __init__(self) -> None:
        self.host = settings.POLYMARKET_CLOB_HOST
        self.chain_id = settings.POLYMARKET_CHAIN_ID
        self._client: Optional[ClobClient] = None
        self._api_creds: Optional[ApiCreds] = None
        self._httpx_client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> ClobClient:
        """Get or create sync CLOB client (used for blocking calls in thread)."""
        if self._client is None:
            self._client = ClobClient(
                host=self.host,
                key=settings.POLYMARKET_PRIVATE_KEY,
                chain_id=self.chain_id,
            )
            self._api_creds = self._client.create_or_derive_api_creds()
            self._client.set_api_creds(self._api_creds)
        return self._client

    async def get_markets(self, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch active, non-closed markets from Polymarket Gamma API sorted by 24h volume."""
        gamma_url = settings.POLYMARKET_GAMMA_URL
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(
                    f"{gamma_url}/markets",
                    params={
                        "limit": limit,
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
        except Exception:
            return []

    async def get_token_id_from_market(self, market_id: str, outcome: str) -> Optional[str]:
        """Get token ID for a market outcome. Fetches market from Gamma API."""
        gamma_url = settings.POLYMARKET_GAMMA_URL
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(f"{gamma_url}/markets/{market_id}")
                if r.status_code != 200:
                    markets = await self.get_markets(limit=100)
                    for m in markets:
                        if str(m.get("conditionId", m.get("id", ""))) == market_id:
                            return self._extract_token_id(m, outcome)
                    return None
                m = r.json()
                return self._extract_token_id(m, outcome)
        except Exception:
            return None

    def _extract_token_id(self, market: dict[str, Any], outcome: str) -> Optional[str]:
        """Extract token_id from market dict for YES/NO outcome."""
        tokens = market.get("clobTokenIds") or market.get("tokens") or []
        if not isinstance(tokens, list) or len(tokens) < 2:
            return None
        yes_tok = tokens[0] if isinstance(tokens[0], dict) else {"token_id": tokens[0], "outcome": "Yes"}
        no_tok = tokens[1] if isinstance(tokens[1], dict) else {"token_id": tokens[1], "outcome": "No"}
        yes_id = yes_tok.get("token_id") if isinstance(yes_tok, dict) else str(yes_tok)
        no_id = no_tok.get("token_id") if isinstance(no_tok, dict) else str(no_tok)
        return yes_id if outcome.upper() == "YES" else no_id

    async def get_mid_price(self, market_id: str, outcome: str) -> Optional[float]:
        """Get midpoint price for a market outcome (convenience wrapper)."""
        token_id = await self.get_token_id_from_market(market_id, outcome)
        return await self.get_midpoint(token_id) if token_id else None

    async def get_order_book(self, token_id: str) -> dict[str, Any]:
        """Get order book for a market token."""
        def _fetch() -> dict[str, Any]:
            client = self._get_client()
            return client.get_order_book(token_id)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

    async def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """Get mid price for token."""
        def _fetch() -> Optional[float]:
            client = self._get_client()
            try:
                price = client.get_price(token_id, side=side)
                if price is not None:
                    return float(price) if not isinstance(price, float) else price
            except Exception:
                pass
            return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

    async def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price between best bid and ask."""
        try:
            ob = await self.get_order_book(token_id)
            bids = ob.get("bids", []) or []
            asks = ob.get("asks", []) or []
            best_bid = float(bids[0]["price"]) if bids else None
            best_ask = float(asks[0]["price"]) if asks else None
            if best_bid is not None and best_ask is not None:
                return (best_bid + best_ask) / 2
            return best_bid or best_ask
        except Exception:
            return None

    async def place_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        expiration: int = 0,
    ) -> Optional[dict[str, Any]]:
        """Size is in shares (outcome tokens), not USD."""
        """Place limit order. Returns order ID or None on failure."""
        def _place() -> Optional[dict[str, Any]]:
            try:
                client = self._get_client()
                order_args = OrderArgs(
                    token_id=token_id,
                    price=Decimal(str(price)),
                    size=Decimal(str(size)),
                    side=BUY if side.upper() == "BUY" else "SELL",
                )
                signed = client.create_and_sign_order(order_args, OrderType.GTC)
                resp = client.post_order(signed)
                return resp if isinstance(resp, dict) else {"orderId": str(resp)}
            except Exception:
                return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _place)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        def _cancel() -> bool:
            try:
                client = self._get_client()
                client.cancel(order_id)
                return True
            except Exception:
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _cancel)

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get open positions."""
        def _fetch() -> list[dict[str, Any]]:
            try:
                client = self._get_client()
                positions = client.get_balance_allowance() or []
                return positions if isinstance(positions, list) else [positions]
            except Exception:
                return []

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

    async def close(self) -> None:
        """Close HTTP client."""
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None
