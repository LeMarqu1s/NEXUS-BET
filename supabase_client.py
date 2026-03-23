"""
NEXUS BET - Supabase logging client for trades, debates, positions, smart money.
Hardened: retry 3x, never raise — if Supabase down, continue without logging.
"""

import asyncio
from typing import Any, Optional
from datetime import datetime

from supabase import create_client, Client
from config.settings import settings

DB_RETRIES = 3


class SupabaseClient:
    """Async-friendly Supabase client for NEXUS BET logging."""

    def __init__(self):
        self._client: Optional[Client] = None
        self._loop = asyncio.get_event_loop()

    def _get_client(self) -> Client:
        if self._client is None and settings.SUPABASE_URL and settings.SUPABASE_KEY:
            self._client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_KEY,
            )
        return self._client

    def _run_sync(self, coro_or_fn, *args, **kwargs) -> Any:
        """Run sync Supabase calls in executor to not block event loop."""
        if asyncio.iscoroutinefunction(coro_or_fn):
            return coro_or_fn(*args, **kwargs)
        return asyncio.get_event_loop().run_in_executor(
            None, lambda: coro_or_fn(*args, **kwargs)
        )

    async def log_trade(
        self,
        market_id: str,
        token_id: str,
        side: str,
        amount_usd: float,
        shares: float,
        price: float,
        order_type: str = "LIMIT",
        status: str = "PENDING",
        market_question: Optional[str] = None,
        raw_order_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[str]:
        """Insert trade record, returns trade_id."""
        client = self._get_client()
        if not client:
            return None

        def _insert():
            for _ in range(DB_RETRIES):
                try:
                    result = client.table("trades").insert(
                        {
                            "market_id": market_id,
                            "token_id": token_id,
                            "side": side,
                            "amount_usd": amount_usd,
                            "shares": shares,
                            "price": price,
                            "order_type": order_type,
                            "status": status,
                            "market_question": market_question,
                            "raw_order_id": raw_order_id,
                            "metadata": metadata or {},
                        }
                    ).execute()
                    if result.data and len(result.data) > 0:
                        return result.data[0].get("id")
                    return None
                except Exception:
                    pass
                import time
                time.sleep(2)
            return None

        return await asyncio.get_event_loop().run_in_executor(None, _insert)

    async def update_trade(
        self,
        trade_id: str,
        status: Optional[str] = None,
        pnl_usd: Optional[float] = None,
        exit_reason: Optional[str] = None,
        filled_at: Optional[datetime] = None,
    ) -> bool:
        """Update trade status and PnL."""
        client = self._get_client()
        if not client:
            return False

        updates = {}
        if status:
            updates["status"] = status
        if pnl_usd is not None:
            updates["pnl_usd"] = pnl_usd
        if exit_reason:
            updates["exit_reason"] = exit_reason
        if filled_at:
            updates["filled_at"] = filled_at.isoformat()

        if not updates:
            return True

        def _update():
            client.table("trades").update(updates).eq("id", trade_id).execute()
            return True

        await asyncio.get_event_loop().run_in_executor(None, _update)
        return True

    async def log_debate(
        self,
        trade_id: Optional[str],
        market_id: Optional[str],
        round_num: int,
        role: str,
        content: str,
        vote: Optional[str] = None,
        tokens_used: Optional[int] = None,
        model_used: Optional[str] = None,
    ) -> bool:
        """Log adversarial debate entry."""
        client = self._get_client()
        if not client:
            return False

        def _insert():
            client.table("agent_debates").insert(
                {
                    "trade_id": trade_id,
                    "market_id": market_id,
                    "round": round_num,
                    "role": role,
                    "content": content,
                    "vote": vote,
                    "tokens_used": tokens_used,
                    "model_used": model_used,
                }
            ).execute()
            return True

        await asyncio.get_event_loop().run_in_executor(None, _insert)
        return True

    async def upsert_position(
        self,
        market_id: str,
        token_id: str,
        side: str,
        shares: float,
        avg_entry_price: float,
        cost_basis_usd: float,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        status: str = "OPEN",
        metadata: Optional[dict] = None,
    ) -> bool:
        """Insert or update position."""
        client = self._get_client()
        if not client:
            return False

        payload = {
            "market_id": market_id,
            "token_id": token_id,
            "side": side,
            "shares": shares,
            "avg_entry_price": avg_entry_price,
            "cost_basis_usd": cost_basis_usd,
            "take_profit_price": take_profit_price,
            "stop_loss_price": stop_loss_price,
            "status": status,
            "metadata": metadata or {},
        }

        def _upsert():
            client.table("positions").upsert(
                payload, on_conflict="market_id,token_id"
            ).execute()
            return True

        await asyncio.get_event_loop().run_in_executor(None, _upsert)
        return True

    async def log_smart_money_signal(
        self,
        symbol: Optional[str] = None,
        market_ticker: Optional[str] = None,
        signal_type: Optional[str] = None,
        flow_data: Optional[dict] = None,
        confidence_score: Optional[float] = None,
    ) -> bool:
        """Log Unusual Whales / smart money signal."""
        client = self._get_client()
        if not client:
            return False

        def _insert():
            client.table("smart_money_signals").insert(
                {
                    "symbol": symbol,
                    "market_ticker": market_ticker,
                    "signal_type": signal_type,
                    "flow_data": flow_data or {},
                    "confidence_score": confidence_score,
                }
            ).execute()
            return True

        await asyncio.get_event_loop().run_in_executor(None, _insert)
        return True

    async def start_bot_run(self) -> Optional[str]:
        """Start a bot run session."""
        client = self._get_client()
        if not client:
            return None

        def _insert():
            result = client.table("bot_runs").insert(
                {"status": "RUNNING"}
            ).execute()
            if result.data and len(result.data) > 0:
                return result.data[0].get("id")
            return None

        return await asyncio.get_event_loop().run_in_executor(None, _insert)

    async def end_bot_run(
        self,
        run_id: str,
        markets_scanned: int = 0,
        trades_executed: int = 0,
        total_pnl_usd: float = 0,
        error_message: Optional[str] = None,
    ) -> bool:
        """End bot run with stats."""
        client = self._get_client()
        if not client:
            return False

        def _update():
            client.table("bot_runs").update(
                {
                    "ended_at": datetime.utcnow().isoformat(),
                    "status": "ERROR" if error_message else "STOPPED",
                    "markets_scanned": markets_scanned,
                    "trades_executed": trades_executed,
                    "total_pnl_usd": total_pnl_usd,
                    "error_message": error_message,
                }
            ).eq("id", run_id).execute()
            return True

        await asyncio.get_event_loop().run_in_executor(None, _update)
        return True


supabase_client = SupabaseClient()
