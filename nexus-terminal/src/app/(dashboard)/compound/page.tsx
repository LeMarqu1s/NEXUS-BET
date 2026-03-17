"use client";

import { ModuleCard } from "@/components/module-card";

export default function CompoundPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-mono text-2xl font-bold text-nexus-cyan">
          Auto-Compound Manager
        </h1>
        <p className="text-nexus-muted text-sm mt-1">
          Jauge de réinvestissement automatique des profits
        </p>
      </div>

      <ModuleCard title="RÉINVESTISSEMENT">
        <div className="space-y-6">
          <div>
            <div className="flex justify-between text-sm font-mono mb-2">
              <span className="text-nexus-muted">Auto-compound</span>
              <span className="text-nexus-green">75%</span>
            </div>
            <div className="h-2 bg-nexus-border rounded-full overflow-hidden">
              <div
                className="h-full bg-nexus-green rounded-full transition-all"
                style={{ width: "75%" }}
              />
            </div>
          </div>
          <p className="text-nexus-muted text-sm font-mono">
          Slider à venir : 0% → 100% des profits réinvestis automatiquement.
          </p>
        </div>
      </ModuleCard>
    </div>
  );
}
