"""
Configuration for the Notas Lave trading engine.

All settings are loaded from environment variables (.env file).
No secrets are ever hardcoded — this file only defines structure.
"""

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

    # -- Instruments we trade --
    instruments: list[str] = Field(
        default=["XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD"]
    )

    # -- Timeframes --
    entry_timeframes: list[str] = Field(
        default=["1m", "5m", "15m", "30m", "1h"]
    )
    context_timeframes: list[str] = Field(default=["4h", "1d"])

    # -- Risk Management (FundingPips Rules) --
    max_daily_drawdown_pct: float = Field(default=0.05)
    max_total_drawdown_pct: float = Field(default=0.10)
    max_single_day_profit_pct: float = Field(default=0.45)
    min_risk_reward_ratio: float = Field(default=2.0)
    max_risk_per_trade_pct: float = Field(default=0.01)
    max_concurrent_positions: int = Field(default=3)
    news_blackout_minutes: int = Field(default=5)

    # -- Confluence Scoring --
    min_confluence_score: float = Field(default=6.0)
    default_weights: dict[str, float] = Field(default={
        "ict": 0.25, "scalping": 0.25, "fibonacci": 0.25, "volume": 0.25,
    })

    # -- Server --
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    db_url: str = Field(default="sqlite+aiosqlite:///./notas_lave.db")

    # -- Paper Trading --
    initial_balance: float = Field(default=100_000.0)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


config = TradingConfig()
