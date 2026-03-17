"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SIDEBAR_MODULES, GROUP_LABELS } from "@/config/modules";
import { cn } from "@/lib/utils";

const ICONS: Record<string, string> = {
  wallet: "💳",
  repeat: "🔄",
  fish: "🐋",
  radar: "📡",
  crosshair: "🎯",
  zap: "⚡",
  "message-square": "💬",
  radio: "📻",
  shield: "🛡️",
  sliders: "⚙️",
  "file-text": "📋",
  send: "✈️",
};

export function Sidebar() {
  const pathname = usePathname();

  const grouped = SIDEBAR_MODULES.reduce<Record<string, typeof SIDEBAR_MODULES>>(
    (acc, m) => {
      if (!acc[m.group]) acc[m.group] = [];
      acc[m.group].push(m);
      return acc;
    },
    {}
  );

  return (
    <aside className="w-64 min-h-screen border-r border-zinc-800 bg-zinc-900/50 flex flex-col">
      <div className="p-4 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="font-semibold text-zinc-100 text-lg">NEXUS</span>
          <span className="text-zinc-500 text-sm">Terminal</span>
        </div>
        <p className="text-xs text-zinc-500 mt-1">SaaS Institutionnel</p>
      </div>

      <nav className="flex-1 overflow-y-auto py-4">
        {Object.entries(grouped).map(([group, modules]) => (
          <div key={group} className="mb-6">
            <div className="px-4 mb-2">
              <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
                {GROUP_LABELS[group] || group}
              </span>
            </div>
            <ul className="space-y-0.5">
              {modules.map((m) => {
                const href = `/${m.id}`;
                const isActive = pathname === href || pathname.startsWith(href + "/");
                return (
                  <li key={m.id}>
                    <Link
                      href={href}
                      className={cn(
                        "flex items-center gap-3 px-4 py-2.5 mx-2 rounded-lg text-sm transition-all",
                        isActive
                          ? "bg-blue-600/15 text-blue-400 border-l-2 border-blue-500 -ml-0.5 pl-4"
                          : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/50"
                      )}
                    >
                      <span className="text-base">{ICONS[m.icon] || "•"}</span>
                      <span className="truncate">{m.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="p-4 border-t border-zinc-800">
        <div className="text-xs text-zinc-500">Antenne → Usine → Exécution</div>
      </div>
    </aside>
  );
}
