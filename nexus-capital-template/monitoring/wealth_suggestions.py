"""
NEXUS CAPITAL - Pending Wealth Suggestions (Phase 6)
Stocke les suggestions Swarm en attente d'approbation CEO.
Callback approve/wait → exécution <500ms.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("nexus.wealth_suggestions")

SUGGESTIONS_PATH = Path(__file__).resolve().parent.parent / "wealth_pending_suggestions.json"
_MAX_AGE_SEC = 3600  # 1h


def _load() -> dict[str, list[dict[str, Any]]]:
    if not SUGGESTIONS_PATH.exists():
        return {"suggestions": []}
    try:
        with open(SUGGESTIONS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"suggestions": []}


def _save(data: dict[str, Any]) -> None:
    try:
        SUGGESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SUGGESTIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.warning("wealth_suggestions save error: %s", e)


def store_suggestion(
    market_id: str,
    outcome: str,
    side: str,
    size_usd: float,
    limit_price: float,
    question: str,
    pct_yes: float,
    profile: str,
) -> str:
    """Stocke une suggestion et retourne l'ID."""
    sid = str(uuid.uuid4())[:8]
    data = _load()
    suggestions = data.get("suggestions", [])
    suggestions.append({
        "id": sid,
        "market_id": market_id,
        "outcome": outcome,
        "side": side.upper(),
        "size_usd": size_usd,
        "limit_price": limit_price,
        "question": question[:80],
        "pct_yes": pct_yes,
        "profile": profile,
        "created": time.time(),
    })
    data["suggestions"] = suggestions[-50:]  # garder 50 max
    _save(data)
    return sid


def get_suggestion(sid: str) -> Optional[dict[str, Any]]:
    """Récupère une suggestion par ID."""
    data = _load()
    now = time.time()
    for s in data.get("suggestions", []):
        if s.get("id") == sid:
            if now - s.get("created", 0) > _MAX_AGE_SEC:
                return None
            return s
    return None


def remove_suggestion(sid: str) -> None:
    """Supprime une suggestion."""
    data = _load()
    data["suggestions"] = [s for s in data.get("suggestions", []) if s.get("id") != sid]
    _save(data)
