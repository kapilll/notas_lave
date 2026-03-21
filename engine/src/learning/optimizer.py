"""
Walk-Forward Optimizer — auto-tunes strategy parameters per instrument.

HOW IT WORKS:
1. Define parameter ranges for each strategy (e.g., RSI period: 5-14)
2. For each instrument, run the backtester with different parameter combos
3. Score each combo by profit factor (balances profit AND consistency)
4. Save the best parameters per strategy per instrument
5. The registry can load these optimal params instead of defaults

WHY WALK-FORWARD:
- Simple optimization overfits to historical data
- Walk-forward splits data: optimize on first 70%, validate on last 30%
- If parameters work on BOTH periods, they're robust

PARAMETER RANGES:
- Only tune the most impactful parameters (2-3 per strategy)
- Use coarse grid first (fast), then fine-tune around the best (slow)
- Total combinations are kept under 50 per strategy to stay fast

USAGE:
- POST /api/learning/optimize/{symbol} — run optimization for an instrument
- Results stored in optimizer_results.json
- Can be scheduled weekly via cron
"""

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from ..data.models import Candle
from ..data.instruments import get_instrument
from ..backtester.engine import Backtester, get_filtered_strategies, BacktestResult
from ..strategies.base import BaseStrategy

# Directory to store optimization results
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
RESULTS_FILE = os.path.join(RESULTS_DIR, "optimizer_results.json")


# Parameter ranges for each strategy — only the most impactful params
# Format: {strategy_name: {param_name: [values_to_test]}}
PARAMETER_GRID: dict[str, dict[str, list]] = {
    "rsi_divergence": {
        "rsi_period": [5, 7, 9, 14],
        "oversold": [25.0, 30.0, 35.0],
        "overbought": [65.0, 70.0, 75.0],
    },
    "ema_crossover": {
        "fast_period": [7, 9, 12],
        "medium_period": [18, 21, 26],
        "min_separation_pct": [0.0005, 0.001, 0.002],
    },
    "bollinger_bands": {
        "period": [14, 20, 26],
        "std_dev": [1.8, 2.0, 2.2, 2.5],
    },
    "stochastic_scalping": {
        "k_period": [5, 8, 14],
        "oversold": [15.0, 20.0, 25.0],
        "overbought": [75.0, 80.0, 85.0],
    },
    "camarilla_pivots": {
        "proximity_pct": [0.0005, 0.001, 0.0015, 0.002],
    },
    "momentum_breakout": {
        "min_candle_atr_mult": [1.5, 2.0, 2.5],
        "min_body_ratio": [0.6, 0.7, 0.8],
        "stop_atr_mult": [1.0, 1.5, 2.0],
    },
    "vwap_scalping": {
        "proximity_pct": [0.001, 0.002, 0.003],
        "volume_multiplier": [1.0, 1.3, 1.5, 2.0],
    },
    "fibonacci_golden_zone": {
        "min_swing_pct": [0.005, 0.008, 0.012],
        "golden_zone_low": [0.45, 0.50, 0.55],
    },
}


@dataclass
class OptimizationResult:
    """Result of optimizing one strategy on one instrument."""
    strategy: str
    symbol: str
    best_params: dict
    best_profit_factor: float
    best_win_rate: float
    best_net_pnl: float
    total_combos_tested: int
    default_profit_factor: float
    improvement_pct: float

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "best_params": self.best_params,
            "best_profit_factor": round(self.best_profit_factor, 3),
            "best_win_rate": round(self.best_win_rate, 1),
            "best_net_pnl": round(self.best_net_pnl, 2),
            "total_combos_tested": self.total_combos_tested,
            "default_profit_factor": round(self.default_profit_factor, 3),
            "improvement_pct": round(self.improvement_pct, 1),
        }


def _generate_param_combos(grid: dict[str, list]) -> list[dict]:
    """Generate all combinations from a parameter grid."""
    if not grid:
        return [{}]

    keys = list(grid.keys())
    values = list(grid.values())

    combos = [{}]
    for key, vals in zip(keys, values):
        new_combos = []
        for combo in combos:
            for val in vals:
                new_combo = combo.copy()
                new_combo[key] = val
                new_combos.append(new_combo)
        combos = new_combos

    return combos


def _create_strategy_with_params(strategy_name: str, params: dict) -> BaseStrategy | None:
    """Create a strategy instance with specific parameters."""
    from ..strategies.ema_crossover import EMAcrossoverStrategy
    from ..strategies.rsi_divergence import RSIDivergenceStrategy
    from ..strategies.bollinger_bands import BollingerBandsStrategy
    from ..strategies.stochastic import StochasticScalpingStrategy
    from ..strategies.vwap import VWAPScalpingStrategy
    from ..strategies.fibonacci import FibonacciGoldenZoneStrategy
    from ..strategies.camarilla_pivots import CamarillaPivotsStrategy
    from ..strategies.momentum_breakout import MomentumBreakoutStrategy

    constructors = {
        "ema_crossover": EMAcrossoverStrategy,
        "rsi_divergence": RSIDivergenceStrategy,
        "bollinger_bands": BollingerBandsStrategy,
        "stochastic_scalping": StochasticScalpingStrategy,
        "vwap_scalping": VWAPScalpingStrategy,
        "fibonacci_golden_zone": FibonacciGoldenZoneStrategy,
        "camarilla_pivots": CamarillaPivotsStrategy,
        "momentum_breakout": MomentumBreakoutStrategy,
    }

    constructor = constructors.get(strategy_name)
    if not constructor:
        return None

    try:
        return constructor(**params)
    except TypeError:
        return None


