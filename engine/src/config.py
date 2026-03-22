"""
Configuration for the Notas Lave trading engine.

All settings are loaded from environment variables (.env file).
No secrets are ever hardcoded — this file only defines structure.

TRADING MODES:
- "prop": FundingPips challenge mode. USD, $100K balance, FundingPips rules.
- "personal": CoinDCX personal trading. INR, small balance, leverage.
  Set TRADING_MODE=personal in .env to switch.
"""

import logging
import os
import stat
from datetime import datetime

logger = logging.getLogger(__name__)
from pydantic_settings import BaseSettings
from pydantic import Field


class TradingConfig(BaseSettings):
    """Core trading engine configuration."""

    # -- API Keys (loaded from .env) --
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    twelvedata_api_key: str = Field(default="", alias="TWELVEDATA_API_KEY")

    # -- Claude Settings --
    # Provider: "anthropic" (direct API) or "vertex" (Google Cloud Vertex AI)
    claude_provider: str = Field(default="vertex", alias="CLAUDE_PROVIDER")
    claude_model: str = Field(default="claude-sonnet-4-20250514")
    claude_max_tokens: int = Field(default=1024)
    claude_min_confidence: int = Field(default=7)
    # Vertex AI settings
    google_cloud_project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_region: str = Field(default="us-east5", alias="GOOGLE_CLOUD_REGION")

    # -- Telegram Alerts --
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # -- Trading Mode --
    # "prop" = FundingPips (USD, $100K, strict rules)
    # "personal" = CoinDCX (INR, small account, leverage)
    trading_mode: str = Field(default="personal", alias="TRADING_MODE")

    # -- Leverage (personal mode) --
    leverage: float = Field(default=15.0, alias="LEVERAGE")
    usd_inr_rate: float = Field(default=84.0, alias="USD_INR_RATE")

    # -- Instruments we trade --
    instruments: list[str] = Field(
        default=["XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD"]
    )
    # Personal mode instruments (CoinDCX crypto only)
    personal_instruments: list[str] = Field(
        default=["BTCUSDT", "ETHUSDT"]
    )

    # -- Timeframes --
    entry_timeframes: list[str] = Field(
        default=["1m", "5m", "15m", "30m", "1h"]
    )
    context_timeframes: list[str] = Field(default=["4h", "1d"])

    # -- Risk Management (FundingPips Rules — prop mode) --
    max_daily_drawdown_pct: float = Field(default=0.05)
    max_total_drawdown_pct: float = Field(default=0.10)
    max_single_day_profit_pct: float = Field(default=0.45)
    min_risk_reward_ratio: float = Field(default=2.0)
    max_risk_per_trade_pct: float = Field(default=0.01)
    max_concurrent_positions: int = Field(default=3)
    news_blackout_minutes: int = Field(default=5)

    # -- Risk Management (Personal mode — more aggressive but still disciplined) --
    personal_risk_per_trade_pct: float = Field(default=0.02)  # 2% risk per trade
    personal_max_daily_dd_pct: float = Field(default=0.06)    # 6% daily limit
    personal_max_total_dd_pct: float = Field(default=0.20)    # 20% total (leverage amplifies)
    personal_max_concurrent: int = Field(default=2)

    # -- Confluence Scoring --
    min_confluence_score: float = Field(default=6.0)
    default_weights: dict[str, float] = Field(default={
        "scalping": 0.20, "ict": 0.20, "fibonacci": 0.20,
        "volume": 0.20, "breakout": 0.20,
    })  # Must match categories in confluence/scorer.py

    # -- Broker Selection --
    # "paper" = simulated (default), "coindcx" = live CoinDCX, "mt5" = MetaTrader 5
    broker: str = Field(default="paper", alias="BROKER")

    # -- Binance Testnet (paper trading on real exchange) --
    binance_testnet_key: str = Field(default="", alias="BINANCE_TESTNET_KEY")
    binance_testnet_secret: str = Field(default="", alias="BINANCE_TESTNET_SECRET")

    # -- CoinDCX API --
    coindcx_api_key: str = Field(default="", alias="COINDCX_API_KEY")
    coindcx_api_secret: str = Field(default="", alias="COINDCX_API_SECRET")

    # -- MetaTrader 5 (FundingPips) --
    mt5_login: str = Field(default="", alias="MT5_LOGIN")
    mt5_password: str = Field(default="", alias="MT5_PASSWORD")
    mt5_server: str = Field(default="", alias="MT5_SERVER")

    # -- Server --
    # SEC-02: Bind to localhost by default. Use reverse proxy for external access.
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)
    # SEC-01: API key for mutation endpoints. If empty, auth is disabled (dev mode).
    api_key: str = Field(default="", alias="API_KEY")
    db_url: str = Field(default="sqlite+aiosqlite:///./notas_lave.db")

    # -- Paper Trading --
    initial_balance: float = Field(default=100_000.0)          # USD (prop mode)
    initial_balance_inr: float = Field(default=1000.0,         # INR (personal mode)
                                       alias="INITIAL_BALANCE_INR")

    # CQ-16/OPS-16: Use absolute path to .env so it works regardless of cwd
    model_config = {
        "env_file": os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        "env_file_encoding": "utf-8",
    }

    @property
    def is_personal_mode(self) -> bool:
        return self.trading_mode == "personal"

    @property
    def active_instruments(self) -> list[str]:
        """Return instruments based on trading mode."""
        if self.is_personal_mode:
            return self.personal_instruments
        return self.instruments

    @property
    def active_balance(self) -> float:
        """Starting balance in the mode's currency (INR or USD)."""
        if self.is_personal_mode:
            return self.initial_balance_inr
        return self.initial_balance

    @property
    def active_balance_usd(self) -> float:
        """Starting balance converted to USD (for consistency)."""
        if self.is_personal_mode:
            return self.initial_balance_inr / self.usd_inr_rate
        return self.initial_balance

    @property
    def currency_symbol(self) -> str:
        return "INR" if self.is_personal_mode else "USD"

    @property
    def env_age_days(self) -> int | None:
        """SEC-15: Check how old the .env file is (for key rotation reminders)."""
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            mtime = os.path.getmtime(env_path)
            return int((datetime.now().timestamp() - mtime) / 86400)
        return None


def _check_env_permissions():
    """SEC-03: Warn if .env file has overly permissive permissions."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        mode = os.stat(env_path).st_mode
        if mode & stat.S_IROTH or mode & stat.S_IWOTH:  # World-readable or world-writable
            logger.warning("SECURITY: %s has permissive permissions (%s). Run: chmod 600 %s", env_path, oct(mode), env_path)


config = TradingConfig()
_check_env_permissions()
