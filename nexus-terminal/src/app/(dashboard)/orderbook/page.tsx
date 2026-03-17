"use client";

import { ModuleCard } from "@/components/module-card";

export default function OrderbookPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-mono text-2xl font-bold text-nexus-cyan">
          Order Book Anomaly Radar
        </h1>
        <p className="text-nexus-muted text-sm mt-1">
          Détection anti-manipulation (Anti-Rug) des carnets d&apos;ordres Polymarket
        </p>
      </div>

      <ModuleCard title="ANOMALY DETECTION">
        <div className="space-y-6">
          <div className="text-nexus-muted font-mono text-sm">
            Surveillance des flux bid/ask suspects, wash trading, spoofing.
            Alertes en temps réel avant exécution.
          </div>
          <div className="border border-nexus-border rounded p-4 font-mono text-xs text-nexus-muted">
            Module à venir : CLOB book + heuristiques anti-manipulation
          </div>
        </div>
      </ModuleCard>
    </div>
  );
}
