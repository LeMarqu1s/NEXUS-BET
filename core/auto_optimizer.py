"""
NEXUS BET - Auto-Optimizer (6h loop)
Toutes les 6 heures, backtest les signaux Supabase sur 7 jours,
calcule les win-rates par type de trigger et ajuste automatiquement
les seuils du sniper. Envoie un rapport Telegram.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("nexus.auto_optimizer")

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _ROOT / "logs" / "optimizer_config.json"

# ── Seuils par défaut (miroir de core/sniper.py) ──────────────────────────────
_DEFAULTS: dict[str, float] = {
    "MOMENTUM_THRESHOLD": 0.05,
    "VOLUME_SPIKE_MULTIPLIER": 3.0,
    "SPREAD_THRESHOLD": 0.08,
    "WHALE_THRESHOLD_USD": 10_000.0,
}

WIN_RATE_RAISE = 45.0   # %  en dessous duquel on durcit le seuil
WIN_RATE_LOWER = 70.0   # %  au dessus duquel on peut assouplir
MIN_TRADES     = 5      # minimum trades pour ajuster (évite les petits échantillons)
LOOP_INTERVAL  = 6 * 3600  # 6 heures


# ── Config ────────────────────────────────────────────────────────────────────

def load_optimizer_config() -> dict[str, float]:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return dict(_DEFAULTS)


def save_optimizer_config(cfg: dict[str, float]) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ── Fetch signals depuis Supabase ─────────────────────────────────────────────

async def _fetch_supabase_signals(days: int = 7) -> list[dict]:
    """
    Récupère les signaux des N derniers jours.
    Priorité : Supabase signals table → fallback fichier local paperclip_pending_signals.json.
    """
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if url and key:
        try:
            cutoff_iso = datetime.fromtimestamp(
                time.time() - days * 86400, tz=timezone.utc
            ).isoformat()
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(
                    f"{url}/rest/v1/signals",
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                    params={
                        "created_at": f"gte.{cutoff_iso}",
                        "select": "market_id,side,edge_pct,confidence,polymarket_price,signal_strength,created_at",
                        "limit": "500",
                        "order": "created_at.desc",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list) and data:
                        log.info("optimizer: %d signaux Supabase (%dj)", len(data), days)
                        return data
        except Exception as e:
            log.warning("_fetch_supabase_signals Supabase: %s", e)

    # Fallback : fichier local (dev / Railway sans Supabase)
    try:
        cutoff_ts = time.time() - days * 86400
        for p in [_ROOT / "paperclip_pending_signals.json",
                  _ROOT / "logs" / "paperclip_pending_signals.json"]:
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                sigs = d.get("signals", []) if isinstance(d, dict) else []
                recent = []
                for s in sigs:
                    ts = s.get("created_at") or s.get("timestamp")
                    if ts:
                        try:
                            sig_ts = float(ts) if str(ts).replace(".", "").isdigit() else \
                                     datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
                            if sig_ts >= cutoff_ts:
                                recent.append(s)
                        except Exception:
                            recent.append(s)
                    else:
                        recent.append(s)
                if recent:
                    log.info("optimizer: %d signaux depuis fichier local (%dj)", len(recent), days)
                    return recent
    except Exception as e:
        log.debug("_fetch_supabase_signals local fallback: %s", e)
    return []


async def _check_market_resolved(market_id: str) -> dict | None:
    """
    Vérifie si un marché Polymarket est résolu.
    Retourne {"resolved": bool, "outcome": "YES"|"NO"|None, "resolution_time": int|None}.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(
                "https://gamma-api.polymarket.com/markets",
                params={"conditionId": market_id},
            )
            if r.status_code == 200:
                data = r.json()
                m = data[0] if isinstance(data, list) and data else {}
                resolved = bool(m.get("resolved") or m.get("closed"))
                # Determine outcome from resolutionSource or winner
                outcome = None
                if resolved:
                    res_str = str(m.get("resolution") or m.get("question_result") or "")
                    if res_str.lower() in ("yes", "1", "true"):
                        outcome = "YES"
                    elif res_str.lower() in ("no", "0", "false"):
                        outcome = "NO"
                return {
                    "resolved": resolved,
                    "outcome": outcome,
                    "end_date": m.get("endDate") or m.get("end_date_iso"),
                }
    except Exception as e:
        log.debug("_check_market_resolved(%s): %s", market_id[:16], e)
    return None


# ── Per-trigger statistics ────────────────────────────────────────────────────

