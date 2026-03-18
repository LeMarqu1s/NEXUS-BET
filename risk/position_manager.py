"""
NEXUS BET - Position Manager
Capital management and position sizing with Supabase persistence.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from config.settings import settings

log = logging.getLogger("nexus.positions")


@dataclass
class Position:
    """Single position record."""
    market_id: str
    outcome: str          # YES or NO
    size_usd: float
    entry_price: float
    unrealized_pnl: float = 0.0
    token_id: str = ""


class PositionManager:
    """Manages capital allocation and position limits. Persists to Supabase."""

    def __init__(self):
        self.max_position_pct = settings.MAX_POSITION_PCT
        self.max_total_exposure = settings.MAX_TOTAL_EXPOSURE_USD
        self.positions: dict[str, Position] = {}
        self._load_from_supabase()

    # ------------------------------------------------------------------
    # Supabase persistence helpers
    # ------------------------------------------------------------------

    def _get_supabase(self):
        """Return the Supabase raw client, or None."""
        try:
            from supabase_client import supabase_client
            return supabase_client._get_client()
        except Exception:
            return None

    def _load_from_supabase(self) -> None:
        """Load OPEN positions from Supabase at startup."""
        try:
            client = self._get_supabase()
            if not client:
                return
            result = client.table("positions").select("*").eq("status", "OPEN").execute()
            rows = result.data or []
            for row in rows:
                mid = row.get("market_id", "")
                side = row.get("side", "YES")
                token_id = row.get("token_id", "")
                key = f"{mid}:{side}"
                self.positions[key] = Position(
                    market_id=mid,
                    outcome=side,
                    size_usd=float(row.get("cost_basis_usd", 0)),
                    entry_price=float(row.get("avg_entry_price", 0)),
                    unrealized_pnl=float(row.get("unrealized_pnl", 0) or 0),
                    token_id=token_id,
                )
            if rows:
                log.info("Loaded %d open positions from Supabase", len(rows))
        except Exception as e:
            log.warning("Could not load positions from Supabase (starting empty): %s", e)

    def _upsert_to_supabase(self, pos: Position, status: str = "OPEN") -> None:
        """Upsert a position row to Supabase (fire-and-forget)."""
        try:
            client = self._get_supabase()
            if not client:
                return
            shares = pos.size_usd / pos.entry_price if pos.entry_price > 0 else 0
            payload = {
                "market_id": pos.market_id,
                "token_id": pos.token_id or pos.outcome,
                "side": pos.outcome,
                "shares": round(shares, 6),
                "avg_entry_price": round(pos.entry_price, 4),
                "cost_basis_usd": round(pos.size_usd, 6),
                "unrealized_pnl": round(pos.unrealized_pnl, 6),
                "status": status,
                "metadata": {},
            }
            client.table("positions").upsert(
                payload, on_conflict="market_id,token_id"
            ).execute()
        except Exception as e:
            log.warning("Supabase upsert_position failed: %s", e)

    def _close_in_supabase(self, pos: Position) -> None:
        """Mark a position as CLOSED in Supabase."""
        try:
            client = self._get_supabase()
            if not client:
                return
            token_id = pos.token_id or pos.outcome
            client.table("positions").update(
                {"status": "CLOSED", "closed_at": "now()"}
            ).eq("market_id", pos.market_id).eq("token_id", token_id).execute()
        except Exception as e:
            log.warning("Supabase close_position failed: %s", e)

    # ------------------------------------------------------------------
    # Public API (unchanged signatures)
    # ------------------------------------------------------------------

    def total_exposure(self) -> float:
        """Total USD at risk across all positions."""
        return sum(p.size_usd for p in self.positions.values())

    def position_count(self) -> int:
        return len(self.positions)

    def can_open_position(self, size_usd: float) -> tuple[bool, str]:
        """Check if new position is allowed under risk limits."""
        if size_usd <= 0:
            return False, "Size must be positive"
        if self.total_exposure() + size_usd > self.max_total_exposure:
            return False, f"Would exceed max total exposure ${self.max_total_exposure}"
        pct = size_usd / self.max_total_exposure
        if pct > self.max_position_pct:
            return False, f"Position would exceed max single position {self.max_position_pct:.0%}"
        return True, "OK"

    def allocate_size(self, kelly_fraction: float, edge_bps: float) -> float:
        """Compute position size from Kelly fraction and edge."""
        capital = settings.POLYMARKET_CAPITAL_USD or 100.0
        raw_size = capital * kelly_fraction
        edge_mult = min(1.0 + edge_bps / 10000, 1.5)
        size = min(raw_size * edge_mult, self.max_total_exposure * self.max_position_pct)
        return round(size, 2)

    def add_position(
        self, market_id: str, outcome: str, size_usd: float, entry_price: float, token_id: str = ""
    ):
        """Register new position and persist to Supabase."""
        key = f"{market_id}:{outcome}"
        pos = Position(
            market_id=market_id,
            outcome=outcome,
            size_usd=size_usd,
            entry_price=entry_price,
            token_id=token_id,
        )
        self.positions[key] = pos
        self._upsert_to_supabase(pos)

    def remove_position(self, market_id: str, outcome: str):
        """Remove closed position and mark CLOSED in Supabase."""
        key = f"{market_id}:{outcome}"
        pos = self.positions.pop(key, None)
        if pos:
            self._close_in_supabase(pos)

    def update_pnl(self, market_id: str, outcome: str, current_price: float):
        """Update unrealized PnL for a position and sync to Supabase."""
        key = f"{market_id}:{outcome}"
        if key in self.positions:
            p = self.positions[key]
            p.unrealized_pnl = (current_price - p.entry_price) * p.size_usd / p.entry_price
            self._upsert_to_supabase(p)
