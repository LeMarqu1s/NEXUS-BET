"""
NEXUS CAPITAL - WebSocket Market Scanner
Uses wss://ws-subscriptions-clob.polymarket.com/ws/market instead of polling.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional

import aiohttp

from config.settings import settings
from data.polymarket_client import PolymarketClient
from core.edge_engine import EdgeEngine, EdgeSignal
from core.market_filter import passes_filter

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
PING_INTERVAL = 10.0
MARKETS_REFRESH_INTERVAL = 60.0


def _mid_from_book(bids: list, asks: list) -> Optional[float]:
    """Compute mid price from bids/asks."""
    best_bid = float(bids[0]["price"]) if bids else None
    best_ask = float(asks[0]["price"]) if asks else None
    if best_bid is not None and best_ask is not None:
        return (best_bid + best_ask) / 2
    return best_bid or best_ask


def _orderbook_from_event(bids: list, asks: list) -> dict[str, Any]:
    """WebSocket book format matches scanner format: bids/asks with price, size."""
    return {"bids": bids or [], "asks": asks or []}


class WebSocketScanner:
    """Market scanner via Polymarket WebSocket."""

    def __init__(
        self,
        polymarket: PolymarketClient,
        edge_engine: EdgeEngine,
        on_signal: Optional[Callable[[EdgeSignal], Any]] = None,
    ) -> None:
        self.polymarket = polymarket
        self.edge_engine = edge_engine
        self.on_signal = on_signal
        self._running = False
        self._task: Optional[asyncio.Task[None]] = None
        self._token_to_market: dict[str, tuple[dict, str]] = {}  # token_id -> (market, side)
        self._last_markets_refresh = 0.0

    async def _refresh_markets(self) -> None:
        """Fetch markets and build token_id -> (market, side) map."""
        from core.market_filter import get_min_market_volume, get_min_liquidity
        try:
            markets = await self.polymarket.get_markets(limit=100)
            logger.info(
                "Scanner: %d raw markets from Gamma API | thresholds: MIN_VOLUME=%.0f, MIN_LIQUIDITY=%.0f",
                len(markets), get_min_market_volume(), get_min_liquidity(),
            )
            if markets:
                sample = markets[0]
                logger.info(
                    "Scanner: sample market keys=%s | volumeNum=%s liquidity=%s liquidityNum=%s volume24hr=%s clobTokenIds=%s",
                    list(sample.keys())[:20],
                    sample.get("volumeNum"), sample.get("liquidity"),
                    sample.get("liquidityNum"), sample.get("volume24hr"),
                    str(sample.get("clobTokenIds", []))[:80],
                )
            self._token_to_market.clear()
            filtered_count = 0
            no_tokens_count = 0
            for market in markets:
                q = (market.get("question") or "")[:60]
                reason: list[str] = []
                if not passes_filter(market, reason_out=reason):
                    if filtered_count < 5:
                        logger.info("  REJECTED: %s → %s", q, reason[0] if reason else "unknown")
                    filtered_count += 1
                    continue
                tokens = market.get("clobTokenIds") or market.get("tokens") or []
                if not isinstance(tokens, list) or len(tokens) < 2:
                    if no_tokens_count < 3:
                        logger.info("  NO_TOKENS: %s → clobTokenIds=%s", q, tokens)
                    no_tokens_count += 1
                    continue
                yes_tok = tokens[0] if isinstance(tokens[0], dict) else {"token_id": tokens[0]}
                no_tok = tokens[1] if isinstance(tokens[1], dict) else {"token_id": tokens[1]}
                yes_id = yes_tok.get("token_id") if isinstance(yes_tok, dict) else str(yes_tok)
                no_id = no_tok.get("token_id") if isinstance(no_tok, dict) else str(no_tok)
                if yes_id:
                    self._token_to_market[str(yes_id)] = (market, "YES")
                if no_id:
                    self._token_to_market[str(no_id)] = (market, "NO")
            self._last_markets_refresh = time.monotonic()
            logger.info(
                "Scanner: %d tokens retained | %d filtered out | %d no tokens",
                len(self._token_to_market), filtered_count, no_tokens_count,
            )
        except Exception as e:
            logger.warning("WebSocket scanner: failed to refresh markets: %s", e)

    async def _run(self) -> None:
        """Main WebSocket loop with reconnect."""
        while self._running:
            try:
                await self._connect_and_process()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("WebSocket scanner error: %s, reconnecting in 5s", e)
                await asyncio.sleep(5)

    async def _connect_and_process(self) -> None:
        """Connect, subscribe, process messages."""
        await self._refresh_markets()
        if not self._token_to_market:
            logger.warning("WebSocket scanner: no markets, retrying in 30s")
            await asyncio.sleep(30)
            return

        asset_ids = list(self._token_to_market.keys())
        subscribe_msg = json.dumps({
            "assets_ids": asset_ids,
            "type": "market",
            "custom_feature_enabled": True,
        })

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(WS_URL) as ws:
                await ws.send_str(subscribe_msg)
                logger.info("WebSocket scanner connected, subscribed to %d assets", len(asset_ids))

                last_ping = time.monotonic()
                last_markets = last_ping

                async for msg in ws:
                    if not self._running:
                        break
                    now = time.monotonic()

                    # Refresh markets periodically
                    if now - last_markets > MARKETS_REFRESH_INTERVAL:
                        await self._refresh_markets()
                        last_markets = now

                    # PING every 10s
                    if now - last_ping > PING_INTERVAL:
                        await ws.send_str("PING")
                        last_ping = now

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        break

    async def _handle_message(self, data: str) -> None:
        """Process WebSocket message (book, price_change, etc.)."""
        try:
            obj = json.loads(data) if isinstance(data, str) else data
            if not isinstance(obj, dict):
                return
            event_type = obj.get("event_type") or obj.get("type")
            asset_id = str(obj.get("asset_id", ""))
            if not asset_id:
                return

            if event_type == "book":
                bids = obj.get("bids") or []
                asks = obj.get("asks") or []
                entry = self._token_to_market.get(asset_id)
                if not entry:
                    return
                market, side = entry
                mid = _mid_from_book(bids, asks)
                if mid is None or mid <= 0 or mid >= 1:
                    return
                ob = _orderbook_from_event(bids, asks)
                sig = self.edge_engine.compute_edge(market, asset_id, side, mid, ob)
                if sig and self.on_signal:
                    try:
                        if asyncio.iscoroutinefunction(self.on_signal):
                            await self.on_signal(sig)
                        else:
                            self.on_signal(sig)
                    except Exception as e:
                        logger.warning("WebSocket on_signal error: %s", e)

            elif event_type == "price_change":
                # price_change can have price level updates; for full book we rely on book
                pass
        except Exception as e:
            logger.debug("WebSocket message parse error: %s", e)

    def start(self) -> None:
        """Start the WebSocket scanner."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("WebSocket scanner started")

    async def stop(self) -> None:
        """Stop the WebSocket scanner."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("WebSocket scanner stopped")


async def run_scanner_ws() -> None:
    """
    Main entry point for WebSocket market scanner.
    Replaces polling with real-time WebSocket updates.
    """
    polymarket = PolymarketClient()
    edge_engine = EdgeEngine()
    try:
        from paperclip_bridge import on_signal as paperclip_on_signal
        _on_signal = paperclip_on_signal
    except ImportError:
        _on_signal = None

    scanner = WebSocketScanner(
        polymarket=polymarket,
        edge_engine=edge_engine,
        on_signal=_on_signal,
    )
    scanner.start()
    try:
        while scanner._running and scanner._task:
            await asyncio.sleep(1)
            if scanner._task.done():
                break
    except asyncio.CancelledError:
        pass
    finally:
        await scanner.stop()
        await polymarket.close()