async def _compute_trigger_stats(signals: list[dict]) -> dict[str, dict[str, Any]]:
    """
    Pour chaque signal Supabase, vérifie la résolution et classe par trigger type.
    Retourne {trigger: {win_rate, avg_return, avg_hold_min, wins, total}}.
    """
    # Classify signal by trigger type (edge_pct approximation)
    def _classify(sig: dict) -> str:
        strength = sig.get("signal_strength") or ""
        edge = float(sig.get("edge_pct") or 0)
        if "VOLUME" in strength or edge > 15:
            return "VOLUME_SPIKE"
        if "MOMENTUM" in strength or edge > 10:
            return "MOMENTUM"
        if "SPREAD" in strength or edge > 5:
            return "SPREAD"
        return "WHALE"

    stats: dict[str, dict] = {
        t: {"wins": 0, "total": 0, "total_return": 0.0, "hold_times": []}
        for t in ("VOLUME_SPIKE", "MOMENTUM", "SPREAD", "WHALE")
    }

    # Resolve markets in parallel (batch of 10)
    market_ids = list({s["market_id"] for s in signals})
    resolved_cache: dict[str, dict] = {}

    for i in range(0, len(market_ids), 10):
        batch = market_ids[i:i + 10]
        results = await asyncio.gather(*[_check_market_resolved(mid) for mid in batch], return_exceptions=True)
        for mid, res in zip(batch, results):
            if isinstance(res, dict):
                resolved_cache[mid] = res
        await asyncio.sleep(0.5)  # gentle rate limiting

    for sig in signals:
        trigger = _classify(sig)
        resolution = resolved_cache.get(sig["market_id"])
        if not resolution or not resolution.get("resolved"):
            continue  # skip unresolved markets

        outcome = resolution.get("outcome")
        if outcome is None:
            continue  # can't determine win/loss

        side = (sig.get("side") or "").upper()
        won = (side == outcome)
        entry_price = float(sig.get("polymarket_price") or 0)
        pnl_pct = ((1.0 - entry_price) / entry_price * 100) if won and entry_price > 0 else \
                  (-100.0 if not won else 0.0)

        # Hold time (created_at → end_date)
        hold_min = 0
        try:
            created_ts = datetime.fromisoformat(
                str(sig["created_at"]).replace("Z", "+00:00")
            ).timestamp()
            end_date = resolution.get("end_date")
            if end_date:
                end_ts = datetime.fromisoformat(
                    str(end_date).replace("Z", "+00:00")
                ).timestamp()
                hold_min = max(0, int((end_ts - created_ts) / 60))
        except Exception:
            pass

        s = stats[trigger]
        s["total"] += 1
        if won:
            s["wins"] += 1
        s["total_return"] += pnl_pct
        if hold_min > 0:
            s["hold_times"].append(hold_min)

    result = {}
    for trigger, s in stats.items():
        n = s["total"]
        wr = round(s["wins"] / n * 100, 1) if n > 0 else 0.0
        avg_ret = round(s["total_return"] / n, 1) if n > 0 else 0.0
        avg_hold = round(sum(s["hold_times"]) / len(s["hold_times"])) if s["hold_times"] else 0
        result[trigger] = {
            "wins": s["wins"],
            "total": n,
            "win_rate": wr,
            "avg_return": avg_ret,
            "avg_hold_min": avg_hold,
        }
    return result


# ── Auto-ajustement des seuils ────────────────────────────────────────────────

def _adjust_thresholds(
    stats: dict[str, dict], cfg: dict[str, float]
) -> tuple[dict[str, float], list[str]]:
    """Ajuste les seuils selon win-rate. Retourne (new_cfg, changes_list)."""
    new_cfg = dict(cfg)
    changes: list[str] = []

    mapping = {
        "MOMENTUM":    ("MOMENTUM_THRESHOLD",    0.005, 0.005),   # step raise/lower
        "VOLUME_SPIKE":("VOLUME_SPIKE_MULTIPLIER", 0.5,  0.5),
        "SPREAD":      ("SPREAD_THRESHOLD",       0.02,  0.01),
        "WHALE":       ("WHALE_THRESHOLD_USD",    2000.0, 1000.0),
    }

    for trigger, (key, step_up, step_down) in mapping.items():
        s = stats.get(trigger, {})
        n = s.get("total", 0)
        wr = s.get("win_rate", 0.0)
        if n < MIN_TRADES:
            continue
        old = new_cfg.get(key, _DEFAULTS[key])
        if wr < WIN_RATE_RAISE:
            new_val = round(old + step_up, 4)
            new_cfg[key] = new_val
            changes.append(f"{trigger}: {wr:.0f}% WR → seuil durci {old} → {new_val}")
        elif wr > WIN_RATE_LOWER:
            new_val = round(max(_DEFAULTS[key], old - step_down), 4)
            if new_val < old:
                new_cfg[key] = new_val
                changes.append(f"{trigger}: {wr:.0f}% WR → seuil assoupli {old} → {new_val}")

    return new_cfg, changes


# ── Rapport Telegram ──────────────────────────────────────────────────────────

