"use client";

import { useEffect, useState } from "react";
import { ModuleCard } from "@/components/module-card";

interface Position {
  id?: string;
  market_id?: string;
  market_question?: string;
  side?: string;
  shares?: number;
  avg_entry_price?: number;
  cost_basis_usd?: number;
  unrealized_pnl?: number;
  status?: string;
}

interface Trade {
  id?: string;
  market_question?: string;
  side?: string;
  amount_usd?: number;
  price?: number;
  status?: string;
  pnl_usd?: number;
  created_at?: string;
}

interface Stats {
  totalTrades?: number;
  wins?: number;
  winRate?: string;
  totalPnl?: string;
}

export default function PortfolioPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [stats, setStats] = useState<Stats>({});
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const res = await fetch("/api/portfolio");
      const data = await res.json();
      setPositions(data.positions || []);
      setTrades(data.trades || []);
      setStats(data.stats || {});
    } catch {
      /* ignore */
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
        <h1 className="text-2xl font-bold text-zinc-100">Portfolio</h1>
        <p className="text-zinc-500 text-sm mt-1">
          Positions ouvertes · Historique des trades · PnL
        </p>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "TRADES", value: stats.totalTrades ?? "—" },
          { label: "WINS", value: stats.wins ?? "—" },
          { label: "WIN RATE", value: stats.winRate ? `${stats.winRate}%` : "—" },
          {
            label: "PNL",
            value: stats.totalPnl ? `$${stats.totalPnl}` : "—",
            color:
              parseFloat(stats.totalPnl || "0") > 0
                ? "text-emerald-400"
                : parseFloat(stats.totalPnl || "0") < 0
                ? "text-red-400"
                : "text-zinc-300",
          },
        ].map((s) => (
          <div
            key={s.label}
            className="border border-zinc-800 rounded-xl p-4 bg-zinc-900/30"
          >
            <div className="text-[10px] text-zinc-500 mb-1">{s.label}</div>
            <div className={`text-xl font-bold ${s.color || "text-zinc-100"}`}>
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* Open positions */}
      <ModuleCard
        title="POSITIONS OUVERTES"
        subtitle={`${positions.length} position${positions.length !== 1 ? "s" : ""}`}
      >
        {loading ? (
          <div className="text-zinc-500 font-mono text-sm py-8 text-center">
            Chargement...
          </div>
        ) : positions.length === 0 ? (
          <div className="text-zinc-500 font-mono text-sm py-8 text-center">
            Aucune position ouverte.
          </div>
        ) : (
          <div className="space-y-2">
            {positions.map((p, i) => (
              <div
                key={p.id || i}
                className="flex items-center justify-between border border-zinc-800 rounded-lg p-3 text-sm"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-zinc-100 truncate">
                    {p.market_question || p.market_id?.slice(0, 40) || "—"}
                  </p>
                  <p className="text-zinc-500 text-xs mt-0.5">
                    {p.side} · {p.shares?.toFixed(2)} shares @ $
                    {p.avg_entry_price?.toFixed(3)}
                  </p>
                </div>
                <div className="text-right ml-4">
                  <p className="text-zinc-300 font-mono text-xs">
                    ${p.cost_basis_usd?.toFixed(2)}
                  </p>
                  {p.unrealized_pnl != null && (
                    <p
                      className={`text-xs font-mono ${
                        p.unrealized_pnl > 0
                          ? "text-emerald-400"
                          : "text-red-400"
                      }`}
                    >
                      {p.unrealized_pnl > 0 ? "+" : ""}
                      {p.unrealized_pnl.toFixed(2)}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </ModuleCard>

      {/* Trade history */}
      <ModuleCard title="HISTORIQUE" subtitle={`${trades.length} trades`}>
        {trades.length === 0 ? (
          <div className="text-zinc-500 font-mono text-sm py-8 text-center">
            Aucun trade enregistré.
          </div>
        ) : (
          <div className="space-y-2">
            {trades.map((t, i) => (
              <div
                key={t.id || i}
                className="flex items-center justify-between border border-zinc-800 rounded-lg p-3 text-sm"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-zinc-200 truncate text-xs">
                    {t.market_question || "—"}
                  </p>
                  <p className="text-zinc-500 text-[10px] mt-0.5">
                    {t.side} · ${t.amount_usd?.toFixed(2)} @ {((t.price || 0) * 100).toFixed(1)}% ·{" "}
                    <span
                      className={
                        t.status === "FILLED"
                          ? "text-emerald-400"
                          : t.status === "CANCELLED"
                          ? "text-red-400"
                          : "text-yellow-400"
                      }
                    >
                      {t.status}
                    </span>
                  </p>
                </div>
                <div className="text-right ml-4">
                  {t.pnl_usd != null && t.pnl_usd !== 0 && (
                    <p
                      className={`text-xs font-mono ${
                        t.pnl_usd > 0 ? "text-emerald-400" : "text-red-400"
                      }`}
                    >
                      {t.pnl_usd > 0 ? "+" : ""}${t.pnl_usd.toFixed(2)}
                    </p>
                  )}
                  {t.created_at && (
                    <p className="text-zinc-600 text-[10px]">
                      {new Date(t.created_at).toLocaleDateString("fr-FR")}
                    </p>
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
