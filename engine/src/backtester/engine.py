"""
Backtesting Engine — test strategies against historical data.

WHY THIS MATTERS:
Without backtesting, you don't know if a strategy is profitable.
The "14 Sessions" project tested 15 strategies — only 1 survived.
We need to know BEFORE risking money.

HOW IT WORKS:
1. Load historical candles (from yfinance or saved data)
2. Walk forward through time, candle by candle
3. At each candle, run all strategies as if it were live
4. If a signal fires and meets criteria, simulate the trade
5. Track P&L with realistic spread and slippage
6. After the run, analyze performance: win rate, Sharpe, max drawdown

RISK CONTROLS (10 levers for FundingPips compliance):
1. Risk per trade: 0.3% (conservative — FundingPips max 1%)
2. Max concurrent: 1 trade at a time (no stacking risk)
3. Min signal score: 60 (higher bar = fewer but better trades)
4. Signal strength: STRONG only (rejects MODERATE signals)
5. Daily loss circuit breaker: halt after 4% daily loss
6. Total drawdown halt: stop trading if account drops 8%
7. Trade cooldown: 5 candles between trades (no impulse trading)
8. Max trades per day: 4 (quality over quantity)
9. Trailing breakeven: move SL to entry after 1:1 R:R reached
10. Regime filter: skip VOLATILE regime (biggest DD contributor)
11. Loss streak throttle: halve size after 3 consecutive losses

Per-instrument strategy blacklist filters out known losers.

KEY METRICS:
- Win Rate: % of trades that were profitable
- Profit Factor: Gross profit / Gross loss (>1.5 is good, >2 is excellent)
- Sharpe Ratio: Risk-adjusted return (>1 is decent, >2 is great)
- Max Drawdown: Largest peak-to-trough decline (must stay < 10% for prop firm)
- Expectancy: Average $ per trade (must be positive)
"""

import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field
from datetime import datetime, timezone, date, timedelta
from ..data.models import Candle, Signal, Direction, SignalStrength, MarketRegime
from ..data.instruments import get_instrument, InstrumentSpec
from ..data.economic_calendar import is_in_blackout, EventImpact
from ..strategies.registry import get_all_strategies
from ..strategies.base import BaseStrategy
from ..confluence.scorer import detect_regime


# Per-instrument strategy blacklist — strategies known to lose money
# on specific instruments based on backtest analysis.
INSTRUMENT_STRATEGY_BLACKLIST: dict[str, set[str]] = {
    "XAUUSD": {
        "fibonacci_golden_zone",  # -$15K on Gold
        "vwap_scalping",          # -$15K on Gold — VWAP unreliable 24/5
    },
    "XAGUSD": set(),
    # BTC: Only RSI Divergence + Stochastic profitable over 1 year
    "BTCUSD": {
        "break_retest",
        "fibonacci_golden_zone",
        "vwap_scalping",          # -$3.7K over 1 year
        "camarilla_pivots",       # -$4.3K over 1 year
        "momentum_breakout",      # -$5.2K over 1 year
    },
    # ETH: Only RSI Divergence + Stochastic + Bollinger close to breakeven
    "ETHUSD": {
        "fibonacci_golden_zone",
        "camarilla_pivots",
        "vwap_scalping",
        "momentum_breakout",
        "ema_gold",
        "break_retest",
    },
    # CoinDCX personal instruments — same blacklists as USD equivalents
    # Mirror BTCUSD blacklist for CoinDCX symbol
    "BTCUSDT": {
        "break_retest", "fibonacci_golden_zone",
        "vwap_scalping", "camarilla_pivots", "momentum_breakout",
    },
    # Mirror ETHUSD blacklist for CoinDCX symbol
    "ETHUSDT": {
        "fibonacci_golden_zone", "camarilla_pivots",
        "vwap_scalping", "momentum_breakout", "ema_gold", "break_retest",
    },
}


def update_blacklist(symbol: str, strategies: set[str]):
    """Update the runtime blacklist for an instrument.

    ML-24 FIX: MERGE new strategies into the existing blacklist instead of
    replacing it. The static blacklist contains strategies with catastrophic
    losses (e.g., order_block_fvg: -$87K on Gold). Replacing it with the
    dynamic blacklist would silently re-enable those strategies.

    Called by the learning engine when daily review identifies
    strategies that should be disabled on specific instruments.
    """
    existing = INSTRUMENT_STRATEGY_BLACKLIST.get(symbol, set())
    INSTRUMENT_STRATEGY_BLACKLIST[symbol] = existing | strategies  # Union, not replace

    # ML-15: Persist blacklist changes
    _save_blacklist_state()


def _save_blacklist_state():
    """ML-15: Persist dynamic blacklist additions to disk."""
    import json, os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data", "learned_blacklists.json"
    )
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        state = {
            symbol: sorted(strats)
            for symbol, strats in INSTRUMENT_STRATEGY_BLACKLIST.items()
        }
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error("Failed to save blacklist state: %s", e)


