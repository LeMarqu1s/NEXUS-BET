# NEXUS CAPITAL Template

Prediction market trading system with AI agents, Polymarket, and Telegram.

## Quick Deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/LeMarqu1s/nexus-capital-template&env=TELEGRAM_BOT_TOKEN&env=TELEGRAM_CHAT_ID&env=SUPABASE_URL&env=SUPABASE_ANON_KEY&env=SUPABASE_SERVICE_ROLE_KEY&env=ANTHROPIC_API_KEY)

## Required Variables

Set these 6 environment variables in Railway (or `.env`):

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anon/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (requis pour `/access` et dashboard auth) |
| `ANTHROPIC_API_KEY` | Anthropic API key for AI agents |

## Supabase Setup

Avant de démarrer le bot, exécuter `supabase_schema.sql` dans le **SQL Editor** de ton projet Supabase.
Ce script crée les 6 tables nécessaires : `trades`, `debates`, `positions`, `smart_money_signals`, `bot_runs`, `users`.

Les clés se trouvent dans **Supabase → Settings → API** :
- `SUPABASE_ANON_KEY` → `anon / public`
- `SUPABASE_SERVICE_ROLE_KEY` → `service_role` (⚠️ ne jamais exposer côté client)

## Setup

1. Clone and deploy to Railway (or run locally)
2. Configure the 6 variables above
3. Run `supabase_schema.sql` in Supabase SQL Editor
4. On first deploy, a welcome message is sent to your Telegram

## Dashboard

- **Vercel**: Deploy `api/` to get the Bloomberg-style dashboard
- **URL**: `https://your-app.vercel.app`

## Create Template Repo

To publish as a standalone template:

```bash
cd nexus-capital-template
git init && git add . && git commit -m "NEXUS CAPITAL template"
git remote add origin https://github.com/YOUR_USER/nexus-capital-template.git
git branch -M main && git push -u origin main
```

Then enable "Template repository" in GitHub repo Settings.

## Structure

```
├── main.py           # Master loop
├── core/             # Scanner, EdgeEngine
├── monitoring/       # Telegram bot
├── api/              # Dashboard (Vercel)
└── agents.py         # AI adversarial team
```
