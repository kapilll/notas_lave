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

FUNDINGPIPS RISK CONTROLS (enforced in backtest):
- Daily loss circuit breaker: halt trading if daily P&L drops below -4%
- Total drawdown halt: stop all trading if account drops 8% from starting balance
- Max 2 concurrent trades (conservative — leaves margin for error)
- 0.5% risk per trade (half of max allowed)
- These match the live risk manager but with safety buffers

KEY METRICS:
- Win Rate: % of trades that were profitable
- Profit Factor: Gross profit / Gross loss (>1.5 is good, >2 is excellent)
- Sharpe Ratio: Risk-adjusted return (>1 is decent, >2 is great)
- Max Drawdown: Largest peak-to-trough decline (must stay < 10% for prop firm)
- Expectancy: Average $ per trade (must be positive)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from ..data.models import Candle, Signal, Direction, MarketRegime
from ..data.instruments import get_instrument, InstrumentSpec
from ..strategies.registry import get_all_strategies
from ..strategies.base import BaseStrategy
from ..confluence.scorer import detect_regime


# Per-instrument strategy blacklist — strategies known to lose money
# on specific instruments based on backtest analysis.
# Key = symbol, Value = set of strategy names to SKIP.
INSTRUMENT_STRATEGY_BLACKLIST: dict[str, set[str]] = {
    "XAUUSD": {
        "order_block_fvg",     # -$87K on Gold, 28% WR — terrible
        "fibonacci_golden_zone",  # -$15K on Gold — Gold swings too fast for fib zones
        "vwap_scalping",       # -$15K on Gold — VWAP unreliable with 24/5 session
    },
    "XAGUSD": set(),  # No data yet — will update after backtesting
    "BTCUSD": {
        "break_retest",        # -$16K on BTC — crypto consolidations break unpredictably
    },
    "ETHUSD": set(),  # No data yet — will update after backtesting
}


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
    exit_reason: str = ""  # tp_hit, sl_hit, timeout
    strategy_name: str = ""
    confluence_score: float = 0.0
    regime: str = ""
    max_favorable: float = 0.0
    max_adverse: float = 0.0


