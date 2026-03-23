"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const errParam = params.get("error");
    if (errParam === "invalid") setError("Token invalide ou abonnement expiré.");
    else if (errParam === "server") setError("Erreur serveur. Réessaie.");
  }, [params]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;
    setLoading(true);
    setError(null);
    // Redirect with token — middleware will validate and set cookie
    router.push(`/signals?token=${encodeURIComponent(token.trim())}`);
  };

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="flex items-center justify-center gap-2 mb-2">
            <div className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-2xl font-bold text-zinc-100">NEXUS Terminal</span>
          </div>
          <p className="text-zinc-500 text-sm">SaaS Institutionnel · Prediction Markets</p>
        </div>

        <div className="border border-zinc-800 rounded-2xl bg-zinc-900/50 p-8">
          <h2 className="text-zinc-100 font-semibold text-lg mb-1">Accès abonné</h2>
          <p className="text-zinc-500 text-sm mb-6">
            Entre ton token d&apos;accès reçu sur Telegram via{" "}
            <code className="text-blue-400">/dashboard</code>.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <input
                type="text"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Coller ton token ici..."
                className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-blue-500 transition font-mono text-sm"
                autoFocus
              />
            </div>
            {error && (
              <p className="text-red-400 text-sm">{error}</p>
            )}
            <button
              type="submit"
              disabled={loading || !token.trim()}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white rounded-xl py-3 font-semibold transition text-sm"
            >
              {loading ? "Vérification..." : "Accéder au terminal →"}
            </button>
          </form>

          <p className="text-zinc-600 text-xs mt-6 text-center">
            Pas encore abonné ? Contacte-nous sur Telegram.
          </p>
        </div>
      </div>
    </div>
  );
}
