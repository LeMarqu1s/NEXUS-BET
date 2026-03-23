"""
NEXUS BET - Configuration centralisée
Variables d'environnement pour Polymarket, Supabase, Anthropic, Telegram, paramètres de risque.
"""
import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class PolymarketSettings:
    """Configuration Polymarket CLOB API."""
    clob_url: str = "https://clob.polymarket.com"
    gamma_url: str = "https://gamma-api.polymarket.com"
    chain_id: int = 137  # Polygon
    private_key: Optional[str] = None
    host: str = "https://clob.polymarket.com"


@dataclass
class SupabaseSettings:
    """Configuration Supabase."""
    url: str = ""
    anon_key: str = ""
    service_role_key: Optional[str] = None


@dataclass
class AnthropicSettings:
    """Configuration Anthropic Claude API."""
    api_key: Optional[str] = None
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096


@dataclass
class TelegramSettings:
    """Configuration Telegram Bot."""
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    enabled: bool = False


@dataclass
class RiskSettings:
    """Paramètres de risque."""
    max_position_pct: float = 0.05  # 5% max par position
    max_total_exposure_pct: float = 0.25  # 25% exposition max
    kelly_fraction: float = 0.25  # Fraction Kelly conservatrice
    min_edge_pct: float = 2.0  # Edge minimum 2%
    max_daily_loss_pct: float = 0.10  # Stop jour à -10%
    take_profit_pct: float = 0.50  # Take profit 50%
    stop_loss_pct: float = 0.25  # Stop loss 25%
    min_confidence: float = 0.60  # Confiance min 60%


@dataclass
class ScannerSettings:
    """Configuration du scanneur de marchés."""
    scan_interval_seconds: float = 10.0
    max_concurrent_orders: int = 5
    markets_cache_ttl_seconds: int = 60
    min_edge_threshold: float = 3.0  # % edge minimum for signals
    min_ev_threshold: float = 20.0
    min_market_volume: float = 1000.0
    min_liquidity: float = 100.0


def _get_env(key: str, default: str = "") -> str:
    """Récupère une variable d'environnement."""
    return os.getenv(key, default)


def _get_env_float(key: str, default: float) -> float:
    """Récupère un float depuis l'env."""
    val = os.getenv(key)
    return float(val) if val else default


def _get_env_int(key: str, default: int) -> int:
    """Récupère un int depuis l'env."""
    val = os.getenv(key)
    return int(val) if val else default


def _get_env_bool(key: str, default: bool = False) -> bool:
    """Récupère un bool depuis l'env."""
    val = os.getenv(key, "").lower()
    return val in ("true", "1", "yes") if val else default


