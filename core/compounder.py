"""
NEXUS BET - Compound Reinvestment Engine
Après chaque trade gagnant : 70% réinvesti, 30% réserve.
Projette la courbe de croissance composée.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("nexus.compounder")

_ROOT  = Path(__file__).resolve().parent.parent
_FILE  = _ROOT / "logs" / "compounder.json"
_LOCK  = threading.Lock()

REINVEST_RATIO  = 0.70   # 70% des gains réinvestis
RESERVE_RATIO   = 0.30   # 30% mis de côté


# ── Persistance ───────────────────────────────────────────────────────────────

def _load() -> dict:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _FILE.exists():
        base = float(os.getenv("PAPER_CAPITAL_USD", "50"))
        return {
            "capital": base,
            "reserve": 0.0,
            "total_reinvested": 0.0,
            "total_reserved": 0.0,
            "wins": 0,
            "losses": 0,
            "history": [],  # [{ts, profit, reinvested, reserved, capital}]
        }
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        base = float(os.getenv("PAPER_CAPITAL_USD", "50"))
        return {"capital": base, "reserve": 0.0, "total_reinvested": 0.0,
                "total_reserved": 0.0, "wins": 0, "losses": 0, "history": []}


def _save(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── API publique ──────────────────────────────────────────────────────────────

def record_win(profit_usd: float) -> dict:
    """
    Enregistre un gain : 70% → réinvestissement, 30% → réserve.
    Retourne {"reinvested": X, "reserved": Y, "new_capital": Z}.
    """
    if profit_usd <= 0:
        return {"reinvested": 0.0, "reserved": 0.0, "new_capital": get_state()["capital"]}
    with _LOCK:
        data = _load()
        reinvested = round(profit_usd * REINVEST_RATIO, 4)
        reserved   = round(profit_usd * RESERVE_RATIO, 4)
        data["capital"]          = round(data["capital"] + reinvested, 4)
        data["reserve"]          = round(data["reserve"]  + reserved,   4)
        data["total_reinvested"] = round(data["total_reinvested"] + reinvested, 4)
        data["total_reserved"]   = round(data["total_reserved"]   + reserved,   4)
        data["wins"] += 1
        data["history"].append({
            "ts": int(time.time()), "profit": round(profit_usd, 4),
            "reinvested": reinvested, "reserved": reserved,
            "capital": data["capital"],
        })
        data["history"] = data["history"][-100:]  # keep last 100
        _save(data)
        log.info("Compound: win +$%.2f → reinvest $%.2f | reserve $%.2f | capital $%.2f",
                 profit_usd, reinvested, reserved, data["capital"])
        return {"reinvested": reinvested, "reserved": reserved, "new_capital": data["capital"]}


def record_loss(loss_usd: float) -> None:
    """Enregistre une perte (tracking uniquement, ne réduit pas le capital ici)."""
    with _LOCK:
        data = _load()
        data["losses"] += 1
        _save(data)


def get_state() -> dict:
    with _LOCK:
        return _load()


# ── Projection composée ───────────────────────────────────────────────────────

def project_growth(
    capital: float,
    win_rate: float,          # 0-100
    avg_return_pct: float,    # % gain moyen par trade gagnant
    trades_per_week: float = 5.0,
    target_usd: float = 10_000.0,
    max_weeks: int = 52,
) -> dict:
    """
    Projette la croissance composée.
    Retourne {"weeks_to_100": N, "weeks_to_1000": N, "weeks_to_10000": N,
              "week_by_week": [{week, capital}]}.
    """
    wr = win_rate / 100.0
    avg_ret = avg_return_pct / 100.0
    cap = capital
    milestones: dict[float, Optional[int]] = {100: None, 1_000: None, 10_000: None}
    week_by_week: list[dict] = []

    for w in range(1, max_weeks + 1):
        for _ in range(int(trades_per_week)):
            if wr > 0:
                # Expected value per trade
                ev = wr * (cap * avg_ret * REINVEST_RATIO) - (1 - wr) * (cap * 0.025)
                cap = max(0.01, cap + ev)
        week_by_week.append({"week": w, "capital": round(cap, 2)})
        for milestone in list(milestones.keys()):
            if milestones[milestone] is None and cap >= milestone:
                milestones[milestone] = w

    return {
        "weeks_to_100":   milestones.get(100),
        "weeks_to_1000":  milestones.get(1_000),
        "weeks_to_10000": milestones.get(10_000),
        "final_capital":  round(cap, 2),
        "week_by_week":   week_by_week[:12],  # first 12 weeks
    }


def get_compound_section(win_rate: float = 60.0, avg_return: float = 15.0) -> str:
    """Texte HTML pour la section COMPOUND TRACKER dans /portfolio."""
    state   = get_state()
    capital = state["capital"]
    reserve = state["reserve"]
    proj    = project_growth(capital, win_rate, avg_return)

    w100   = proj["weeks_to_100"]
    w1k    = proj["weeks_to_1000"]
    w10k   = proj["weeks_to_10000"]

    def _wk(n: Optional[int]) -> str:
        return f"~{n} sem." if n else "N/A"

    L = "━━━━━━━━━━━━━━━"
    return (
        f"\n{L}\n<b>📈 COMPOUND TRACKER</b>\n"
        f"<code>"
        f"💰 Capital    ${capital:.2f}  (réserve ${reserve:.2f})\n"
        f"📊 Au taux {win_rate:.0f}% WR + {avg_return:.0f}% retour moyen :\n"
        f"   → $100    {_wk(w100)}\n"
        f"   → $1 000  {_wk(w1k)}\n"
        f"   → $10 000 {_wk(w10k)}\n"
        f"🔄 Réinvesti  ${state['total_reinvested']:.2f} total\n"
        f"🏦 Réservé    ${state['total_reserved']:.2f} total"
        f"</code>"
    )