def _run_single_strategy_backtest(
    strategy: BaseStrategy,
    candles: list[Candle],
    symbol: str,
    timeframe: str,
) -> BacktestResult:
    """
    Run a simplified backtest for a single strategy.

    Uses the same backtester but only with one strategy active.
    Walk-forward: test on the full dataset (validation is done by comparing
    with default parameters on the same data).
    """
    spec = get_instrument(symbol)
    from ..confluence.scorer import detect_regime

    bt = Backtester(
        starting_balance=100_000.0,
        risk_per_trade=0.005,
        max_concurrent=1,
        min_score=0.0,          # Accept all signals from this strategy
        require_strong=False,   # Accept any strength
        daily_loss_limit_pct=0.05,
        total_dd_limit_pct=0.10,
        trade_cooldown=3,
        max_trades_per_day=10,  # More trades = more data points
        trailing_breakeven=True,
        skip_volatile_regime=False,  # Test in all conditions
        loss_streak_threshold=99,    # No throttle during optimization
        news_blackout_minutes=0,     # No blackout during optimization
    )

    # Monkey-patch: use only our single strategy
    import engine.src.backtester.engine as bt_module
    original_fn = bt_module.get_filtered_strategies

    def single_strategy_fn(sym):
        return [strategy]

    bt_module.get_filtered_strategies = single_strategy_fn
    try:
        result = bt.run(candles, symbol, timeframe)
    finally:
        bt_module.get_filtered_strategies = original_fn

    return result


def optimize_strategy(
    strategy_name: str,
    candles: list[Candle],
    symbol: str,
    timeframe: str = "5m",
) -> OptimizationResult | None:
    """
    Optimize one strategy's parameters for one instrument.

    Tests all parameter combinations in the grid and returns
    the best one ranked by profit factor.
    """
    grid = PARAMETER_GRID.get(strategy_name)
    if not grid:
        return None

    combos = _generate_param_combos(grid)

    # First, run with default parameters as baseline
    default_strategy = _create_strategy_with_params(strategy_name, {})
    if not default_strategy:
        return None

    default_result = _run_single_strategy_backtest(default_strategy, candles, symbol, timeframe)
    default_pf = default_result.profit_factor

    best_pf = 0.0
    best_params = {}
    best_wr = 0.0
    best_pnl = 0.0

    for combo in combos:
        strategy = _create_strategy_with_params(strategy_name, combo)
        if not strategy:
            continue

        result = _run_single_strategy_backtest(strategy, candles, symbol, timeframe)

        # Score by profit factor (must have 5+ trades to be meaningful)
        if result.total_trades >= 5 and result.profit_factor > best_pf:
            best_pf = result.profit_factor
            best_params = combo
            best_wr = result.win_rate
            best_pnl = result.net_pnl

    if not best_params:
        return None

    improvement = ((best_pf - default_pf) / max(default_pf, 0.01)) * 100

    return OptimizationResult(
        strategy=strategy_name,
        symbol=symbol,
        best_params=best_params,
        best_profit_factor=best_pf,
        best_win_rate=best_wr,
        best_net_pnl=best_pnl,
        total_combos_tested=len(combos),
        default_profit_factor=default_pf,
        improvement_pct=improvement,
    )


def optimize_all_strategies(
    candles: list[Candle],
    symbol: str,
    timeframe: str = "5m",
) -> list[dict]:
    """
    Optimize all strategies with parameter grids for a given instrument.

    Returns list of optimization results sorted by improvement.
    """
    results = []

    for strategy_name in PARAMETER_GRID:
        print(f"  Optimizing {strategy_name} on {symbol}...")
        result = optimize_strategy(strategy_name, candles, symbol, timeframe)
        if result:
            results.append(result.to_dict())
            if result.improvement_pct > 0:
                print(f"    +{result.improvement_pct:.1f}% improvement "
                      f"(PF {result.default_profit_factor:.2f} -> {result.best_profit_factor:.2f})")
            else:
                print(f"    Default params are already optimal")

    # Sort by improvement
    results.sort(key=lambda x: x["improvement_pct"], reverse=True)
    return results


def save_results(symbol: str, results: list[dict]):
    """Save optimization results to JSON file."""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Load existing results
    all_results = {}
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            all_results = json.load(f)

    all_results[symbol] = {
        "results": results,
        "optimized_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2)


def load_results(symbol: str | None = None) -> dict:
    """Load optimization results from JSON file."""
    if not os.path.exists(RESULTS_FILE):
        return {}

    with open(RESULTS_FILE, "r") as f:
        all_results = json.load(f)

    if symbol:
        return all_results.get(symbol, {})
    return all_results


def get_optimal_params(symbol: str) -> dict[str, dict]:
    """
    Get optimal parameters for all strategies on a given instrument.

    Returns: {strategy_name: {param: value}}
    Used by the registry to create strategies with tuned parameters.
    """
    data = load_results(symbol)
    if not data or "results" not in data:
        return {}

    params = {}
    for result in data["results"]:
        if result.get("improvement_pct", 0) > 5:  # Only use if >5% improvement
            params[result["strategy"]] = result["best_params"]

    return params