@dataclass
class BacktestResult:
    """Complete results of a backtest run."""
    symbol: str
    timeframe: str
    period: str  # e.g., "2025-01-01 to 2025-12-31"
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
    expectancy: float = 0.0       # Average $ per trade
    max_drawdown: float = 0.0     # Largest peak-to-trough decline
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    avg_trade_duration_mins: float = 0.0
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    # Per-strategy breakdown
    strategy_stats: dict[str, dict] = field(default_factory=dict)
    # Risk metrics
    daily_halts: int = 0          # Days where circuit breaker triggered
    total_halt_triggered: bool = False  # Did total drawdown halt fire?

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "period": self.period,
            "total_candles": self.total_candles,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 1),
            "net_pnl": round(self.net_pnl, 2),
            "profit_factor": round(self.profit_factor, 2),
            "expectancy": round(self.expectancy, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "largest_win": round(self.largest_win, 2),
            "largest_loss": round(self.largest_loss, 2),
            "avg_trade_duration_mins": round(self.avg_trade_duration_mins, 1),
            "strategy_stats": self.strategy_stats,
            "equity_curve": [round(e, 2) for e in self.equity_curve[::max(1, len(self.equity_curve) // 200)]],
            "daily_halts": self.daily_halts,
            "total_halt_triggered": self.total_halt_triggered,
        }


def get_filtered_strategies(symbol: str) -> list[BaseStrategy]:
    """
    Get strategies filtered by instrument blacklist.

    Some strategies consistently lose money on specific instruments.
    Rather than disabling them globally (they work on other instruments),
    we skip them only for the instruments where they underperform.
    """
    blacklist = INSTRUMENT_STRATEGY_BLACKLIST.get(symbol, set())
    return [s for s in get_all_strategies() if s.name not in blacklist]


class Backtester:
    """
    Walk-forward backtesting engine with FundingPips risk controls.

    Now enforces the same rules as the live risk manager:
    - Daily loss circuit breaker (stop trading for the day)
    - Total drawdown halt (stop all trading)
    - Conservative position sizing
    - Per-instrument strategy filtering
    """

    def __init__(
        self,
        starting_balance: float = 100_000.0,
        risk_per_trade: float = 0.005,       # 0.5% risk (was 1% — too aggressive)
        min_confluence_score: float = 6.0,
        min_rr: float = 2.0,
        max_concurrent: int = 2,             # Conservative: 2 (was 3)
        max_trade_duration_candles: int = 100,
        daily_loss_limit_pct: float = 0.04,  # Halt after 4% daily loss (FundingPips = 5%)
        total_dd_limit_pct: float = 0.08,    # Halt after 8% total DD (FundingPips = 10%)
    ):
        self.starting_balance = starting_balance
        self.risk_per_trade = risk_per_trade
        self.min_confluence_score = min_confluence_score
        self.min_rr = min_rr
        self.max_concurrent = max_concurrent
        self.max_trade_duration = max_trade_duration_candles
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.total_dd_limit_pct = total_dd_limit_pct

    def run(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
    ) -> BacktestResult:
        """
        Run the backtest on historical candles with full risk controls.

        Walks forward candle by candle. At each step:
        1. Check daily/total drawdown circuit breakers
        2. Check open trades against current candle's high/low (SL/TP)
        3. Run filtered strategies on the candle window
        4. If signal is strong enough AND risk allows, open a new trade
        """
        spec = get_instrument(symbol)
        strategies = get_filtered_strategies(symbol)

        balance = self.starting_balance
        peak_balance = balance
        open_trades: list[BacktestTrade] = []
        closed_trades: list[BacktestTrade] = []
        equity_curve = [balance]
        daily_returns: list[float] = []

        # FundingPips risk tracking
        daily_loss_limit = self.starting_balance * self.daily_loss_limit_pct
        total_dd_limit = self.starting_balance * self.total_dd_limit_pct
        current_day: date | None = None
        daily_pnl = 0.0
        daily_halted = False
        total_halted = False
        daily_halt_count = 0

        # Minimum candles needed before we start scanning
        warmup = 210  # EMA(200) + buffer

        if len(candles) < warmup + 50:
            return BacktestResult(
                symbol=symbol, timeframe=timeframe,
                period="Insufficient data", total_candles=len(candles),
            )

        period_str = f"{candles[warmup].timestamp.date()} to {candles[-1].timestamp.date()}"

        for i in range(warmup, len(candles)):
            current = candles[i]
            prev_balance = balance

            # --- Day change detection: reset daily P&L ---
            candle_date = current.timestamp.date()
            if current_day != candle_date:
                current_day = candle_date
                daily_pnl = 0.0
                daily_halted = False

            # --- Total drawdown halt: stop ALL trading if DD too deep ---
            total_dd = self.starting_balance - balance
            if total_dd >= total_dd_limit:
                total_halted = True

            # --- Step 1: Check open trades against this candle ---
            # (Always process open trades even if halted — we need to close them)
            still_open = []
            for trade in open_trades:
                closed = False
                trade_age = i - getattr(trade, '_entry_idx', i)

                if trade.direction == "LONG":
                    if current.low <= trade.stop_loss:
                        trade.exit_price = trade.stop_loss
                        trade.exit_reason = "sl_hit"
                        closed = True
                    elif current.high >= trade.take_profit:
                        trade.exit_price = trade.take_profit
                        trade.exit_reason = "tp_hit"
                        closed = True
                else:  # SHORT
                    if current.high >= trade.stop_loss:
                        trade.exit_price = trade.stop_loss
                        trade.exit_reason = "sl_hit"
                        closed = True
                    elif current.low <= trade.take_profit:
                        trade.exit_price = trade.take_profit
                        trade.exit_reason = "tp_hit"
                        closed = True

                # Timeout: force close after max duration
                if not closed and trade_age >= self.max_trade_duration:
                    trade.exit_price = current.close
                    trade.exit_reason = "timeout"
                    closed = True

                if closed:
                    trade.exit_time = current.timestamp
                    trade.pnl = spec.calculate_pnl(
                        trade.entry_price, trade.exit_price,
                        trade.position_size, trade.direction,
                    )
                    trade.pnl_pct = trade.pnl / balance * 100 if balance > 0 else 0
                    balance += trade.pnl
                    daily_pnl += trade.pnl
                    closed_trades.append(trade)

                    # Check if daily loss limit is breached after this close
                    if daily_pnl <= -daily_loss_limit:
                        daily_halted = True
                        daily_halt_count += 1
                else:
                    # Track MFE/MAE while trade is open
                    if trade.direction == "LONG":
                        unrealized = (current.close - trade.entry_price) * spec.contract_size * trade.position_size
                    else:
                        unrealized = (trade.entry_price - current.close) * spec.contract_size * trade.position_size
                    trade.max_favorable = max(trade.max_favorable, unrealized)
                    trade.max_adverse = min(trade.max_adverse, unrealized)
                    still_open.append(trade)

            open_trades = still_open

            # --- Step 2: Skip new trades if risk limits hit ---
            if daily_halted or total_halted or len(open_trades) >= self.max_concurrent:
                equity_curve.append(balance)
                daily_returns.append(balance - prev_balance)
                if balance > peak_balance:
                    peak_balance = balance
                continue

            # Get the window of candles up to (and including) current
            window = candles[:i + 1]

            # Detect regime and run strategies
            regime = detect_regime(window[-60:] if len(window) > 60 else window)

            # Run each strategy individually and find the best signal
            best_signal: Signal | None = None
            for strategy in strategies:
                try:
                    signal = strategy.analyze(window[-250:], symbol)
                    if signal.direction and signal.score > 0:
                        if best_signal is None or signal.score > best_signal.score:
                            best_signal = signal
                except Exception:
                    continue

            # --- Step 3: Open trade if signal is strong enough ---
            if best_signal and best_signal.entry_price and best_signal.stop_loss and best_signal.take_profit:
                risk = abs(best_signal.entry_price - best_signal.stop_loss)
                reward = abs(best_signal.take_profit - best_signal.entry_price)
                rr = reward / risk if risk > 0 else 0

                if best_signal.score >= self.min_confluence_score * 10 and rr >= self.min_rr:
                    # Apply spread to entry
                    entry = spec.apply_spread(best_signal.entry_price, best_signal.direction.value)
                    pos_size = spec.calculate_position_size(
                        entry, best_signal.stop_loss, balance, self.risk_per_trade,
                    )

                    # Pre-trade risk check: would this trade risk more than our daily budget allows?
                    potential_loss = abs(entry - best_signal.stop_loss) * spec.contract_size * pos_size
                    remaining_daily_budget = daily_loss_limit + daily_pnl  # How much more we can lose today
                    if potential_loss > remaining_daily_budget and remaining_daily_budget > 0:
                        # Reduce position to fit within daily budget
                        loss_per_lot = abs(entry - best_signal.stop_loss) * spec.contract_size
                        if loss_per_lot > 0:
                            pos_size = remaining_daily_budget / loss_per_lot
                            pos_size = round(pos_size / spec.lot_step) * spec.lot_step
                            pos_size = max(spec.min_lot, pos_size)

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
                        trade._entry_idx = i  # For timeout tracking
                        open_trades.append(trade)

            # Track equity and daily returns
            equity_curve.append(balance)
            daily_returns.append(balance - prev_balance)

            # Update peak for drawdown
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
        import math
        if daily_returns:
            mean_ret = sum(daily_returns) / len(daily_returns)
            if len(daily_returns) > 1:
                variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
                std_ret = math.sqrt(variance)
                sharpe = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0
            else:
                sharpe = 0
        else:
            sharpe = 0

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
            avg_trade_duration_mins=sum(durations) / max(len(durations), 1),
            trades=trades,
            equity_curve=equity_curve,
            strategy_stats=strat_stats,
        )
