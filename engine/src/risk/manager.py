"""
Risk Manager — the final gatekeeper before any trade executes.

TWO MODES:
- PROP MODE: FundingPips rules — strict, no exceptions, designed to pass challenges
- PERSONAL MODE: Your own money — still disciplined, but no artificial constraints
  like consistency rules or mandatory news blackouts

The core principle is the same in both modes: protect capital.
But the RULES are different because the GOALS are different.

Prop firm: "Don't break their rules or you lose the account"
Personal: "Don't blow up, maximize risk-adjusted returns"
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
    date: date = field(default_factory=lambda: datetime.now(timezone.utc).date())
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    num_trades: int = 0
    open_positions: int = 0
    peak_equity: float = 0.0
    trough_equity: float = 0.0
    is_trading_halted: bool = False


class RiskManager:
    """
    Mode-aware risk manager.

    PROP MODE rules (FundingPips):
    1. Max daily drawdown: 5%
    2. Max total drawdown: 10% (static from starting balance)
    3. Consistency rule: No single day > 45% of total profits
    4. Min R:R ratio: 2:1
    5. Max risk per trade: 1%
    6. Max concurrent positions: 3
    7. News blackout: mandatory 5 min around high-impact
    8. SL/TP validation

    PERSONAL MODE rules:
    1. Max daily drawdown: configurable (default 6%)
    2. Max total drawdown: configurable (default 20%)
    3. NO consistency rule (it's your money)
    4. Min R:R ratio: 1.5:1 (more flexible)
    5. Max risk per trade: configurable (default 2%)
    6. Max concurrent positions: configurable (default 2)
    7. News blackout: optional (configurable, default OFF)
    8. SL/TP validation (always on — this is basic sanity)
    """

    def __init__(self, starting_balance: float | None = None):
        self.starting_balance = starting_balance or (
            config.active_balance_usd if config.is_personal_mode else config.initial_balance
        )
        self.current_balance = self.starting_balance
        self.total_pnl = 0.0
        self.daily_stats: dict[date, DailyStats] = {}
        self.peak_balance = self.starting_balance

        # Only load persisted state if no explicit balance was provided
        # (tests pass explicit balances and shouldn't be overwritten by DB)
        if starting_balance is None:
            try:
                from ..journal.database import load_risk_state
                saved = load_risk_state()
                if saved:
                    self.starting_balance = saved["starting_balance"]
                    self.current_balance = saved["current_balance"]
                    self.total_pnl = saved["total_pnl"]
                    self.peak_balance = saved["peak_balance"]
            except Exception:
                pass

    @property
    def _is_prop(self) -> bool:
        return not config.is_personal_mode

    @property
    def _max_daily_dd(self) -> float:
        return config.max_daily_drawdown_pct if self._is_prop else config.personal_max_daily_dd_pct

    @property
    def _max_total_dd(self) -> float:
        return config.max_total_drawdown_pct if self._is_prop else config.personal_max_total_dd_pct

    @property
    def _max_risk_per_trade(self) -> float:
        return config.max_risk_per_trade_pct if self._is_prop else config.personal_risk_per_trade_pct

    @property
    def _max_concurrent(self) -> int:
        return config.max_concurrent_positions if self._is_prop else config.personal_max_concurrent

    @property
    def _min_rr(self) -> float:
        return config.min_risk_reward_ratio if self._is_prop else 1.5

    def _get_today_stats(self) -> DailyStats:
        today = datetime.now(timezone.utc).date()
        if today not in self.daily_stats:
            self.daily_stats[today] = DailyStats(
                date=today,
                peak_equity=self.current_balance,
                trough_equity=self.current_balance,
            )
        return self.daily_stats[today]

    def validate_trade(self, setup: TradeSetup) -> tuple[bool, list[str]]:
        """
        Validate a trade against risk rules.
        Rules applied depend on trading mode (prop vs personal).
        """
        rejections: list[str] = []
        today = self._get_today_stats()
        potential_loss = abs(setup.entry_price - setup.stop_loss) * setup.position_size

        # UNIVERSAL: Daily drawdown limit
        max_daily_loss = self.starting_balance * self._max_daily_dd
        if today.realized_pnl - potential_loss < -max_daily_loss:
            rejections.append(
                f"DAILY DRAWDOWN: Would breach {self._max_daily_dd*100:.0f}% limit. "
                f"Today P&L: ${today.realized_pnl:.2f}, Max loss: -${max_daily_loss:.2f}"
            )

        # UNIVERSAL: Total drawdown limit
        max_total_loss = self.starting_balance * self._max_total_dd
        if self.total_pnl - potential_loss < -max_total_loss:
            rejections.append(
                f"TOTAL DRAWDOWN: Would breach {self._max_total_dd*100:.0f}% limit. "
                f"Total P&L: ${self.total_pnl:.2f}, Max loss: -${max_total_loss:.2f}"
            )

        # UNIVERSAL: Trading halted for the day
        if today.is_trading_halted:
            rejections.append("HALTED: Trading halted for today (daily loss limit hit)")

        # UNIVERSAL: R:R ratio minimum
        if setup.risk_reward_ratio < self._min_rr:
            rejections.append(
                f"R:R TOO LOW: {setup.risk_reward_ratio:.1f}:1, min {self._min_rr:.1f}:1"
            )

        # UNIVERSAL: Max risk per trade
        max_risk_amount = self.current_balance * self._max_risk_per_trade
        if potential_loss > max_risk_amount:
            rejections.append(
                f"POSITION TOO LARGE: Risk ${potential_loss:.2f} exceeds "
                f"{self._max_risk_per_trade*100:.1f}% limit (${max_risk_amount:.2f})"
            )

        # UNIVERSAL: Max concurrent positions
        if today.open_positions >= self._max_concurrent:
            rejections.append(
                f"MAX POSITIONS: {today.open_positions} open (max {self._max_concurrent})"
            )

        # UNIVERSAL: SL/TP on correct side
        if setup.direction == Direction.LONG:
            if setup.stop_loss >= setup.entry_price:
                rejections.append("INVALID SL: Stop loss above entry for LONG")
            if setup.take_profit <= setup.entry_price:
                rejections.append("INVALID TP: Take profit below entry for LONG")
        elif setup.direction == Direction.SHORT:
            if setup.stop_loss <= setup.entry_price:
                rejections.append("INVALID SL: Stop loss below entry for SHORT")
            if setup.take_profit >= setup.entry_price:
                rejections.append("INVALID TP: Take profit above entry for SHORT")

        # PROP ONLY: News blackout (mandatory for FundingPips funded accounts)
        if self._is_prop:
            blocked, event = is_in_blackout(
                datetime.now(timezone.utc),
                blackout_minutes=config.news_blackout_minutes,
            )
            if blocked and event:
                rejections.append(
                    f"NEWS BLACKOUT: {event.name} at {event.dt.strftime('%H:%M UTC')}. "
                    f"No trading within {config.news_blackout_minutes} min (prop rule)."
                )

        # PROP ONLY: Consistency rule (45% — funded accounts)
        if self._is_prop and self.total_pnl > 0:
            max_single_day = self.total_pnl * config.max_single_day_profit_pct
            if today.realized_pnl > max_single_day * 0.8:
                rejections.append(
                    f"CONSISTENCY: Today profit ${today.realized_pnl:.2f} approaching "
                    f"45% of total (${max_single_day:.2f}). Prop firm rule."
                )

        return len(rejections) == 0, rejections

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        symbol: str,
    ) -> float:
        """Calculate position size using mode-appropriate risk percentage."""
        spec = get_instrument(symbol)
        leverage = config.leverage if config.is_personal_mode else 1.0
        return spec.calculate_position_size(
            entry=entry_price,
            stop_loss=stop_loss,
            account_balance=self.current_balance,
            risk_pct=self._max_risk_per_trade,
            leverage=leverage,
        )

    def record_trade_result(self, pnl: float):
        """Record a completed trade's P&L and persist state."""
        today = self._get_today_stats()
        today.realized_pnl += pnl
        today.num_trades += 1
        self.total_pnl += pnl
        self.current_balance += pnl

        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

        max_daily_loss = self.starting_balance * self._max_daily_dd
        if today.realized_pnl <= -max_daily_loss:
            today.is_trading_halted = True

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
        max_daily_loss = self.starting_balance * self._max_daily_dd
        max_total_loss = self.starting_balance * self._max_total_dd

        return {
            "mode": "prop" if self._is_prop else "personal",
            "balance": round(self.current_balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round((self.total_pnl / self.starting_balance) * 100, 2),
            "daily_pnl": round(today.realized_pnl, 2),
            "daily_drawdown_used_pct": round(
                (abs(min(today.realized_pnl, 0)) / max(max_daily_loss, 0.01)) * 100, 1
            ),
            "total_drawdown_used_pct": round(
                (abs(min(self.total_pnl, 0)) / max(max_total_loss, 0.01)) * 100, 1
            ),
            "trades_today": today.num_trades,
            "open_positions": today.open_positions,
            "is_halted": today.is_trading_halted,
            "can_trade": not today.is_trading_halted and today.open_positions < self._max_concurrent,
            "limits": {
                "max_daily_dd": f"{self._max_daily_dd*100:.0f}%",
                "max_total_dd": f"{self._max_total_dd*100:.0f}%",
                "max_risk_per_trade": f"{self._max_risk_per_trade*100:.1f}%",
                "max_concurrent": self._max_concurrent,
                "min_rr": self._min_rr,
                "news_blackout": self._is_prop,
                "consistency_rule": self._is_prop,
            },
        }


    def get_personal_recommendations(self) -> dict:
        """
        Smart recommendations for personal trading mode.

        Unlike prop mode (which just enforces rules), personal mode should
        actively help you make MORE money with LESS risk. These recommendations
        adapt based on your actual performance.
        """
        if self._is_prop:
            return {"mode": "prop", "message": "Prop mode uses fixed rules, no adaptive recommendations."}

        today = self._get_today_stats()
        recs = []

        # Winning streak → slightly increase risk
        if today.num_trades >= 3 and today.realized_pnl > 0:
            win_rate_today = today.realized_pnl / max(today.num_trades, 1)
            if win_rate_today > 0:
                recs.append({
                    "type": "risk_up",
                    "message": f"Winning day (${today.realized_pnl:.2f}). Consider maintaining current risk level.",
                    "priority": "low",
                })

        # Losing day → reduce risk
        daily_dd_used = abs(min(today.realized_pnl, 0)) / max(self.starting_balance * self._max_daily_dd, 0.01) * 100
        if daily_dd_used > 50:
            recs.append({
                "type": "risk_down",
                "message": f"Daily drawdown at {daily_dd_used:.0f}% of limit. Reduce position size or stop trading today.",
                "priority": "high",
            })

        # Account growing → could increase base risk
        growth_pct = (self.current_balance - self.starting_balance) / self.starting_balance * 100
        if growth_pct > 10:
            recs.append({
                "type": "scale_up",
                "message": f"Account up {growth_pct:.1f}%. Consider increasing starting_balance to lock in gains.",
                "priority": "medium",
            })

        # Account shrinking → defensive mode
        if growth_pct < -10:
            recs.append({
                "type": "defensive",
                "message": f"Account down {abs(growth_pct):.1f}%. Consider halving risk per trade until recovery.",
                "priority": "high",
            })

        # No trades today → market might be quiet
        if today.num_trades == 0:
            recs.append({
                "type": "patience",
                "message": "No trades today. Quality setups only — don't force trades.",
                "priority": "low",
            })

        return {
            "mode": "personal",
            "account_growth_pct": round(growth_pct, 1),
            "daily_dd_used_pct": round(daily_dd_used, 1),
            "trades_today": today.num_trades,
            "recommendations": recs,
            "active_limits": {
                "risk_per_trade": f"{self._max_risk_per_trade*100:.1f}%",
                "daily_dd": f"{self._max_daily_dd*100:.0f}%",
                "total_dd": f"{self._max_total_dd*100:.0f}%",
                "max_concurrent": self._max_concurrent,
                "min_rr": self._min_rr,
                "leverage": config.leverage if config.is_personal_mode else 1.0,
            },
        }


# Singleton instance
risk_manager = RiskManager()
