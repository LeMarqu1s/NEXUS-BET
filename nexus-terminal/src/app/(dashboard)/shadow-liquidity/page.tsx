"use client";

import { ModuleCard } from "@/components/module-card";

export default function ShadowLiquidityPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-mono text-2xl font-bold text-nexus-cyan">
          Shadow Liquidity Sniper
        </h1>
        <p className="text-nexus-muted text-sm mt-1">
          Croise les flux Unusual Whales ↔ Polymarket
        </p>
      </div>

      <ModuleCard title="FLUX CROISÉS">
        <div className="space-y-6">
          <div className="text-nexus-muted font-mono text-sm">
            Corrélation : anomalies options/équités Unusual Whales → marchés Polymarket.
            Détection des opportunités avant le marché.
          </div>
          <div className="border border-nexus-border rounded p-4 font-mono text-xs text-nexus-muted">
            Intégration Unusual Whales + Polymarket API
          </div>
        </div>
      </ModuleCard>
    </div>
  );
}
