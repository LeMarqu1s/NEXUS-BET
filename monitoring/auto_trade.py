"""
NEXUS CAPITAL - Auto-Trade with Safeguards
STRONG_BUY → execute immediately | BUY → Telegram confirmation, 30min timeout → auto-execute
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("nexus.auto_trade")

PENDING_CONFIRM_PATH = Path(__file__).resolve().parent.parent / "auto_trade_pending.json"
CONFIRM_TIMEOUT_SEC = 30 * 60  # 30 min
STRONG_BUY_EDGE_PCT = 15.0
STRONG_BUY_CONFIDENCE = 0.9


def _get(key: str, default: Any) -> Any:
    v = os.getenv(key)
    if v is None:
        return default
    if isinstance(default, bool):
        return v.lower() in ("true", "1", "yes")
    if isinstance(default, int):
        try:
            return int(v)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(v)
        except ValueError:
            return default
    return v


def is_auto_trade_enabled() -> bool:
    return _get("AUTO_TRADE_ENABLED", False)


def get_max_positions() -> int:
    return _get("AUTO_TRADE_MAX_POSITIONS", 3)


def get_daily_drawdown_limit_pct() -> float:
    return _get("AUTO_TRADE_DAILY_DRAWDOWN_LIMIT", 20.0)


def get_max_position_pct() -> float:
    from config.settings import settings
    return settings.MAX_POSITION_PCT


def get_confirm_required_for_buy() -> bool:
    return _get("AUTO_TRADE_CONFIRM_BUY", True)


def _daily_pnl() -> float:
    """Sum PnL for today from trade_logger."""
    try:
        from monitoring.trade_logger import trade_logger
        trades = trade_logger.get_recent_trades(limit=500)
        today = datetime.now(timezone.utc).date().isoformat()
        return sum(float(t.get("pnl") or 0) for t in trades if str(t.get("created_at", ""))[:10] == today)
    except Exception:
        return 0.0


def _daily_drawdown_pct() -> float:
    """Daily drawdown as % of capital. Positive = loss."""
    try:
        from config.settings import settings
        cap = settings.POLYMARKET_CAPITAL_USD
        if cap <= 0:
            return 0.0
        pnl = _daily_pnl()
        if pnl >= 0:
            return 0.0
        return abs(pnl) / cap * 100
    except Exception:
        return 0.0


def is_daily_drawdown_breached() -> bool:
    limit = get_daily_drawdown_limit_pct()
    current = _daily_drawdown_pct()
    return current >= limit


def get_open_positions_count() -> int:
    try:
        from monitoring.trade_logger import trade_logger
        return len(trade_logger.get_positions())
    except Exception:
        return 0


def _compute_size_usd(sig: dict[str, Any]) -> float:
    """Size respecting MAX_POSITION_PCT."""
    try:
        from config.settings import settings
        cap = settings.POLYMARKET_CAPITAL_USD
        kelly = float(sig.get("kelly_fraction", 0.25))
        max_pct = get_max_position_pct()
        size = cap * min(kelly, max_pct)
        return max(1.0, min(size, cap * max_pct))
    except Exception:
        return 10.0


def _signal_strength(sig: dict[str, Any]) -> str:
    """STRONG_BUY or BUY."""
    edge = float(sig.get("edge_pct", 0))
    conf = float(sig.get("confidence", 0))
    if edge >= STRONG_BUY_EDGE_PCT and conf >= STRONG_BUY_CONFIDENCE:
        return "STRONG_BUY"
    return "BUY"


def _load_pending() -> dict[str, Any]:
    if not PENDING_CONFIRM_PATH.exists():
        return {"pending": []}
    try:
        return json.loads(PENDING_CONFIRM_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"pending": []}


def _save_pending(data: dict[str, Any]) -> None:
    try:
        PENDING_CONFIRM_PATH.parent.mkdir(parents=True, exist_ok=True)
        PENDING_CONFIRM_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("auto_trade save pending: %s", e)


def store_pending_confirm(sig: dict[str, Any]) -> str:
    sid = str(uuid.uuid4())[:8]
    data = _load_pending()
    data["pending"] = data.get("pending", []) + [{
        "id": sid,
        "signal": sig,
        "created": time.time(),
    }]
    data["pending"] = data["pending"][-20:]
    _save_pending(data)
    return sid


def get_pending_confirm(sid: str) -> Optional[dict[str, Any]]:
    data = _load_pending()
    now = time.time()
    for p in data.get("pending", []):
        if p.get("id") == sid:
            if now - p.get("created", 0) > CONFIRM_TIMEOUT_SEC:
                return None
            return p.get("signal")
    return None


def remove_pending_confirm(sid: str) -> None:
    data = _load_pending()
    data["pending"] = [p for p in data.get("pending", []) if p.get("id") != sid]
    _save_pending(data)


def get_and_clear_expired_pending() -> list[dict[str, Any]]:
    """Returns and removes pending signals past 30min timeout."""
    data = _load_pending()
    now = time.time()
    pending = data.get("pending", [])
    expired = [p for p in pending if now - p.get("created", 0) >= CONFIRM_TIMEOUT_SEC]
    if expired:
        data["pending"] = [p for p in pending if p not in expired]
        _save_pending(data)
    return expired


async def execute_signal(sig: dict[str, Any]) -> Optional[str]:
    """Place order for signal. Returns order_id or None."""
    try:
        from execution.order_manager import OrderManager, OrderConfig
        size = _compute_size_usd(sig)
        cfg = OrderConfig(
            market_id=sig["market_id"],
            outcome=sig["side"],
            side="BUY",
            size_usd=size,
            limit_price=float(sig.get("polymarket_price", 0.5)),
        )
        om = OrderManager()
        return await om.place_limit_order(cfg)
    except Exception as e:
        log.warning("auto_trade execute_signal: %s", e)
        return None


async def process_signal(
    sig: dict[str, Any],
    send_telegram: Callable[[str, Optional[dict]], Any],
) -> bool:
    """
    Process signal: STRONG_BUY → execute if enabled; BUY → confirm or auto after timeout.
    Returns True if executed or queued.
    """
    if not is_auto_trade_enabled():
        return False
    if is_daily_drawdown_breached():
        log.info("[AUTO_TRADE] Daily drawdown limit breached, skipping")
        return False
    if get_open_positions_count() >= get_max_positions():
        log.info("[AUTO_TRADE] Max positions reached, skipping")
        return False

    strength = _signal_strength(sig)
    sig["signal_strength"] = strength

    if strength == "STRONG_BUY":
        order_id = await execute_signal(sig)
        if order_id:
            await send_telegram(
                f"⚡ <b>STRONG_BUY exécuté</b>\n{sig.get('question','')[:50]}...\nOrder: {order_id}",
                reply_markup=None,
            )
            return True
        return False

    # BUY: confirmation required?
    if get_confirm_required_for_buy():
        sid = store_pending_confirm(sig)
        q = (sig.get("question") or "")[:60]
        msg = (
            f"<b>BUY</b> – Confirmer?\n"
            f"Edge: {sig.get('edge_pct',0):.1f}% | Kelly: {(sig.get('kelly_fraction',0)*100):.1f}%\n"
            f"<i>{q}...</i>\n\n"
            f"⏱ Auto-exécution dans 30 min si pas de réponse."
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "✅ Confirmer", "callback_data": f"autotrade_confirm_{sid}"},
                    {"text": "❌ Ignorer", "callback_data": f"autotrade_ignore_{sid}"},
                ]
            ]
        }
        await send_telegram(msg, reply_markup=kb)
        return True

    # BUY without confirmation: execute
    order_id = await execute_signal(sig)
    return order_id is not None
