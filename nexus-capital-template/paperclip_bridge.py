"""
NEXUS BET - Pont Paperclip ↔ Python
Écrit les signaux dans un fichier pour que les agents Paperclip les traitent.
Le scanner appelle on_signal() → écrit dans paperclip_pending_signals.json.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.edge_engine import EdgeSignal

PENDING_SIGNALS_FILE = Path(__file__).resolve().parent / "paperclip_pending_signals.json"
log = logging.getLogger("nexus.paperclip_bridge")


def on_signal(sig: EdgeSignal) -> None:
    """
    Callback appelé par le scanner quand un signal est détecté.
    Ajoute le signal à la file pour que les agents Paperclip le traitent.
    """
    if not PENDING_SIGNALS_FILE.parent.exists():
        return
    try:
        existing: list[dict[str, Any]] = []
        if PENDING_SIGNALS_FILE.exists():
            with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
                data = json.load(f)
                existing = data.get("signals", []) if isinstance(data, dict) else data

        entry = {
            "market_id": sig.market_id,
            "token_id": sig.token_id,
            "side": sig.side,
            "question": sig.metadata.get("question", "")[:120],
            "polymarket_price": sig.polymarket_price,
            "edge_pct": sig.edge_pct * 100,
            "kelly_fraction": sig.kelly_fraction,
            "model": sig.model.value,
            "confidence": sig.confidence,
        }
        # Éviter les doublons
        if not any(e.get("market_id") == entry["market_id"] and e.get("side") == entry["side"] for e in existing):
            existing.append(entry)
            with open(PENDING_SIGNALS_FILE, "w", encoding="utf-8") as f:
                json.dump({"signals": existing[-50:], "count": len(existing)}, f, indent=2)
            log.info("Signal enregistré pour Paperclip: %s %s edge=%.2f%%", sig.market_id, sig.side, sig.edge_pct * 100)
    except Exception as e:
        log.warning("paperclip_bridge on_signal error: %s", e)


def get_pending_signals() -> list[dict[str, Any]]:
    """Retourne les signaux en attente (pour les agents Paperclip)."""
    if not PENDING_SIGNALS_FILE.exists():
        return []
    try:
        with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return data.get("signals", []) if isinstance(data, dict) else data
    except Exception:
        return []


def clear_signal(market_id: str, side: str) -> None:
    """Retire un signal traité de la file."""
    if not PENDING_SIGNALS_FILE.exists():
        return
    try:
        with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        signals = data.get("signals", []) if isinstance(data, dict) else []
        signals = [s for s in signals if not (s.get("market_id") == market_id and s.get("side") == side)]
        with open(PENDING_SIGNALS_FILE, "w", encoding="utf-8") as f:
            json.dump({"signals": signals, "count": len(signals)}, f, indent=2)
    except Exception:
        pass
