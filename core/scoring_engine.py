"""
NEXUS BET - Scoring Engine
Moteur de scoring hybride pour les trades Polymarket.
Pilier 1: Capital Efficiency (Time Decay)
Pilier 2: Sport Arbitrage (The Odds API)
Pilier 3: News Sentiment (Claude)
Pilier 4: Whale Modifier (Polymarket whale tracker)
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

log = logging.getLogger("nexus.scoring")


@dataclass
class ScoringWeights:
    """Poids des piliers pour le score final."""
    capital_efficiency: float = 0.40  # Time Decay
    sport_arbitrage: float = 0.25
    news_sentiment: float = 0.25
    whale_modifier: float = 0.10


class NexusScoringEngine:
    """
    Moteur de scoring hybride pour les marchés Polymarket.
    Score final sur 100, combinant plusieurs piliers.
    """

    TIME_DECAY_TAU_DAYS = 15.0
    TIME_SCORE_UNKNOWN_DAYS = 50.0

    def __init__(self, weights: Optional[ScoringWeights] = None) -> None:
        self.weights = weights or ScoringWeights()

    def calculate_score(self, market_data: dict[str, Any]) -> float:
        """
        Calcule le score global du marché (0–100).
        Combine les piliers avec leurs poids respectifs.
        """
        time_score = self._calc_capital_efficiency_score(market_data)
        sport_score = self._calc_sport_arbitrage_score(market_data)
        news_score = self._calc_news_sentiment_score(market_data)
        whale_score = self._calc_whale_modifier(market_data)

        total = (
            time_score / 100.0 * self.weights.capital_efficiency
            + sport_score * self.weights.sport_arbitrage
            + news_score * self.weights.news_sentiment
            + whale_score * self.weights.whale_modifier
        ) * 100

        return round(max(0.0, min(100.0, total)), 2)

    def _days_to_resolution(self, market_data: dict[str, Any]) -> Optional[float]:
        """Jours restants jusqu'à la résolution du marché."""
        end = market_data.get("endDate") or market_data.get("end_date_iso") or market_data.get("end_date")
        if not end:
            return None
        try:
            if isinstance(end, (int, float)):
                dt = datetime.fromtimestamp(end, tz=timezone.utc)
            elif isinstance(end, str):
                dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            else:
                return None
            delta = dt - datetime.now(timezone.utc)
            return max(0.0, delta.total_seconds() / 86400.0)
        except (ValueError, TypeError, OSError):
            return None

    def _calc_capital_efficiency_score(self, market_data: dict[str, Any]) -> float:
        """
        Pilier 1: Capital Efficiency (Time Decay).
        Formule: score = 100 * exp(-days / tau)
        """
        days = self._days_to_resolution(market_data)
        if days is None:
            return self.TIME_SCORE_UNKNOWN_DAYS
        raw = 100.0 * math.exp(-days / self.TIME_DECAY_TAU_DAYS)
        return round(max(0.0, min(100.0, raw)), 2)

    # ------------------------------------------------------------------
    # Pilier 2 — Sport Arbitrage (The Odds API)
    # ------------------------------------------------------------------

    def _calc_sport_arbitrage_score(self, market_data: dict[str, Any]) -> float:
        """
        Compare Polymarket implied probability to bookmaker fair value.
        Returns 0–1 (>0.5 = Polymarket cheaper than books → opportunity).
        Falls back to 0.5 when ODDS_API_KEY is absent or no matching event.
        """
        api_key = os.getenv("ODDS_API_KEY", "")
        if not api_key:
            return 0.5

        question = (market_data.get("question") or "").lower()
        pm_price = self._extract_pm_yes_price(market_data)

        try:
            resp = httpx.get(
                "https://api.the-odds-api.com/v4/sports",
                params={"apiKey": api_key},
                timeout=10.0,
            )
            resp.raise_for_status()
            sports = resp.json()

            sport_key = self._match_sport_key(question, sports)
            if not sport_key:
                return 0.5

            odds_resp = httpx.get(
                f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds",
                params={"apiKey": api_key, "regions": "us,eu", "markets": "h2h", "oddsFormat": "decimal"},
                timeout=10.0,
            )
            odds_resp.raise_for_status()
            events = odds_resp.json()

            book_prob = self._best_book_probability(question, events)
            if book_prob is None:
                return 0.5

            diff = book_prob - pm_price
            return round(max(0.0, min(1.0, 0.5 + diff * 2)), 4)
        except Exception as e:
            log.debug("sport_arbitrage: %s", e)
            return 0.5

    @staticmethod
    def _extract_pm_yes_price(market_data: dict[str, Any]) -> float:
        prices = market_data.get("outcomePrices")
        if isinstance(prices, (list, tuple)) and prices:
            try:
                return float(prices[0])
            except (ValueError, TypeError):
                pass
        return float(market_data.get("yes_price", 0.5) or 0.5)

    @staticmethod
    def _match_sport_key(question: str, sports: list[dict]) -> Optional[str]:
        """Find the best matching sport key for a Polymarket question."""
        keywords_map = {
            "nba": "basketball_nba", "nfl": "americanfootball_nfl",
            "nhl": "icehockey_nhl", "mlb": "baseball_mlb",
            "ncaa": "basketball_ncaab", "premier league": "soccer_epl",
            "champions league": "soccer_uefa_champs_league",
            "ucl": "soccer_uefa_champs_league",
            "la liga": "soccer_spain_la_liga", "serie a": "soccer_italy_serie_a",
            "mls": "soccer_usa_mls", "ufc": "mma_mixed_martial_arts",
        }
        available = {s.get("key", "") for s in sports if s.get("active")}
        for kw, key in keywords_map.items():
            if kw in question and key in available:
                return key
        return None

    @staticmethod
    def _best_book_probability(question: str, events: list[dict]) -> Optional[float]:
        """Extract best matching bookmaker implied probability for the question."""
        q_words = set(question.split())
        best_event, best_overlap = None, 0
        for ev in events:
            title_words = set(
                (ev.get("home_team", "") + " " + ev.get("away_team", "")).lower().split()
            )
            overlap = len(q_words & title_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_event = ev

        if not best_event or best_overlap < 2:
            return None

        for bm in best_event.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                if mkt.get("key") != "h2h":
                    continue
                for outcome in mkt.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    if name in question:
                        decimal_odds = float(outcome.get("price", 2.0))
                        return round(1.0 / decimal_odds, 4) if decimal_odds > 0 else None
        return None

    # ------------------------------------------------------------------
    # Pilier 3 — News Sentiment (Claude)
    # ------------------------------------------------------------------

    def _calc_news_sentiment_score(self, market_data: dict[str, Any]) -> float:
        """
        Ask Claude for a bullish sentiment score (0–1) on the YES outcome.
        Returns 0.5 on any failure or missing API key.
        """
        from config.settings import settings as _settings
        api_key = _settings.ANTHROPIC_API_KEY
        if not api_key:
            return 0.5

        question = (market_data.get("question") or "")[:120]
        if not question:
            return 0.5

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, self._sentiment_async(api_key, question)).result(timeout=20)
            else:
                return asyncio.run(self._sentiment_async(api_key, question))
        except Exception:
            return 0.5

    @staticmethod
    async def _sentiment_async(api_key: str, question: str) -> float:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 50,
                        "system": "Return ONLY valid JSON. No other text.",
                        "messages": [{"role": "user", "content": (
                            f'Polymarket question: "{question}". '
                            "Rate the bullish sentiment for YES outcome from 0.0 (very bearish) "
                            "to 1.0 (very bullish) based on current public knowledge. "
                            'Reply ONLY: {"score": <float>}'
                        )}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data.get("content", [{}])[0].get("text", "")
                parsed = json.loads(text)
                score = float(parsed.get("score", 0.5))
                return max(0.0, min(1.0, score))
        except Exception as e:
            log.debug("news_sentiment: %s", e)
            return 0.5

    # ------------------------------------------------------------------
    # Pilier 4 — Whale Modifier (Polymarket whale tracker)
    # ------------------------------------------------------------------

    def _calc_whale_modifier(self, market_data: dict[str, Any]) -> float:
        """
        Net whale flow: majority BUY → >0.5, majority SELL → <0.5.
        Uses UnusualWhalesMCPClient (backed by free Polymarket APIs).
        """
        market_id = str(
            market_data.get("conditionId")
            or market_data.get("condition_id")
            or market_data.get("id", "")
        )
        if not market_id:
            return 0.5

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, self._whale_async(market_id)).result(timeout=15)
            else:
                return asyncio.run(self._whale_async(market_id))
        except Exception:
            return 0.5

    @staticmethod
    async def _whale_async(market_id: str) -> float:
        try:
            from data.unusual_whales_mcp import UnusualWhalesMCPClient
            client = UnusualWhalesMCPClient()
            try:
                trades = await client.get_flow_for_ticker(market_id)
            finally:
                await client.close()

            if not trades:
                return 0.5

            buy_vol, sell_vol = 0.0, 0.0
            for t in trades:
                size = float(t.get("size", 0))
                side = str(t.get("side", "")).upper()
                if side == "BUY":
                    buy_vol += size
                else:
                    sell_vol += size

            total = buy_vol + sell_vol
            if total == 0:
                return 0.5
            return round(max(0.0, min(1.0, buy_vol / total)), 4)
        except Exception as e:
            log.debug("whale_modifier: %s", e)
            return 0.5