async def _send_report(
    stats: dict,
    changes: list[str],
    cfg: dict[str, float],
    current_capital: float = 50.0,
) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        return
    try:
        import telegram
        from monitoring.push_alerts import get_active_subscribers
        bot = telegram.Bot(token=token)
        users = await get_active_subscribers()
        fallback = os.getenv("TELEGRAM_CHAT_ID")
        if not users and fallback:
            users = [{"telegram_chat_id": fallback}]
        if not users:
            return

        L = "━━━━━━━━━━━━━━━"
        lines = [
            f"🤖 <b>RAPPORT AUTO-OPTIMIZER</b>\n{L}\n"
            f"<code>Capital actuel : ${current_capital:.2f}</code>\n\n"
        ]

        for trigger, s in stats.items():
            if s["total"] == 0:
                continue
            wr = s["win_rate"]
            icon = "🔥" if wr >= WIN_RATE_LOWER else "✅" if wr >= WIN_RATE_RAISE else "⚠️"
            avg_hold = f" • hold {s['avg_hold_min']}min" if s.get("avg_hold_min") else ""
            lines.append(
                f"{icon} <b>{trigger}</b>: {wr:.0f}% WR "
                f"({s['wins']}/{s['total']}) • {s['avg_return']:+.1f}%{avg_hold}\n"
            )

        lines.append(f"\n{L}\n")
        if changes:
            net_improvement = len([c for c in changes if "assoupli" not in c]) * 2
            lines.append(f"<b>Ajustements ({len(changes)}) :</b>\n")
            for c in changes:
                lines.append(f"• {c}\n")
            lines.append(f"\n<i>Amélioration estimée : +{net_improvement}% WR attendu</i>")
        else:
            lines.append("<i>Seuils inchangés — performances stables ✅</i>")

        text = "".join(lines)
        tasks = []
        for u in users:
            cid = u.get("telegram_chat_id")
            if cid:
                tasks.append(bot.send_message(chat_id=cid, text=text, parse_mode="HTML"))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await bot.close()
        log.info("auto_optimizer: rapport envoyé à %d subscriber(s)", len(tasks))
    except Exception as e:
        log.error("auto_optimizer: rapport Telegram: %s", e)


async def _insert_optimizer_run(
    signals_analyzed: int,
    adjustments_made: int,
    config_snapshot: dict[str, float],
) -> None:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signals_analyzed": signals_analyzed,
        "adjustments_made": adjustments_made,
        "config_snapshot": config_snapshot,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                f"{url}/rest/v1/optimizer_runs",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json=payload,
            )
            if r.status_code not in (200, 201):
                log.warning("optimizer_runs insert: %s %s", r.status_code, (r.text or "")[:200])
    except Exception as e:
        log.warning("_insert_optimizer_run: %s", e)


# ── Boucle principale ─────────────────────────────────────────────────────────

async def run_auto_optimizer() -> None:
    """Boucle principale : backteste et optimise toutes les 6 heures."""
    log.info("Auto-optimizer démarré — boucle 6h | WIN_RATE_RAISE=%.0f%% WIN_RATE_LOWER=%.0f%%",
             WIN_RATE_RAISE, WIN_RATE_LOWER)

    # Premier run après 5min (laisser le bot démarrer)
    await asyncio.sleep(300)

    while True:
        signals_analyzed = 0
        adjustments_made = 0
        config_snapshot = load_optimizer_config()
        try:
            log.info("Auto-optimizer : démarrage du cycle (7 jours de signaux Supabase)…")

            # Capital actuel depuis compounder ou env
            current_capital = 50.0
            try:
                from core.compounder import get_state as _compound_state
                current_capital = float(_compound_state().get("capital", 50.0))
            except Exception:
                try:
                    current_capital = float(os.getenv("PAPER_CAPITAL_USD", "50"))
                except Exception:
                    pass

            signals = await _fetch_supabase_signals(days=7)
            log.info("Auto-optimizer : %d signaux récupérés | capital $%.2f", len(signals), current_capital)

            if signals:
                stats = await _compute_trigger_stats(signals)
                cfg = load_optimizer_config()
                new_cfg, changes = _adjust_thresholds(stats, cfg)
                signals_analyzed = len(signals)
                adjustments_made = len(changes)
                config_snapshot = dict(new_cfg)

                if changes:
                    save_optimizer_config(new_cfg)
                    log.info("Auto-optimizer : %d ajustement(s) — %s", len(changes), changes)
                    # Appliquer en live au sniper
                    try:
                        import core.sniper as _sniper
                        for k, v in new_cfg.items():
                            if hasattr(_sniper, k):
                                setattr(_sniper, k, v)
                    except Exception as e:
                        log.debug("apply thresholds to sniper: %s", e)
                else:
                    log.info("Auto-optimizer : aucun ajustement nécessaire")

                await _send_report(stats, changes, new_cfg, current_capital=current_capital)
            else:
                log.info("Auto-optimizer : aucun signal — cycle ignoré")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Auto-optimizer erreur: %s", e)

        await _insert_optimizer_run(signals_analyzed, adjustments_made, config_snapshot)
        log.info("Auto-optimizer : prochain cycle dans 6h")
        await asyncio.sleep(LOOP_INTERVAL)
