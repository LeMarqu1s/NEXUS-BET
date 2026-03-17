"use client";

import { ModuleCard } from "@/components/module-card";
import { Button } from "@/components/ui/button";
import { WalletConnectButton } from "@/components/wallet-connect-button";

export default function WalletPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">
          Hybrid Wallet System
        </h1>
        <p className="text-zinc-500 text-sm mt-1">
          Web3Modal ou Custodial • DeFi Yield Hedging (Aave USDC)
        </p>
      </div>

      <ModuleCard title="Connect Wallet">
        <div className="space-y-6">
          <div className="flex gap-4 items-center">
            <WalletConnectButton />
            <Button variant="outline">Afficher Custodial</Button>
          </div>
          <div className="border border-zinc-800 rounded-xl p-4 text-sm">
            <div className="text-zinc-500 mb-2">DeFi Yield Hedging</div>
            <div className="text-zinc-300">
              USDC inactif → Aave pour générer du rendement. Intégration à venir.
            </div>
          </div>
        </div>
      </ModuleCard>
    </div>
  );
}
