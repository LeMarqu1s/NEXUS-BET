"use client";

import { ModuleCard } from "@/components/module-card";

export default function ExecutionPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-mono text-2xl font-bold text-nexus-cyan">
          Execution Log
        </h1>
        <p className="text-nexus-muted text-sm mt-1">
          Historique ordres • Trades • Smart Contracts
        </p>
      </div>

      <ModuleCard title="HISTORIQUE">
        <div className="text-nexus-muted font-mono text-sm py-8 text-center">
          Intégration ordres Polymarket + execution/order_manager.py
        </div>
      </ModuleCard>
    </div>
  );
}
