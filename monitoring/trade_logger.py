"""
NEXUS BET - Logging des trades en SQLite
Enregistrement local des positions, ordres et PnL.
"""
import asyncio
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, Any


DB_PATH = Path(__file__).resolve().parent.parent / "logs" / "nexus_trades.db"


def _get_conn() -> sqlite3.Connection:
    """Crée ou ouvre la DB SQLite."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    """Initialise le schéma SQLite local."""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE,
                market_id TEXT,
                outcome TEXT,
                side TEXT,
                size REAL,
                price REAL,
                pnl REAL,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT,
                outcome TEXT,
                size REAL,
                avg_price REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id);
            CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at);
        """)
        conn.commit()
    finally:
        conn.close()


class TradeLogger:
    """Logger SQLite pour les trades NEXUS BET."""

    def __init__(self) -> None:
        _init_db()

    def log_trade(
        self,
        trade_id: str,
        market_id: str,
        outcome: str,
        side: str,
        size: float,
        price: float,
        pnl: Optional[float] = None,
        status: str = "filled",
    ) -> None:
        """Enregistre un trade exécuté."""
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO trades
                   (trade_id, market_id, outcome, side, size, price, pnl, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade_id, market_id, outcome, side, size, price, pnl, status),
            )
            conn.commit()
        finally:
            conn.close()

    def update_position(
        self,
        market_id: str,
        outcome: str,
        size: float,
        avg_price: float,
    ) -> None:
        """Met à jour une position."""
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT INTO positions (market_id, outcome, size, avg_price, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(market_id) DO UPDATE SET
                     size = excluded.size,
                     avg_price = excluded.avg_price,
                     updated_at = CURRENT_TIMESTAMP""",
                (market_id, outcome, size, avg_price),
            )
            conn.commit()
        except sqlite3.OperationalError:
            conn.execute(
                """UPDATE positions SET size=?, avg_price=?, updated_at=CURRENT_TIMESTAMP
                   WHERE market_id=? AND outcome=?""",
                (size, avg_price, market_id, outcome),
            )
            conn.commit()
        finally:
            conn.close()

    def get_positions(self) -> list[dict[str, Any]]:
        """Retourne les positions actuelles."""
        conn = _get_conn()
        try:
            cur = conn.execute(
                "SELECT market_id, outcome, size, avg_price, updated_at FROM positions WHERE size > 0"
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_recent_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retourne les trades récents."""
        conn = _get_conn()
        try:
            cur = conn.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


# Instance globale
trade_logger = TradeLogger()
