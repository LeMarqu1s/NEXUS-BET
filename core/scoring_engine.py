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
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

log = logging.getLogger("nexus.scoring")

# Mots-clés NON-SPORT → retourner 0.5 sans appel API
NON_SPORT_KEYWORDS = frozenset((
    "trump", "biden", "president", "election", "congress", "senate", "vote",
    "bitcoin", "ethereum", "crypto", "btc", "eth", "price",
    "oscar", "grammy", "golden globe", "eurovision", "emmy", "tony",
    "fed", "rate", "inflation", "gdp", "recession",
))

# Sports to scan (most active on Polymarket)
SPORTS_TO_SCAN = (
    "soccer_france_ligue1",
    "soccer_england_league1",
    "soccer_uefa_champs_league",
    "basketball_nba",
    "basketball_ncaab",
    "americanfootball_nfl",
    "tennis_atp",  # tennis_atp_french_open when in season
    "icehockey_nhl",
)

# Mots-clés → sport_key (ordre prioritaire, mapped to SPORTS_TO_SCAN)
SPORT_KEYWORDS_MAP = (
    ("ligue 1", "soccer_france_ligue1"),
    ("ligue1", "soccer_france_ligue1"),
    ("france", "soccer_france_ligue1"),
    ("league one", "soccer_england_league1"),
    ("league1", "soccer_england_league1"),
    ("champions league", "soccer_uefa_champs_league"),
    ("ucl", "soccer_uefa_champs_league"),
    ("uefa", "soccer_uefa_champs_league"),
    ("nba finals", "basketball_nba"),
    ("nba", "basketball_nba"),
    ("lakers", "basketball_nba"),
    ("celtics", "basketball_nba"),
    ("ncaa", "basketball_ncaab"),
    ("march madness", "basketball_ncaab"),
    ("college basketball", "basketball_ncaab"),
    ("nfl", "americanfootball_nfl"),
    ("super bowl", "americanfootball_nfl"),
    ("french open", "tennis_atp"),
    ("tennis", "tennis_atp"),
    ("nhl", "icehockey_nhl"),
    ("stanley cup", "icehockey_nhl"),
    ("hockey", "icehockey_nhl"),
)

ODDS_CACHE_TTL = 300


