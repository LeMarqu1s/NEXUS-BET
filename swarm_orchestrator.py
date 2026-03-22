"""
NEXUS CAPITAL - Swarm Intelligence Orchestrator (Phase 5 - Mode 500%)
Lorsqu'un signal dépasse le seuil critique (Unusual Whales / Polymarket),
déploie dynamiquement un essaim de 20 micro-agents IA qui votent YES/NO.
Export des débats et du résultat vers ai_debates_log.json pour le dashboard.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("nexus.swarm")

# Fichier lu par /api/debates (Next.js dashboard)
DEBATES_LOG_PATH = Path(__file__).resolve().parent / "ai_debates_log.json"

# Seuil critique : edge % au-delà duquel le Swarm est déployé
SWARM_CRITICAL_EDGE_PCT = float(os.getenv("SWARM_CRITICAL_EDGE_PCT", "3.0"))

# Nombre de micro-agents (20 par défaut)
SWARM_AGENT_COUNT = int(os.getenv("SWARM_AGENT_COUNT", "20"))

# Personnalités des micro-agents pour diversification des angles
AGENT_PERSONAS = [
    {"name": "Analyste Juridique", "system": "Tu es un avocat spécialisé en marchés prédictifs. Tu évalues les risques réglementaires et contractuels. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Trader Dégénéré", "system": "Tu es un trader de memecoins. Tu prends des positions agressives. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Macro-Économiste", "system": "Tu es un macro-économiste. Tu analyses cycles, liquidité et contexte global. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Quant Systematic", "system": "Tu es un quant. Tu regardes les probabilités, Kelly, edge mathématique. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Risk Manager Conservateur", "system": "Tu es un risk manager ultra-conservateur. Tu cherches les failles. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Scientifique des Données", "system": "Tu analyses les données brutes, historique, corrélations. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Spécialiste Liquidité", "system": "Tu évalues spread, profondeur, slippage. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Sentiment Analyst", "system": "Tu lis le sentiment du marché et des réseaux sociaux. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Contrarian", "system": "Tu prends systématiquement la position inverse du consensus. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Value Investor", "system": "Tu compares valeur intrinsèque vs prix. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Options Trader", "system": "Tu penses en termes d'options, convexité, gamma. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Crypto Native", "system": "Tu comprends l'on-chain et les flows crypto. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Event-Driven Specialist", "system": "Tu analyses les catalyseurs d'événements à venir. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Market Maker", "system": "Tu penses comme un market maker: inventory, adverse selection. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Behavioral Economist", "system": "Tu analyses les biais cognitifs et l'irrationalité des acteurs. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Geopolitical Analyst", "system": "Tu intègres les risques géopolitiques. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Technical Analyst", "system": "Tu utilises supports, résistances, volumes. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Fundamental Long-Term", "system": "Tu penses long terme, fondamentaux structurels. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Arbitrageur", "system": "Tu cherches les inefficiences entre marchés. Réponds brièvement en YES ou NO puis une phrase."},
    {"name": "Night Auditor", "system": "Tu fais une dernière vérification avant exécution. Réponds brièvement en YES ou NO puis une phrase."},
]


@dataclass
class SwarmVote:
    agent_name: str
    vote: str  # YES | NO
    reasoning: str


@dataclass
class SwarmResult:
    market_id: str
    side: str
    question: str
    edge_pct: float
    kelly: float
    votes_yes: int
    votes_no: int
    pct_yes: float
    approved: bool  # True si pct_yes >= 70%
    debates: list[dict[str, Any]]
    timestamp: str


def _get_persona_for_agent(i: int) -> dict[str, str]:
    """Cycle through personas for 20+ agents."""
    return AGENT_PERSONAS[i % len(AGENT_PERSONAS)]


async def _call_llm(api_key: str | None, model: str, system: str, user: str) -> str:
    """Appel Claude API (Anthropic)."""
    if not api_key:
        # Mode mock : vote aléatoire pour tests
        import random
        vote = "YES" if random.random() > 0.3 else "NO"
        return f"{vote}. Mock reasoning: no API key configured."
    base = "https://api.anthropic.com/v1/messages"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            base,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 256,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        resp.raise_for_status()
        content = resp.json().get("content", [])
        if content and isinstance(content[0], dict):
            return content[0].get("text", "")
    return ""


def _parse_vote(text: str) -> str:
    """Extrait YES ou NO du texte de l'agent."""
    t = text.upper()
    if "YES" in t[:50] or t.startswith("YES"):
        return "YES"
    if "NO" in t[:50] or t.startswith("NO"):
        return "NO"
    # Heuristique : si "APPROVE" ou "BUY" -> YES
    if "APPROVE" in t or "BUY" in t or "LONG" in t:
        return "YES"
    if "REJECT" in t or "SELL" in t or "SHORT" in t:
        return "NO"
    return "NO"  # défaut conservateur


