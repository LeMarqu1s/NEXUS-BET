"""
NEXUS BET - Market Scanner
Async market scan loop every 10 seconds.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from config.settings import settings
from data.polymarket_client import PolymarketClient
from core.edge_engine import EdgeEngine, EdgeSignal

logger = logging.getLogger(__name__)


class MarketScanner:
    """Async market scanner with configurable scan interval."""

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
        self.scan_interval = getattr(
            settings,
            "SCAN_INTERVAL_SECONDS",
            10,
        )

    async def _scan_once(self) -> list[EdgeSignal]:
        """Run a single scan pass over markets."""
        signals: list[EdgeSignal] = []
        try:
            markets = await self.polymarket.get_markets(limit=50)
        except Exception as e:
            logger.warning("Scanner: failed to fetch markets: %s", e)
            return signals

        for market in markets:
            try:
                tokens = market.get("clobTokenIds") or market.get("tokens") or []
                if isinstance(tokens, list) and len(tokens) >= 2:
                    # Binary market: YES and NO tokens
                    yes_token = tokens[0] if isinstance(tokens[0], dict) else {"token_id": tokens[0]}
                    no_token = tokens[1] if isinstance(tokens[1], dict) else {"token_id": tokens[1]}
                    yes_id = yes_token.get("token_id") if isinstance(yes_token, dict) else str(yes_token)
                    no_id = no_token.get("token_id") if isinstance(no_token, dict) else str(no_token)
                    if not yes_id or not no_id:
                        continue
                else:
                    continue

                ob_yes = await self.polymarket.get_order_book(yes_id)
                ob_no = await self.polymarket.get_order_book(no_id)
                price_yes = await self.polymarket.get_midpoint(yes_id) or await self.polymarket.get_price(yes_id)
                price_no = await self.polymarket.get_midpoint(no_id) or await self.polymarket.get_price(no_id)

                if price_yes is not None:
                    sig = self.edge_engine.compute_edge(
                        market, yes_id, "YES", price_yes, ob_yes
                    )
                    if sig:
                        signals.append(sig)

                if price_no is not None:
                    sig = self.edge_engine.compute_edge(
                        market, no_id, "NO", price_no, ob_no
                    )
                    if sig:
                        signals.append(sig)

            except Exception as e:
                logger.debug("Scanner: error processing market %s: %s", market.get("id"), e)

        return signals

    async def _loop(self) -> None:
        """Main scan loop."""
        while self._running:
            try:
                signals = await self._scan_once()
                for sig in signals:
                    if self.on_signal:
                        try:
                            if asyncio.iscoroutinefunction(self.on_signal):
                                await self.on_signal(sig)
                            else:
                                self.on_signal(sig)
                        except Exception as e:
                            logger.warning("Scanner: on_signal error: %s", e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Scanner: loop error: %s", e)

            await asyncio.sleep(self.scan_interval)

    def start(self) -> None:
        """Start the scanner loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Scanner started (interval=%ss)", self.scan_interval)

    async def stop(self) -> None:
        """Stop the scanner loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Scanner stopped")


async def run_scanner() -> None:
    """
    Main entry point for the market scanner.
    Creates Polymarket client, EdgeEngine, MarketScanner and runs the scan loop.
    Connects to agents/execution via on_signal callback (optional).
    """
    polymarket = PolymarketClient()
    edge_engine = EdgeEngine()
    # Hook Paperclip: signaux écrits dans paperclip_pending_signals.json
    try:
        from paperclip_bridge import on_signal as paperclip_on_signal
        _on_signal = paperclip_on_signal
    except ImportError:
        _on_signal = None

    scanner = MarketScanner(
        polymarket=polymarket,
        edge_engine=edge_engine,
        on_signal=_on_signal,  # Paperclip bridge ou pipeline execution
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
