/**
 * NEXUS Terminal - 12 Modules Institutionnels
 * Architecture: Antenne (Unusual Whales + Polymarket) | Usine (Paperclip) | Exécution (Telegram + Web3)
 */

export interface NavModule {
  id: string;
  label: string;
  icon: string;
  group: "gestion" | "analyse" | "usine" | "execution";
  description: string;
}

export const SIDEBAR_MODULES: NavModule[] = [
  // MODULES DE GESTION
  {
    id: "portfolio",
    label: "Portfolio & PnL",
    icon: "wallet",
    group: "gestion",
    description: "Positions ouvertes · Historique trades · PnL en temps réel",
  },
  {
    id: "compound",
    label: "Auto-Compound Manager",
    icon: "repeat",
    group: "gestion",
    description: "Jauge de réinvestissement automatique des profits",
  },
  // MODULES D'ANALYSE & COPY-TRADING
  {
    id: "whale",
    label: "Smart Whale Tracker",
    icon: "fish",
    group: "analyse",
    description: "Top Wallets Polymarket • AI Shield Copy (audit Risk Manager)",
  },
  {
    id: "orderbook",
    label: "Order Book Anomaly Radar",
    icon: "radar",
    group: "analyse",
    description: "Détection anti-manipulation (Anti-Rug) carnets d'ordres",
  },
  {
    id: "shadow-liquidity",
    label: "Shadow Liquidity Sniper",
    icon: "crosshair",
    group: "analyse",
    description: "Croise les flux Unusual Whales ↔ Polymarket",
  },
  // MODULES USINE PAPERCLIP
  {
    id: "signals",
    label: "Edge Signals",
    icon: "zap",
    group: "usine",
    description: "Signaux Paperclip (priorité) + fallback Gamma/CLOB",
  },
  {
    id: "debates",
    label: "AI Debates",
    icon: "message-square",
    group: "usine",
    description: "Flux Quant → Risk Manager → Head Analyst → Nightly Auditor",
  },
  {
    id: "antenna",
    label: "Antenna Dashboard",
    icon: "radio",
    group: "usine",
    description: "Unusual Whales (Options/Équités) + Polymarket feeds",
  },
  {
    id: "risk",
    label: "Risk Management",
    icon: "shield",
    group: "usine",
    description: "Position limits • Kelly • Stop-loss • Exposition",
  },
  // MODULES EXÉCUTION
  {
    id: "control",
    label: "Control Panel",
    icon: "sliders",
    group: "execution",
    description: "Mode Autonome • Copy-Trading • Kill Switch",
  },
  {
    id: "execution",
    label: "Execution Log",
    icon: "file-text",
    group: "execution",
    description: "Historique ordres • Trades • Smart Contracts",
  },
  {
    id: "telegram",
    label: "Telegram Alerts",
    icon: "send",
    group: "execution",
    description: "Bot premium type FProject • Alertes temps réel",
  },
];

export const GROUP_LABELS: Record<string, string> = {
  gestion: "GESTION",
  analyse: "ANALYSE & COPY-TRADING",
  usine: "USINE PAPERCLIP",
  execution: "EXÉCUTION",
};
