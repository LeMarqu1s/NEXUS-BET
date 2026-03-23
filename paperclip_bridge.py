"""
NEXUS BET - Pont Paperclip ↔ Python
Écrit les signaux dans un fichier pour que les agents Paperclip les traitent.
Le scanner appelle on_signal() → écrit dans paperclip_pending_signals.json.
IN-MEMORY CACHE: both scanner and Telegram share _signal_store (same process).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from core.edge_engine import EdgeSignal

# Use project root: parent of paperclip_bridge.py. Fallback to cwd for Railway.
_proj_root = Path(__file__).resolve().parent
PENDING_SIGNALS_FILE = _proj_root / "paperclip_pending_signals.json"
PENDING_SIGNALS_PATH = str(PENDING_SIGNALS_FILE.resolve())
log = logging.getLogger("nexus.paperclip_bridge")

# ── In-memory signal store (shared across scanner + telegram in same process) ──
_signal_store: list[dict[str, Any]] = []
_market_count: int = 0
_last_scan_ts: float = 0.0


def _update_memory(signals: list[dict[str, Any]], market_count: int = 0, scan_ts: float = 0.0) -> None:
    """Sync in-memory store from file data."""
    global _signal_store, _market_count, _last_scan_ts
    _signal_store = list(signals[-50:])
    if market_count:
        _market_count = market_count
    if scan_ts:
        _last_scan_ts = scan_ts


def write_scanner_state(market_count: int = 0, token_count: int = 0) -> None:
    """Met à jour market_count pour le dashboard et Telegram (assets trackés)."""
    global _market_count, _last_scan_ts
    n = market_count or token_count
    _market_count = n
    _last_scan_ts = time.time()
    try:
        data: dict[str, Any] = {"signals": list(_signal_store)}
        if PENDING_SIGNALS_FILE.exists():
            with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                data = existing
        data["market_count"] = n
        data["last_scan_ts"] = _last_scan_ts
        data["count"] = len(data.get("signals", []))
        with open(PENDING_SIGNALS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.debug("write_scanner_state: %s", e)


def on_signal(sig: EdgeSignal) -> None:
    """
    Callback appelé par le scanner quand un signal est détecté.
    Ajoute le signal à la file en mémoire ET dans le fichier JSON.
    """
    global _signal_store, _last_scan_ts
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
        "signal_strength": getattr(sig, "signal_strength", "BUY"),
        "market_type": getattr(sig, "market_type", "binary"),
        "recommended_outcome": getattr(sig, "recommended_outcome", sig.side),
        "ts": time.time(),
    }

    # ── Update in-memory store first (always succeeds) ──
    if not any(e.get("market_id") == entry["market_id"] and e.get("side") == entry["side"] for e in _signal_store):
        _signal_store.append(entry)
        _signal_store = _signal_store[-50:]
        _last_scan_ts = time.time()
        log.info("Signal stored (memory): %s %s edge=%.2f%%", sig.market_id, sig.side, sig.edge_pct * 100)

    # ── Persist to file ──
    if not PENDING_SIGNALS_FILE.parent.exists():
        return
    try:
        existing: list[dict[str, Any]] = list(_signal_store)  # use memory as source of truth
        out: dict[str, Any] = {
            "signals": existing,
            "count": len(existing),
            "market_count": _market_count,
            "last_scan_ts": _last_scan_ts,
        }
        with open(PENDING_SIGNALS_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        # Push notification for STRONG_BUY: send signal card image
        if getattr(sig, "signal_strength", "BUY") == "STRONG_BUY":
            try:
                import asyncio
                from monitoring.telegram_alerts import send_signal_card
                loop = asyncio.get_running_loop()
                loop.create_task(send_signal_card(entry))
            except RuntimeError:
                pass
            except Exception:
                pass
    except Exception as e:
        log.warning("paperclip_bridge on_signal file write error: %s", e)


def get_pending_signals() -> list[dict[str, Any]]:
    """Retourne les signaux en attente. Uses in-memory store first, file as fallback."""
    # ── 1. Return from memory if populated ──
    if _signal_store:
        log.info("Signals from memory: %d signals", len(_signal_store))
        return list(_signal_store)

    # ── 2. Try file ──
    log.info("Memory empty, reading from file: %s", PENDING_SIGNALS_PATH)
    if not PENDING_SIGNALS_FILE.exists():
        log.info("File does not exist: %s", PENDING_SIGNALS_PATH)
        return []
    try:
        with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        signals = data.get("signals", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        log.info("File fallback: %d signals", len(signals))
        # Warm up memory from file
        if signals:
            mc = data.get("market_count", 0) if isinstance(data, dict) else 0
            ts = data.get("last_scan_ts", 0) if isinstance(data, dict) else 0
            _update_memory(signals, mc, ts)
        return signals
    except Exception as e:
        log.warning("File read error: %s", e)
        return []


def get_market_count() -> int:
    """Returns tracked market count (from memory or file)."""
    if _market_count:
        return _market_count
    try:
        if PENDING_SIGNALS_FILE.exists():
            with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data.get("market_count", 0)
    except Exception:
        pass
    return 0


def get_last_scan_ts() -> float:
    """Returns last scan timestamp."""
    if _last_scan_ts:
        return _last_scan_ts
    try:
        if PENDING_SIGNALS_FILE.exists():
            with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return float(data.get("last_scan_ts", 0))
    except Exception:
        pass
    return 0.0


def clear_signal(market_id: str, side: str) -> None:
    """Retire un signal traité de la file (mémoire + fichier)."""
    global _signal_store
    _signal_store = [s for s in _signal_store if not (s.get("market_id") == market_id and s.get("side") == side)]
    if not PENDING_SIGNALS_FILE.exists():
        return
    try:
        with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        signals = data.get("signals", []) if isinstance(data, dict) else []
        signals = [s for s in signals if not (s.get("market_id") == market_id and s.get("side") == side)]
        out: dict[str, Any] = {
            "signals": signals,
            "count": len(signals),
            "market_count": data.get("market_count", 0) if isinstance(data, dict) else 0,
            "last_scan_ts": data.get("last_scan_ts", time.time()) if isinstance(data, dict) else time.time(),
        }
        with open(PENDING_SIGNALS_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
    except Exception:
        pass
