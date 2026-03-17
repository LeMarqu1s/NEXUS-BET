"""
NEXUS BET - Order Manager
Limit orders with auto take-profit and stop-loss.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

from config.settings import settings
from data.polymarket_client import PolymarketClient


@dataclass
class OrderConfig:
    """Order configuration with TP/SL."""
    market_id: str
    outcome: str  # YES or NO
    side: str  # BUY or SELL
    size_usd: float
    limit_price: float
    take_profit_pct: Optional[float] = None  # e.g. 0.15 = 15%
    stop_loss_pct: Optional[float] = None    # e.g. 0.10 = 10%


class OrderManager:
    """Manages limit orders with TP/SL tracking."""

    def __init__(self):
        self.client = PolymarketClient()
        self.active_orders: dict[str, OrderConfig] = {}
        self._monitor_task: Optional[asyncio.Task] = None

    async def place_limit_order(self, cfg: OrderConfig) -> Optional[str]:
        """Place limit order on Polymarket. Returns order_id or None."""
        try:
            token_id = await self.client.get_token_id_from_market(cfg.market_id, cfg.outcome)
            if not token_id:
                return None
            # Polymarket uses size in shares: shares = amount_usd / price
            size_shares = cfg.size_usd / cfg.limit_price if cfg.limit_price > 0 else 0
            if size_shares <= 0:
                return None
            result = await self.client.place_limit_order(
                token_id=token_id,
                side=cfg.side,
                price=cfg.limit_price,
                size=size_shares,
            )
            if not result:
                return None
            order_id = result.get("orderID") or result.get("orderId") if isinstance(result, dict) else str(result)
            if order_id and (cfg.take_profit_pct or cfg.stop_loss_pct):
                self.active_orders[order_id] = cfg
            return order_id
        except Exception as e:
            if settings.DEBUG:
                print(f"[OrderManager] place_limit_order error: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        try:
            success = await self.client.cancel_order(order_id)
            self.active_orders.pop(order_id, None)
            return success
        except Exception:
            return False

    def _should_tp_or_sl(self, entry_price: float, current_price: float, cfg: OrderConfig) -> Optional[str]:
        """Check if TP or SL triggered. Returns 'tp', 'sl', or None."""
        pct_change = (current_price - entry_price) / entry_price if entry_price else 0
        if cfg.take_profit_pct and pct_change >= cfg.take_profit_pct:
            return "tp"
        if cfg.stop_loss_pct and pct_change <= -cfg.stop_loss_pct:
            return "sl"
        return None

    async def start_monitor_loop(self, interval_sec: float = 30.0):
        """Background loop to check TP/SL on active orders."""
        while True:
            await asyncio.sleep(interval_sec)
            for order_id, cfg in list(self.active_orders.items()):
                try:
                    # In production: fetch current market price from Polymarket
                    # For now, just placeholder - actual price fetch in polymarket_client
                    current_price = await self.client.get_mid_price(cfg.market_id, cfg.outcome)
                    if current_price is None:
                        continue
                    trigger = self._should_tp_or_sl(cfg.limit_price, current_price, cfg)
                    if trigger:
                        await self.cancel_order(order_id)
                        # Emit event for TP/SL hit (handled by trade_logger / telegram)
                except Exception:
                    pass

    def stop_monitor(self):
        """Stop TP/SL monitor loop."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
