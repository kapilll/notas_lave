"""
Configuration for the Notas Lave trading engine.

All settings are loaded from environment variables (.env file).
No secrets are ever hardcoded — this file only defines structure.

TRADING MODES:
- "prop": FundingPips challenge mode. USD, $100K balance, strict rules.
- "personal": Delta Exchange personal trading. USD, leverage.
  Set TRADING_MODE=personal in .env to switch.

Currency is always USD. No INR conversion.
"""

import logging
import os
import stat
from datetime import datetime

logger = logging.getLogger(__name__)
from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr


class TradingConfig(BaseSettings):
    """Core trading engine configuration."""

    # -- API Keys (loaded from .env) --
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    twelvedata_api_key: str = Field(default="", alias="TWELVEDATA_API_KEY")

    # -- Claude Settings --
    claude_provider: str = Field(default="vertex", alias="CLAUDE_PROVIDER")
    claude_model: str = Field(default="claude-sonnet-4-20250514")
    claude_max_tokens: int = Field(default=1024)
    claude_min_confidence: int = Field(default=7)
    google_cloud_project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_region: str = Field(default="us-east5", alias="GOOGLE_CLOUD_REGION")

    # -- Trade Autopsy (post-trade AI analysis) --
    autopsy_enabled: bool = Field(default=True, alias="AUTOPSY_ENABLED")
    autopsy_model: str = Field(default="claude-sonnet-4-6", alias="AUTOPSY_MODEL")
    autopsy_max_tokens: int = Field(default=512, alias="AUTOPSY_MAX_TOKENS")
    edge_analysis_model: str = Field(default="claude-sonnet-4-6", alias="EDGE_ANALYSIS_MODEL")
    edge_analysis_max_tokens: int = Field(default=1500, alias="EDGE_ANALYSIS_MAX_TOKENS")

    # -- Strategy Control --
    # Stored as plain str so pydantic-settings reads it without JSON-parsing.
    # Registry splits on commas at runtime. Both formats work:
    #   DISABLED_STRATEGIES=williams_system,trend_momentum,breakout_system
    #   DISABLED_STRATEGIES=["williams_system","trend_momentum","breakout_system"]
    disabled_strategies: str = Field(
        default="",
        alias="DISABLED_STRATEGIES",
    )

    # -- Telegram Alerts --
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # -- Trading Mode --
    # "prop" = FundingPips (USD, $100K, strict rules)
    # "personal" = Delta Exchange (USD, leverage, relaxed rules)
    trading_mode: str = Field(default="personal", alias="TRADING_MODE")

    # -- Leverage (personal mode) --
    leverage: float = Field(default=15.0, alias="LEVERAGE")

    # -- Instruments --
    instruments: list[str] = Field(
        default=["BTCUSD", "ETHUSD", "SOLUSD"]
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
    max_risk_per_trade_pct: float = Field(default=0.05)  # Must match RISK_PER_TRADE in lab.py
    max_concurrent_positions: int = Field(default=3)
    news_blackout_minutes: int = Field(default=5)

    # -- Risk Management (Personal mode / demo account) --
    # Lab engine risks 5% per trade (RISK_PER_TRADE). Set limits above that
    # so the Risk Manager doesn't block valid positions due to tight defaults.
    personal_risk_per_trade_pct: float = Field(default=0.10)   # allow up to 10% per trade
    personal_max_daily_dd_pct: float = Field(default=0.20)     # 20% daily DD (4 max losses/day)
    personal_max_total_dd_pct: float = Field(default=0.50)     # 50% total DD (demo, can reload)
    personal_max_concurrent: int = Field(default=5)

    # -- Confluence Scoring --
    min_confluence_score: float = Field(default=6.0)
    default_weights: dict[str, float] = Field(default={
        "scalping": 0.20, "ict": 0.20, "fibonacci": 0.20,
        "volume": 0.20, "breakout": 0.20,
    })

    # -- Broker Selection --
    broker: str = Field(default="delta_testnet", alias="BROKER")

    # -- Delta Exchange Testnet --
    delta_testnet_key: SecretStr = Field(default="", alias="DELTA_TESTNET_KEY")
    delta_testnet_secret: SecretStr = Field(default="", alias="DELTA_TESTNET_SECRET")
    delta_testnet_url: str = Field(
        default="https://cdn-ind.testnet.deltaex.org",
        alias="DELTA_TESTNET_URL",
    )

    # -- Server --
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_key: str = Field(default="", alias="API_KEY")
    db_url: str = Field(default="sqlite+aiosqlite:///./notas_lave.db")

    # -- Initial Balance (USD, used only for paper broker / prop mode) --
    initial_balance: float = Field(default=100_000.0, alias="INITIAL_BALANCE")

    # extra="ignore": don't fail on env vars that no longer have config fields
    model_config = {
        "env_file": os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def is_personal_mode(self) -> bool:
        return self.trading_mode == "personal"

    @property
    def active_instruments(self) -> list[str]:
        return self.instruments

    @property
    def env_age_days(self) -> int | None:
        """SEC-15: Check how old the .env file is (for key rotation reminders)."""
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
        if os.path.exists(env_path):
            mtime = os.path.getmtime(env_path)
            return int((datetime.now().timestamp() - mtime) / 86400)
        return None


def _check_env_permissions():
    """SEC-03: Warn if .env file has overly permissive permissions."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    if os.path.exists(env_path):
        mode = os.stat(env_path).st_mode
        if mode & stat.S_IROTH or mode & stat.S_IWOTH:
            logger.warning("SECURITY: %s has permissive permissions (%s). Run: chmod 600 %s", env_path, oct(mode), env_path)


def _check_db_permissions():
    """SE-23: Ensure SQLite databases are not world-readable."""
    engine_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    project_dir = os.path.dirname(engine_dir)
    for search_dir in [engine_dir, project_dir]:
        for db_name in ["notas_lave.db", "notas_lave_lab.db"]:
            db_path = os.path.join(search_dir, db_name)
            if os.path.exists(db_path):
                mode = os.stat(db_path).st_mode
                if mode & stat.S_IROTH or mode & stat.S_IWOTH:
                    try:
                        os.chmod(db_path, 0o600)
                        logger.info("SE-23: Fixed permissions on %s (was %s, now 0600)", db_path, oct(mode))
                    except OSError as e:
                        logger.warning("SE-23: Could not fix permissions on %s: %s", db_path, e)


config = TradingConfig()
_check_env_permissions()
_check_db_permissions()
