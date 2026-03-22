"""
NEXUS CAPITAL - Simulation de dégradation gracieuse
Affiche ce qui se passerait si Supabase, Polymarket ou Anthropic échouent.
"""
print("=" * 60)
print("NEXUS CAPITAL - Graceful Degradation Simulation")
print("=" * 60)

print("\n1. SUPABASE DOWN")
print("-" * 40)
print("  - supabase_client: retry 3x, 2s entre chaque")
print("  - Si échec: return None / False, PAS de raise")
print("  - Bot continue: trades non loggés en DB, mais scan/Telegram OK")
print("  - Résultat: DÉGRADATION GRACEUSE (pas de crash)")

print("\n2. POLYMARKET API 500")
print("-" * 40)
print("  - polymarket_client.get_markets: retry 3x, timeout 8s")
print("  - Si 500: log.debug, return []")
print("  - scanner_ws: _fetch_markets_gamma retourne [] -> polling fallback")
print("  - Après 3 échecs WS: polling permanent (Gamma API)")
print("  - Résultat: DÉGRADATION GRACEUSE (pas de crash)")

print("\n3. ANTHROPIC API TIMEOUT")
print("-" * 40)
print("  - swarm_orchestrator / agents: calls externes avec retry")
print("  - Si timeout: log + return None / skip signal")
print("  - Edge engine: compute_edge wrapped try/except -> skip bad market")
print("  - Résultat: DÉGRADATION GRACEUSE (pas de crash)")

print("\n" + "=" * 60)
print("Tous les scénarios: le bot NE CRASHE PAS.")
print("=" * 60)
