"""
Agent Configuration — defines what the autonomous trader can and cannot do.

THE PHILOSOPHY:
The human (Kapil) is the OVERSEER. Claude is the TRADER.
The system runs 24/7 without human intervention.
The human reviews performance and sets boundaries.
The agent operates within those boundaries autonomously.

PERMISSION LEVELS:
1. FULL_AUTO: Agent does everything — paper trade, learn, adjust, evolve
2. SEMI_AUTO: Agent trades and learns, but human approves strategy changes
3. ALERT_ONLY: Agent only sends alerts, human places all trades (current mode)

SAFETY BOUNDARIES (NEVER overridden, even by Claude):
- Risk per trade capped at max_risk_pct (never exceeded)
- Daily loss limit halts all trading (no override)
- Total drawdown halts all trading (no override)
- Real money trades ALWAYS require human confirmation
- Core strategy code cannot be modified at runtime

WHAT THE AGENT CAN DO (paper mode):
- Scan markets and generate signals
- Auto-execute paper trades on qualifying signals
- Monitor and close positions (SL/TP/breakeven)
- Analyze every closed trade (why win/loss)
- Update strategy blacklists based on performance
- Adjust confluence weights based on learning engine
- Retune parameters via walk-forward optimizer
- Send Telegram reports of what it did and learned

WHAT THE AGENT CANNOT DO:
- Place real money trades (requires BROKER != paper + human approval)
- Override risk limits (hardcoded, not configurable by agent)
- Modify strategy source code at runtime
- Disable the learning/journaling system
- Exceed position size limits
"""

from dataclasses import dataclass
from enum import Enum


class AgentMode(str, Enum):
    FULL_AUTO = "full_auto"    # Agent does everything (paper trading)
    SEMI_AUTO = "semi_auto"    # Agent trades, human approves changes
    ALERT_ONLY = "alert_only"  # Agent only sends alerts (legacy co-pilot)


@dataclass
class AgentConfig:
    """
    Boundaries for the autonomous trading agent.

    These define what the agent CAN and CANNOT do.
    The human sets these once, then the agent operates within them.
    """
    # Operating mode
    mode: AgentMode = AgentMode.FULL_AUTO

    # --- Trading permissions ---
    can_auto_paper_trade: bool = True       # Auto-execute on paper
    can_auto_live_trade: bool = False        # NEVER True without human override
    min_score_to_trade: float = 50.0        # Minimum confluence score to auto-trade
    min_rr_to_trade: float = 2.0            # Minimum risk:reward ratio

    # --- Learning permissions ---
    can_analyze_trades: bool = True          # Claude analyzes each closed trade
    can_update_blacklists: bool = True       # Auto-disable failing strategies
    can_adjust_weights: bool = True          # Auto-tune confluence weights
    can_run_optimizer: bool = True           # Auto-run parameter optimization

    # --- Safety boundaries (NEVER overridden) ---
    max_risk_per_trade_pct: float = 0.003   # 0.3% max risk per trade
    max_daily_loss_pct: float = 0.04        # 4% daily halt
    max_total_dd_pct: float = 0.08          # 8% total halt
    max_concurrent_positions: int = 1        # 1 position at a time
    max_trades_per_day: int = 6             # Don't overtrade
    # AT-21: For small accounts (<$100), set max_trades_per_day to 2-3
    # to avoid overtrading — commissions and spread eat into thin margins fast.

    # --- Scanning ---
    scan_interval_seconds: int = 60         # How often to scan markets
    scan_timeframes: list[str] = None       # Which timeframes to scan

    # --- Learning schedule ---
    learn_after_every_trade: bool = True     # Claude analyzes each trade
    daily_review: bool = True               # Daily performance summary
    weekly_optimizer: bool = True           # Weekly parameter retuning
    weekly_report: bool = True              # Weekly Telegram report

    # --- Notification preferences ---
    notify_on_trade_open: bool = True       # Telegram on trade open
    notify_on_trade_close: bool = True      # Telegram on trade close
    notify_on_blacklist_change: bool = True  # Telegram when strategy disabled
    notify_on_weight_change: bool = True     # Telegram when weights adjusted
    notify_daily_summary: bool = True       # Daily P&L summary

    def __post_init__(self):
        if self.scan_timeframes is None:
            self.scan_timeframes = ["5m", "15m", "1h"]

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "can_auto_paper_trade": self.can_auto_paper_trade,
            "can_auto_live_trade": self.can_auto_live_trade,
            "min_score_to_trade": self.min_score_to_trade,
            "safety": {
                "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
                "max_daily_loss_pct": self.max_daily_loss_pct,
                "max_total_dd_pct": self.max_total_dd_pct,
                "max_concurrent": self.max_concurrent_positions,
                "max_trades_per_day": self.max_trades_per_day,
            },
            "learning": {
                "after_every_trade": self.learn_after_every_trade,
                "daily_review": self.daily_review,
                "weekly_optimizer": self.weekly_optimizer,
            },
        }


# Singleton — the active agent configuration
agent_config = AgentConfig()
