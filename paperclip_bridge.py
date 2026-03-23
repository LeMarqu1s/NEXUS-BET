"""
NEXUS BET - Pont Paperclip ↔ Python
Écrit les signaux dans un fichier pour que les agents Paperclip les traitent.
Le scanner appelle on_signal() → écrit dans paperclip_pending_signals.json.
Supabase backup: signaux aussi persistés en DB pour survivre aux redéploiements Railway.
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

# ── Supabase persistence (survives Railway redeploys) ──────────────────────────
_sb_client = None
_sb_initialized = False


def _sb():
    """Lazy singleton for sync Supabase client; returns None if not configured."""
    global _sb_client, _sb_initialized
    if _sb_initialized:
        return _sb_client
    _sb_initialized = True
    try:
        from config.settings import settings
        if not (getattr(settings, "SUPABASE_URL", None) and getattr(settings, "SUPABASE_KEY", None)):
            return None
        from supabase import create_client
        _sb_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    except Exception as e:
        log.debug("Supabase client init failed (non-critical): %s", e)
    return _sb_client


def _sb_upsert_signal(entry: dict[str, Any]) -> None:
    """Upsert a single signal to Supabase pending_signals table. Never raises."""
    try:
        sb = _sb()
        if sb is None:
            return
        import time
        payload = {**entry, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        sb.table("pending_signals").upsert(payload, on_conflict="market_id,side").execute()
    except Exception as e:
        log.debug("_sb_upsert_signal failed (non-critical): %s", e)


def _sb_delete_signal(market_id: str, side: str) -> None:
    """Remove a signal from Supabase pending_signals. Never raises."""
    try:
        sb = _sb()
        if sb is None:
            return
        sb.table("pending_signals").delete().eq("market_id", market_id).eq("side", side).execute()
    except Exception as e:
        log.debug("_sb_delete_signal failed (non-critical): %s", e)


def _sb_fetch_signals() -> list[dict[str, Any]]:
    """Fetch pending signals from Supabase, ordered by updated_at desc. Returns [] on failure."""
    try:
        sb = _sb()
        if sb is None:
            return []
        result = sb.table("pending_signals").select("*").order("updated_at", desc=True).limit(50).execute()
        rows = result.data or []
        # Remove Supabase metadata columns
        clean = []
        for r in rows:
            clean.append({k: v for k, v in r.items() if k not in ("id", "created_at", "updated_at")})
        return clean
    except Exception as e:
        log.debug("_sb_fetch_signals failed (non-critical): %s", e)
        return []


def write_scanner_state(market_count: int = 0, token_count: int = 0) -> None:
    """Met à jour market_count pour le dashboard et Telegram (assets trackés)."""
    try:
        data: dict[str, Any] = {"signals": []}
        if PENDING_SIGNALS_FILE.exists():
            try:
                with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {"signals": []}
        n = market_count or token_count
        data["market_count"] = n
        data["last_scan_ts"] = __import__("time").time()
        data["count"] = len(data.get("signals", []))
        tmp = PENDING_SIGNALS_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(PENDING_SIGNALS_FILE)
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
            # Persist to Supabase so signal survives Railway redeploys
            _sb_upsert_signal(entry)
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
    """Retourne les signaux en attente.
    Lit le fichier local en priorité; si absent/vide, bascule sur Supabase
    (survie aux redéploiements Railway où le filesystem est éphémère).
    """
    # 1. Try local file
    if PENDING_SIGNALS_FILE.exists():
        try:
            with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            signals = data.get("signals", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            if signals:
                log.info("Signals from local file: %d", len(signals))
                return signals
        except Exception as e:
            log.info("Local file read error: %s", e)
    else:
        log.info("Local signal file not found: %s", PENDING_SIGNALS_PATH)

    # 2. Fallback: fetch from Supabase
    sb_signals = _sb_fetch_signals()
    if sb_signals:
        log.info("Signals from Supabase fallback: %d", len(sb_signals))
        # Re-hydrate local file so next reads are fast
        try:
            import time
            out: dict[str, Any] = {
                "signals": sb_signals,
                "count": len(sb_signals),
                "market_count": 0,
                "last_scan_ts": time.time(),
            }
            tmp = PENDING_SIGNALS_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
            tmp.replace(PENDING_SIGNALS_FILE)
        except Exception:
            pass
    return sb_signals


def clear_signal(market_id: str, side: str) -> None:
    """Retire un signal traité de la file (local + Supabase)."""
    # Remove from local file
    if PENDING_SIGNALS_FILE.exists():
        try:
            with open(PENDING_SIGNALS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            signals = data.get("signals", []) if isinstance(data, dict) else []
            signals = [s for s in signals if not (s.get("market_id") == market_id and s.get("side") == side)]
            out: dict[str, Any] = {"signals": signals, "count": len(signals)}
            if isinstance(data, dict):
                out["market_count"] = data.get("market_count", 0)
                out["last_scan_ts"] = data.get("last_scan_ts", __import__("time").time())
            tmp = PENDING_SIGNALS_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
            tmp.replace(PENDING_SIGNALS_FILE)
        except Exception:
            pass
    # Remove from Supabase
    _sb_delete_signal(market_id, side)
