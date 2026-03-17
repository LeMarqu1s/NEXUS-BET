# NEXUS Terminal

Dashboard institutionnel type Arkham/Bloomberg pour NEXUS BET SaaS.

## Architecture

- **Antenne** : Unusual Whales + Polymarket API
- **Usine** : Moteur Paperclip (4 agents)
- **Exécution** : Telegram + Web3

## Modules (12)

| Gestion | Analyse | Usine | Exécution |
|---------|---------|-------|-----------|
| Hybrid Wallet | Smart Whale Tracker | Edge Signals | Control Panel |
| Auto-Compound | Order Book Radar | AI Debates | Execution Log |
| | Shadow Liquidity Sniper | Antenna | Telegram Alerts |
| | | Risk Management | |

## Démarrage

```bash
cd nexus-terminal
npm install
npm run dev
```

Ouvre http://localhost:3000

## Wallet (Wagmi)

Connexion via wallet injecté (MetaMask, etc.). Wagmi + viem + React Query.

Pour Web3Modal/WalletConnect : ajouter `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` et migrer vers Reown AppKit.

## Données

Le dashboard lit les fichiers JSON à la racine du projet parent :
- `paperclip_pending_signals.json`
- `ai_debates_log.json`
- `dashboard_state.json`

Variable d'environnement optionnelle : `NEXUS_DATA_ROOT` (chemin vers le dossier contenant ces fichiers).
