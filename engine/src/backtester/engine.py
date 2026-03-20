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

KEY METRICS:
- Win Rate: % of trades that were profitable
- Profit Factor: Gross profit / Gross loss (>1.5 is good, >2 is excellent)
- Sharpe Ratio: Risk-adjusted return (>1 is decent, >2 is great)
- Max Drawdown: Largest peak-to-trough decline (must stay < 10% for prop firm)
- Expectancy: Average $ per trade (must be positive)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from ..data.models import Candle, Signal, Direction, MarketRegime
from ..data.instruments import get_instrument, InstrumentSpec
from ..strategies.registry import get_all_strategies
from ..confluence.scorer import detect_regime


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
        }


class Backtester:
    """
    Walk-forward backtesting engine.

    Simulates trading by walking through historical candles one at a time,
    running strategies at each step, and tracking simulated trades with
    realistic spread and slippage.
    """

    def __init__(
        self,
        starting_balance: float = 100_000.0,
        risk_per_trade: float = 0.01,
        min_confluence_score: float = 6.0,
        min_rr: float = 2.0,
        max_concurrent: int = 3,
        max_trade_duration_candles: int = 100,  # Force close after 100 candles
    ):
        self.starting_balance = starting_balance
        self.risk_per_trade = risk_per_trade
        self.min_confluence_score = min_confluence_score
        self.min_rr = min_rr
        self.max_concurrent = max_concurrent
        self.max_trade_duration = max_trade_duration_candles

    def run(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
    ) -> BacktestResult:
        """
        Run the backtest on historical candles.

        Walks forward candle by candle. At each step:
        1. Check open trades against current candle's high/low (SL/TP)
        2. Run strategies on the candle window
        3. If confluence is high enough, open a new trade
        """
        spec = get_instrument(symbol)
        strategies = get_all_strategies()

        balance = self.starting_balance
        peak_balance = balance
        open_trades: list[BacktestTrade] = []
        closed_trades: list[BacktestTrade] = []
        equity_curve = [balance]
        daily_returns: list[float] = []

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

            # --- Step 1: Check open trades against this candle ---
            still_open = []
            for trade in open_trades:
                # Check SL/TP using candle HIGH and LOW (not just close)
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
                    closed_trades.append(trade)
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

            # --- Step 2: Run strategies on window ending at current candle ---
            if len(open_trades) >= self.max_concurrent:
                equity_curve.append(balance)
                continue  # Max positions reached

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
        return self._compute_results(
            closed_trades, equity_curve, daily_returns,
            symbol, timeframe, period_str, len(candles),
        )

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
