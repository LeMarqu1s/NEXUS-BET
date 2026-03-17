"""
NEXUS BET - Position Manager
Capital management and position sizing.
"""

from dataclasses import dataclass
from typing import Optional

from config.settings import settings


@dataclass
class Position:
    """Single position record."""
    market_id: str
    outcome: str
    size_usd: float
    entry_price: float
    unrealized_pnl: float = 0.0


class PositionManager:
    """Manages capital allocation and position limits."""

    def __init__(self):
        self.max_position_pct = settings.MAX_POSITION_PCT
        self.max_total_exposure = settings.MAX_TOTAL_EXPOSURE_USD
        self.positions: dict[str, Position] = {}

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
        # Kelly-inspired: size = kelly * capital
        capital = settings.POLYMARKET_CAPITAL_USD or 100.0
        raw_size = capital * kelly_fraction
        # Cap by edge (higher edge = allow slightly more)
        edge_mult = min(1.0 + edge_bps / 10000, 1.5)
        size = min(raw_size * edge_mult, self.max_total_exposure * self.max_position_pct)
        return round(size, 2)

    def add_position(self, market_id: str, outcome: str, size_usd: float, entry_price: float):
        """Register new position."""
        key = f"{market_id}:{outcome}"
        self.positions[key] = Position(
            market_id=market_id,
            outcome=outcome,
            size_usd=size_usd,
            entry_price=entry_price,
        )

    def remove_position(self, market_id: str, outcome: str):
        """Remove closed position."""
        key = f"{market_id}:{outcome}"
        self.positions.pop(key, None)

    def update_pnl(self, market_id: str, outcome: str, current_price: float):
        """Update unrealized PnL for a position."""
        key = f"{market_id}:{outcome}"
        if key in self.positions:
            p = self.positions[key]
            p.unrealized_pnl = (current_price - p.entry_price) * p.size_usd / p.entry_price