def _mask_api_key(s: str) -> str:
    """Mask apiKey in URLs/logs for security. Replaces apiKey=xxx with apiKey=******"""
    if not s:
        return s
    import re
    return re.sub(r"apiKey=[^&\s\"']+", "apiKey=******", str(s), flags=re.IGNORECASE)


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
        self._odds_cache: dict[str, tuple[float, Any]] = {}

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
        Compare Polymarket à bookmakers selon le type de marché.
        BINARY: fair_value = 1/moyenne(cotes YES), score = 0.5 + (fair_value - pm_price)*2
        MULTI_OUTCOME: compare pm_price de recommended_outcome à 1/cote bookmaker
        NON-SPORT: retourne 0.5 sans appel API
        """
        api_key = os.getenv("ODDS_API_KEY", "")
        if not api_key:
            return 0.5

        question = (market_data.get("question") or "").lower()
        if not question:
            return 0.5

        if self._is_non_sport(question):
            return 0.5

        sport_key = self._match_sport_key_static(question)
        if not sport_key:
            return 0.5

        try:
            market_type = self._get_market_type(market_data)
            recommended_outcome = market_data.get("recommended_outcome", "")

            if market_type == "scalar":
                return 0.5
            if market_type == "binary":
                return self._score_binary_sport(market_data, sport_key, api_key, question)
            if market_type == "multi_outcome":
                return self._score_multi_sport(market_data, sport_key, api_key, question, recommended_outcome)
        except Exception as e:
            log.debug("sport_arbitrage: %s", e)
        return 0.5

    def _is_non_sport(self, question: str) -> bool:
        """Détection non-sport sans appel API."""
        return any(kw in question for kw in NON_SPORT_KEYWORDS)

    @staticmethod
    def _match_sport_key_static(question: str) -> Optional[str]:
        """Mappe la question vers un sport_key The Odds API (sans appel API)."""
        q = question.lower()
        for kw, key in SPORT_KEYWORDS_MAP:
            if kw in q:
                return key
        return None

    def _get_market_type(self, market_data: dict[str, Any]) -> str:
        """Détecte binary, multi_outcome ou scalar."""
        try:
            from core.edge_engine import detect_market_type
            return detect_market_type(market_data)
        except ImportError:
            outcomes = market_data.get("outcomes") or []
            if isinstance(outcomes, str):
                try:
                    outcomes = json.loads(outcomes)
                except Exception:
                    outcomes = []
            return "multi_outcome" if len(outcomes) > 2 else "binary"

    def _get_cached_odds(self, sport_key: str, api_key: str, market: str = "h2h") -> Optional[list]:
        """Fetch odds from Odds API. regions=eu, markets=h2h, decimal format. Cache TTL 300s."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_key = f"{sport_key}_{date_str}_{market}"
        now = time.time()
        if cache_key in self._odds_cache:
            ts, data = self._odds_cache[cache_key]
            if now - ts < ODDS_CACHE_TTL:
                return data
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
            params = {
                "apiKey": api_key,
                "regions": "eu",
                "markets": market,
                "oddsFormat": "decimal",
            }
            r = httpx.get(url, params=params, timeout=10.0)
            r.raise_for_status()
            events = r.json()
            if isinstance(events, list):
                self._odds_cache[cache_key] = (now, events)
                return events
        except Exception as e:
            log.debug("odds fetch %s: %s", sport_key, _mask_api_key(str(e)))
        return None

    def get_fair_value_for_yes(self, market_data: dict[str, Any]) -> Optional[float]:
        """
        Return fair value (0-1) for YES outcome from Odds API, or None if not available.
        Matches Polymarket question to Odds API events by team names and dates.
        """
        api_key = os.getenv("ODDS_API_KEY", "")
        if not api_key:
            return None
        question = (market_data.get("question") or "").strip()
        q_lower = question.lower()
        if not question or self._is_non_sport(q_lower):
            return None
        sport_key = self._match_sport_key_static(q_lower)
        if not sport_key:
            return None
        try:
            events = self._get_cached_odds(sport_key, api_key, "h2h")
            if not events:
                return None
            result = self._binary_fair_value_with_match(question, events, market_data)
            if result is not None:
                fair, odds_game, outcome_name = result
                pm_price = self._extract_pm_yes_price(market_data)
                edge_pct = ((fair - pm_price) / pm_price * 100) if pm_price > 0.01 else 0
                log.info(
                    "ODDS MATCH: %s ↔ %s | odds_prob=%.2f | poly_prob=%.2f | edge=%.2f%%",
                    question[:50], odds_game, fair, pm_price, edge_pct,
                )
                return fair
        except Exception as e:
            log.debug("get_fair_value_for_yes: %s", _mask_api_key(str(e)))
        return None

    def _score_binary_sport(
        self,
        market_data: dict[str, Any],
        sport_key: str,
        api_key: str,
        question: str,
    ) -> float:
        """BINARY: fair_value = 1/(moyenne cotes YES), score = 0.5 + (fair_value - pm_price)*2."""
        pm_price = self._extract_pm_yes_price(market_data)
        events = self._get_cached_odds(sport_key, api_key, "h2h")
        if not events:
            return 0.5

        fair_value = self._binary_fair_value(question, events)
        if fair_value is None:
            return 0.5
        score = 0.5 + (fair_value - pm_price) * 2
        return round(max(0.0, min(1.0, score)), 4)

    def _binary_fair_value_with_match(
        self, question: str, events: list[dict], market_data: dict[str, Any]
    ) -> Optional[tuple[float, str, str]]:
        """
        Match Polymarket question to Odds API event by team names.
        Return (fair_value, odds_game_str, outcome_name) or None.
        Fair value = implied probability (1/decimal_odds) averaged across bookmakers.
        """
        q_lower = question.lower()
        q_words = set(w for w in q_lower.replace("?", "").replace(".", "").split() if len(w) > 1)
        best_event, best_overlap = None, 0

        for ev in events:
            home = (ev.get("home_team") or "").lower()
            away = (ev.get("away_team") or "").lower()
            title_words = set(home.split() + away.split())
            overlap = len(q_words & title_words)
            if overlap > best_overlap and overlap >= 1:
                best_overlap = overlap
                best_event = ev

        if not best_event or best_overlap < 1:
            return None

        odds_list: list[float] = []
        matched_outcome = None
        for bm in best_event.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                if mkt.get("key") != "h2h":
                    continue
                for outcome in mkt.get("outcomes", []):
                    name = (outcome.get("name") or "").lower()
                    name_words = set(name.split())
                    if len(q_words & name_words) >= 1 or (len(name) > 2 and name in q_lower):
                        try:
                            d = float(outcome.get("price", 2.0))
                            if d > 0:
                                odds_list.append(1.0 / d)
                                matched_outcome = outcome.get("name", "")
                        except (ValueError, TypeError):
                            pass
                if odds_list:
                    break
            if odds_list:
                break

        if not odds_list:
            return None
        fair = round(sum(odds_list) / len(odds_list), 4)
        odds_game = f"{best_event.get('home_team','')} vs {best_event.get('away_team','')}"
        return (fair, odds_game, matched_outcome or "")

    def _binary_fair_value(self, question: str, events: list[dict]) -> Optional[float]:
        """Legacy: returns fair value only. Used by _score_binary_sport."""
        result = self._binary_fair_value_with_match(question, events, {})
        return result[0] if result else None

    def _score_multi_sport(
        self,
        market_data: dict[str, Any],
        sport_key: str,
        api_key: str,
        question: str,
        recommended_outcome: str,
    ) -> float:
        """MULTI_OUTCOME: compare pm_price de recommended_outcome à 1/cote bookmaker."""
        outcomes, prices = self._parse_outcomes(market_data)
        if not outcomes or not recommended_outcome:
            rec_idx = 0
            pm_price = float(prices[0]) if prices else 0.5
        else:
            rec_lower = recommended_outcome.lower()
            rec_idx = next((i for i, o in enumerate(outcomes) if str(o).lower() == rec_lower), 0)
            pm_price = float(prices[rec_idx]) if rec_idx < len(prices) else 0.5

        events_h2h = self._get_cached_odds(sport_key, api_key, "h2h")
        events_outright = self._get_cached_odds(sport_key, api_key, "outrights")
        for events in (events_outright, events_h2h):
            if not events:
                continue
            fair_value = self._multi_fair_value_for_outcome(events, outcomes[rec_idx] if outcomes else "", question)
            if fair_value is not None:
                score = 0.5 + (fair_value - pm_price) * 2
                return round(max(0.0, min(1.0, score)), 4)
        return 0.5

    def _multi_fair_value_for_outcome(
        self,
        events: list[dict],
        outcome_name: str,
        question: str,
    ) -> Optional[float]:
        """Pour un outcome, extrait 1/cote bookmaker (outrights ou h2h)."""
        out_lower = (outcome_name or "").lower()
        if not out_lower:
            return None
        odds_list: list[float] = []
        for ev in events:
            for bm in ev.get("bookmakers", []):
                for mkt in bm.get("markets", []):
                    for outcome in mkt.get("outcomes", []):
                        name = (outcome.get("name") or "").lower()
                        if out_lower in name or name in out_lower or (out_lower in question and name in question):
                            try:
                                d = float(outcome.get("price", 2.0))
                                if d > 0:
                                    odds_list.append(1.0 / d)
                            except (ValueError, TypeError):
                                pass
        if not odds_list:
            return None
        return round(sum(odds_list) / len(odds_list), 4)

    @staticmethod
    def _parse_outcomes(market_data: dict[str, Any]) -> tuple[list[str], list[float]]:
        """Parse outcomes et outcomePrices."""
        outcomes = market_data.get("outcomes") or []
        prices = market_data.get("outcomePrices") or []
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                outcomes = []
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except Exception:
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
                price_floats.append(0.5)
        return list(outcomes), price_floats

    @staticmethod
    def _extract_pm_yes_price(market_data: dict[str, Any]) -> float:
        """Extract YES price from outcomePrices. Handles list or JSON string from Gamma API."""
        prices = market_data.get("outcomePrices")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(prices, (list, tuple)) and prices:
            try:
                return float(prices[0])
            except (ValueError, TypeError):
                pass
        return float(market_data.get("yes_price", 0.5) or 0.5)

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
