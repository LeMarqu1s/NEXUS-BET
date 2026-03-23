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

# Use project root: parent of paperclip_bridge.py. Fallback to cwd for Railway.
_proj_root = Path(__file__).resolve().parent
PENDING_SIGNALS_FILE = _proj_root / "paperclip_pending_signals.json"
PENDING_SIGNALS_PATH = str(PENDING_SIGNALS_FILE.resolve())
log = logging.getLogger("nexus.paperclip_bridge")


def write_scanner_state(market_count: int = 0, token_count: int = 0) -> None:
    """Met à jour market_count pour le dashboard et Telegram (assets trackés)."""
    try:
        data: dict[str, Any] = {"signals": []}
        if PENDING_SIGNALS_FILE.exists():
            with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        n = market_count or token_count
        data["market_count"] = n
        data["last_scan_ts"] = __import__("time").time()
        data["count"] = len(data.get("signals", []))
        with open(PENDING_SIGNALS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.debug("write_scanner_state: %s", e)


def on_signal(sig: EdgeSignal) -> None:
    """
    Callback appelé par le scanner quand un signal est détecté.
    Ajoute le signal à la file pour que les agents Paperclip le traitent.
    """
    if not PENDING_SIGNALS_FILE.parent.exists():
        return
    try:
        existing: list[dict[str, Any]] = []
        data: dict[str, Any] = {}
        if PENDING_SIGNALS_FILE.exists():
            try:
                with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                existing = data.get("signals", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            except Exception as read_err:
                log.warning("on_signal: could not read existing signals (treating as empty): %s", read_err)
                existing = []
                data = {}

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
        }
        # Éviter les doublons
        if not any(e.get("market_id") == entry["market_id"] and e.get("side") == entry["side"] for e in existing):
            existing.append(entry)
            out: dict[str, Any] = {"signals": existing[-50:], "count": len(existing)}
            if isinstance(data, dict):
                out["market_count"] = data.get("market_count", 0)
                out["last_scan_ts"] = data.get("last_scan_ts", __import__("time").time())
            else:
                out["last_scan_ts"] = __import__("time").time()
            # Atomic write: .tmp then rename to prevent partial-write corruption
            tmp = PENDING_SIGNALS_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
            tmp.replace(PENDING_SIGNALS_FILE)
            log.info("Signal enregistré pour Paperclip: %s %s edge=%.2f%%", sig.market_id, sig.side, sig.edge_pct * 100)
            # Push signal card notification (every signal, card for STRONG_BUY)
            try:
                import asyncio
                import os
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN", "")
                chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
                strength = getattr(sig, "signal_strength", "BUY")
                loop = asyncio.get_running_loop()
                if strength == "STRONG_BUY" and bot_token and chat_id:
                    from monitoring.signal_card_generator import send_signal_card
                    loop.create_task(send_signal_card(entry, bot_token, chat_id))
                else:
                    from monitoring.telegram_alerts import send_telegram_message
                    import html as _html
                    q = _html.escape(entry.get("question", "")[:60])
                    edge_val = entry.get("edge_pct", 0)
                    icon = "🔥" if strength == "STRONG_BUY" else "⚡"
                    msg = f"{icon} <b>{strength}</b>\n<i>{q}</i>\nEdge: <b>{edge_val:.1f}%</b>"
                    loop.create_task(send_telegram_message(msg))
            except RuntimeError:
                pass  # No running loop (sync context)
            except Exception:
                pass
    except Exception as e:
        log.warning("paperclip_bridge on_signal error: %s", e)


def get_pending_signals() -> list[dict[str, Any]]:
    """Retourne les signaux en attente (pour les agents Paperclip)."""
    path = PENDING_SIGNALS_PATH
    log.info("Reading signals from: %s", path)
    if not PENDING_SIGNALS_FILE.exists():
        log.info("File does not exist: %s", path)
        return []
    try:
        with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        signals = data.get("signals", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        log.info("File contents: count=%d signals=%d", data.get("count", 0) if isinstance(data, dict) else 0, len(signals))
        return signals
    except Exception as e:
        log.info("File read error: %s", e)
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
        out = {"signals": signals, "count": len(signals)}
        if isinstance(data, dict):
            out["market_count"] = data.get("market_count", 0)
            out["last_scan_ts"] = data.get("last_scan_ts", __import__("time").time())
        with open(PENDING_SIGNALS_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
    except Exception:
        pass
