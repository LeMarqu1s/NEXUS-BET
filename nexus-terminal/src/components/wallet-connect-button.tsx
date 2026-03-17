"use client";

import { useAccount, useConnect, useDisconnect } from "wagmi";
import { Button } from "@/components/ui/button";

export function WalletConnectButton() {
  const { address, isConnected } = useAccount();
  const { connect, connectors, isPending } = useConnect();
  const { disconnect } = useDisconnect();

  if (isConnected && address) {
    return (
      <div className="flex items-center gap-3">
        <span className="text-sm text-zinc-400 font-mono truncate max-w-[180px]">
          {address.slice(0, 6)}...{address.slice(-4)}
        </span>
        <Button variant="outline" size="sm" onClick={() => disconnect()}>
          Déconnecter
        </Button>
      </div>
    );
  }

  const injected = connectors.find((c) => c.id === "injected" || c.type === "injected");

  return (
    <Button
      onClick={() => injected && connect({ connector: injected })}
      disabled={!injected || isPending}
    >
      {isPending ? "Connexion..." : "Connect Wallet"}
    </Button>
  );
}
