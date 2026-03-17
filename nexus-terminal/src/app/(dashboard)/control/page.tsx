"use client";

import { useEffect, useState } from "react";
import { ModuleCard } from "@/components/module-card";
import { Button } from "@/components/ui/button";
import { fetchApi, postApi } from "@/lib/api";

interface ControlState {
  autonomous_mode?: boolean;
  copy_trading_mode?: boolean;
  last_updated?: string;
}

export default function ControlPage() {
  const [state, setState] = useState<ControlState>({});
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const data = await fetchApi<ControlState>("control");
      setState(data);
    } catch {
      setState({});
    } finally {
      setLoading(false);
    }
  };

  const toggle = async (mode: "autonomous" | "copy_trading") => {
    try {
      const data = await postApi<ControlState>("control/toggle", { mode });
      setState(data);
    } catch {}
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
          Control Panel
        </h1>
        <p className="text-zinc-500 text-sm mt-1">
          Mode Autonome • Copy-Trading • Kill Switch
        </p>
      </div>

      <ModuleCard title="CONTROL PANEL">
        {loading ? (
          <div className="text-nexus-muted font-mono text-sm py-8">
            Chargement...
          </div>
        ) : (
          <div className="flex flex-wrap gap-8">
            <div className="flex items-center gap-4">
              <span className="font-mono text-sm w-36">100% Autonome</span>
              <Button
                variant={state.autonomous_mode ? "default" : "outline"}
                onClick={() => toggle("autonomous")}
                className={state.autonomous_mode ? "bg-emerald-600 hover:bg-emerald-500" : ""}
              >
                {state.autonomous_mode ? "ON" : "OFF"}
              </Button>
            </div>
            <div className="flex items-center gap-4">
              <span className="font-mono text-sm w-36">Copy-Trading</span>
              <Button
                variant={state.copy_trading_mode ? "default" : "outline"}
                onClick={() => toggle("copy_trading")}
                className={state.copy_trading_mode ? "bg-amber-500 text-zinc-950 hover:bg-amber-400" : ""}
              >
                {state.copy_trading_mode ? "ON" : "OFF"}
              </Button>
            </div>
          </div>
        )}
      </ModuleCard>
    </div>
  );
}
