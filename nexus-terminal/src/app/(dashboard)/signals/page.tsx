"use client";

import { useEffect, useState } from "react";
import { ModuleCard } from "@/components/module-card";
import { fetchApi } from "@/lib/api";

interface Signal {
  market_id?: string;
  question?: string;
  side?: string;
  edge_pct?: number;
  kelly_fraction?: number;
  confidence?: number;
  polymarket_price?: number;
  model?: string;
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setError(null);
      const data = await fetchApi<{ signals: Signal[] }>("scan");
      setSignals(data.signals || []);
    } catch (e) {
      setError("Aucun fichier paperclip_pending_signals.json trouvé.");
      setSignals([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const handler = () => load();
    window.addEventListener("nexus-refresh", handler);
    return () => window.removeEventListener("nexus-refresh", handler);
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">
          Edge Signals
        </h1>
        <p className="text-zinc-500 text-sm mt-1">
          Signaux Paperclip (priorité) + fallback Gamma/CLOB
        </p>
      </div>

      <ModuleCard title="SIGNALS" subtitle={`${signals.length} signaux`}>
        {loading ? (
          <div className="text-zinc-500 font-mono text-sm py-8 text-center">
            Chargement...
          </div>
        ) : error ? (
          <div className="text-red-400 text-sm py-8 text-center">
            {error}
          </div>
        ) : signals.length === 0 ? (
          <div className="text-zinc-500 font-mono text-sm py-8 text-center">
            Aucun signal (edge &lt; 2%). Les signaux Paperclip apparaîtront ici.
          </div>
        ) : (
          <div className="space-y-6 max-h-[400px] overflow-y-auto">
            {signals.map((s, i) => (
              <div
                key={`${s.market_id}-${s.side}-${i}`}
                className="border border-zinc-800 rounded-xl p-4 hover:border-zinc-700 transition text-sm"
              >
                <div className="text-gray-200 font-medium mb-2">
                  {s.question || s.market_id?.slice(0, 50) || "—"}
                </div>
                <div className="flex flex-wrap gap-4 text-xs">
                  <span className="text-emerald-400">
                    Edge: {(s.edge_pct || 0).toFixed(2)}%
                  </span>
                  <span className="text-blue-400">
                    Kelly: {((s.kelly_fraction || 0) * 100).toFixed(2)}%
                  </span>
                  <span>{s.side}</span>
                  <span>Confiance: {((s.confidence || 0) * 100).toFixed(0)}%</span>
                  <span>Prix: {((s.polymarket_price || 0) * 100).toFixed(1)}%</span>
                  <span className="text-zinc-500">{s.model || ""}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </ModuleCard>
    </div>
  );
}
