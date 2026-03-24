"""
NEXUS BET - Paper Portfolio ($50 simulation capital)
Tracks paper trades from paperclip_pending_signals.json.
Thread-safe JSON storage in logs/paper_trades.json.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.Lock()

PAPER_CAPITAL = float(os.getenv("PAPER_CAPITAL_USD", "50"))
MAX_POSITIONS = 5
TRADE_SIZE_USD = PAPER_CAPITAL / MAX_POSITIONS  # $10 per position
PAPER_FILE = _ROOT / "logs" / "paper_trades.json"


def _load() -> dict:
    PAPER_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not PAPER_FILE.exists():
        return {"trades": []}
    try:
        return json.loads(PAPER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"trades": []}


def _save(data: dict) -> None:
    PAPER_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAPER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_paper_trade(signal: dict) -> bool:
    """Create a paper trade from a signal dict. Returns True if created."""
    market_id = signal.get("market_id") or signal.get("conditionId") or ""
    side = signal.get("side", "YES")
    price = float(signal.get("polymarket_price") or signal.get("entry_price") or 0)
    if not market_id or price <= 0 or price >= 1:
        return False
    with _LOCK:
        data = _load()
        trades = data.get("trades", [])
        open_count = sum(1 for t in trades if t.get("status") == "OPEN")
        if open_count >= MAX_POSITIONS:
            return False
        # No duplicate open positions on same market+side
        if any(t.get("market_id") == market_id and t.get("side") == side and t.get("status") == "OPEN" for t in trades):
            return False
        shares = TRADE_SIZE_USD / price
        trade = {
            "id": f"paper_{int(time.time())}_{market_id[:8]}",
            "market_id": market_id,
            "question": (signal.get("question") or "")[:100],
            "side": side,
            "entry_price": round(price, 4),
            "shares": round(shares, 4),
            "size_usd": TRADE_SIZE_USD,
            "status": "OPEN",
            "created_at": int(time.time()),
            "edge_pct": signal.get("edge_pct"),
            "confidence": signal.get("confidence"),
        }
        trades.append(trade)
        data["trades"] = trades
        _save(data)
        return True


def close_paper_trade(market_id: str, side: str, exit_price: float) -> Optional[dict]:
    """Close an open paper trade. Returns trade dict with pnl or None."""
    with _LOCK:
        data = _load()
        trades = data.get("trades", [])
        for t in trades:
            if t.get("market_id") == market_id and t.get("side") == side and t.get("status") == "OPEN":
                entry = float(t.get("entry_price") or 0)
                shares = float(t.get("shares") or 0)
                size = float(t.get("size_usd") or TRADE_SIZE_USD)
                exit_val = exit_price * shares
                pnl = exit_val - size
                pnl_pct = (pnl / size * 100) if size > 0 else 0.0
                t["status"] = "CLOSED"
                t["exit_price"] = round(exit_price, 4)
                t["pnl_usd"] = round(pnl, 4)
                t["pnl_pct"] = round(pnl_pct, 2)
                t["closed_at"] = int(time.time())
                data["trades"] = trades
                _save(data)
                return t
    return None


def sync_from_signals() -> int:
    """Read paperclip_pending_signals.json and create paper trades for new signals. Returns count added."""
    p = _ROOT / "paperclip_pending_signals.json"
    if not p.exists():
        return 0
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return 0
    signals = raw.get("signals", []) if isinstance(raw, dict) else raw or []
    added = 0
    for s in signals:
        if record_paper_trade(s):
            added += 1
    return added


def get_paper_summary(current_prices: Optional[dict] = None) -> dict:
    """
    Returns summary dict:
    capital, invested, free, unrealized_pnl, closed_pnl, total_pnl, total_pnl_pct,
    open_trades (sorted by |pnl_pct|), closed_trades (last 5), wins, total_closed, win_rate
    """
    data = _load()
    trades = data.get("trades", [])
    cp = current_prices or {}

    open_trades: list = []
    closed_trades: list = []
    total_invested = 0.0
    total_current = 0.0
    closed_pnl = 0.0

    for t in trades:
        entry = float(t.get("entry_price") or 0)
        shares = float(t.get("shares") or 0)
        size = float(t.get("size_usd") or TRADE_SIZE_USD)
        if t.get("status") == "OPEN":
            cur = float(cp.get(t.get("market_id", ""), entry))
            current_val = cur * shares
            pnl_usd = current_val - size
            pnl_pct = (pnl_usd / size * 100) if size > 0 else 0.0
            total_invested += size
            total_current += current_val
            open_trades.append({**t, "current_price": cur, "current_val": round(current_val, 4),
                                 "pnl_usd": round(pnl_usd, 4), "pnl_pct": round(pnl_pct, 2)})
        else:
            closed_pnl += float(t.get("pnl_usd") or 0)
            closed_trades.append(t)

    unrealized_pnl = total_current - total_invested
    total_pnl = unrealized_pnl + closed_pnl
    wins = sum(1 for t in closed_trades if float(t.get("pnl_usd") or 0) > 0)
    total_closed = len(closed_trades)

    return {
        "capital": PAPER_CAPITAL,
        "invested": round(total_invested, 2),
        "free": round(PAPER_CAPITAL - total_invested, 2),
        "current_value": round(total_current, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "closed_pnl": round(closed_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round((total_pnl / PAPER_CAPITAL * 100) if PAPER_CAPITAL > 0 else 0, 1),
        "open_trades": sorted(open_trades, key=lambda x: -abs(x["pnl_pct"])),
        "closed_trades": sorted(closed_trades, key=lambda x: -(x.get("closed_at") or 0))[:5],
        "wins": wins,
        "total_closed": total_closed,
        "win_rate": round((wins / total_closed * 100) if total_closed > 0 else 0, 0),
    }
