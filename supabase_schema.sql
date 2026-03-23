-- NEXUS BET - Supabase Schema
-- Run this in Supabase SQL Editor to create all tables

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- TRADES
-- ============================================
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id TEXT NOT NULL,
    market_question TEXT,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('YES', 'NO', 'BUY', 'SELL')),
    amount_usd DECIMAL(18, 6) NOT NULL,
    shares DECIMAL(18, 6) NOT NULL,
    price DECIMAL(8, 4) NOT NULL,
    order_type TEXT DEFAULT 'LIMIT',
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'FILLED', 'CANCELLED', 'FAILED')),
    raw_order_id TEXT,
    pnl_usd DECIMAL(18, 6),
    exit_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    filled_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

-- Migrations : colonnes ajoutées après la création initiale
ALTER TABLE trades ADD COLUMN IF NOT EXISTS market_question TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS order_type TEXT DEFAULT 'LIMIT';
ALTER TABLE trades ADD COLUMN IF NOT EXISTS raw_order_id TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS pnl_usd DECIMAL(18, 6);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_reason TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_trades_market_id ON trades(market_id);
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);

-- ============================================
-- DEBATES (Adversarial AI discussions)
-- ============================================
CREATE TABLE IF NOT EXISTS debates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id UUID REFERENCES trades(id),
    market_id TEXT,
    round INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL CHECK (role IN ('QUANT', 'RISK_MANAGER', 'HEAD_ANALYST')),
    content TEXT NOT NULL,
    vote TEXT CHECK (vote IN ('APPROVE', 'REJECT', NULL)),
    tokens_used INTEGER,
    model_used TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Migrations
ALTER TABLE debates ADD COLUMN IF NOT EXISTS market_id TEXT;
ALTER TABLE debates ADD COLUMN IF NOT EXISTS tokens_used INTEGER;
ALTER TABLE debates ADD COLUMN IF NOT EXISTS model_used TEXT;

CREATE INDEX IF NOT EXISTS idx_debates_trade_id ON debates(trade_id);
CREATE INDEX IF NOT EXISTS idx_debates_market_id ON debates(market_id);
CREATE INDEX IF NOT EXISTS idx_debates_created_at ON debates(created_at DESC);

-- ============================================
-- POSITIONS
-- ============================================
CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('YES', 'NO')),
    shares DECIMAL(18, 6) NOT NULL,
    avg_entry_price DECIMAL(8, 4) NOT NULL,
    cost_basis_usd DECIMAL(18, 6) NOT NULL,
    current_value_usd DECIMAL(18, 6),
    unrealized_pnl DECIMAL(18, 6),
    take_profit_price DECIMAL(8, 4),
    stop_loss_price DECIMAL(8, 4),
    status TEXT DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED', 'PARTIAL')),
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    UNIQUE(market_id, token_id)
);

-- Migrations : colonnes ajoutées après la création initiale
ALTER TABLE positions ADD COLUMN IF NOT EXISTS current_value_usd DECIMAL(18, 6);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS unrealized_pnl DECIMAL(18, 6);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS take_profit_price DECIMAL(8, 4);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS stop_loss_price DECIMAL(8, 4);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'OPEN';
ALTER TABLE positions ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- Appliquer la contrainte CHECK sur status si elle manque (idempotent via DO block)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'positions_status_check'
    ) THEN
        ALTER TABLE positions ADD CONSTRAINT positions_status_check
            CHECK (status IN ('OPEN', 'CLOSED', 'PARTIAL'));
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_positions_market_id ON positions(market_id);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);

-- ============================================
-- SMART MONEY (Unusual Whales signals)
-- ============================================
CREATE TABLE IF NOT EXISTS smart_money_signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol TEXT,
    market_ticker TEXT,
    signal_type TEXT,
    flow_data JSONB,
    confidence_score DECIMAL(4, 2),
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_smart_money_symbol ON smart_money_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_smart_money_detected_at ON smart_money_signals(detected_at DESC);

-- ============================================
-- BOT RUNS (Session metadata)
-- ============================================
CREATE TABLE IF NOT EXISTS bot_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    status TEXT DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'STOPPED', 'ERROR')),
    markets_scanned INTEGER DEFAULT 0,
    trades_executed INTEGER DEFAULT 0,
    total_pnl_usd DECIMAL(18, 6) DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_bot_runs_started_at ON bot_runs(started_at DESC);

-- ============================================
-- USERS (Auth token pour dashboard privé)
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    telegram_chat_id TEXT UNIQUE NOT NULL,
    access_token TEXT UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT false,
    plan TEXT DEFAULT 'free',
    created_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ,
    referral_code TEXT,
    referred_by TEXT
);

-- Migrations
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by TEXT;

CREATE INDEX IF NOT EXISTS idx_users_telegram_chat_id ON users(telegram_chat_id);
CREATE INDEX IF NOT EXISTS idx_users_access_token ON users(access_token);

-- ============================================
-- ROW LEVEL SECURITY
-- ============================================
-- La table users contient des access_token sensibles → RLS activé.
-- Les autres tables (trades, debates, positions, etc.) sont des données
-- internes, accédées uniquement via service_role ou anon depuis Railway.
-- Laisser RLS désactivé sur ces tables est acceptable si le projet est privé.

ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Le service_role bypasse RLS automatiquement (clé SUPABASE_SERVICE_ROLE_KEY).
-- Si seul l'anon_key est configuré, ces policies permettent au bot de fonctionner.

-- Dashboard : vérification token par valeur exacte (SELECT)
DROP POLICY IF EXISTS "users_anon_select" ON users;
CREATE POLICY "users_anon_select" ON users
    FOR SELECT TO anon
    USING (true);

-- Bot /access : création d'un nouvel utilisateur (INSERT)
DROP POLICY IF EXISTS "users_anon_insert" ON users;
CREATE POLICY "users_anon_insert" ON users
    FOR INSERT TO anon
    WITH CHECK (true);

-- Bot /access : rafraîchissement du token (UPDATE)
DROP POLICY IF EXISTS "users_anon_update" ON users;
CREATE POLICY "users_anon_update" ON users
    FOR UPDATE TO anon
    USING (true)
    WITH CHECK (true);
