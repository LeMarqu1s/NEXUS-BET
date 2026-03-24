"""
NEXUS BET — Paper Portfolio (simulation $50)

Enregistre automatiquement les trades papier à partir des signaux détectés.
Stockage dans logs/paper_trades.json — aucune dépendance externe.

Capital de départ : $50 (PAPER_CAPITAL_USD env ou défaut)
Position size    : capital / MAX_POSITIONS (max 5 simultanées)
Auto-sync        : lit paperclip_pending_signals.json à chaque affichage
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("nexus.paper")

PAPER_CAPITAL: float = float(os.getenv("PAPER_CAPITAL_USD", "50"))
MAX_POSITIONS: int = 5
TRADE_SIZE_USD: float = PAPER_CAPITAL / MAX_POSITIONS  # $10 par position

_ROOT = Path(__file__).resolve().parent.parent
PAPER_FILE = _ROOT / "logs" / "paper_trades.json"
SIGNALS_FILE = _ROOT / "paperclip_pending_signals.json"


# ── Stockage JSON ─────────────────────────────────────────────────────────────

def _load() -> dict[str, Any]:
    PAPER_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PAPER_FILE.exists():
        try:
            return json.loads(PAPER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"trades": [], "created_at": time.time()}


def _save(data: dict[str, Any]) -> None:
    PAPER_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAPER_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Enregistrement d'un trade ─────────────────────────────────────────────────

def record_paper_trade(signal: dict[str, Any]) -> bool:
    """
    Crée un trade papier à partir d'un signal si :
    - Le marché n'est pas déjà en position ouverte
    - On n'a pas atteint MAX_POSITIONS
    - Le prix d'entrée est valide (> 0)
    Retourne True si un nouveau trade a été créé.
    """
    market_id = str(signal.get("market_id") or "").strip()
    side = str(signal.get("side") or "YES").upper()
    if not market_id:
        return False

    data = _load()
    trades: list[dict[str, Any]] = data.setdefault("trades", [])

    # Pas de doublon sur marché + side
    if any(
        t.get("market_id") == market_id
        and t.get("side") == side
        and t.get("status") == "OPEN"
        for t in trades
    ):
        return False

    # Vérifier le budget
    open_count = sum(1 for t in trades if t.get("status") == "OPEN")
    if open_count >= MAX_POSITIONS:
        return False

    entry_price = float(signal.get("polymarket_price") or signal.get("price") or 0)
    if entry_price <= 0 or entry_price >= 1:
        return False

    trade: dict[str, Any] = {
        "id": f"paper_{int(time.time())}_{market_id[:8]}",
        "market_id": market_id,
        "question": str(signal.get("question") or market_id)[:80],
        "side": side,
        "entry_price": entry_price,
        "size_usd": TRADE_SIZE_USD,
        "shares": round(TRADE_SIZE_USD / entry_price, 4),
        "edge_pct": float(signal.get("edge_pct") or 0),
        "status": "OPEN",
        "created_at": time.time(),
        "exit_price": None,
        "closed_at": None,
        "pnl_usd": None,
    }
    trades.append(trade)
    _save(data)
    log.info(
        "Paper trade créé : %s %s @%.3f $%.2f",
        side, trade["question"][:40], entry_price, TRADE_SIZE_USD,
    )
    return True


def close_paper_trade(market_id: str, side: str, exit_price: float) -> bool:
    """Clôture un trade papier. Retourne True si trouvé et clôturé."""
    data = _load()
    changed = False
    for t in data.get("trades", []):
        if (
            t.get("market_id") == market_id
            and t.get("side") == side
            and t.get("status") == "OPEN"
        ):
            t["status"] = "CLOSED"
            t["exit_price"] = exit_price
            t["closed_at"] = time.time()
            t["pnl_usd"] = round((exit_price - t["entry_price"]) * t["shares"], 4)
            changed = True
    if changed:
        _save(data)
    return changed


# ── Sync depuis les signaux détectés ─────────────────────────────────────────

def sync_from_signals() -> int:
    """
    Lit paperclip_pending_signals.json et crée des trades papier pour
    les signaux non encore trackés. Retourne le nombre de nouveaux trades.
    """
    try:
        if not SIGNALS_FILE.exists():
            return 0
        raw = json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
        signals = raw.get("signals", []) if isinstance(raw, dict) else raw
        count = 0
        for sig in signals:
            if record_paper_trade(sig):
                count += 1
        if count:
            log.info("Paper sync: %d nouveau(x) trade(s) créé(s)", count)
        return count
    except Exception as e:
        log.debug("sync_from_signals: %s", e)
        return 0


# ── Résumé portfolio ──────────────────────────────────────────────────────────

def get_paper_summary(current_prices: dict[str, float] | None = None) -> dict[str, Any]:
    """
    Calcule le résumé complet du portfolio papier.

    current_prices : {market_id: prix_actuel} — si absent, utilise le prix d'entrée
                     (P&L = 0 pour les positions sans prix live).
    """
    data = _load()
    trades: list[dict[str, Any]] = data.get("trades", [])

    open_trades: list[dict[str, Any]] = []
    closed_trades: list[dict[str, Any]] = []
    total_invested = 0.0
    total_current = 0.0
    closed_pnl = 0.0

    for t in trades:
        entry = float(t.get("entry_price") or 0)
        shares = float(t.get("shares") or 0)
        size = float(t.get("size_usd") or TRADE_SIZE_USD)

        if t.get("status") == "OPEN":
            cp = (current_prices or {}).get(t["market_id"])
            current_price = cp if cp is not None else entry  # fallback = pas de gain/perte
            current_val = current_price * shares
            pnl_usd = current_val - size
            pnl_pct = (pnl_usd / size * 100) if size > 0 else 0.0
            total_invested += size
            total_current += current_val
            open_trades.append({
                **t,
                "current_price": current_price,
                "current_val": current_val,
                "pnl_usd": round(pnl_usd, 4),
                "pnl_pct": round(pnl_pct, 2),
            })
        else:
            pnl = float(t.get("pnl_usd") or 0)
            closed_pnl += pnl
            closed_trades.append(t)

    unrealized_pnl = total_current - total_invested
    total_pnl = unrealized_pnl + closed_pnl
    free_capital = PAPER_CAPITAL - total_invested

    wins = sum(1 for t in closed_trades if float(t.get("pnl_usd") or 0) > 0)
    total_closed = len(closed_trades)

    return {
        "capital": PAPER_CAPITAL,
        "invested": round(total_invested, 2),
        "free": round(free_capital, 2),
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
