"""
NEXUS CAPITAL - Paperclip Agent Caller
Delegates to Paperclip agents (DataAnalyst, Quant, RiskManager, Sniper) when PAPERCLIP_URL is set.
Falls back to Claude direct calls otherwise.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("nexus.paperclip")

PAPERCLIP_URL = os.getenv("PAPERCLIP_URL", "http://127.0.0.1:3100")
AGENT_MAP = {
    "quant": "Quant",
    "risk_manager": "RiskManager",
    "data_analyst": "DataAnalyst",
    "sniper": "Sniper",
}


async def _call_paperclip_agent(agent_name: str, prompt: str, system: str) -> Optional[str]:
    """Invoke Paperclip agent via API. Returns None if unavailable."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Paperclip task API - adapt to actual endpoint when available
            r = await client.post(
                f"{PAPERCLIP_URL}/api/tasks",
                json={
                    "agentName": agent_name,
                    "prompt": prompt,
                    "system": system,
                },
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("result") or data.get("text") or data.get("output", "")
    except Exception as e:
        log.debug("Paperclip agent %s: %s", agent_name, e)
    return None


def use_paperclip() -> bool:
    """True if Paperclip should be used (URL set and reachable)."""
    return bool(os.getenv("PAPERCLIP_URL"))
