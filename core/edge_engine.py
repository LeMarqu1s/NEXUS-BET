"""
NEXUS BET - Edge Engine
Mispricing detection for binary, multi-outcome, and scalar markets.
"""
from __future__ import annotations

import json
import logging
import os
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from enum import Enum

from config.settings import settings

log = logging.getLogger("nexus.edge")


class MarketModel(Enum):
    NCAA = "ncaa"
    UCL = "ucl"
    BTC = "btc"


def detect_market_type(market: dict[str, Any]) -> str:
    """
    Detect market type from structure and question.
    Returns: "binary" | "scalar" | "multi_outcome"
    """
    outcomes = market.get("outcomes") or []
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except (json.JSONDecodeError, TypeError):
            outcomes = []
    if not isinstance(outcomes, list):
        outcomes = []

    q = (market.get("question") or "").lower()
    scalar_keywords = ("$", "price", "above", "below", "over", "under", "higher", "lower", "bps", "points")

    if len(outcomes) == 2:
        out_lower = [str(o).lower() for o in outcomes]
        if "yes" in out_lower and "no" in out_lower:
            return "binary"

    if any(kw in q for kw in scalar_keywords):
        return "scalar"

    if len(outcomes) > 2:
        return "multi_outcome"

    return "binary"


@dataclass
class EdgeSignal:
    """Represents a detected mispricing edge."""
    market_id: str
    token_id: str
    side: str  # YES, NO, or outcome name
    polymarket_price: float
    model_fair_price: float
    edge_pct: float
    kelly_fraction: float
    model: MarketModel
    confidence: float
    metadata: dict[str, Any]
    signal_strength: str = "BUY"
    market_type: str = "binary"
    recommended_outcome: str = ""


