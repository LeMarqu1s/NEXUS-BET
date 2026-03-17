"use client";

import { Button } from "@/components/ui/button";

export function Header() {
  return (
    <header className="h-14 border-b border-zinc-800 bg-zinc-900/80 backdrop-blur sticky top-0 z-40 flex items-center justify-between px-6">
      <div className="flex items-center gap-4">
        <span className="text-xs text-zinc-500" id="last-update">
          —
        </span>
      </div>
      <div className="flex items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            const el = document.getElementById("last-update");
            if (el) el.textContent = new Date().toLocaleTimeString("fr-FR");
            window.dispatchEvent(new CustomEvent("nexus-refresh"));
          }}
        >
          ⟳ Actualiser
        </Button>
      </div>
    </header>
  );
}