@dataclass
class BacktestTrade:
    """A single trade in the backtest."""
    entry_time: datetime
    exit_time: datetime | None = None
    symbol: str = ""
    direction: str = ""  # LONG or SHORT
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # tp_hit, sl_hit, timeout, breakeven
    strategy_name: str = ""
    confluence_score: float = 0.0
    regime: str = ""
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    # CQ-08: Proper dataclass fields instead of dynamic attributes
    _entry_idx: int = 0
    _at_breakeven: bool = False


@dataclass
class BacktestResult:
    """Complete results of a backtest run."""
    symbol: str
    timeframe: str
    period: str
    total_candles: int = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    expectancy: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0    # QR-20: downside-only risk-adjusted return
    calmar_ratio: float = 0.0     # QR-20: annualized return / max drawdown
    avg_trade_duration_mins: float = 0.0
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    strategy_stats: dict[str, dict] = field(default_factory=dict)
    # Risk metrics
    daily_halts: int = 0
    total_halt_triggered: bool = False
    signals_skipped_regime: int = 0
    signals_skipped_cooldown: int = 0
    signals_skipped_strength: int = 0
    signals_skipped_daily_cap: int = 0
    signals_skipped_news: int = 0
    loss_streak_throttles: int = 0
    breakeven_moves: int = 0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "period": self.period,
            "total_candles": self.total_candles,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "breakevens": self.breakevens,
            "win_rate": round(self.win_rate, 1),
            "net_pnl": round(self.net_pnl, 2),
            "profit_factor": round(self.profit_factor, 2),
            "expectancy": round(self.expectancy, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "largest_win": round(self.largest_win, 2),
            "largest_loss": round(self.largest_loss, 2),
            "avg_trade_duration_mins": round(self.avg_trade_duration_mins, 1),
            "strategy_stats": self.strategy_stats,
            "equity_curve": [round(e, 2) for e in self.equity_curve[::max(1, len(self.equity_curve) // 200)]],
            "daily_halts": self.daily_halts,
            "total_halt_triggered": self.total_halt_triggered,
            "risk_filters": {
                "skipped_regime": self.signals_skipped_regime,
                "skipped_cooldown": self.signals_skipped_cooldown,
                "skipped_strength": self.signals_skipped_strength,
                "skipped_daily_cap": self.signals_skipped_daily_cap,
                "skipped_news": self.signals_skipped_news,
                "loss_streak_throttles": self.loss_streak_throttles,
                "breakeven_moves": self.breakeven_moves,
            },
        }


def get_filtered_strategies(symbol: str) -> list[BaseStrategy]:
    """Get strategies filtered by instrument blacklist."""
    blacklist = INSTRUMENT_STRATEGY_BLACKLIST.get(symbol, set())
    return [s for s in get_all_strategies(symbol=symbol) if s.name not in blacklist]


class Backtester:
    """
    Walk-forward backtesting engine with 10 risk control levers.

    Every lever can be configured independently. Together they enforce
    FundingPips-compliant risk management during backtesting, giving
    realistic results that match what the live system would produce.
    """

    def __init__(
        self,
        starting_balance: float = 100_000.0,
        # Lever 1: Risk per trade (0.3% = very conservative)
        risk_per_trade: float = 0.003,
        # Lever 2: Max concurrent positions (1 = no stacking)
        max_concurrent: int = 1,
        # Lever 3: Min signal score threshold (60 = only strong setups)
        min_score: float = 60.0,
        # Lever 4: Require STRONG signal strength (reject MODERATE)
        require_strong: bool = True,
        # Lever 5: Daily loss circuit breaker
        daily_loss_limit_pct: float = 0.04,
        # Lever 6: Total drawdown halt
        total_dd_limit_pct: float = 0.08,
        # Lever 7: Minimum candles between trades (cooldown)
        trade_cooldown: int = 5,
        # Lever 8: Max trades per day
        max_trades_per_day: int = 4,
        # Lever 9: Trailing breakeven after 1:1 R:R
        trailing_breakeven: bool = True,
        # Lever 10: Skip trading in VOLATILE regime
        skip_volatile_regime: bool = True,
        # Loss streak throttle: halve size after N consecutive losses
        loss_streak_threshold: int = 3,
        # News blackout: skip trading near high-impact events
        news_blackout_minutes: int = 5,
        # Leverage (for personal/CoinDCX mode)
        leverage: float = 1.0,
        # MM-01: Slippage model — SL/TP fills slip by this percentage
        # 0.05% default models real-world order book gaps during fast moves
        slippage_pct: float = 0.0005,
        # Other
        min_rr: float = 2.0,
        max_trade_duration_candles: int = 100,
    ):
        self.starting_balance = starting_balance
        self.risk_per_trade = risk_per_trade
        self.max_concurrent = max_concurrent
        self.min_score = min_score
        self.require_strong = require_strong
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.total_dd_limit_pct = total_dd_limit_pct
        self.trade_cooldown = trade_cooldown
        self.max_trades_per_day = max_trades_per_day
        self.trailing_breakeven = trailing_breakeven
        self.skip_volatile_regime = skip_volatile_regime
        self.loss_streak_threshold = loss_streak_threshold
        self.news_blackout_minutes = news_blackout_minutes
        self.leverage = leverage
        self.slippage_pct = slippage_pct
        self.min_rr = min_rr
        self.max_trade_duration = max_trade_duration_candles

    def run(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
        strategies: list[BaseStrategy] | None = None,
    ) -> BacktestResult:
        """
        Run the backtest with all 10 risk control levers active.

        CQ-04 FIX: Added optional `strategies` parameter so callers can pass
        a specific strategy list without monkey-patching get_filtered_strategies.

        Walk-forward loop:
        1. Reset daily stats on day change
        2. Check circuit breakers (daily loss, total DD)
        3. Apply trailing breakeven to open trades
        4. Check SL/TP on open trades
        5. Apply filters (cooldown, regime, daily cap, strength)
        6. Open trade if all filters pass
        """
        spec = get_instrument(symbol)
        if strategies is None:
            strategies = get_filtered_strategies(symbol)

        balance = self.starting_balance
        peak_balance = balance
        open_trades: list[BacktestTrade] = []
        closed_trades: list[BacktestTrade] = []
        equity_curve = [balance]
        daily_returns: list[float] = []

        # Risk state
        daily_loss_limit = self.starting_balance * self.daily_loss_limit_pct
        total_dd_limit = self.starting_balance * self.total_dd_limit_pct
        current_day: date | None = None
        daily_pnl = 0.0
        daily_trade_count = 0
        daily_halted = False
        total_halted = False
        daily_halt_count = 0

        # Trade tracking
        last_trade_idx = -999        # For cooldown
        consecutive_losses = 0       # For loss streak throttle
        last_win_regime = None       # TP-03: Track regime at last win for regime-conditional throttle

        # Metrics for filters
        skipped_regime = 0
        skipped_cooldown = 0
        skipped_strength = 0
        skipped_daily_cap = 0
        skipped_news = 0
        loss_throttles = 0
        breakeven_moves = 0

        warmup = 210
        if len(candles) < warmup + 50:
            return BacktestResult(
                symbol=symbol, timeframe=timeframe,
                period="Insufficient data", total_candles=len(candles),
            )

        period_str = f"{candles[warmup].timestamp.date()} to {candles[-1].timestamp.date()}"

        for i in range(warmup, len(candles)):
            current = candles[i]
            prev_balance = balance

            # --- Day change: reset daily counters ---
            candle_date = current.timestamp.date()
            if current_day != candle_date:
                current_day = candle_date
                daily_pnl = 0.0
                daily_trade_count = 0
                daily_halted = False

            # --- Funding rate deduction for leveraged crypto positions ---
            # Crypto perpetual futures charge funding every 8 hours (00:00, 08:00, 16:00 UTC)
            # MM-07: Dynamic funding rate model — real rates range from -0.375% to +0.375%
            if self.leverage > 1 and open_trades:
                hour = current.timestamp.hour if current.timestamp.tzinfo is None else current.timestamp.astimezone(timezone.utc).hour
                minute = current.timestamp.minute if current.timestamp.tzinfo is None else current.timestamp.astimezone(timezone.utc).minute
                # Check at funding times (approximate: first candle of each 8h window)
                if hour in (0, 8, 16) and minute < 5:
                    # MM-07: Use ATR-based heuristic for funding rate since regime
                    # detection happens later in the loop. High volatility = higher rates.
                    recent_candles = candles[max(0, i - 20):i + 1]
                    if len(recent_candles) >= 5:
                        avg_range = sum(c.high - c.low for c in recent_candles) / len(recent_candles)
                        avg_price = sum(c.close for c in recent_candles) / len(recent_candles)
                        range_pct = avg_range / avg_price if avg_price > 0 else 0
                        # High volatility (range > 1.5%) => 0.1%, moderate (0.5-1.5%) => 0.03%, low => 0.01%
                        if range_pct > 0.015:
                            funding_rate = 0.001   # 0.1% during volatile
                        elif range_pct > 0.005:
                            funding_rate = 0.0003  # 0.03% during moderate
                        else:
                            funding_rate = 0.0001  # 0.01% typical
                    else:
                        funding_rate = 0.0001  # Default: 0.01%

                    for trade in open_trades:
                        notional = trade.entry_price * spec.contract_size * trade.position_size
                        funding_cost = notional * funding_rate
                        balance -= funding_cost
                        daily_pnl -= funding_cost

            # --- Total drawdown halt ---
            total_dd = self.starting_balance - balance
            if total_dd >= total_dd_limit:
                total_halted = True

            # --- Step 1: Process open trades ---
            still_open = []
            for trade in open_trades:
                closed = False
                trade_age = i - trade._entry_idx

                # Lever 9: Trailing breakeven — after price moves 1:1 R:R in
                # our favor, move SL to breakeven (entry + spread).
                # This converts potential losses into breakevens.
                if self.trailing_breakeven and not trade._at_breakeven:
                    entry_risk = abs(trade.entry_price - trade.stop_loss)
                    if trade.direction == "LONG":
                        if current.high >= trade.entry_price + entry_risk:
                            # Price hit 1:1 — move SL to breakeven
                            trade.stop_loss = spec.breakeven_price(trade.entry_price, "LONG")
                            trade._at_breakeven = True
                            breakeven_moves += 1
                    else:
                        if current.low <= trade.entry_price - entry_risk:
                            trade.stop_loss = spec.breakeven_price(trade.entry_price, "SHORT")
                            trade._at_breakeven = True
                            breakeven_moves += 1

                # Check SL/TP using candle HIGH and LOW
                # MM-01: Apply slippage to fill prices — slippage always
                # makes fills WORSE (SL fills further from entry, TP fills
                # closer to entry) to model real-world order book gaps.
                # QR-18: When both SL and TP trigger on same candle, use
                # distance-from-open heuristic instead of always checking SL first.
                slip = self.slippage_pct
                sl_triggered = False
                tp_triggered = False

                if trade.direction == "LONG":
                    sl_triggered = current.low <= trade.stop_loss
                    tp_triggered = current.high >= trade.take_profit
                else:
                    sl_triggered = current.high >= trade.stop_loss
                    tp_triggered = current.low <= trade.take_profit

                if sl_triggered and tp_triggered:
                    # Both could trigger — use distance from open as heuristic
                    # If open is closer to SL, SL likely hit first; if closer to TP, TP likely hit first
                    sl_dist = abs(current.open - trade.stop_loss)
                    tp_dist = abs(current.open - trade.take_profit)
                    if sl_dist <= tp_dist:
                        tp_triggered = False  # SL was closer to open, hit first
                    else:
                        sl_triggered = False  # TP was closer to open, hit first

                if sl_triggered:
                    if trade.direction == "LONG":
                        # SL hit on LONG: fill BELOW stop (worse)
                        trade.exit_price = trade.stop_loss * (1 - slip)
                    else:
                        # SL hit on SHORT: fill ABOVE stop (worse)
                        trade.exit_price = trade.stop_loss * (1 + slip)
                    trade.exit_reason = "breakeven" if trade._at_breakeven and abs(trade.stop_loss - trade.entry_price) < spec.spread_typical * 2 else "sl_hit"
                    closed = True
                elif tp_triggered:
                    if trade.direction == "LONG":
                        # TP hit on LONG: fill slightly BELOW target (worse)
                        trade.exit_price = trade.take_profit * (1 - slip)
                    else:
                        # TP hit on SHORT: fill slightly ABOVE target (worse)
                        trade.exit_price = trade.take_profit * (1 + slip)
                    trade.exit_reason = "tp_hit"
                    closed = True

                # Timeout
                if not closed and trade_age >= self.max_trade_duration:
                    trade.exit_price = current.close
                    trade.exit_reason = "timeout"
                    closed = True

                if closed:
                    trade.exit_time = current.timestamp
                    raw_pnl = spec.calculate_pnl(
                        trade.entry_price, trade.exit_price,
                        trade.position_size, trade.direction,
                    )
                    # Deduct trading fees (CoinDCX charges per-trade fees)
                    entry_fee = spec.calculate_trading_fee(trade.entry_price, trade.position_size)
                    exit_fee = spec.calculate_trading_fee(trade.exit_price, trade.position_size)
                    trade.pnl = raw_pnl - entry_fee - exit_fee
                    trade.pnl_pct = trade.pnl / balance * 100 if balance > 0 else 0
                    balance += trade.pnl
                    daily_pnl += trade.pnl
                    closed_trades.append(trade)

                    # Track consecutive losses for loss streak throttle
                    if trade.pnl < 0:
                        consecutive_losses += 1
                    elif trade.pnl > 0:
                        consecutive_losses = 0  # Reset on a win
                        last_win_regime = trade.regime  # TP-03: remember regime at last win

                    # Daily circuit breaker check
                    if daily_pnl <= -daily_loss_limit:
                        daily_halted = True
                        daily_halt_count += 1
                else:
                    # Track MFE/MAE
                    if trade.direction == "LONG":
                        unrealized = (current.close - trade.entry_price) * spec.contract_size * trade.position_size
                    else:
                        unrealized = (trade.entry_price - current.close) * spec.contract_size * trade.position_size
                    trade.max_favorable = max(trade.max_favorable, unrealized)
                    trade.max_adverse = min(trade.max_adverse, unrealized)
                    still_open.append(trade)

            open_trades = still_open

            # --- Step 2: Apply all filters before considering new trades ---

            # Circuit breakers
            if daily_halted or total_halted:
                equity_curve.append(balance)
                daily_returns.append(balance - prev_balance)
                if balance > peak_balance:
                    peak_balance = balance
                continue

            # Max concurrent
            if len(open_trades) >= self.max_concurrent:
                equity_curve.append(balance)
                daily_returns.append(balance - prev_balance)
                if balance > peak_balance:
                    peak_balance = balance
                continue

            # Lever 7: Trade cooldown
            if i - last_trade_idx < self.trade_cooldown:
                skipped_cooldown += 1  # CQ-22: Was never incremented
                equity_curve.append(balance)
                daily_returns.append(balance - prev_balance)
                if balance > peak_balance:
                    peak_balance = balance
                continue

            # Lever 8: Max trades per day
            if daily_trade_count >= self.max_trades_per_day:
                skipped_daily_cap += 1  # CQ-22: Was never incremented
                equity_curve.append(balance)
                daily_returns.append(balance - prev_balance)
                if balance > peak_balance:
                    peak_balance = balance
                continue

            # News blackout: skip trading near high-impact events
            if self.news_blackout_minutes > 0:
                news_blocked, _ = is_in_blackout(
                    current.timestamp,
                    blackout_minutes=self.news_blackout_minutes,
                )
                if news_blocked:
                    skipped_news += 1
                    equity_curve.append(balance)
                    daily_returns.append(balance - prev_balance)
                    if balance > peak_balance:
                        peak_balance = balance
                    continue

            # DE-18 FIX: Only pass the last 300 candles as window, not entire history.
            # Strategies only use window[-250:] anyway. The old candles[:i+1] created
            # O(N^2) copies across 100K candles, wasting GBs of memory allocation.
            window_start = max(0, i - 300)
            window = candles[window_start:i + 1]

            # Lever 10: Regime filter — skip VOLATILE
            regime = detect_regime(window[-60:] if len(window) > 60 else window)
            if self.skip_volatile_regime and regime == MarketRegime.VOLATILE:
                skipped_regime += 1
                equity_curve.append(balance)
                daily_returns.append(balance - prev_balance)
                if balance > peak_balance:
                    peak_balance = balance
                continue

            # QR-23: Match live behavior — use first qualifying signal, not cherry-pick best
            # Live system iterates strategies and takes the first that qualifies
            best_signal: Signal | None = None
            for strategy in strategies:
                try:
                    signal = strategy.analyze(window[-250:], symbol)
                    if signal.direction and signal.score > 0:
                        best_signal = signal
                        break  # QR-23: Take first qualifying, not best
                except Exception as e:
                    logger.warning("Strategy %s analysis error on %s: %s", strategy.name, symbol, e)
                    continue

            if not best_signal or not best_signal.entry_price or not best_signal.stop_loss or not best_signal.take_profit:
                equity_curve.append(balance)
                daily_returns.append(balance - prev_balance)
                if balance > peak_balance:
                    peak_balance = balance
                continue

            # Lever 3: Min score check
            if best_signal.score < self.min_score:
                equity_curve.append(balance)
                daily_returns.append(balance - prev_balance)
                if balance > peak_balance:
                    peak_balance = balance
                continue

            # Lever 4: Signal strength filter
            if self.require_strong and best_signal.strength != SignalStrength.STRONG:
                skipped_strength += 1
                equity_curve.append(balance)
                daily_returns.append(balance - prev_balance)
                if balance > peak_balance:
                    peak_balance = balance
                continue

            # R:R check
            risk = abs(best_signal.entry_price - best_signal.stop_loss)
            reward = abs(best_signal.take_profit - best_signal.entry_price)
            rr = reward / risk if risk > 0 else 0
            if rr < self.min_rr:
                equity_curve.append(balance)
                daily_returns.append(balance - prev_balance)
                if balance > peak_balance:
                    peak_balance = balance
                continue

            # --- Step 3: Open trade ---
            # QR-26: Enter on NEXT candle's open to avoid look-ahead bias.
            # The signal analysed candle i's data, so execution can only
            # happen at candle i+1's open price (+ half spread).
            if i + 1 >= len(candles):
                continue  # Can't enter on the last candle
            next_open = candles[i + 1].open

            # MM-F01: Use session-adjusted spread instead of static
            hour_utc = current.timestamp.hour if current.timestamp.tzinfo is None else current.timestamp.astimezone(timezone.utc).hour
            day_of_week = current.timestamp.weekday()
            actual_spread = spec.get_spread(hour_utc, day_of_week)
            # Spread widening: in VOLATILE regime, spreads are 2-3x wider (stacks on top)
            if regime == MarketRegime.VOLATILE:
                actual_spread *= 2.5  # Realistic: spreads widen 2-3x
            entry = next_open + (actual_spread / 2 if best_signal.direction == Direction.LONG
                                 else -actual_spread / 2)

            # TP-03 FIX: Loss streak throttle is now regime-conditional.
            # Old behavior: halve size after N losses (gambler's fallacy — losses
            # in a stable regime are normal noise, not a signal to reduce size).
            # New behavior: only throttle if the regime has CHANGED since the
            # losing streak began, indicating the market shifted against us.
            effective_risk = self.risk_per_trade
            if consecutive_losses >= self.loss_streak_threshold:
                # Only throttle if regime changed (market shifted, not just noise)
                if last_win_regime is not None and last_win_regime != regime.value:
                    effective_risk = self.risk_per_trade / 2.0
                    loss_throttles += 1

            pos_size = spec.calculate_position_size(
                entry, best_signal.stop_loss, balance, effective_risk,
                leverage=self.leverage,
            )

            # Pre-trade daily budget check
            potential_loss = abs(entry - best_signal.stop_loss) * spec.contract_size * pos_size
            remaining_daily_budget = daily_loss_limit + daily_pnl
            if potential_loss > remaining_daily_budget and remaining_daily_budget > 0:
                loss_per_lot = abs(entry - best_signal.stop_loss) * spec.contract_size
                if loss_per_lot > 0:
                    pos_size = remaining_daily_budget / loss_per_lot
                    pos_size = round(pos_size / spec.lot_step) * spec.lot_step
                    pos_size = max(spec.min_lot, pos_size)
                    # QR-22: After clamping to min_lot, re-check if the
                    # min_lot still exceeds the remaining daily budget.
                    # Without this, min_lot can blow through the budget.
                    if pos_size * loss_per_lot > remaining_daily_budget:
                        continue

            if pos_size > 0:
                trade = BacktestTrade(
                    entry_time=current.timestamp,
                    symbol=symbol,
                    direction=best_signal.direction.value,
                    entry_price=round(entry, 2),
                    stop_loss=best_signal.stop_loss,
                    take_profit=best_signal.take_profit,
                    position_size=pos_size,
                    strategy_name=best_signal.strategy_name,
                    confluence_score=best_signal.score,
                    regime=regime.value,
                )
                trade._entry_idx = i
                open_trades.append(trade)
                last_trade_idx = i
                daily_trade_count += 1

            equity_curve.append(balance)
            daily_returns.append(balance - prev_balance)
            if balance > peak_balance:
                peak_balance = balance

        # --- Force close remaining open trades ---
        for trade in open_trades:
            trade.exit_price = candles[-1].close
            trade.exit_time = candles[-1].timestamp
            trade.exit_reason = "end_of_data"
            trade.pnl = spec.calculate_pnl(
                trade.entry_price, trade.exit_price,
                trade.position_size, trade.direction,
            )
            balance += trade.pnl
            closed_trades.append(trade)

        # --- Calculate results ---
        result = self._compute_results(
            closed_trades, equity_curve, daily_returns,
            symbol, timeframe, period_str, len(candles),
        )
        result.daily_halts = daily_halt_count
        result.total_halt_triggered = total_halted
        result.signals_skipped_regime = skipped_regime
        result.signals_skipped_cooldown = skipped_cooldown
        result.signals_skipped_strength = skipped_strength
        result.signals_skipped_daily_cap = skipped_daily_cap
        result.signals_skipped_news = skipped_news
        result.loss_streak_throttles = loss_throttles
        result.breakeven_moves = breakeven_moves
        return result

    def _compute_results(
        self,
        trades: list[BacktestTrade],
        equity_curve: list[float],
        daily_returns: list[float],
        symbol: str,
        timeframe: str,
        period: str,
        total_candles: int,
    ) -> BacktestResult:
        """Calculate all performance metrics from completed trades."""

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]
        breakevens = [t for t in trades if t.pnl == 0]

        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))

        # Max drawdown from equity curve
        peak = equity_curve[0]
        max_dd = 0.0
        max_dd_pct = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd / peak * 100 if peak > 0 else 0

        # Sharpe ratio (annualized, assuming 252 trading days)
        # daily_returns has one entry per candle (e.g. 5-min bars).
        # We must aggregate into actual daily P&L before annualizing.
        if daily_returns:
            # Group per-candle P&L by calendar day using the equity curve
            # Each candle's return is already balance-change; sum per day.
            # We need candle timestamps to group — but we only have returns.
            # Use trades' timestamps to map returns to days.
            # Simpler: reconstruct daily P&L from trades list.
            daily_pnl_map: dict[date, float] = defaultdict(float)
            for t in trades:
                if t.exit_time:
                    day = t.exit_time.date()
                    daily_pnl_map[day] += t.pnl
            # QR-19 FIX: Fill in zero-return days between first and last trade.
            # Without this, Sharpe is calculated from ~60 trade-days out of 252,
            # inflating it by sqrt(252/60) = 2.05x. Zero-return days are real days
            # where the system had capital at risk but no trades closed.
            if daily_pnl_map:
                all_days = sorted(daily_pnl_map.keys())
                first_day, last_day = all_days[0], all_days[-1]
                current_day = first_day
                while current_day <= last_day:
                    if current_day not in daily_pnl_map:
                        daily_pnl_map[current_day] = 0.0
                    current_day += timedelta(days=1)
            actual_daily_returns = [daily_pnl_map[d] for d in sorted(daily_pnl_map.keys())]

            if len(actual_daily_returns) > 1:
                mean_ret = sum(actual_daily_returns) / len(actual_daily_returns)
                variance = sum((r - mean_ret) ** 2 for r in actual_daily_returns) / (len(actual_daily_returns) - 1)
                std_ret = math.sqrt(variance)
                sharpe = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0
            else:
                sharpe = 0
                actual_daily_returns = []
        else:
            sharpe = 0
            actual_daily_returns = []

        # QR-20: Sortino ratio (uses downside deviation instead of total std)
        if actual_daily_returns and len(actual_daily_returns) > 1:
            mean_ret_s = sum(actual_daily_returns) / len(actual_daily_returns)
            downside_returns = [min(r, 0) for r in actual_daily_returns]
            downside_var = sum(r**2 for r in downside_returns) / max(len(downside_returns) - 1, 1)
            downside_std = math.sqrt(downside_var)
            sortino = (mean_ret_s / downside_std * math.sqrt(252)) if downside_std > 0 else 0
        else:
            sortino = 0

        # QR-20: Calmar ratio (annualized return / max drawdown)
        if max_dd_pct > 0 and actual_daily_returns and len(actual_daily_returns) > 0:
            total_return_pct = (equity_curve[-1] - equity_curve[0]) / equity_curve[0] * 100
            n_years = len(actual_daily_returns) / 252
            annual_return_pct = total_return_pct / max(n_years, 0.1)
            calmar = annual_return_pct / max_dd_pct
        else:
            calmar = 0

        # Per-strategy breakdown
        strat_stats: dict[str, dict] = {}
        for t in trades:
            s = t.strategy_name
            if s not in strat_stats:
                strat_stats[s] = {"wins": 0, "losses": 0, "pnl": 0.0, "trades": 0}
            strat_stats[s]["trades"] += 1
            strat_stats[s]["pnl"] += t.pnl
            if t.pnl > 0:
                strat_stats[s]["wins"] += 1
            elif t.pnl < 0:
                strat_stats[s]["losses"] += 1

        for s in strat_stats:
            total = strat_stats[s]["trades"]
            strat_stats[s]["win_rate"] = round(strat_stats[s]["wins"] / max(total, 1) * 100, 1)
            strat_stats[s]["pnl"] = round(strat_stats[s]["pnl"], 2)

        # Average trade duration
        durations = []
        for t in trades:
            if t.entry_time and t.exit_time:
                dur = (t.exit_time - t.entry_time).total_seconds() / 60
                durations.append(dur)

        return BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            period=period,
            total_candles=total_candles,
            total_trades=len(trades),
            wins=len(wins),
            losses=len(losses),
            breakevens=len(breakevens),
            win_rate=len(wins) / max(len(trades), 1) * 100,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_pnl=gross_profit - gross_loss,
            profit_factor=gross_profit / max(gross_loss, 0.01),
            avg_win=gross_profit / max(len(wins), 1),
            avg_loss=-gross_loss / max(len(losses), 1),
            largest_win=max((t.pnl for t in wins), default=0),
            largest_loss=min((t.pnl for t in losses), default=0),
            expectancy=(gross_profit - gross_loss) / max(len(trades), 1),
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            avg_trade_duration_mins=sum(durations) / max(len(durations), 1),
            trades=trades,
            equity_curve=equity_curve,
            strategy_stats=strat_stats,
        )

    def run_walk_forward(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
        n_folds: int = 5,
        train_ratio: float = 0.7,
    ) -> dict:
        """
        N-fold rolling walk-forward validation (QR-01 + QR-02 fix).

        Instead of testing on the same data used to choose strategies/params,
        this splits data into N windows and tests ONLY on unseen data.

        How it works:
        1. Split candles into N equal windows
        2. For each test window i (starting from fold 2):
           - Train = all windows before i
           - Test = window i (unseen data)
           - Derive blacklist from TRAINING data only (fixes QR-02)
           - Run backtest on TEST data with that blacklist
        3. Aggregate ONLY the out-of-sample test results

        Returns dict with:
        - oos_result: aggregated out-of-sample BacktestResult
        - per_fold: list of per-fold results
        - blacklists_derived: what each fold's training data suggested
        - is_result: in-sample result for comparison (to detect overfitting)
        """
        warmup = 250  # candles needed for indicator initialization
        total = len(candles)

        if total < warmup + 500:
            return {"error": f"Need at least {warmup + 500} candles, have {total}"}

        # Split into N equal windows
        usable = total - warmup  # first 'warmup' candles are always for initialization
        window_size = usable // n_folds

        if window_size < 100:
            return {"error": f"Window size too small ({window_size}). Need more data or fewer folds."}

        fold_results = []
        all_oos_trades: list[BacktestTrade] = []
        blacklists_per_fold = []

        for fold in range(1, n_folds):
            # Training: all candles up to this fold
            train_end = warmup + window_size * fold
            train_candles = candles[:train_end]

            # Test: this fold's window (with warmup prepended for indicator init)
            test_start = max(0, train_end - warmup)
            test_end = min(total, train_end + window_size)
            test_candles = candles[test_start:test_end]

            if len(test_candles) < warmup + 50:
                continue

            # QR-02 FIX: Derive blacklist from TRAINING data only
            train_blacklist = self._derive_blacklist_from_data(
                train_candles, symbol, timeframe
            )
            blacklists_per_fold.append({
                "fold": fold,
                "train_candles": len(train_candles),
                "test_candles": len(test_candles),
                "blacklisted": list(train_blacklist),
            })

            # Run test with training-derived blacklist
            original_blacklist = INSTRUMENT_STRATEGY_BLACKLIST.get(symbol, set()).copy()
            INSTRUMENT_STRATEGY_BLACKLIST[symbol] = train_blacklist

            try:
                result = self.run(test_candles, symbol, timeframe)
                fold_results.append({
                    "fold": fold,
                    "trades": result.total_trades,
                    "win_rate": round(result.win_rate, 1),
                    "net_pnl": round(result.net_pnl, 2),
                    "profit_factor": round(result.profit_factor, 2),
                    "max_dd_pct": round(result.max_drawdown_pct, 2),
                })
                # QR-27: Only keep trades whose entry_time falls AFTER the
                # training end boundary. Warmup candles are prepended to each
                # test window for indicator init, so trades from the warmup
                # overlap with training data and must be excluded.
                fold_boundary = candles[train_end].timestamp
                fold_oos_trades = [t for t in result.trades if t.entry_time >= fold_boundary]
                all_oos_trades.extend(fold_oos_trades)
            finally:
                INSTRUMENT_STRATEGY_BLACKLIST[symbol] = original_blacklist

        if not all_oos_trades:
            return {"error": "No trades generated in any fold"}

        # QR-14 FIX: Reconstruct OOS equity curve by replaying all OOS trades
        # sorted by exit time, instead of passing hollow [starting_balance].
        # This gives _compute_results a real equity curve for drawdown/Sharpe.
        sorted_oos_trades = sorted(all_oos_trades, key=lambda t: t.exit_time or t.entry_time)
        oos_equity = [self.starting_balance]
        oos_balance = self.starting_balance
        oos_daily_returns: list[float] = []
        prev_balance = oos_balance
        for t in sorted_oos_trades:
            oos_balance += t.pnl
            oos_equity.append(oos_balance)
            oos_daily_returns.append(oos_balance - prev_balance)
            prev_balance = oos_balance

        # Aggregate out-of-sample results
        oos_result = self._compute_results(
            all_oos_trades, oos_equity, oos_daily_returns,
            symbol, timeframe,
            f"Walk-forward {n_folds}-fold OOS",
            total,
        )

        # Also run in-sample (full data, original blacklist) for comparison
        is_result = self.run(candles, symbol, timeframe)

        # Overfitting ratio: if IS is much better than OOS, we're overfit
        is_pf = is_result.profit_factor
        oos_pf = oos_result.profit_factor
        overfit_ratio = round(is_pf / max(oos_pf, 0.01), 2) if oos_pf > 0 else 999

        return {
            "method": "walk_forward",
            "n_folds": n_folds,
            "total_candles": total,
            "out_of_sample": oos_result.to_dict(),
            "in_sample": {
                "trades": is_result.total_trades,
                "win_rate": round(is_result.win_rate, 1),
                "net_pnl": round(is_result.net_pnl, 2),
                "profit_factor": round(is_result.profit_factor, 2),
                "max_dd_pct": round(is_result.max_drawdown_pct, 2),
            },
            "per_fold": fold_results,
            "blacklists_derived": blacklists_per_fold,
            "overfit_ratio": overfit_ratio,
            "overfit_warning": overfit_ratio > 1.5,
            "oos_profitable": oos_result.net_pnl > 0,
        }

    def _derive_blacklist_from_data(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
    ) -> set[str]:
        """
        Derive a strategy blacklist from historical data (QR-02 fix).

        Runs each strategy independently on the given candles and blacklists
        any strategy with negative P&L and 10+ trades.
        This ensures blacklists come from TRAINING data, not test data.
        """
        all_strategies = get_all_strategies(symbol=symbol)
        blacklist = set()

        for strategy in all_strategies:
            # Quick single-strategy backtest
            bt = Backtester(
                starting_balance=self.starting_balance,
                risk_per_trade=self.risk_per_trade,
                max_concurrent=1,
                min_score=0,
                require_strong=False,
                trade_cooldown=3,
                max_trades_per_day=10,
                trailing_breakeven=self.trailing_breakeven,
                skip_volatile_regime=False,
                news_blackout_minutes=0,
            )

            # CQ-04 FIX: Pass the single strategy directly via the strategies
            # parameter instead of monkey-patching get_filtered_strategies.
            # The old approach was not thread-safe — it temporarily replaced
            # a module-level function, which would break under concurrency.
            try:
                result = bt.run(candles, symbol, timeframe, strategies=[strategy])
                if result.total_trades >= 10 and result.net_pnl < 0:
                    blacklist.add(strategy.name)
            except Exception as e:
                logger.warning("Blacklist derivation failed for strategy %s on %s: %s", strategy.name, symbol, e)

        return blacklist
