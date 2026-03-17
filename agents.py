"""
NEXUS BET - Adversarial AI Team
Quant proposes trades, Risk Manager challenges thesis, Head Analyst validates.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import httpx
from config.settings import settings


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
        """Call Anthropic Claude API asynchronously."""
        if not self.api_key:
            return "[NO_API_KEY] Mock response - configure ANTHROPIC_API_KEY"

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
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", [])
            if content and isinstance(content[0], dict):
                return content[0].get("text", "")
            return str(content)

    async def quant_propose_trade(self, market_id: str, outcome: str, edge_bps: float, kelly: float, rationale: str) -> str:
        """Quant proposes a trade with thesis."""
        system = """You are a quantitative trader at NEXUS Capital. Propose trades based on mispricing.
Be concise. Output ONLY the trade thesis in 2-3 sentences."""
        user = f"Market {market_id}, outcome {outcome}, edge {edge_bps}bps, Kelly {kelly:.2%}. Rationale: {rationale}. Write trade thesis:"
        return await self._call_claude(system, user)

    async def risk_manager_challenge(self, thesis: str, market_context: str) -> str:
        """Risk Manager destroys the thesis - adversarial role."""
        system = """You are a Risk Manager. Your job is to DESTROY every trade thesis.
Find flaws: liquidity, timing, model error, tail risk, slippage. Be harsh. Output only concerns."""
        user = f"Thesis: {thesis}\nContext: {market_context}\nList critical risks:"
        return await self._call_claude(system, user)

    async def head_analyst_validate(self, thesis: str, risk_concerns: str) -> tuple[bool, str]:
        """Head Analyst weighs both sides and gives final verdict."""
        system = """You are Head Analyst. Weigh Quant thesis vs Risk concerns. 
Output format: VERDICT: APPROVE or REJECT (exactly one). Then 1-2 sentence justification."""
        user = f"Thesis: {thesis}\nRisk concerns: {risk_concerns}\nYour verdict:"
        out = await self._call_claude(system, user)
        approved = "VERDICT: APPROVE" in out.upper() or "APPROVE" in out.upper().split()[0:3]
        return approved, out

    async def full_debate(self, market_id: str, outcome: str, edge_bps: float, kelly: float, rationale: str, market_context: str = "") -> TradeThesis:
        """Run full adversarial pipeline: Quant → Risk → Analyst."""
        thesis_text = await self.quant_propose_trade(market_id, outcome, edge_bps, kelly, rationale)
        risk_concerns = await self.risk_manager_challenge(thesis_text, market_context)
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
