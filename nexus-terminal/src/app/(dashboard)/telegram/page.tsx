"use client";

import { ModuleCard } from "@/components/module-card";
import { Button } from "@/components/ui/button";

export default function TelegramPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-mono text-2xl font-bold text-nexus-cyan">
          Telegram Alerts
        </h1>
        <p className="text-nexus-muted text-sm mt-1">
          Bot premium type FProject • Alertes temps réel
        </p>
      </div>

      <ModuleCard title="TELEGRAM BOT">
        <div className="space-y-6">
          <div className="text-nexus-muted font-mono text-sm">
            Alertes signaux, exécutions, débats AI. Intégration monitoring/telegram_bot.py
          </div>
          <Button variant="outline" disabled>
            Configurer le bot — À venir
          </Button>
        </div>
      </ModuleCard>
    </div>
  );
}
