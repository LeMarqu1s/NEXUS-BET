"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

interface Health {
  scannerStatus?: string;
  activeSubscribers?: number;
  lastSignalAt?: string | null;
}

export function Header() {
  const [health, setHealth] = useState<Health>({});
  const [lastUpdate, setLastUpdate] = useState("—");

  const refresh = async () => {
    setLastUpdate(new Date().toLocaleTimeString("fr-FR"));
    window.dispatchEvent(new CustomEvent("nexus-refresh"));
    try {
      const r = await fetch("/api/health", { cache: "no-store" });
      const d = await r.json();
      setHealth(d);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 60000);
    return () => clearInterval(id);
  }, []);

  const dot =
    health.scannerStatus === "online"
      ? "bg-emerald-500"
      : health.scannerStatus === "slow"
      ? "bg-yellow-500"
      : health.scannerStatus === "offline"
      ? "bg-red-500"
      : "bg-zinc-600";

  return (
    <header className="h-14 border-b border-zinc-800 bg-zinc-900/80 backdrop-blur sticky top-0 z-40 flex items-center justify-between px-6">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1.5">
          <div className={`w-1.5 h-1.5 rounded-full ${dot}`} />
          <span className="text-xs text-zinc-500">
            Scanner{" "}
            <span className="text-zinc-400">{health.scannerStatus || "—"}</span>
          </span>
        </div>
        {health.activeSubscribers != null && (
          <span className="text-xs text-zinc-600">
            {health.activeSubscribers} abonné{health.activeSubscribers !== 1 ? "s" : ""}
          </span>
        )}
        <span className="text-xs text-zinc-600">{lastUpdate}</span>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={refresh}
      >
        ⟳ Actualiser
      </Button>
    </header>
  );
}
