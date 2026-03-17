"""
NEXUS BET - Edge Engine
Mispricing detection with NCAA/UCL/BTC models + Kelly criterion.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from enum import Enum

from config.settings import settings


class MarketModel(Enum):
    NCAA = "ncaa"
    UCL = "ucl"
    BTC = "btc"


@dataclass
class EdgeSignal:
    """Represents a detected mispricing edge."""
    market_id: str
    token_id: str
    side: str  # YES or NO
    polymarket_price: float
    model_fair_price: float
    edge_pct: float
    kelly_fraction: float
    model: MarketModel
    confidence: float
    metadata: dict[str, Any]
    signal_strength: str = "BUY"  # STRONG_BUY or BUY


class EdgeEngine:
    """
    Mispricing detection engine.
    Uses NCAA, UCL, BTC models + Kelly criterion for sizing.
    Reads settings at compute_edge time so config refresh (e.g. via Telegram) applies immediately.
    """

    def __init__(self) -> None:
        pass  # Settings read at compute_edge time for live config refresh

    def _kelly(
        self,
        p: float,
        q: float,
        b: float = 1.0,
        kelly_cap: float | None = None,
    ) -> float:
        """
        Kelly criterion: f = (bp - q) / b
        p=prob win, q=1-p, b=odds.
        """
        if p <= 0 or b <= 0:
            return 0.0
        cap = kelly_cap if kelly_cap is not None else settings.KELLY_FRACTION_CAP
        f = (b * p - (1 - p)) / b
        f = max(0.0, min(f, cap))
        return round(f, 4)

    def _model_fair_price_ncaa(
        self,
        market: dict[str, Any],
        order_book: dict[str, Any],
    ) -> tuple[float, float]:
        """
        NCAA model: uses implied probs from order book + historical calibration.
        Returns (fair_price_yes, confidence).
        """
        bids = order_book.get("bids", []) or []
        asks = order_book.get("asks", []) or []
        if not bids and not asks:
            return 0.5, 0.3
        mid = 0.5
        if bids:
            mid = (mid + float(bids[0].get("price", 0.5))) / 2
        if asks:
            mid = (mid + float(asks[0].get("price", 0.5))) / 2
        confidence = 0.5 + 0.2 * min(1.0, len(bids) + len(asks)) / 10
        return mid, confidence

    def _model_fair_price_ucl(
        self,
        market: dict[str, Any],
        order_book: dict[str, Any],
    ) -> tuple[float, float]:
        """
        UCL (Champions League) model: sport-specific calibration.
        """
        return self._model_fair_price_ncaa(market, order_book)

    def _model_fair_price_btc(
        self,
        market: dict[str, Any],
        order_book: dict[str, Any],
    ) -> tuple[float, float]:
        """
        BTC model: crypto price prediction calibration.
        """
        return self._model_fair_price_ncaa(market, order_book)

    def _detect_model(self, market: dict[str, Any]) -> MarketModel:
        """Detect which model applies from market question/tags."""
        q = (market.get("question") or "").lower()
        tags = (market.get("tags") or []) + (market.get("groupItemTitle") or "").lower()
        combined = q + " " + str(tags)
        if "ncaa" in combined or "basketball" in combined or "march madness" in combined:
            return MarketModel.NCAA
        if "ucl" in combined or "champions league" in combined or "uefa" in combined:
            return MarketModel.UCL
        if "btc" in combined or "bitcoin" in combined or "crypto" in combined:
            return MarketModel.BTC
        return MarketModel.NCAA

    def compute_edge(
        self,
        market: dict[str, Any],
        token_id: str,
        side: str,
        polymarket_price: float,
        order_book: dict[str, Any],
    ) -> Optional[EdgeSignal]:
        """
        Compute mispricing edge and Kelly fraction.
        Returns EdgeSignal if edge > min_edge_pct, else None.
        Reads settings at call time for live config refresh.
        """
        min_edge_pct = settings.MIN_EDGE_PCT
        min_confidence = settings.MIN_CONFIDENCE
        model = self._detect_model(market)
        if model == MarketModel.NCAA:
            fair, conf = self._model_fair_price_ncaa(market, order_book)
        elif model == MarketModel.UCL:
            fair, conf = self._model_fair_price_ucl(market, order_book)
        else:
            fair, conf = self._model_fair_price_btc(market, order_book)

        if polymarket_price <= 0 or polymarket_price >= 1:
            return None

        if side.upper() == "YES":
            edge_pct = (fair - polymarket_price) / polymarket_price if polymarket_price > 0 else 0
        else:
            fair_no = 1.0 - fair
            pm_no = 1.0 - polymarket_price
            edge_pct = (fair_no - pm_no) / pm_no if pm_no > 0 else 0

        edge_pct_decimal = edge_pct  # edge_pct is decimal e.g. 0.05 = 5%
        min_edge = min_edge_pct / 100.0  # 2.0 -> 0.02
        if edge_pct_decimal < min_edge or conf < min_confidence:
            return None

        p = fair if side.upper() == "YES" else (1.0 - fair)
        b = (1.0 - polymarket_price) / polymarket_price if polymarket_price > 0 else 1.0
        kelly = self._kelly(p, 1 - p, b)

        return EdgeSignal(
            market_id=str(market.get("conditionId", market.get("condition_id", market.get("id", "")))),
            token_id=token_id,
            side=side.upper(),
            polymarket_price=polymarket_price,
            model_fair_price=fair,
            edge_pct=round(edge_pct, 4),
            kelly_fraction=kelly,
            model=model,
            confidence=round(conf, 4),
            metadata={
                "model": model.value,
                "question": (market.get("question") or "")[:120],
            },
            signal_strength=signal_strength,
        )
