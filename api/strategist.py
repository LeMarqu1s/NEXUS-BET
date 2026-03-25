"""
NEXUS BET - Claude Strategist
Claude analyse ton portfolio et donne des recommandations stratégiques.
POST /api/strategist  ou  appelé directement via get_strategy().
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

log = logging.getLogger("nexus.strategist")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # rapide + économique pour le stratège
MAX_TOKENS   = 800
TIMEOUT_SEC  = 20.0


async def get_strategy(
    balance: float,
    positions: list[dict],
    recent_signals: list[dict],
    win_rate: float,
    risk_profile: str = "conservative",
) -> str:
    """
    Appelle Claude avec le contexte complet du portfolio.
    Retourne des recommandations stratégiques en français.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "⚠️ ANTHROPIC_API_KEY non configurée — stratège indisponible."

    try:
        import anthropic
    except ImportError:
        return "⚠️ Package anthropic manquant (pip install anthropic)."

    # ── Construire le contexte ──────────────────────────────────────────────
    pos_text = ""
    for p in positions[:5]:
        q   = (p.get("_question") or p.get("question") or "?")[:50]
        entry = float(p.get("avgPrice") or p.get("entry_price") or 0)
        cur   = float(p.get("_current") or p.get("current_price") or entry)
        pnl   = float(p.get("pnl_usd") or 0)
        side  = (p.get("outcome") or p.get("side") or "?").upper()
        pos_text += f"• {q} ({side}) @{entry:.2f}→{cur:.2f} P&L {pnl:+.2f}$\n"

    sig_text = ""
    for s in recent_signals[:3]:
        q = (s.get("question") or s.get("market_id") or "?")[:45]
        edge = float(s.get("edge_pct") or 0)
        side = (s.get("side") or "YES").upper()
        sig_text += f"• {q}: {side} edge {edge:+.1f}%\n"

    system_prompt = (
        "Tu es le stratège de NEXUS BET, un bot de trading automatique sur Polymarket. "
        "Ton rôle est d'analyser le portfolio et de donner des conseils précis et actionnables. "
        "Sois direct, concis, parle en français, utilise des chiffres. "
        "Tes recommandations doivent être spécifiques (ex: 'ferme X si price < 0.15', "
        "'cible les signaux BOND avec edge > 8%', 'réserve $5 pour la prochaine opportunité'). "
        "Max 5 recommandations, chacune en 1-2 lignes."
    )

    user_prompt = (
        f"Voici l'état actuel du portfolio NEXUS BET :\n\n"
        f"💵 Balance: ${balance:.2f} USDC\n"
        f"📊 Win rate récent: {win_rate:.0f}%\n"
        f"🎯 Profil de risque: {risk_profile}\n\n"
        f"📋 Positions ouvertes ({len(positions)}) :\n{pos_text or '  Aucune position ouverte.\n'}\n"
        f"⚡ Signaux récents disponibles :\n{sig_text or '  Aucun signal récent.\n'}\n"
        f"Donne-moi 3-5 recommandations stratégiques spécifiques pour maximiser les gains "
        f"et protéger le capital."
    )

    # ── Appel Claude ────────────────────────────────────────────────────────
    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await asyncio.wait_for(
            client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ),
            timeout=TIMEOUT_SEC,
        )
        text = response.content[0].text if response.content else ""
        await client.close()
        return text.strip()
    except asyncio.TimeoutError:
        return "⏱️ Claude timeout — réessaie dans quelques secondes."
    except Exception as e:
        log.error("get_strategy: %s", e)
        return f"⚠️ Erreur stratège : {type(e).__name__}"
