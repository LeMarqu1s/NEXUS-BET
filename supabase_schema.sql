-- NEXUS BET - Supabase Schema
-- Idempotent : peut être relancé sur un projet existant sans erreur
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- TRADES
-- ============================================
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id TEXT NOT NULL,
    market_question TEXT,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    amount_usd DECIMAL(18, 6) NOT NULL,
    shares DECIMAL(18, 6) NOT NULL,
    price DECIMAL(8, 4) NOT NULL,
    order_type TEXT DEFAULT 'LIMIT',
    status TEXT DEFAULT 'PENDING',
    raw_order_id TEXT,
    pnl_usd DECIMAL(18, 6),
    exit_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    filled_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS market_question TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS order_type TEXT DEFAULT 'LIMIT';
ALTER TABLE trades ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'PENDING';
ALTER TABLE trades ADD COLUMN IF NOT EXISTS raw_order_id TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS pnl_usd DECIMAL(18, 6);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_reason TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_trades_market_id ON trades(market_id);
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);

-- ============================================
-- DEBATES
-- ============================================
CREATE TABLE IF NOT EXISTS debates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id UUID REFERENCES trades(id),
    market_id TEXT,
    round INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    vote TEXT,
    tokens_used INTEGER,
    model_used TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
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
    side TEXT NOT NULL,
    shares DECIMAL(18, 6) NOT NULL,
    avg_entry_price DECIMAL(8, 4) NOT NULL,
    cost_basis_usd DECIMAL(18, 6) NOT NULL,
    current_value_usd DECIMAL(18, 6),
    unrealized_pnl DECIMAL(18, 6),
    take_profit_price DECIMAL(8, 4),
    stop_loss_price DECIMAL(8, 4),
    status TEXT DEFAULT 'OPEN',
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS current_value_usd DECIMAL(18, 6);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS unrealized_pnl DECIMAL(18, 6);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS take_profit_price DECIMAL(8, 4);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS stop_loss_price DECIMAL(8, 4);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'OPEN';
ALTER TABLE positions ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_positions_market_id ON positions(market_id);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);

-- ============================================
-- SMART MONEY
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
-- BOT RUNS
-- ============================================
CREATE TABLE IF NOT EXISTS bot_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    status TEXT DEFAULT 'RUNNING',
    markets_scanned INTEGER DEFAULT 0,
    trades_executed INTEGER DEFAULT 0,
    total_pnl_usd DECIMAL(18, 6) DEFAULT 0,
    error_message TEXT
);
ALTER TABLE bot_runs ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'RUNNING';
ALTER TABLE bot_runs ADD COLUMN IF NOT EXISTS markets_scanned INTEGER DEFAULT 0;
ALTER TABLE bot_runs ADD COLUMN IF NOT EXISTS trades_executed INTEGER DEFAULT 0;
ALTER TABLE bot_runs ADD COLUMN IF NOT EXISTS total_pnl_usd DECIMAL(18, 6) DEFAULT 0;
ALTER TABLE bot_runs ADD COLUMN IF NOT EXISTS error_message TEXT;
CREATE INDEX IF NOT EXISTS idx_bot_runs_started_at ON bot_runs(started_at DESC);

-- ============================================
-- USERS
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
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_count INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS dashboard_token TEXT;
CREATE INDEX IF NOT EXISTS idx_users_telegram_chat_id ON users(telegram_chat_id);
CREATE INDEX IF NOT EXISTS idx_users_access_token ON users(access_token);
CREATE INDEX IF NOT EXISTS idx_users_dashboard_token ON users(dashboard_token);

-- ============================================
-- SIGNALS
-- ============================================
CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id TEXT NOT NULL,
    side TEXT NOT NULL,
    question TEXT,
    edge_pct DECIMAL(8, 4),
    kelly_fraction DECIMAL(8, 4),
    confidence DECIMAL(4, 2),
    polymarket_price DECIMAL(8, 4),
    fair_price DECIMAL(8, 4),
    signal_strength TEXT DEFAULT 'BUY',
    market_type TEXT DEFAULT 'binary',
    reasoning TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_market_id ON signals(market_id);

-- ============================================
-- RLS
-- ============================================
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users_anon_select" ON users;
CREATE POLICY "users_anon_select" ON users FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "users_anon_insert" ON users;
CREATE POLICY "users_anon_insert" ON users FOR INSERT TO anon WITH CHECK (true);
DROP POLICY IF EXISTS "users_anon_update" ON users;
CREATE POLICY "users_anon_update" ON users FOR UPDATE TO anon USING (true) WITH CHECK (true);

-- ============================================
-- SNIPER — colonnes ajoutées pour SaaS multi-client
-- ============================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS polymarket_private_key_enc TEXT;   -- AES-256 Fernet
ALTER TABLE users ADD COLUMN IF NOT EXISTS polymarket_api_key_enc TEXT;        -- AES-256 Fernet
ALTER TABLE users ADD COLUMN IF NOT EXISTS capital_allocated FLOAT DEFAULT 50;
ALTER TABLE users ADD COLUMN IF NOT EXISTS risk_profile TEXT DEFAULT 'conservative';
ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_snipe BOOLEAN DEFAULT FALSE;