def load_settings() -> dict:
    """Charge toute la configuration depuis l'environnement."""
    polymarket = PolymarketSettings(
        clob_url=_get_env("POLYMARKET_CLOB_URL", "https://clob.polymarket.com"),
        gamma_url=_get_env("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com"),
        chain_id=_get_env_int("POLYMARKET_CHAIN_ID", 137),
        private_key=_get_env("POLYMARKET_PRIVATE_KEY"),
    )
    supabase = SupabaseSettings(
        url=_get_env("SUPABASE_URL"),
        anon_key=_get_env("SUPABASE_ANON_KEY") or _get_env("SUPABASE_SERVICE_ROLE_KEY"),
        service_role_key=_get_env("SUPABASE_SERVICE_ROLE_KEY"),
    )
    anthropic = AnthropicSettings(
        api_key=_get_env("ANTHROPIC_API_KEY"),
        model=_get_env("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=_get_env_int("ANTHROPIC_MAX_TOKENS", 4096),
    )
    # Canonical: TELEGRAM_BOT_TOKEN (fallback: TELEGRAM_TOKEN)
    _tg_token = _get_env("TELEGRAM_BOT_TOKEN") or _get_env("TELEGRAM_TOKEN")
    _tg_chat = _get_env("TELEGRAM_CHAT_ID")
    telegram = TelegramSettings(
        bot_token=_tg_token,
        chat_id=_tg_chat,
        enabled=_get_env_bool("TELEGRAM_ENABLED", bool(_tg_token and _tg_chat)),
    )
    risk = RiskSettings(
        max_position_pct=_get_env_float("RISK_MAX_POSITION_PCT", 0.05),
        max_total_exposure_pct=_get_env_float("RISK_MAX_TOTAL_EXPOSURE_PCT", 0.25),
        kelly_fraction=_get_env_float("RISK_KELLY_FRACTION", 0.25),
        min_edge_pct=_get_env_float("RISK_MIN_EDGE_PCT", 2.0),
        max_daily_loss_pct=_get_env_float("RISK_MAX_DAILY_LOSS_PCT", 0.10),
        take_profit_pct=_get_env_float("RISK_TAKE_PROFIT_PCT", 0.50),
        stop_loss_pct=_get_env_float("RISK_STOP_LOSS_PCT", 0.25),
        min_confidence=_get_env_float("RISK_MIN_CONFIDENCE", 0.60),
    )
    scanner = ScannerSettings(
        scan_interval_seconds=_get_env_float("SCANNER_INTERVAL_SECONDS", 10.0),
        max_concurrent_orders=_get_env_int("SCANNER_MAX_CONCURRENT_ORDERS", 5),
        markets_cache_ttl_seconds=_get_env_int("SCANNER_MARKETS_CACHE_TTL", 60),
        min_edge_threshold=_get_env_float("MIN_EDGE_THRESHOLD", 3.0),
        min_ev_threshold=_get_env_float("MIN_EV_THRESHOLD", 20.0),
        min_market_volume=_get_env_float("MIN_MARKET_VOLUME", 1000.0),
        min_liquidity=_get_env_float("MIN_LIQUIDITY", 100.0),
    )
    return {
        "polymarket": polymarket,
        "supabase": supabase,
        "anthropic": anthropic,
        "telegram": telegram,
        "risk": risk,
        "scanner": scanner,
    }


# Instance globale pour import facile
SETTINGS = load_settings()


class _SettingsProxy:
    """Proxy plat pour accès settings.ATTRIBUTE depuis tous les modules."""

    def __init__(self) -> None:
        self._s = SETTINGS

    @property
    def POLYMARKET_CLOB_HOST(self) -> str:
        return self._s["polymarket"].clob_url or self._s["polymarket"].host

    @property
    def POLYMARKET_CHAIN_ID(self) -> int:
        return self._s["polymarket"].chain_id

    @property
    def POLYMARKET_PRIVATE_KEY(self) -> Optional[str]:
        return self._s["polymarket"].private_key

    @property
    def POLYMARKET_GAMMA_URL(self) -> str:
        return self._s["polymarket"].gamma_url

    @property
    def POLYMARKET_CAPITAL_USD(self) -> float:
        val = os.getenv("POLYMARKET_CAPITAL_USD") or os.getenv("TOTAL_CAPITAL")
        return float(val) if val else 1000.0

    @property
    def SUPABASE_URL(self) -> str:
        return self._s["supabase"].url or ""

    @property
    def SUPABASE_KEY(self) -> str:
        return self._s["supabase"].anon_key or ""

    @property
    def SUPABASE_ANON_KEY(self) -> str:
        return self._s["supabase"].anon_key or ""

    @property
    def ANTHROPIC_API_KEY(self) -> Optional[str]:
        return self._s["anthropic"].api_key

    @property
    def KELLY_FRACTION_CAP(self) -> float:
        return self._s["risk"].kelly_fraction

    @property
    def MIN_EDGE_PCT(self) -> float:
        thresh = os.getenv("MIN_EDGE_THRESHOLD")
        if thresh:
            return float(thresh) / 100.0
        return self._s["risk"].min_edge_pct / 100.0

    @property
    def MIN_EDGE_THRESHOLD(self) -> float:
        return _get_env_float("MIN_EDGE_THRESHOLD", 3.0)

    @property
    def MIN_EV_THRESHOLD(self) -> float:
        return _get_env_float("MIN_EV_THRESHOLD", 20.0)

    @property
    def MIN_MARKET_VOLUME(self) -> float:
        return _get_env_float("MIN_MARKET_VOLUME", 1000.0)

    @property
    def MIN_LIQUIDITY(self) -> float:
        return _get_env_float("MIN_LIQUIDITY", 100.0)

    @property
    def MIN_CONFIDENCE(self) -> float:
        return self._s["risk"].min_confidence

    @property
    def SCAN_INTERVAL_SECONDS(self) -> float:
        return self._s["scanner"].scan_interval_seconds

    @property
    def MAX_POSITION_PCT(self) -> float:
        return self._s["risk"].max_position_pct

    @property
    def MAX_TOTAL_EXPOSURE_USD(self) -> float:
        return self.POLYMARKET_CAPITAL_USD * self._s["risk"].max_total_exposure_pct

    @property
    def UNUSUAL_WHALES_API_KEY(self) -> Optional[str]:
        return os.getenv("UNUSUAL_WHALES_API_KEY") or ""

    @property
    def DEBUG(self) -> bool:
        return _get_env_bool("DEBUG", False)


settings = _SettingsProxy()
