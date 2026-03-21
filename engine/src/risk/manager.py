"""
Risk Manager — the final gatekeeper before any trade executes.

This module enforces FundingPips prop firm rules as HARD constraints.
No trade can bypass this. Even if Claude says "BUY with confidence 10",
if it violates a risk rule, it gets BLOCKED.

Think of this as the seat belt that can never be unbuckled.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from ..data.models import TradeSetup, TradeStatus, Direction
from ..data.instruments import get_instrument
from ..data.economic_calendar import is_in_blackout
from ..config import config


@dataclass
class DailyStats:
    """Tracks P&L and risk metrics for the current trading day."""
    date: date = field(default_factory=date.today)
    realized_pnl: float = 0.0         # Total P&L closed today
    unrealized_pnl: float = 0.0       # Current open position P&L
    num_trades: int = 0                # Trades executed today
    open_positions: int = 0            # Currently open positions
    peak_equity: float = 0.0           # Highest equity today
    trough_equity: float = 0.0        # Lowest equity today
    is_trading_halted: bool = False    # True if daily loss limit hit


class RiskManager:
    """
    Enforces all prop firm risk rules.

    Rules enforced:
    1. Max daily drawdown: 5% of starting balance
    2. Max total drawdown: 10% of starting balance
    3. Consistency rule: No single day > 45% of total profits
    4. Min risk:reward ratio: 2:1
    5. Max risk per trade: 1% of account
    6. Max concurrent positions: 3
    7. News blackout: No trades 5 min around high-impact news
    """

    def __init__(self, starting_balance: float | None = None):
        self.starting_balance = starting_balance or config.initial_balance
        self.current_balance = self.starting_balance
        self.total_pnl = 0.0
        self.daily_stats: dict[date, DailyStats] = {}
        self.peak_balance = self.starting_balance

        # Fix #8: Restore state from DB if available
        try:
            from ..journal.database import load_risk_state
            saved = load_risk_state()
            if saved:
                self.starting_balance = saved["starting_balance"]
                self.current_balance = saved["current_balance"]
                self.total_pnl = saved["total_pnl"]
                self.peak_balance = saved["peak_balance"]
        except Exception:
            pass  # First run — no saved state yet

    def _get_today_stats(self) -> DailyStats:
        """Get or create today's stats."""
        today = date.today()
        if today not in self.daily_stats:
            self.daily_stats[today] = DailyStats(
                date=today,
                peak_equity=self.current_balance,
                trough_equity=self.current_balance,
            )
        return self.daily_stats[today]

    def validate_trade(self, setup: TradeSetup) -> tuple[bool, list[str]]:
        """
        Validate a trade setup against ALL risk rules.

        Returns:
            (is_valid, list_of_reasons_if_rejected)

        If ANY rule fails, the trade is rejected. No exceptions.
        """
        rejections: list[str] = []
        today = self._get_today_stats()

        # Rule 1: Daily drawdown limit (5%)
        max_daily_loss = self.starting_balance * config.max_daily_drawdown_pct
        potential_loss = abs(setup.entry_price - setup.stop_loss) * setup.position_size
        if today.realized_pnl - potential_loss < -max_daily_loss:
            rejections.append(
                f"DAILY DRAWDOWN: Adding this trade could breach 5% daily limit. "
                f"Today P&L: ${today.realized_pnl:.2f}, Potential loss: ${potential_loss:.2f}, "
                f"Max allowed: -${max_daily_loss:.2f}"
            )

        # Rule 2: Total drawdown limit (10%)
        max_total_loss = self.starting_balance * config.max_total_drawdown_pct
        if self.total_pnl - potential_loss < -max_total_loss:
            rejections.append(
                f"TOTAL DRAWDOWN: Would breach 10% total limit. "
                f"Total P&L: ${self.total_pnl:.2f}, Max allowed: -${max_total_loss:.2f}"
            )

        # Rule 3: Trading halted for the day
        if today.is_trading_halted:
            rejections.append("HALTED: Trading is halted for today (daily loss limit reached)")

        # Rule 4: Risk:Reward ratio minimum (2:1)
        if setup.risk_reward_ratio < config.min_risk_reward_ratio:
            rejections.append(
                f"R:R TOO LOW: {setup.risk_reward_ratio:.1f}:1, "
                f"minimum required: {config.min_risk_reward_ratio:.1f}:1"
            )

        # Rule 5: Max risk per trade (1%)
        max_risk_amount = self.current_balance * config.max_risk_per_trade_pct
        if potential_loss > max_risk_amount:
            rejections.append(
                f"POSITION TOO LARGE: Risk ${potential_loss:.2f} exceeds 1% limit "
                f"(${max_risk_amount:.2f})"
            )

        # Rule 6: Max concurrent positions
        if today.open_positions >= config.max_concurrent_positions:
            rejections.append(
                f"MAX POSITIONS: Already have {today.open_positions} open "
                f"(max {config.max_concurrent_positions})"
            )

        # Rule 7: Stop loss must be on correct side
        if setup.direction == Direction.LONG:
            if setup.stop_loss >= setup.entry_price:
                rejections.append("INVALID SL: Stop loss above entry for a LONG trade")
            if setup.take_profit <= setup.entry_price:
                rejections.append("INVALID TP: Take profit below entry for a LONG trade")
        elif setup.direction == Direction.SHORT:
            if setup.stop_loss <= setup.entry_price:
                rejections.append("INVALID SL: Stop loss below entry for a SHORT trade")
            if setup.take_profit >= setup.entry_price:
                rejections.append("INVALID TP: Take profit above entry for a SHORT trade")

        # Rule 8: News blackout — no trades near high-impact events
        blocked, event = is_in_blackout(
            datetime.now(timezone.utc),
            blackout_minutes=config.news_blackout_minutes,
        )
        if blocked and event:
            rejections.append(
                f"NEWS BLACKOUT: {event.name} at {event.dt.strftime('%H:%M UTC')}. "
                f"No trading within {config.news_blackout_minutes} min of high-impact news."
            )

        # Rule 9: Consistency rule check (45%)
        # Only matters on funded accounts, but we enforce from the start to build habit
        if self.total_pnl > 0:
            max_single_day = self.total_pnl * config.max_single_day_profit_pct
            if today.realized_pnl > max_single_day * 0.8:  # Warn at 80% of limit
                rejections.append(
                    f"CONSISTENCY WARNING: Today's profit (${today.realized_pnl:.2f}) "
                    f"approaching 45% of total profits. Consider smaller positions."
                )

        is_valid = len(rejections) == 0
        return is_valid, rejections

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        symbol: str,
    ) -> float:
        """
        Calculate position size using proper instrument specifications.

        Uses contract_size to convert price risk into dollar risk per lot,
        then determines how many lots fit within our risk budget.

        Example (Gold XAUUSD, $100K account, 1% risk, $5 SL):
        - Risk budget: $100,000 * 0.01 = $1,000
        - Contract size: 100 oz per lot
        - Loss per lot if SL hit: $5 * 100 = $500
        - Position size: $1,000 / $500 = 2.0 lots
        """
        spec = get_instrument(symbol)
        return spec.calculate_position_size(
            entry=entry_price,
            stop_loss=stop_loss,
            account_balance=self.current_balance,
            risk_pct=config.max_risk_per_trade_pct,
        )

    def record_trade_result(self, pnl: float):
        """Record a completed trade's P&L and persist state (Fix #8)."""
        today = self._get_today_stats()
        today.realized_pnl += pnl
        today.num_trades += 1
        self.total_pnl += pnl
        self.current_balance += pnl

        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

        max_daily_loss = self.starting_balance * config.max_daily_drawdown_pct
        if today.realized_pnl <= -max_daily_loss:
            today.is_trading_halted = True

        # Persist to DB so state survives restart
        try:
            from ..journal.database import save_risk_state
            save_risk_state(
                self.starting_balance, self.current_balance,
                self.total_pnl, self.peak_balance,
            )
        except Exception:
            pass

    def get_status(self) -> dict:
        """Get current risk status for the dashboard."""
        today = self._get_today_stats()
        max_daily_loss = self.starting_balance * config.max_daily_drawdown_pct
        max_total_loss = self.starting_balance * config.max_total_drawdown_pct

        return {
            "balance": round(self.current_balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round((self.total_pnl / self.starting_balance) * 100, 2),
            "daily_pnl": round(today.realized_pnl, 2),
            "daily_drawdown_used_pct": round(
                (abs(min(today.realized_pnl, 0)) / max_daily_loss) * 100, 1
            ),
            "total_drawdown_used_pct": round(
                (abs(min(self.total_pnl, 0)) / max_total_loss) * 100, 1
            ),
            "trades_today": today.num_trades,
            "open_positions": today.open_positions,
            "is_halted": today.is_trading_halted,
            "can_trade": not today.is_trading_halted and today.open_positions < config.max_concurrent_positions,
        }


# Singleton instance
risk_manager = RiskManager()
