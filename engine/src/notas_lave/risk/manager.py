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

import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timezone

logger = logging.getLogger(__name__)
from ..data.models import TradeSetup, TradeStatus, Direction
from ..data.instruments import get_instrument
from ..data.economic_calendar import is_in_blackout
from ..config import config

# RC-21: Weight and blacklist guardrails — documented constants.
# Strategy confluence weights must stay within these bounds.
# The learning engine (recommendations.py) clamps weights to this range.
WEIGHT_BOUNDS = (0.05, 0.50)
# Maximum number of strategies that can be blacklisted per week.
# Prevents the learning engine from blacklisting everything after a bad week.
MAX_BLACKLIST_GROWTH_PER_WEEK = 3

# RC-19: Minimum trade duration threshold (seconds).
# Trades shorter than this are flagged as HFT-like behavior.
# FundingPips forbids HFT — callers should log/alert on violations.
MIN_TRADE_DURATION_SECONDS = 60


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
    3. Consistency rule: No single day > 45% of total profits (HARD BLOCK)
    4. Min R:R ratio: 2:1
    5. Max risk per trade: 1%
    6. Max concurrent positions: 3
    7. News blackout: mandatory 5 min around high-impact
    8. SL/TP validation
    9. No hedging (opposing positions on same symbol)

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
        self.starting_balance = starting_balance or config.initial_balance
        # RC-04 FIX: Original starting balance is set ONCE and NEVER modified.
        # FundingPips total drawdown is STATIC from the challenge's initial balance.
        # If the account grows from $100K to $110K, the 10% DD floor is still $90K.
        self.original_starting_balance = self.starting_balance
        self.current_balance = self.starting_balance
        self.total_pnl = 0.0
        self.daily_stats: dict[date, DailyStats] = {}
        self.peak_balance = self.starting_balance
        # RC-11: Track last trade date for inactivity rule (FundingPips 30-day limit)
        self.last_trade_date: date | None = None

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
                    # RC-04: original_starting_balance stays as initially set — NEVER overwritten
            except Exception as e:
                logger.debug("Non-critical error loading risk state: %s", e)

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
            # RC-12 FIX: When rolling over to a new day, carry forward the
            # open_positions count from the previous day so it doesn't reset to 0.
            # Without this, if you have 2 positions open at midnight, the new day
            # would show 0 open positions and allow opening beyond the limit.
            yesterday_open = 0
            yesterday_unrealized = 0.0
            if self.daily_stats:
                latest_date = max(self.daily_stats.keys())
                yesterday_open = self.daily_stats[latest_date].open_positions
                # RC-18 FIX: Carry forward unrealized P&L at rollover.
                # If we have open positions at midnight, the new day's equity
                # tracking should start from balance + unrealized, not just balance.
                yesterday_unrealized = self.daily_stats[latest_date].unrealized_pnl
            initial_equity = self.current_balance + yesterday_unrealized
            self.daily_stats[today] = DailyStats(
                date=today,
                peak_equity=initial_equity,
                trough_equity=initial_equity,
                open_positions=yesterday_open,
            )
        return self.daily_stats[today]

    def update_unrealized_pnl(self, unrealized: float):
        """
        RC-03 FIX: Update unrealized P&L from open positions.
        Called by the autonomous trader every tick to keep equity tracking current.
        FundingPips monitors EQUITY (balance + unrealized), not just closed P&L.
        """
        today = self._get_today_stats()
        today.unrealized_pnl = unrealized

    def _check_hedging(
        self, symbol: str, direction: str, open_positions: dict | None = None
    ) -> bool:
        """
        RC-05 FIX: Detect hedging — opposing positions on the same symbol.

        FundingPips explicitly forbids hedging. If you have a LONG on XAUUSD,
        you cannot open a SHORT on XAUUSD (and vice versa).

        Args:
            symbol: The instrument to trade.
            direction: "LONG" or "SHORT".
            open_positions: Dict of {symbol: direction_str} for currently open positions.
                            If None, hedging check is skipped (no position data available).

        Returns:
            True if this trade would create a hedge (should be REJECTED).
        """
        if open_positions is None:
            return False

        if symbol in open_positions:
            existing_direction = open_positions[symbol]
            # If existing position is opposite direction, this is hedging
            if existing_direction != direction:
                return True
        return False

    def validate_trade(
        self, setup: TradeSetup, open_positions: dict | None = None,
    ) -> tuple[bool, list[str]]:
        """
        Validate a trade against risk rules.
        Rules applied depend on trading mode (prop vs personal).

        Args:
            setup: The trade setup to validate.
            open_positions: Optional dict of {symbol: direction_str} for hedging check.
                            Pass this from the position tracker if available.
        """
        rejections: list[str] = []
        today = self._get_today_stats()

        # AT-36 FIX: Include contract_size in potential loss calculation.
        # Gold has contract_size=100 (100 oz/lot), so without this,
        # potential_loss is understated by 100x for metals.
        spec = get_instrument(setup.symbol)
        contract_size = spec.contract_size if spec else 1.0
        potential_loss = abs(setup.entry_price - setup.stop_loss) * setup.position_size * contract_size

        # RC-03 FIX: Daily drawdown must include unrealized (floating) P&L.
        # FundingPips monitors equity in real-time, not just closed trades.
        current_equity_dd = today.realized_pnl + today.unrealized_pnl
        max_daily_loss = self.starting_balance * self._max_daily_dd
        if current_equity_dd - potential_loss < -max_daily_loss:
            rejections.append(
                f"DAILY DRAWDOWN: Would breach {self._max_daily_dd*100:.0f}% limit. "
                f"Today P&L (realized+unrealized): ${current_equity_dd:.2f}, "
                f"Potential loss: ${potential_loss:.2f}, Max loss: -${max_daily_loss:.2f}"
            )

        # RC-04 FIX: Total drawdown uses original_starting_balance (static).
        # FundingPips 10% drawdown is measured from the ORIGINAL balance, not
        # from peak or current balance.
        max_total_loss = self.original_starting_balance * self._max_total_dd
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

        # RC-02 FIX: Consistency rule — HARD BLOCK at 100% of 45% threshold (prop only).
        # Previously this was only a soft warning at 80%. FundingPips will fail your
        # challenge if any single day accounts for >45% of total profits. This MUST
        # be a hard block, not a warning.
        #
        # RC-22 FIX: Only enforce when total_pnl exceeds 1% of starting balance.
        # Right after drawdown recovery, total_pnl might be $5 on a $100K account.
        # Any decent day ($3+) would trigger >45%, blocking trades unnecessarily.
        # FundingPips applies consistency to meaningful profit accumulation, not noise.
        consistency_threshold = self.starting_balance * 0.01
        if self._is_prop and self.total_pnl > consistency_threshold:
            max_single_day = self.total_pnl * config.max_single_day_profit_pct
            # Hard block at 100% — if today's profit already >= 45% of total, STOP
            if today.realized_pnl >= max_single_day:
                rejections.append(
                    f"CONSISTENCY BLOCK: Today profit ${today.realized_pnl:.2f} has reached "
                    f"45% of total profits (${max_single_day:.2f}). "
                    f"Trading BLOCKED for today (prop firm rule)."
                )
            # Soft warning at 80% — informational only, does NOT block the trade
            elif today.realized_pnl > max_single_day * 0.8:
                logger.warning("CONSISTENCY: Today profit $%.2f approaching 45%% of total ($%.2f). "
                               "Consider stopping for the day.", today.realized_pnl, max_single_day)
            # RC-F05 FIX: Soft warning if a winning trade COULD push past consistency limit.
            # This does NOT block — it warns the trader before they take the trade.
            else:
                potential_win = abs(setup.take_profit - setup.entry_price) * setup.position_size * contract_size
                if today.realized_pnl + potential_win > max_single_day:
                    logger.warning("CONSISTENCY (potential): If this trade wins (+$%.2f), "
                                   "today's profit ($%.2f) would exceed 45%% of total profits ($%.2f). "
                                   "Consider the consistency rule before proceeding.",
                                   potential_win, today.realized_pnl + potential_win, max_single_day)

        # RC-05 FIX: No hedging allowed in prop mode.
        # FundingPips explicitly forbids hedging (opposing positions on same symbol).
        # RC-24 FIX: In personal mode, warn but don't block. With leverage (e.g. 15x),
        # holding opposing positions means paying funding rates on both sides — a
        # guaranteed loss. We log the warning but let the trade proceed.
        if self._check_hedging(setup.symbol, setup.direction.value, open_positions):
            if self._is_prop:
                rejections.append(
                    f"HEDGING BLOCKED: Opposing position already open on {setup.symbol}. "
                    f"FundingPips forbids hedging."
                )
            else:
                logger.warning("HEDGING WARNING (personal): Opposing position on %s. "
                               "With leverage, you pay funding on both sides (guaranteed loss). "
                               "Trade allowed — it's your money.", setup.symbol)

        # RC-14 FIX: Audit trail — log every validation result.
        # This creates a traceable record of every trade decision for review.
        passed = len(rejections) == 0
        if passed:
            logger.info("RISK PASS: %s %s size=%s entry=%s sl=%s tp=%s potential_loss=$%.2f",
                         setup.symbol, setup.direction.value, setup.position_size,
                         setup.entry_price, setup.stop_loss, setup.take_profit, potential_loss)
        else:
            logger.warning("RISK REJECT: %s %s size=%s entry=%s reasons=%s",
                            setup.symbol, setup.direction.value, setup.position_size,
                            setup.entry_price, rejections)

        return passed, rejections

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

        # RC-11: Track last trade date for inactivity monitoring
        self.last_trade_date = datetime.now(timezone.utc).date()

        # RC-F07 FIX: Daily halt must include unrealized (floating) P&L.
        # FundingPips monitors equity, not just realized. If realized + unrealized
        # breaches the limit, trading must halt even if some positions are still open.
        max_daily_loss = self.starting_balance * self._max_daily_dd
        if (today.realized_pnl + today.unrealized_pnl) <= -max_daily_loss:
            today.is_trading_halted = True

        try:
            from ..journal.database import save_risk_state
            save_risk_state(
                self.starting_balance, self.current_balance,
                self.total_pnl, self.peak_balance,
            )
        except Exception as e:
            logger.exception("Failed to persist risk state: %s", e)

    def check_fill_deviation(
        self, expected_price: float, filled_price: float, sl_distance: float,
    ) -> tuple[bool, float]:
        """
        RC-09: Check if a live fill deviated too far from the expected price.

        This is a POST-FILL utility — call it after receiving a fill from the broker.
        If the deviation is too large, the caller should log a warning and potentially
        close the position (slippage ate into the risk budget).

        Args:
            expected_price: The price we expected to fill at.
            filled_price: The actual fill price from the broker.
            sl_distance: The absolute distance to stop loss (for context).

        Returns:
            Tuple of (is_acceptable, deviation_pct).
            is_acceptable is False if deviation > 0.5% of price.
        """
        if expected_price == 0:
            return False, 100.0
        deviation = abs(filled_price - expected_price)
        deviation_pct = (deviation / expected_price) * 100
        max_deviation_pct = 0.5
        is_ok = deviation_pct <= max_deviation_pct
        if not is_ok:
            logger.warning("RISK SLIPPAGE: Fill deviation %.3f%% exceeds %.1f%% limit. "
                           "Expected=%s, Filled=%s, SL distance=%s",
                           deviation_pct, max_deviation_pct, expected_price, filled_price, sl_distance)
        return is_ok, deviation_pct

    def check_inactivity(self, days_limit: int = 30, warn_at: int = 25) -> dict:
        """
        RC-11: Check for inactivity rule violation (FundingPips 30-day limit).

        FundingPips deactivates accounts after 30 days of no trading activity.
        This method tracks how long since the last trade and warns before the deadline.

        Args:
            days_limit: Maximum allowed inactive days (default 30 for FundingPips).
            warn_at: Days at which to start warning (default 25).

        Returns:
            Dict with status, days_since_last_trade, should_alert, and message.
        """
        today = datetime.now(timezone.utc).date()
        if self.last_trade_date is None:
            return {
                "status": "unknown",
                "days_since_last_trade": None,
                "should_alert": True,
                "message": "No trades recorded yet. Place a trade to start tracking.",
            }
        days_inactive = (today - self.last_trade_date).days
        should_alert = days_inactive >= warn_at
        if days_inactive >= days_limit:
            status = "violated"
            message = (
                f"INACTIVITY VIOLATION: {days_inactive} days since last trade. "
                f"FundingPips limit is {days_limit} days. Account may be deactivated."
            )
        elif days_inactive >= warn_at:
            status = "warning"
            message = (
                f"INACTIVITY WARNING: {days_inactive} days since last trade. "
                f"FundingPips limit is {days_limit} days. "
                f"Place a trade within {days_limit - days_inactive} days."
            )
        else:
            status = "ok"
            message = f"Last trade {days_inactive} days ago. Within {days_limit}-day limit."
        return {
            "status": status,
            "days_since_last_trade": days_inactive,
            "should_alert": should_alert,
            "message": message,
        }

    @staticmethod
    def check_trade_duration(duration_seconds: float) -> bool:
        """
        RC-19: Check if a trade duration is suspiciously short (HFT-like).

        FundingPips forbids HFT-like behavior. Trades that open and close within
        seconds are flagged. Callers should log this and alert if it happens
        repeatedly.

        Args:
            duration_seconds: How long the trade was open, in seconds.

        Returns:
            True if the duration is suspiciously short (< MIN_TRADE_DURATION_SECONDS).
        """
        return duration_seconds < MIN_TRADE_DURATION_SECONDS

    def get_status(self) -> dict:
        """Get current risk status for the dashboard."""
        today = self._get_today_stats()
        max_daily_loss = self.starting_balance * self._max_daily_dd
        # RC-04: Use original_starting_balance for total drawdown (static)
        max_total_loss = self.original_starting_balance * self._max_total_dd

        return {
            "mode": "prop" if self._is_prop else "personal",
            "balance": round(self.current_balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round((self.total_pnl / self.starting_balance) * 100, 2),
            "daily_pnl": round(today.realized_pnl, 2),
            "daily_unrealized_pnl": round(today.unrealized_pnl, 2),
            "daily_drawdown_used_pct": round(
                (abs(min(today.realized_pnl + today.unrealized_pnl, 0)) / max(max_daily_loss, 0.01)) * 100, 1
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


# CQ-04 FIX: Removed module-level singleton.
# Create RiskManager instances explicitly with the actual broker balance:
#   risk_mgr = RiskManager(starting_balance=broker_balance)
# The old singleton used config.active_balance_usd which was wrong
# (INR conversion of a hardcoded default, not the real broker balance).
