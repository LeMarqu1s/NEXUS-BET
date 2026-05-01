# NEXUS BET - CONTEXT

## Infrastructure (TOUT EST DÉJÀ CONFIGURÉ)
- Railway : worker online 24/7 (worker-DwCy)
- Supabase : xironmvmumzzrfscryie.supabase.co
- Vercel : nexus-capital-api.vercel.app
- GitHub : github.com/LeMarqu1s/NEXUS-BET (private)
- Telegram bot : token + chat_id déjà dans Railway env vars

## Variables Railway (DÉJÀ CONFIGURÉES - NE PAS REDEMANDER)
SIMULATION_MODE, AUTO_SNIPE, POLYMARKET_PRIVATE_KEY,
POLYMARKET_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_TOKEN,
TELEGRAM_CHAT_ID, SUPABASE_URL, SUPABASE_SERVICE_KEY,
ODDS_API_KEY, NEXUS_ENCRYPTION_KEY, MIN_EDGE_THRESHOLD,
MAX_CONCURRENT_POSITIONS, RELAYER_API_KEY_ADDRESS
RAILWAY_TOKEN : déjà configuré dans les variables Railway sous le nom RAILWAY_TOKEN. Utilise os.getenv('RAILWAY_TOKEN'). Ne jamais le redemander.

## État actuel du bot
- Scalper BTC/ETH : ACTIF en SIM, 100% win rate, +22.81 USDC sur 3 trades
- Sniper classique : ACTIF en SIM, 100% win rate, +49.70 USDC sur 1 trade
- Commande /mode : permet de switcher SIM/LIVE depuis Telegram
- Sniper désactivé ligne 432-433 avec return — NE PAS TOUCHER
- Calcul edge : 3 bugs corrigés (detect_market_type L48, compute_edge_scalar L392-394 et L408)
- Objectif à terme : +5,000€/10,000€ par mois avec le bot

## Stratégie scalper BTC/ETH
- Filtre : marchés "Up or Down" BTC/ETH uniquement
- Timing : entrée entre 30s et 5min avant résolution
- Prix : entre $0.55 et $0.92
- Mouvement BTC minimum : 0.15% sur 5min via CoinGecko
- TP : +12%, SL : -8%
- Sizing : configurable par l'utilisateur (actuellement $27)
- Cooldown : 5min après un SL
- Max 2 positions simultanées

## Stratégie sniper classique
- Filtre prix : entre $0.15 et $0.85 uniquement
- TP : +40%, SL : -25%
- Marchés : tous sauf BTC/ETH Up or Down (géré par scalper)

## Commandes Telegram disponibles
/scan, /portfolio, /whales, /referral, /settings,
/strategy, /backtest, /selftest, /scalp_stats,
/scalp_settings, /mode, /comparatif

## Règles absolues
1. Ne jamais demander les variables Railway
2. Ne modifier QUE les fichiers explicitement demandés
3. Chaque fix = minimum de lignes changées possible
4. Toujours montrer le diff exact avant de pusher
5. Push directement sur main sauf si le diff est > 20 lignes
6. Ne jamais toucher au sniper désactivé ligne 432-433
