"use client";

import { useEffect, useState } from "react";
import { ModuleCard } from "@/components/module-card";
import { fetchApi } from "@/lib/api";

interface Debate {
  agent?: string;
  message?: string;
  content?: string;
}

export default function DebatesPage() {
  const [debates, setDebates] = useState<Debate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setError(null);
      const data = await fetchApi<{ debates: Debate[] }>("debates");
      setDebates(data.debates || []);
    } catch (e) {
      setError("Aucun fichier ai_debates_log.json trouvé.");
      setDebates([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    window.addEventListener("nexus-refresh", load);
    return () => window.removeEventListener("nexus-refresh", load);
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">
          AI Debates
        </h1>
        <p className="text-zinc-500 text-sm mt-1">
          Flux Quant → Risk Manager → Head Analyst → Nightly Auditor
        </p>
      </div>

      <ModuleCard title="AI DEBATES" subtitle={`${debates.length} débats`}>
        {loading ? (
          <div className="text-zinc-500 font-mono text-sm py-8 text-center">
            Chargement...
          </div>
        ) : error ? (
          <div className="text-red-400 text-sm py-8 text-center">
            {error}
          </div>
        ) : debates.length === 0 ? (
          <div className="text-zinc-500 font-mono text-sm py-8 text-center">
            Aucun débat en attente. Les agents Paperclip alimenteront ce flux.
          </div>
        ) : (
          <div className="space-y-6 max-h-[400px] overflow-y-auto">
            {[...debates].reverse().slice(0, 15).map((d, i) => (
              <div
                key={i}
                className="border border-zinc-800 rounded-xl p-3 text-sm"
              >
                <div className="text-amber-400 font-medium mb-1">
                  {d.agent || "Agent"}
                </div>
                <div className="text-zinc-300">
                  {(d.message || d.content || "").slice(0, 300)}
                </div>
              </div>
            ))}
          </div>
        )}
      </ModuleCard>
    </div>
  );
}
