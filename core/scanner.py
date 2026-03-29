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

    @staticmethod
    def _mid_from_book(ob: dict) -> float | None:
        """Compute midpoint from an order book dict."""
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2
        return best_bid or best_ask

    async def _scan_once(self) -> list[EdgeSignal]:
        """Run a single scan pass over markets using batch book fetch."""
        signals: list[EdgeSignal] = []
        try:
            markets = await self.polymarket.get_markets(limit=50)
        except Exception as e:
            logger.warning("Scanner: failed to fetch markets: %s", e)
            return signals

        # Collect all token IDs in one pass
        market_tokens: list[tuple[dict, str, str, str, str]] = []  # (market, yes_id, no_id, ...)
        all_token_ids: list[str] = []
        for market in markets:
            try:
                tokens = market.get("clobTokenIds") or market.get("tokens") or []
                if not isinstance(tokens, list) or len(tokens) < 2:
                    continue
                yes_tok = tokens[0] if isinstance(tokens[0], dict) else {"token_id": tokens[0]}
                no_tok = tokens[1] if isinstance(tokens[1], dict) else {"token_id": tokens[1]}
                yes_id = (yes_tok.get("token_id") if isinstance(yes_tok, dict) else str(yes_tok)) or ""
                no_id = (no_tok.get("token_id") if isinstance(no_tok, dict) else str(no_tok)) or ""
                if yes_id and no_id:
                    market_tokens.append((market, yes_id, no_id))
                    all_token_ids.extend([yes_id, no_id])
            except Exception:
                continue

        if not all_token_ids:
            return signals

        # 1 batch call for all order books instead of N serial calls
        books = await self.polymarket.get_batch_books(all_token_ids)

        for market, yes_id, no_id in market_tokens:
            try:
                ob_yes = books.get(yes_id) or {}
                ob_no = books.get(no_id) or {}
                price_yes = self._mid_from_book(ob_yes)
                price_no = self._mid_from_book(ob_no)

                if price_yes is not None:
                    sig = self.edge_engine.compute_edge(market, yes_id, "YES", price_yes, ob_yes)
                    if sig:
                        signals.append(sig)

                if price_no is not None:
                    sig = self.edge_engine.compute_edge(market, no_id, "NO", price_no, ob_no)
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
