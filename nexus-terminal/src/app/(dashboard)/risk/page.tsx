"use client";

import { ModuleCard } from "@/components/module-card";

export default function RiskPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-mono text-2xl font-bold text-nexus-cyan">
          Risk Management
        </h1>
        <p className="text-nexus-muted text-sm mt-1">
          Position limits • Kelly • Stop-loss • Exposition
        </p>
      </div>

      <ModuleCard title="PARAMÈTRES DE RISQUE">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-sm">
          <div className="border border-nexus-border rounded p-4">
            <div className="text-nexus-muted text-xs mb-1">Max position</div>
            <div className="text-nexus-green">5%</div>
          </div>
          <div className="border border-nexus-border rounded p-4">
            <div className="text-nexus-muted text-xs mb-1">Exposition max</div>
            <div className="text-nexus-green">25%</div>
          </div>
          <div className="border border-nexus-border rounded p-4">
            <div className="text-nexus-muted text-xs mb-1">Kelly fraction</div>
            <div className="text-nexus-cyan">0.25</div>
          </div>
          <div className="border border-nexus-border rounded p-4">
            <div className="text-nexus-muted text-xs mb-1">Stop loss</div>
            <div className="text-nexus-red">25%</div>
          </div>
        </div>
      </ModuleCard>
    </div>
  );
}
