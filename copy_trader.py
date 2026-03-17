"""
NEXUS BET - Copy-Trader Polymarket
Stratégie: repérer les portefeuilles Polymarket les plus rentables et calquer leurs mouvements.
API: data-api.polymarket.com (leaderboard, positions, trades).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

DATA_API_URL = "https://data-api.polymarket.com"

log = logging.getLogger(__name__)


@dataclass
class TraderProfile:
    """Profil d'un trader du leaderboard."""
    rank: int
    proxy_wallet: str
    user_name: str
    pnl: float
    vol: float
    profile_image: Optional[str] = None
    verified: bool = False


@dataclass
class TraderPosition:
    """Position ouverte d'un trader."""
    market_id: str
    outcome: str  # YES | NO
    size: float
    avg_price: float
    current_value: Optional[float] = None


@dataclass
class CopyTarget:
    """Cible de copy-trading avec métriques."""
    profile: TraderProfile
    positions: list[TraderPosition] = field(default_factory=list)
    recent_trades_count: int = 0


class PolymarketCopyTrader:
    """
    Moteur Copy-Trading Polymarket.
    - Récupère le leaderboard (PNL, volume)
    - Identifie les traders les plus rentables
    - Récupère leurs positions et trades récents
    - Prépare les signaux pour réplication
    """

    def __init__(self, data_api_url: str = DATA_API_URL) -> None:
        self.data_api_url = data_api_url.rstrip("/")

    async def get_leaderboard(
        self,
        category: str = "OVERALL",
        time_period: str = "MONTH",
        order_by: str = "PNL",
        limit: int = 25,
        offset: int = 0,
    ) -> list[TraderProfile]:
        """Récupère le leaderboard des traders les plus rentables."""
        url = f"{self.data_api_url}/v1/leaderboard"
        params = {
            "category": category,
            "timePeriod": time_period,
            "orderBy": order_by,
            "limit": limit,
            "offset": offset,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.warning("Leaderboard fetch failed: %s", e)
            return []

        profiles: list[TraderProfile] = []
        for i, entry in enumerate(data if isinstance(data, list) else []):
            try:
                profiles.append(TraderProfile(
                    rank=i + 1 + offset,
                    proxy_wallet=entry.get("proxyWallet", ""),
                    user_name=entry.get("userName", "Unknown"),
                    pnl=float(entry.get("pnl", 0)),
                    vol=float(entry.get("vol", 0)),
                    profile_image=entry.get("profileImage"),
                    verified=bool(entry.get("verifiedBadge", False)),
                ))
            except (TypeError, ValueError):
                pass
        return profiles

    async def get_positions(self, wallet: str) -> list[TraderPosition]:
        """Récupère les positions actuelles d'un trader."""
        url = f"{self.data_api_url}/positions"
        params = {"user": wallet, "limit": 100}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.warning("Positions fetch failed for %s: %s", wallet[:10], e)
            return []

        positions: list[TraderPosition] = []
        for p in (data if isinstance(data, list) else []):
            try:
                market_id = str(p.get("conditionId", p.get("market", "")))
                outcome = (p.get("outcome") or "YES").upper()
                if outcome not in ("YES", "NO"):
                    outcome = "YES" if (p.get("outcomeIndex", 0) == 0) else "NO"
                positions.append(TraderPosition(
                    market_id=market_id,
                    outcome=outcome,
                    size=float(p.get("size", 0)),
                    avg_price=float(p.get("avgPrice", p.get("curPrice", 0))),
                    current_value=float(p["currentValue"]) if "currentValue" in p else None,
                ))
            except (TypeError, ValueError, KeyError):
                pass
        return positions

    async def get_recent_trades(self, wallet: str, limit: int = 50) -> list[dict[str, Any]]:
        """Récupère les trades récents d'un trader."""
        url = f"{self.data_api_url}/trades"
        params = {"user": wallet, "limit": limit}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.warning("Trades fetch failed for %s: %s", wallet[:10], e)
            return []
        return data if isinstance(data, list) else []

    async def discover_top_traders(
        self,
        top_n: int = 10,
        min_pnl: float = 1000.0,
        min_vol: float = 10000.0,
    ) -> list[CopyTarget]:
        """
        Découvre les top traders et enrichit avec leurs positions.
        Filtre: PnL > min_pnl, volume > min_vol.
        """
        profiles = await self.get_leaderboard(
            time_period="MONTH",
            order_by="PNL",
            limit=top_n,
        )
        targets: list[CopyTarget] = []
        for p in profiles:
            if p.pnl < min_pnl or p.vol < min_vol:
                continue
            positions = await self.get_positions(p.proxy_wallet)
            trades = await self.get_recent_trades(p.proxy_wallet, limit=20)
            targets.append(CopyTarget(
                profile=p,
                positions=positions,
                recent_trades_count=len(trades),
            ))
        return targets

    async def get_copy_signals(self, target: CopyTarget) -> list[dict[str, Any]]:
        """
        Transforme les positions d'un CopyTarget en signaux pour réplication.
        """
        signals: list[dict[str, Any]] = []
        for pos in target.positions:
            if pos.size <= 0:
                continue
            signals.append({
                "market_id": pos.market_id,
                "outcome": pos.outcome,
                "size": pos.size,
                "avg_price": pos.avg_price,
                "source": "copy_trader",
                "trader": target.profile.user_name,
                "trader_pnl": target.profile.pnl,
            })
        return signals


async def run_copy_discovery(limit: int = 5) -> list[CopyTarget]:
    """Point d'entrée: découvre les top traders pour copy-trading."""
    ct = PolymarketCopyTrader()
    return await ct.discover_top_traders(top_n=limit, min_pnl=500.0, min_vol=5000.0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    targets = asyncio.run(run_copy_discovery(limit=5))
    for t in targets:
        print(f"#{t.profile.rank} {t.profile.user_name} | PnL: ${t.profile.pnl:,.0f} | "
              f"Positions: {len(t.positions)} | Trades: {t.recent_trades_count}")
</think>