"""
NEXUS CAPITAL - WebSocket Market Scanner
Uses wss://ws-subscriptions-clob.polymarket.com/ws/market.
Fallback: Gamma API polling every 30s if WebSocket fails.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional

import aiohttp
import httpx

from config.settings import settings
from data.polymarket_client import PolymarketClient
from core.edge_engine import EdgeEngine, EdgeSignal
from core.market_filter import passes_filter

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
PING_INTERVAL = 10.0
MARKETS_REFRESH_INTERVAL = 60.0
GAMMA_MARKETS_LIMIT = 200
GAMMA_FETCH_TIMEOUT = 15.0


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

    async def _fetch_markets_gamma(self) -> list[dict[str, Any]]:
        """Fetch markets from Gamma API with extended timeout (scanner critical path)."""
        base = getattr(settings, "POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com")
        url = f"{base.rstrip('/')}/markets"
        try:
            async with httpx.AsyncClient(timeout=GAMMA_FETCH_TIMEOUT) as client:
                r = await client.get(
                    url,
                    params={
                        "limit": GAMMA_MARKETS_LIMIT,
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
        except Exception as e:
            logger.warning("Gamma API fetch failed: %s", e)
            return []

    async def _refresh_markets(self) -> None:
        """Fetch markets and build token_id -> (market, side) map."""
        from core.market_filter import get_min_market_volume, get_min_liquidity

        try:
            markets = await self._fetch_markets_gamma()
            logger.info(
                "Scanner: Fetched %d raw markets from Gamma API | thresholds: MIN_VOLUME=%.0f, MIN_LIQUIDITY=%.0f",
                len(markets), get_min_market_volume(), get_min_liquidity(),
            )
            if not markets:
                logger.warning("Scanner: Gamma API returned 0 markets")
                return
            sample = markets[0]
            logger.info(
                "Scanner: sample market keys=%s | volume=%s liquidity=%s clobTokenIds=%s",
                list(sample.keys())[:15],
                sample.get("volume") or sample.get("volume24hr"),
                sample.get("liquidity"),
                str(sample.get("clobTokenIds", []))[:100],
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
                if isinstance(tokens, str):
                    try:
                        tokens = json.loads(tokens)
                    except (json.JSONDecodeError, TypeError):
                        tokens = []
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
            n_tokens = len(self._token_to_market)
            logger.info(
                "Scanner: Fetched %d tokens from %d markets | filtered=%d | no_tokens=%d",
                n_tokens, len(markets), filtered_count, no_tokens_count,
            )
            try:
                from paperclip_bridge import write_scanner_state
                write_scanner_state(token_count=n_tokens, market_count=n_tokens // 2)
            except Exception:
                pass
        except Exception as e:
            logger.warning("WebSocket scanner: failed to refresh markets: %s", e)

    async def _run(self) -> None:
        """Main WebSocket loop with reconnect. Falls back to polling if WS fails."""
        while self._running:
            try:
                await self._connect_and_process()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("WebSocket failed: %s — switching to polling fallback", e)
                await self._run_polling_fallback()

    async def _run_polling_fallback(self) -> None:
        """Fallback: poll Gamma API + order books every 30s when WS fails or no tokens."""
        logger.warning("Running polling fallback (Gamma API every 30s)")
        while self._running:
            try:
                await self._refresh_markets()
                n = len(self._token_to_market)
                if n == 0:
                    logger.warning("Polling fallback: 0 tokens, retry in 30s")
                    await asyncio.sleep(30)
                    continue
                for token_id, (market, side) in list(self._token_to_market.items())[:200]:
                    if not self._running:
                        break
                    try:
                        ob = await self.polymarket.get_order_book(token_id)
                        mid = _mid_from_book(
                            ob.get("bids") or [], ob.get("asks") or []
                        )
                        if mid is None or mid <= 0 or mid >= 1:
                            continue
                        sig = self.edge_engine.compute_edge(
                            market, token_id, side, mid, ob
                        )
                        if sig:
                            edge_pct = sig.edge_pct * 100
                            if edge_pct > 3.0:
                                q = (market.get("question") or "")[:50]
                                logger.info("POTENTIAL SIGNAL: %s edge=%.2f%% | %s", token_id[:16], edge_pct, q)
                        if sig and self.on_signal:
                            if asyncio.iscoroutinefunction(self.on_signal):
                                await self.on_signal(sig)
                            else:
                                self.on_signal(sig)
                    except Exception as e:
                        logger.debug("Polling market %s: %s", token_id[:16], e)
                try:
                    from paperclip_bridge import write_scanner_state
                    write_scanner_state(token_count=n, market_count=n // 2)
                except Exception:
                    pass
                logger.info("Polling fallback: processed %d tokens", n)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Polling fallback error: %s", e)
            await asyncio.sleep(30)

    async def _connect_and_process(self) -> None:
        """Connect, subscribe, process messages."""
        await self._refresh_markets()
        if not self._token_to_market:
            logger.warning("WebSocket scanner: no tokens — switching to polling fallback")
            await self._run_polling_fallback()
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
                logger.info("Connected to WS — subscribed to %d assets", len(asset_ids))

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
                q = (market.get("question") or "")[:40]
                logger.debug("Processing market: %s | %s", asset_id[:16], q)
                mid = _mid_from_book(bids, asks)
                if mid is None or mid <= 0 or mid >= 1:
                    return
                ob = _orderbook_from_event(bids, asks)
                sig = self.edge_engine.compute_edge(market, asset_id, side, mid, ob)
                if sig:
                    edge_pct = sig.edge_pct * 100
                    if edge_pct > 3.0:
                        q = (market.get("question") or "")[:50]
                        logger.info("POTENTIAL SIGNAL: %s edge=%.2f%% | %s", asset_id[:16], edge_pct, q)
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
