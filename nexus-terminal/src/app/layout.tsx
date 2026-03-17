import type { Metadata } from "next";
import "./globals.css";
import { Web3Provider } from "@/components/web3-provider";

export const metadata: Metadata = {
  title: "NEXUS Terminal | Institutional Prediction Markets",
  description: "SaaS institutionnel - Antenne Unusual Whales + Polymarket | Usine Paperclip | Exécution Telegram & Web3",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr" className="dark">
      <body className="min-h-screen bg-zinc-950">
        <Web3Provider>{children}</Web3Provider>
      </body>
    </html>
  );
}