def _export_to_json(result: SwarmResult) -> None:
    """Écrit le résultat dans ai_debates_log.json pour le dashboard."""
    try:
        existing: dict[str, Any] = {"debates": [], "last_updated": None}
        if DEBATES_LOG_PATH.exists():
            with open(DEBATES_LOG_PATH, encoding="utf-8") as f:
                existing = json.load(f)
        debates_list = existing.get("debates", [])
        if not isinstance(debates_list, list):
            debates_list = []
        # Format attendu par le dashboard: { agent, message?, content? }
        for d in result.debates:
            debates_list.append({
                "agent": d.get("agent", ""),
                "message": d.get("reasoning", "")[:400],
                "content": d.get("reasoning", "")[:400],
                "vote": d.get("vote", ""),
            })
        # Ajouter le résultat consolidé
        debates_list.append({
            "agent": "SWARM RESULT",
            "message": f"Résultat: {result.pct_yes:.0f}% YES ({result.votes_yes}/{result.votes_yes + result.votes_no}) • {'APPROUVÉ' if result.approved else 'REJETÉ'}",
            "content": f"Market {result.market_id} | {result.side} | Edge {result.edge_pct:.2f}% | Kelly {result.kelly:.2%} | Verdict: {'EXECUTE' if result.approved else 'SKIP'}",
        })
        with open(DEBATES_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "debates": debates_list[-100:],  # garder les 100 derniers
                "count": len(debates_list),
                "last_updated": datetime.utcnow().isoformat() + "Z",
                "latest_swarm": {
                    "market_id": result.market_id,
                    "side": result.side,
                    "pct_yes": result.pct_yes,
                    "approved": result.approved,
                    "votes_yes": result.votes_yes,
                    "votes_no": result.votes_no,
                },
            }, f, indent=2)
        log.info("Swarm result exported to ai_debates_log.json | pct_yes=%.0f%% | approved=%s", result.pct_yes, result.approved)
    except Exception as e:
        log.warning("swarm export error: %s", e)


def should_deploy_swarm(signal: dict[str, Any]) -> bool:
    """
    Détermine si le signal dépasse le seuil critique pour déployer le Swarm.
    Signaux: Unusual Whales, Polymarket (paperclip_pending_signals / EdgeEngine).
    """
    edge = float(signal.get("edge_pct", 0) or 0)
    return edge >= SWARM_CRITICAL_EDGE_PCT


async def run_swarm(signal: dict[str, Any]) -> SwarmResult:
    """
    Déploie l'essaim de micro-agents, collecte les votes, calcule le résultat.
    Export vers ai_debates_log.json.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    market_id = str(signal.get("market_id", ""))
    side = str(signal.get("side", "YES")).upper()
    question = str(signal.get("question", ""))[:200]
    edge_pct = float(signal.get("edge_pct", 0))
    kelly = float(signal.get("kelly_fraction", 0.25))
    polymarket_price = float(signal.get("polymarket_price", 0.5))

    user_prompt = (
        f"Market: {market_id}\nQuestion: {question}\n"
        f"Side: {side} | Polymarket price: {polymarket_price:.2f} | Edge: {edge_pct:.2f}% | Kelly: {kelly:.2%}\n"
        "Dois-tu voter YES (prendre le trade) ou NO (rejeter) ? Réponds en commençant par YES ou NO, puis une phrase."
    )

    votes: list[SwarmVote] = []
    tasks = []
    for i in range(SWARM_AGENT_COUNT):
        persona = _get_persona_for_agent(i)
        tasks.append((persona["name"], persona["system"], user_prompt))

    # Exécution parallèle (timeout 10s par agent pour ne pas bloquer)
    sem = asyncio.Semaphore(5)
    async def _one_agent(name: str, system: str, prompt: str) -> SwarmVote:
        async with sem:
            try:
                out = await asyncio.wait_for(_call_llm(api_key, model, system, prompt), timeout=10.0)
            except asyncio.TimeoutError:
                out = "NO. Timeout."
            except Exception as e:
                out = f"NO. {str(e)[:50]}"
        v = _parse_vote(out)
        return SwarmVote(agent_name=name, vote=v, reasoning=out[:300])

    results = await asyncio.gather(*[_one_agent(n, s, p) for n, s, p in tasks])
    votes = list(results)

    votes_yes = sum(1 for v in votes if v.vote == "YES")
    votes_no = len(votes) - votes_yes
    pct_yes = (votes_yes / len(votes)) * 100.0 if votes else 0
    approved = pct_yes >= 70.0

    debates_export = [
        {"agent": v.agent_name, "vote": v.vote, "reasoning": v.reasoning}
        for v in votes
    ]

    result = SwarmResult(
        market_id=market_id,
        side=side,
        question=question,
        edge_pct=edge_pct,
        kelly=kelly,
        votes_yes=votes_yes,
        votes_no=votes_no,
        pct_yes=pct_yes,
        approved=approved,
        debates=debates_export,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )

    _export_to_json(result)

    # Alpha Stream : poster une analyse condensée (style Twitter/X)
    try:
        from monitoring.telegram_alerts import send_alpha_stream

        best_yes = next((d for d in debates_export if d.get("vote") == "YES"), None)
        best_no = next((d for d in debates_export if d.get("vote") == "NO"), None)
        agent = (best_yes or best_no or debates_export[0]) if debates_export else {}
        analysis = (
            f"{result.question[:80]}...\n\n"
            f"Verdict Swarm: {'✅ EXECUTE' if result.approved else '❌ SKIP'} ({result.pct_yes:.0f}% YES)\n"
            f"{agent.get('reasoning', '')[:200]}"
        )
        await send_alpha_stream(
            agent_name=agent.get("agent", "Swarm"),
            analysis=analysis,
            market_context=f"{result.market_id} | Edge {result.edge_pct:.2f}%",
        )
    except Exception:
        pass

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_signal = {
        "market_id": "0x123",
        "side": "YES",
        "question": "Will BTC hit $100k by EOY?",
        "edge_pct": 4.5,
        "kelly_fraction": 0.2,
        "polymarket_price": 0.45,
    }
    r = asyncio.run(run_swarm(test_signal))
    print(f"Result: {r.pct_yes:.0f}% YES | Approved: {r.approved}")
