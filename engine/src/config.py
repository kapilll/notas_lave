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

    # -- Claude Settings --
    claude_model: str = Field(default="claude-sonnet-4-20250514")
    claude_max_tokens: int = Field(default=1024)
    # Minimum confidence (1-10) for Claude to approve a trade
    claude_min_confidence: int = Field(default=7)

    # -- Instruments we trade --
    instruments: list[str] = Field(
        default=["XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD"]
    )

    # -- Timeframes --
    # Entry timeframes (what we scan for setups)
    entry_timeframes: list[str] = Field(
        default=["1m", "5m", "15m", "30m", "1h"]
    )
    # Context timeframes (for trend direction and key levels)
    context_timeframes: list[str] = Field(default=["4h", "1d"])

    # -- Risk Management (FundingPips Rules) --
    max_daily_drawdown_pct: float = Field(default=0.05)  # 5%
    max_total_drawdown_pct: float = Field(default=0.10)  # 10%
    max_single_day_profit_pct: float = Field(default=0.45)  # 45% consistency rule
    min_risk_reward_ratio: float = Field(default=2.0)  # Minimum 2:1 R:R
    max_risk_per_trade_pct: float = Field(default=0.01)  # 1% risk per trade
    max_concurrent_positions: int = Field(default=3)
    news_blackout_minutes: int = Field(default=5)  # No trades 5 min around news

    # -- Confluence Scoring --
    min_confluence_score: float = Field(default=6.0)  # Minimum 6/10 to consider
    # Strategy gate weights (must sum to 1.0) — these shift with regime
    default_weights: dict[str, float] = Field(default={
        "ict": 0.25,
        "scalping": 0.25,
        "fibonacci": 0.25,
        "volume": 0.25,
    })

    # -- Server --
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    db_url: str = Field(default="sqlite+aiosqlite:///./notas_lave.db")

    # -- Paper Trading --
    initial_balance: float = Field(default=100_000.0)  # Simulated starting balance

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton config instance
config = TradingConfig()
