"use client";

import { ModuleCard } from "@/components/module-card";

export default function AntennaPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-mono text-2xl font-bold text-nexus-cyan">
          Antenna Dashboard
        </h1>
        <p className="text-nexus-muted text-sm mt-1">
          Unusual Whales (Options/Équités) + Polymarket feeds
        </p>
      </div>

      <ModuleCard title="ANTENNE">
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="border border-nexus-border rounded p-4 font-mono text-sm">
              <div className="text-nexus-green mb-2">Unusual Whales</div>
              <div className="text-nexus-muted text-xs">
                Anomalies options & équités. API à intégrer.
              </div>
            </div>
            <div className="border border-nexus-border rounded p-4 font-mono text-sm">
              <div className="text-nexus-cyan mb-2">Polymarket</div>
              <div className="text-nexus-muted text-xs">
                Flux Gamma + CLOB en temps réel.
              </div>
            </div>
          </div>
        </div>
      </ModuleCard>
    </div>
  );
}
