"use client";

import { ModuleCard } from "@/components/module-card";
import { Button } from "@/components/ui/button";

export default function WhalePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-mono text-2xl font-bold text-nexus-cyan">
          Smart Whale Tracker
        </h1>
        <p className="text-nexus-muted text-sm mt-1">
          Top Wallets Polymarket • AI Shield Copy (audit Risk Manager)
        </p>
      </div>

      <ModuleCard title="TOP WALLETS">
        <div className="space-y-6">
          <div className="text-nexus-muted font-mono text-sm">
            Liste des portefeuilles les plus rentables du leaderboard Polymarket.
            Chaque trade peut être audité par le Risk Manager Paperclip avant exécution.
          </div>
          <Button variant="outline" disabled>
            AI Shield Copy — À venir
          </Button>
          <div className="border border-nexus-border rounded p-4 font-mono text-xs text-nexus-muted">
            Intégration copy_trader.py + Polymarket Data API
          </div>
        </div>
      </ModuleCard>
    </div>
  );
}