class EdgeEngine:
    """
    Mispricing detection engine for binary, multi-outcome, and scalar markets.
    """

    def __init__(self) -> None:
        pass

    def _kelly(
        self,
        p: float,
        q: float,
        b: float = 1.0,
        kelly_cap: float | None = None,
    ) -> float:
        if p <= 0 or b <= 0:
            return 0.0
        cap = kelly_cap if kelly_cap is not None else settings.KELLY_FRACTION_CAP
        f = (b * p - (1 - p)) / b
        return round(max(0.0, min(f, cap)), 4)

    def _model_fair_price_ncaa(
        self,
        market: dict[str, Any],
        order_book: dict[str, Any],
    ) -> tuple[float, float]:
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

    def _model_fair_price_ucl(self, market: dict[str, Any], order_book: dict[str, Any]) -> tuple[float, float]:
        return self._model_fair_price_ncaa(market, order_book)

    def _model_fair_price_btc(self, market: dict[str, Any], order_book: dict[str, Any]) -> tuple[float, float]:
        return self._model_fair_price_ncaa(market, order_book)

    def _detect_model(self, market: dict[str, Any]) -> MarketModel:
        q = (market.get("question") or "").lower()
        tags = (market.get("tags") or []) + [str(market.get("groupItemTitle") or "").lower()]
        combined = q + " " + " ".join(str(t) for t in tags)
        if "ncaa" in combined or "basketball" in combined or "march madness" in combined:
            return MarketModel.NCAA
        if "ucl" in combined or "champions league" in combined or "uefa" in combined:
            return MarketModel.UCL
        if "btc" in combined or "bitcoin" in combined or "crypto" in combined:
            return MarketModel.BTC
        return MarketModel.NCAA

    def _parse_outcome_prices(self, market: dict[str, Any]) -> tuple[list[str], list[float]]:
        """Return (outcomes list, prices list)."""
        outcomes = market.get("outcomes") or []
        prices = market.get("outcomePrices") or []
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except (json.JSONDecodeError, TypeError):
                outcomes = []
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except (json.JSONDecodeError, TypeError):
                prices = []
        if not isinstance(outcomes, list):
            outcomes = []
        if not isinstance(prices, list):
            prices = []
        price_floats = []
        for p in prices:
            try:
                price_floats.append(float(p))
            except (ValueError, TypeError):
                price_floats.append(0.0)
        return list(outcomes), price_floats

    def _days_to_resolution(self, market: dict[str, Any]) -> float:
        end = market.get("endDate") or market.get("end_date_iso") or market.get("end_date")
        if not end:
            return 0.25
        try:
            if isinstance(end, (int, float)):
                dt = datetime.fromtimestamp(end, tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            delta = (dt - datetime.now(timezone.utc)).total_seconds() / 86400.0
            return max(0.01, delta / 365.0)
        except Exception:
            return 0.25

    def _fetch_btc_spot(self) -> Optional[float]:
        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                r = client.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
                if r.status_code == 200:
                    return float(r.json().get("price", 0))
        except Exception:
            pass
        return None

    def _compute_edge_binary(
        self,
        market: dict[str, Any],
        token_id: str,
        side: str,
        polymarket_price: float,
        order_book: dict[str, Any],
    ) -> Optional[EdgeSignal]:
        """Existing binary logic."""
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

        # Debug: log edges for each market (set DEBUG_EDGE=1 to use 1% threshold)
        question = (market.get("question") or "")[:40]
        log.info("Market: %s | price=%.2f | edge=%.2f%%", question, polymarket_price, edge_pct * 100)

        min_edge = 0.01 if os.getenv("DEBUG_EDGE") == "1" else (settings.MIN_EDGE_PCT / 100.0)
        if edge_pct < min_edge or conf < min_confidence:
            return None

        p = fair if side.upper() == "YES" else (1.0 - fair)
        b = (1.0 - polymarket_price) / polymarket_price if polymarket_price > 0 else 1.0
        kelly = self._kelly(p, 1 - p, b)
        signal_strength = "STRONG_BUY" if edge_pct >= 0.15 and conf >= 0.9 else "BUY"

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
            metadata={"model": model.value, "question": (market.get("question") or "")[:120]},
            signal_strength=signal_strength,
            market_type="binary",
            recommended_outcome=side.upper(),
        )

    def _compute_edge_multi_outcome(
        self,
        market: dict[str, Any],
        token_id: str,
        side: str,
        polymarket_price: float,
        order_book: dict[str, Any],
    ) -> Optional[EdgeSignal]:
        outcomes, prices = self._parse_outcome_prices(market)
        if len(outcomes) < 2 or len(prices) < 2:
            return None

        sum_prices = sum(prices)
        if sum_prices >= 0.97:
            return None

        edge_pct = (1.0 - sum_prices)
        min_edge = settings.MIN_EDGE_PCT / 100.0
        if edge_pct < min_edge:
            return None

        n = len(outcomes)
        fair_uniform = 1.0 / n
        best_idx = 0
        best_gap = 0.0
        for i, (out_name, p) in enumerate(zip(outcomes, prices)):
            gap = abs(fair_uniform - p)
            if gap > best_gap:
                best_gap = gap
                best_idx = i

        best_outcome = str(outcomes[best_idx]) if best_idx < len(outcomes) else ""
        best_price = prices[best_idx] if best_idx < len(prices) else 0.5

        tokens = market.get("clobTokenIds") or market.get("tokens") or []
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except (json.JSONDecodeError, TypeError):
                tokens = []
        best_token_id = token_id
        if isinstance(tokens, list) and best_idx < len(tokens):
            t = tokens[best_idx]
            best_token_id = t.get("token_id", t) if isinstance(t, dict) else str(t)

        log.info(
            "MULTI_OUTCOME: sum=%.3f best=[%s] edge=%.2f%%",
            sum_prices, best_outcome, edge_pct * 100,
        )

        kelly = self._kelly(fair_uniform, 1 - fair_uniform, (1 - best_price) / best_price if best_price > 0 else 1.0)
        signal_strength = "STRONG_BUY" if edge_pct >= 0.15 else "BUY"

        return EdgeSignal(
            market_id=str(market.get("conditionId", market.get("condition_id", market.get("id", "")))),
            token_id=str(best_token_id),
            side=best_outcome,
            polymarket_price=best_price,
            model_fair_price=fair_uniform,
            edge_pct=round(edge_pct, 4),
            kelly_fraction=kelly,
            model=self._detect_model(market),
            confidence=0.6,
            metadata={"model": "multi_outcome", "question": (market.get("question") or "")[:120]},
            signal_strength=signal_strength,
            market_type="multi_outcome",
            recommended_outcome=best_outcome,
        )

    def _compute_edge_scalar(
        self,
        market: dict[str, Any],
        token_id: str,
        side: str,
        polymarket_price: float,
        order_book: dict[str, Any],
    ) -> Optional[EdgeSignal]:
        outcomes, prices = self._parse_outcome_prices(market)
        if not outcomes or not prices:
            return None

        q = (market.get("question") or "").lower()
        spot = None
        if "btc" in q or "bitcoin" in q:
            spot = self._fetch_btc_spot()
        if spot is None or spot <= 0:
            return None

        sigma_vol = 0.15
        horizon = self._days_to_resolution(market)
        sigma_ln = sigma_vol * math.sqrt(horizon)
        ln_spot = math.log(spot)

        best_idx = 0
        best_fair = 0.5
        best_edge = 0.0
        bin_str = "?"

        import re
        for i, (out_name, market_price) in enumerate(zip(outcomes, prices)):
            out_str = str(out_name)
            low, high = None, None
            nums = re.findall(r"[\d.]+", out_str.replace(",", ""))
            if len(nums) >= 2:
                low, high = float(nums[0]), float(nums[1])
                if "k" in out_str.lower() or "000" in out_str:
                    low, high = low * 1000, high * 1000
            elif len(nums) == 1:
                val = float(nums[0])
                low, high = val * 0.95, val * 1.05

            if low is None or high is None or low <= 0 or high <= 0:
                continue

            if sigma_ln <= 0:
                continue
            z_low = (math.log(low) - ln_spot) / sigma_ln
            z_high = (math.log(high) - ln_spot) / sigma_ln
            fair = 0.5 * (math.erf(z_high / math.sqrt(2)) - math.erf(z_low / math.sqrt(2)))
            fair = max(0.01, min(0.99, fair))

            if market_price <= 0:
                continue
            edge = abs(fair - market_price) / market_price
            if edge > best_edge:
                best_edge = edge
                best_idx = i
                best_fair = fair
                bin_str = f"{low:.0f}-{high:.0f}"

        min_edge = settings.MIN_EDGE_PCT / 100.0
        if best_edge < min_edge:
            return None

        best_price = prices[best_idx] if best_idx < len(prices) else polymarket_price
        best_outcome = str(outcomes[best_idx]) if best_idx < len(outcomes) else side

        tokens = market.get("clobTokenIds") or market.get("tokens") or []
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except (json.JSONDecodeError, TypeError):
                tokens = []
        best_token_id = token_id
        if isinstance(tokens, list) and best_idx < len(tokens):
            t = tokens[best_idx]
            best_token_id = t.get("token_id", t) if isinstance(t, dict) else str(t)

        log.info(
            "SCALAR: bin=[%s] fair=%.3f market=%.3f edge=%.2f%%",
            bin_str, best_fair, best_price, best_edge * 100,
        )

        kelly = self._kelly(best_fair, 1 - best_fair, (1 - best_price) / best_price if best_price > 0 else 1.0)
        signal_strength = "STRONG_BUY" if best_edge >= 0.15 else "BUY"

        return EdgeSignal(
            market_id=str(market.get("conditionId", market.get("condition_id", market.get("id", "")))),
            token_id=str(best_token_id),
            side=best_outcome,
            polymarket_price=best_price,
            model_fair_price=best_fair,
            edge_pct=round(best_edge, 4),
            kelly_fraction=kelly,
            model=self._detect_model(market),
            confidence=0.55,
            metadata={"model": "scalar", "question": (market.get("question") or "")[:120]},
            signal_strength=signal_strength,
            market_type="scalar",
            recommended_outcome=best_outcome,
        )

    def compute_edge(
        self,
        market: dict[str, Any],
        token_id: str,
        side: str,
        polymarket_price: float,
        order_book: dict[str, Any],
    ) -> Optional[EdgeSignal]:
        """
        Compute mispricing edge by market type. Never raises — skip bad markets.
        Returns EdgeSignal if edge > min_edge_pct, else None.
        """
        try:
            market_type = detect_market_type(market)

            if market_type == "binary":
                return self._compute_edge_binary(market, token_id, side, polymarket_price, order_book)
            if market_type == "multi_outcome":
                return self._compute_edge_multi_outcome(market, token_id, side, polymarket_price, order_book)
            if market_type == "scalar":
                return self._compute_edge_scalar(market, token_id, side, polymarket_price, order_book)

            return self._compute_edge_binary(market, token_id, side, polymarket_price, order_book)
        except Exception as e:
            log.debug("compute_edge skip market %s: %s", token_id[:16] if token_id else "?", e)
            return None
