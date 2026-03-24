"""
NEXUS CAPITAL - Adversarial AI Team
Paperclip agents: DataAnalyst (UW smart money), Quant (edge/EV), RiskManager (destroys thesis), Sniper (executes).
Falls back to Claude direct when PAPERCLIP_URL not set.
Tavily web search enriches agent debates with real-time news context.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from config.settings import settings

log = logging.getLogger("nexus.agents")

_last_claude_call: float = 0.0
_MIN_INTERVAL = 15  # seconds between Claude API calls


async def _tavily_search(query: str, max_results: int = 3) -> str:
    """
    Search the web using Tavily API for real-time context.
    Returns a formatted string with top results or empty string if unavailable.
    """
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": True,
                },
            )
            if r.status_code != 200:
                return ""
            data = r.json()
            parts = []
            if data.get("answer"):
                parts.append(f"Summary: {data['answer'][:300]}")
            for res in data.get("results", [])[:max_results]:
                title = res.get("title", "")
                snippet = res.get("content", "")[:150]
                parts.append(f"• {title}: {snippet}")
            return "\n".join(parts)
    except Exception as e:
        log.debug("Tavily search failed: %s", e)
        return ""


@dataclass
class TradeThesis:
    """Thesis proposed by Quant, challenged by Risk, validated by Analyst."""
    market_id: str
    outcome: str  # YES or NO
    edge_bps: float
    kelly_fraction: float
    rationale: str
    risk_concerns: Optional[str] = None
    final_verdict: Optional[str] = None
    approved: bool = False


class AdversarialAITeam:
    """Three-agent adversarial debate system for trade validation."""

    def __init__(self):
        self.api_key = settings.ANTHROPIC_API_KEY
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.model = "claude-sonnet-4-20250514"

    async def _call_claude(self, system: str, user: str) -> str:
        """Call Anthropic Claude API — rate-limited (1 call / 15s) with 429 guard."""
        global _last_claude_call
        if not self.api_key:
            return "[NO_API_KEY] Mock response - configure ANTHROPIC_API_KEY"

        now = time.time()
        wait = _MIN_INTERVAL - (now - _last_claude_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_claude_call = time.time()

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    self.base_url,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "max_tokens": 1024,
                        "system": system,
                        "messages": [{"role": "user", "content": user}],
                    },
                )
                if resp.status_code == 429:
                    log.warning("Anthropic 429 rate limit — sleeping 60s")
                    await asyncio.sleep(60)
                    return "Agent indisponible"
                resp.raise_for_status()
                data = resp.json()
                content = data.get("content", [])
                if content and isinstance(content[0], dict):
                    return content[0].get("text", "")
                return str(content)
        except Exception as e:
            if "429" in str(e):
                log.warning("Anthropic 429 (exc) — sleeping 60s: %s", e)
                await asyncio.sleep(60)
            else:
                log.error("Claude API error: %s", e)
            return "Agent indisponible"

    async def _call_agent(self, role: str, system: str, user: str) -> str:
        """Route to Paperclip agent if available, otherwise fall back to Claude."""
        # TODO: add Paperclip routing per role when PAPERCLIP_URL is set
        return await self._call_claude(system, user)

    async def quant_propose_trade(self, market_id: str, outcome: str, edge_bps: float, kelly: float, rationale: str) -> str:
        """Quant proposes a trade with thesis (Paperclip Quant or Claude)."""
        system = """You are a quantitative trader at NEXUS Capital. Propose trades based on mispricing.
Be concise. Output ONLY the trade thesis in 2-3 sentences."""
        user = f"Market {market_id}, outcome {outcome}, edge {edge_bps}bps, Kelly {kelly:.2%}. Rationale: {rationale}. Write trade thesis:"
        return await self._call_agent("Quant", system, user)

    async def risk_manager_challenge(self, thesis: str, market_context: str) -> str:
        """Risk Manager destroys the thesis (Paperclip RiskManager or Claude)."""
        system = """You are a Risk Manager. Your job is to DESTROY every trade thesis.
Find flaws: liquidity, timing, model error, tail risk, slippage. Be harsh. Output only concerns."""
        user = f"Thesis: {thesis}\nContext: {market_context}\nList critical risks:"
        return await self._call_agent("RiskManager", system, user)

    async def head_analyst_validate(self, thesis: str, risk_concerns: str) -> tuple[bool, str]:
        """Head Analyst / Sniper weighs both sides and gives final verdict."""
        system = """You are Head Analyst. Weigh Quant thesis vs Risk concerns. 
Output format: VERDICT: APPROVE or REJECT (exactly one). Then 1-2 sentence justification."""
        user = f"Thesis: {thesis}\nRisk concerns: {risk_concerns}\nYour verdict:"
        out = await self._call_agent("Sniper", system, user)
        approved = "VERDICT: APPROVE" in out.upper() or "APPROVE" in out.upper().split()[0:3]
        return approved, out

    async def full_debate(self, market_id: str, outcome: str, edge_bps: float, kelly: float, rationale: str, market_context: str = "") -> TradeThesis:
        """Run full adversarial pipeline: Quant → Risk → Analyst.
        Enriches context with Tavily web search for real-time news when available.
        """
        # Enrich with Tavily web search if available
        tavily_context = ""
        if rationale and len(rationale) > 10:
            search_query = f"Polymarket prediction {rationale[:100]}"
            tavily_context = await _tavily_search(search_query)
            if tavily_context:
                log.debug("Tavily enrichment: %d chars for market %s", len(tavily_context), market_id)

        enriched_context = market_context
        if tavily_context:
            enriched_context = f"{market_context}\n\nWeb context:\n{tavily_context}".strip()

        thesis_text = await self.quant_propose_trade(market_id, outcome, edge_bps, kelly, rationale)
        risk_concerns = await self.risk_manager_challenge(thesis_text, enriched_context)
        approved, verdict = await self.head_analyst_validate(thesis_text, risk_concerns)
        return TradeThesis(
            market_id=market_id,
            outcome=outcome,
            edge_bps=edge_bps,
            kelly_fraction=kelly,
            rationale=rationale,
            risk_concerns=risk_concerns,
            final_verdict=verdict,
            approved=approved,
        )


async def call_claude(system: str = "", user: str = "") -> str:
    """Module-level wrapper — rate-limited Claude call via AdversarialAITeam."""
    return await AdversarialAITeam()._call_claude(system, user)
