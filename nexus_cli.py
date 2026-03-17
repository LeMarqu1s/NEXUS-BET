"""
NEXUS BET - CLI Bridge pour Paperclip
Expose le scanner, le moteur Edge, Polymarket et les agents aux agents Paperclip.
Usage: python -m nexus_cli <command> [args]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ajouter le projet au path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Imports légers pour debate/propose/challenge/validate (sans Polymarket)
from agents import AdversarialAITeam

try:
    from paperclip_bridge import get_pending_signals, clear_signal
except ImportError:
    def get_pending_signals():
        return []

    def clear_signal(*_):
        pass


def _get_polymarket():
    from data.polymarket_client import PolymarketClient
    return PolymarketClient()


def _get_edge_engine():
    from core.edge_engine import EdgeEngine
    return EdgeEngine()


def _get_order_manager():
    from execution.order_manager import OrderManager, OrderConfig
    return OrderManager, OrderConfig


def _run(coro):
    """Exécute une coroutine."""
    return asyncio.run(coro)


# --- Commandes ---

async def cmd_scan(limit: int = 20) -> str:
    """Exécute un scan des marchés et retourne les signaux en JSON."""
    polymarket = _get_polymarket()
    edge_engine = _get_edge_engine()
    signals: list[dict] = []
    try:
        markets = await polymarket.get_markets(limit=limit)
        for market in markets:
            try:
                tokens = market.get("clobTokenIds") or market.get("tokens") or []
                if not isinstance(tokens, list) or len(tokens) < 2:
                    continue
                yes_token = tokens[0] if isinstance(tokens[0], dict) else {"token_id": tokens[0]}
                no_token = tokens[1] if isinstance(tokens[1], dict) else {"token_id": tokens[1]}
                yes_id = yes_token.get("token_id") if isinstance(yes_token, dict) else str(yes_token)
                no_id = no_token.get("token_id") if isinstance(no_token, dict) else str(no_token)
                if not yes_id or not no_id:
                    continue

                ob_yes = await polymarket.get_order_book(yes_id)
                ob_no = await polymarket.get_order_book(no_id)
                price_yes = await polymarket.get_midpoint(yes_id) or await polymarket.get_price(yes_id)
                price_no = await polymarket.get_midpoint(no_id) or await polymarket.get_price(no_id)

                for token_id, side, price, ob in [
                    (yes_id, "YES", price_yes, ob_yes),
                    (no_id, "NO", price_no, ob_no),
                ]:
                    if price is not None:
                        sig = edge_engine.compute_edge(market, token_id, side, price, ob)
                        if sig:
                            signals.append({
                                "market_id": sig.market_id,
                                "token_id": sig.token_id,
                                "side": sig.side,
                                "polymarket_price": sig.polymarket_price,
                                "edge_pct": sig.edge_pct * 100,
                                "kelly_fraction": sig.kelly_fraction,
                                "model": sig.model.value,
                                "confidence": sig.confidence,
                            })
            except Exception:
                pass
    finally:
        await polymarket.close()
    return json.dumps({"signals": signals, "count": len(signals)}, indent=2)


async def cmd_propose(market_id: str, outcome: str, edge_bps: float, kelly: float, rationale: str) -> str:
    """Head Quant propose une thèse de trade."""
    team = AdversarialAITeam()
    thesis = await team.quant_propose_trade(market_id, outcome, edge_bps, kelly, rationale)
    return json.dumps({"thesis": thesis, "market_id": market_id, "outcome": outcome})


async def cmd_challenge(thesis: str, market_context: str = "") -> str:
    """Risk Manager challenge la thèse."""
    team = AdversarialAITeam()
    concerns = await team.risk_manager_challenge(thesis, market_context)
    return json.dumps({"risk_concerns": concerns, "thesis": thesis})


async def cmd_validate(thesis: str, risk_concerns: str) -> str:
    """Head Analyst valide ou rejette."""
    team = AdversarialAITeam()
    approved, verdict = await team.head_analyst_validate(thesis, risk_concerns)
    return json.dumps({"approved": approved, "verdict": verdict})


async def cmd_full_debate(
    market_id: str, outcome: str, edge_bps: float, kelly: float, rationale: str, market_context: str = ""
) -> str:
    """Pipeline complet: Quant → Risk → Analyst."""
    team = AdversarialAITeam()
    result = await team.full_debate(market_id, outcome, edge_bps, kelly, rationale, market_context)
    return json.dumps({
        "market_id": result.market_id,
        "outcome": result.outcome,
        "approved": result.approved,
        "thesis": result.rationale,
        "risk_concerns": result.risk_concerns,
        "final_verdict": result.final_verdict,
    }, indent=2)


async def cmd_execute(
    market_id: str, outcome: str, edge_pct: float, kelly: float, size_usd: float
) -> str:
    """Exécute un ordre si approuvé (Head Analyst)."""
    polymarket = _get_polymarket()
    try:
        token_id = await polymarket.get_token_id_from_market(market_id, outcome)
        if not token_id:
            return json.dumps({"error": "Token not found", "market_id": market_id, "outcome": outcome})

        price = await polymarket.get_midpoint(token_id) or await polymarket.get_price(token_id)
        if price is None or price <= 0:
            return json.dumps({"error": "Price not available", "market_id": market_id})

        OrderManager, OrderConfig = _get_order_manager()
        order_mgr = OrderManager()
        cfg = OrderConfig(
            market_id=market_id,
            outcome=outcome,
            side="BUY",
            size_usd=size_usd,
            limit_price=price,
        )
        order_id = await order_mgr.place_limit_order(cfg)
        if order_id:
            return json.dumps({
                "status": "placed",
                "order_id": order_id,
                "market_id": market_id,
                "outcome": outcome,
                "price": price,
                "size_usd": size_usd,
            })
        return json.dumps({"error": "Order placement failed", "market_id": market_id})
    finally:
        await polymarket.close()


async def cmd_pending() -> str:
    """Liste les signaux en attente (du scanner, pour Paperclip)."""
    signals = get_pending_signals()
    return json.dumps({"signals": signals, "count": len(signals)}, indent=2)


async def cmd_risk_check(edge_pct: float, kelly: float) -> str:
    """Vérifie si le risque de ruine est acceptable (Risk Manager)."""
    # Ruine: si kelly > 0.5 ou edge très faible avec kelly élevé
    ruin_risk = kelly > 0.5 or (edge_pct < 2.0 and kelly > 0.25)
    return json.dumps({
        "ruin_risk": ruin_risk,
        "edge_pct": edge_pct,
        "kelly": kelly,
        "recommendation": "REJECT" if ruin_risk else "PROCEED",
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="NEXUS BET CLI - Bridge Paperclip")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = subparsers.add_parser("scan", help="Scanner les marchés")
    p_scan.add_argument("--limit", type=int, default=20)

    # propose
    p_propose = subparsers.add_parser("propose", help="Head Quant propose une thèse")
    p_propose.add_argument("--market", required=True)
    p_propose.add_argument("--outcome", required=True, choices=["YES", "NO"])
    p_propose.add_argument("--edge", type=float, required=True, help="Edge en bps")
    p_propose.add_argument("--kelly", type=float, required=True)
    p_propose.add_argument("--rationale", default="", help="Rationale du trade")

    # challenge
    p_challenge = subparsers.add_parser("challenge", help="Risk Manager challenge la thèse")
    p_challenge.add_argument("--thesis", required=True)
    p_challenge.add_argument("--context", default="")

    # validate
    p_validate = subparsers.add_parser("validate", help="Head Analyst valide")
    p_validate.add_argument("--thesis", required=True)
    p_validate.add_argument("--risks", required=True)

    # full_debate
    p_debate = subparsers.add_parser("debate", help="Pipeline complet Quant→Risk→Analyst")
    p_debate.add_argument("--market", required=True)
    p_debate.add_argument("--outcome", required=True, choices=["YES", "NO"])
    p_debate.add_argument("--edge", type=float, required=True)
    p_debate.add_argument("--kelly", type=float, required=True)
    p_debate.add_argument("--rationale", default="")
    p_debate.add_argument("--context", default="")

    # execute
    p_execute = subparsers.add_parser("execute", help="Exécuter un ordre (si approuvé)")
    p_execute.add_argument("--market", required=True)
    p_execute.add_argument("--outcome", required=True, choices=["YES", "NO"])
    p_execute.add_argument("--edge", type=float, default=0)
    p_execute.add_argument("--kelly", type=float, default=0.25)
    p_execute.add_argument("--size", type=float, default=100.0)

    # risk_check
    p_risk = subparsers.add_parser("risk_check", help="Vérifier risque de ruine")
    p_risk.add_argument("--edge", type=float, required=True)
    p_risk.add_argument("--kelly", type=float, required=True)

    # pending
    subparsers.add_parser("pending", help="Signaux en attente (scanner → Paperclip)")

    args = parser.parse_args()

    try:
        if args.command == "scan":
            out = _run(cmd_scan(limit=getattr(args, "limit", 20)))
        elif args.command == "propose":
            out = _run(cmd_propose(args.market, args.outcome, args.edge, args.kelly, args.rationale))
        elif args.command == "challenge":
            out = _run(cmd_challenge(args.thesis, args.context))
        elif args.command == "validate":
            out = _run(cmd_validate(args.thesis, args.risks))
        elif args.command == "debate":
            out = _run(cmd_full_debate(
                args.market, args.outcome, args.edge, args.kelly, args.rationale, args.context
            ))
        elif args.command == "execute":
            out = _run(cmd_execute(args.market, args.outcome, args.edge, args.kelly, args.size))
        elif args.command == "risk_check":
            out = _run(cmd_risk_check(args.edge, args.kelly))
        elif args.command == "pending":
            out = _run(cmd_pending())
        else:
            parser.print_help()
            sys.exit(1)
        print(out)
    except Exception as e:
        print(json.dumps({"error": str(e) or type(e).__name__}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
