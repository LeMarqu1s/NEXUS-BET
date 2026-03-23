"use client";

import { useEffect, useState } from "react";
import { ModuleCard } from "@/components/module-card";

interface Signal {
  id?: string;
  market_id?: string;
  question?: string;
  side?: string;
  edge_pct?: number;
  kelly_fraction?: number;
  confidence?: number;
  polymarket_price?: number;
  fair_price?: number;
  signal_strength?: string;
  market_type?: string;
  created_at?: string;
}

function StrengthBadge({ strength }: { strength?: string }) {
  const isStrong = strength === "STRONG_BUY";
  return (
    <span
      className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
        isStrong
          ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
          : "bg-blue-500/10 text-blue-400 border border-blue-500/20"
      }`}
    >
      {isStrong ? "⚡ STRONG BUY" : "📈 BUY"}
    </span>
  );
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setError(null);
      const res = await fetch("/api/signals?limit=50");
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setSignals(data.signals || []);
    } catch {
      setError("Impossible de charger les signaux.");
      setSignals([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const handler = () => load();
    window.addEventListener("nexus-refresh", handler);
    // Auto-refresh every 30s
    const interval = setInterval(load, 30000);
    return () => {
      window.removeEventListener("nexus-refresh", handler);
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">Edge Signals</h1>
        <p className="text-zinc-500 text-sm mt-1">
          Signaux IA temps réel · Claude AI + Polymarket CLOB
        </p>
      </div>

      <ModuleCard
        title="SIGNALS LIVE"
        subtitle={loading ? "..." : `${signals.length} signaux`}
      >
        {loading ? (
          <div className="text-zinc-500 font-mono text-sm py-12 text-center">
            Chargement...
          </div>
        ) : error ? (
          <div className="text-red-400 text-sm py-12 text-center">{error}</div>
        ) : signals.length === 0 ? (
          <div className="text-zinc-500 font-mono text-sm py-12 text-center">
            Aucun signal pour l&apos;instant. Le scanner tourne toutes les 30s.
          </div>
        ) : (
          <div className="space-y-3">
            {signals.map((s, i) => (
              <div
                key={s.id || `${s.market_id}-${i}`}
                className="border border-zinc-800 rounded-xl p-4 hover:border-zinc-700 transition"
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <p className="text-zinc-100 font-medium text-sm leading-snug flex-1">
                    {s.question || s.market_id?.slice(0, 60) || "—"}
                  </p>
                  <StrengthBadge strength={s.signal_strength} />
                </div>
                <div className="grid grid-cols-4 gap-2 text-xs">
                  <div className="bg-zinc-900 rounded-lg p-2 text-center">
                    <div className="text-zinc-500 text-[10px] mb-1">EDGE</div>
                    <div className="text-emerald-400 font-bold">
                      {(s.edge_pct || 0).toFixed(1)}%
                    </div>
                  </div>
                  <div className="bg-zinc-900 rounded-lg p-2 text-center">
                    <div className="text-zinc-500 text-[10px] mb-1">KELLY</div>
                    <div className="text-blue-400 font-bold">
                      {((s.kelly_fraction || 0) * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div className="bg-zinc-900 rounded-lg p-2 text-center">
                    <div className="text-zinc-500 text-[10px] mb-1">PRIX</div>
                    <div className="text-zinc-200 font-bold">
                      {((s.polymarket_price || 0) * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div className="bg-zinc-900 rounded-lg p-2 text-center">
                    <div className="text-zinc-500 text-[10px] mb-1">CONF</div>
                    <div
                      className={`font-bold ${
                        (s.confidence || 0) >= 0.8
                          ? "text-emerald-400"
                          : (s.confidence || 0) >= 0.6
                          ? "text-yellow-400"
                          : "text-zinc-400"
                      }`}
                    >
                      {((s.confidence || 0) * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
                <div className="flex items-center justify-between mt-3 text-[10px] text-zinc-600">
                  <span>
                    {s.side} · {s.market_type || "binary"}
                  </span>
                  {s.created_at && (
                    <span>
                      {new Date(s.created_at).toLocaleTimeString("fr-FR")}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </ModuleCard>
    </div>
  );
}
