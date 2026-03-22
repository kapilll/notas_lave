"""Lab Engine Configuration -- aggressive settings for maximum learning."""

from dataclasses import dataclass, field


@dataclass
class LabConfig:
    """Lab is aggressive -- the goal is DATA, not capital preservation."""

    # Scanning -- higher timeframes that actually work
    scan_timeframes: list[str] = field(default_factory=lambda: ["15m", "1h", "4h"])
    scan_interval_seconds: int = 30  # Faster than production (60s)

    # Lab instruments -- scan MORE coins to find signals
    lab_instruments: list[str] = field(default_factory=lambda: [
        "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD",
        "DOGEUSD", "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD",
        "LTCUSD", "NEARUSD", "SUIUSD", "ARBUSD",
        "PEPEUSD", "WIFUSD", "FTMUSD", "ATOMUSD",
    ])

    # Trading -- accept more signals, execute on exchange
    min_score_to_trade: float = 3.0    # Production: 5.0
    min_rr_to_trade: float = 1.0       # Production: 2.0
    max_trades_per_day: int = 30       # Production: 6 — capped for exchange rate limits
    max_concurrent_positions: int = 8   # Production: 1 — 18 coins need more slots
    risk_per_trade_pct: float = 0.01   # 1% of demo balance (small, many trades)
    cooldown_seconds: int = 60         # Production: 300 — gives exchange time between orders

    # What to test
    use_blacklist: bool = False        # Test ALL strategies
    skip_volatile_regime: bool = False  # Test in ALL regimes

    # Learning
    auto_backtest_hours: int = 6       # Run backtester every N hours
    auto_optimize_hours: int = 12      # Run optimizer every N hours
    daily_review_hour: int = 22        # Claude review at 22:00 UTC

    # Notifications
    telegram_prefix: str = "[LAB]"

    def to_dict(self) -> dict:
        return {
            "mode": "lab",
            "scan_timeframes": self.scan_timeframes,
            "instruments": self.lab_instruments,
            "min_score": self.min_score_to_trade,
            "min_rr": self.min_rr_to_trade,
            "max_trades_per_day": self.max_trades_per_day,
            "max_concurrent": self.max_concurrent_positions,
            "risk_per_trade": self.risk_per_trade_pct,
            "use_blacklist": self.use_blacklist,
        }


lab_config = LabConfig()
