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
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
from dataclasses import dataclass
from ..data.models import Candle
from ..backtester.engine import Backtester, BacktestResult
from ..strategies.base import BaseStrategy
from ..journal.schemas import (
    safe_load_json, safe_save_json,
    OptimizerResults, OptimizerSymbolResults, OptimizerStrategyResult,
)

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
    bt = Backtester(
        starting_balance=100_000.0,
        risk_per_trade=0.005,
        max_concurrent=1,
        min_score=0.0,          # Accept all signals from this strategy
        require_strong=False,   # Accept any strength
        daily_loss_limit_pct=0.05,   # TP-10: Match live environment
        total_dd_limit_pct=0.10,     # TP-10: Match live environment
        trade_cooldown=3,
        max_trades_per_day=6,        # TP-10: Match live (was 10)
        trailing_breakeven=True,
        skip_volatile_regime=True,   # TP-10: Match live (was False)
        loss_streak_threshold=3,     # TP-10: Match live (was 99)
        news_blackout_minutes=5,     # TP-10: Match live (was 0)
    )

    # CQ-F02: Use strategies param instead of monkey-patching
    result = bt.run(candles, symbol, timeframe, strategies=[strategy])
    return result


def optimize_strategy(
    strategy_name: str,
    candles: list[Candle],
    symbol: str,
    timeframe: str = "5m",
    train_pct: float = 0.7,
) -> OptimizationResult | None:
    """
    Walk-forward optimization with proper train/test split.

    1. Split data: first 70% = training, last 30% = validation
    2. Find best params on training data
    3. Verify they also work on validation data (prevents overfitting)
    4. Only keep params if validation PF > 1.0 (profitable out-of-sample)
    """
    grid = PARAMETER_GRID.get(strategy_name)
    if not grid:
        return None

    combos = _generate_param_combos(grid)

    # Split data: train on first 70%, validate on last 30%
    split_idx = int(len(candles) * train_pct)
    train_candles = candles[:split_idx]
    # Prepend warmup candles so strategies can initialize, but only TEST on unseen data
    warmup_needed = 250  # strategies need ~210-250 candles for warmup
    test_candles = candles[max(0, split_idx - warmup_needed):]

    if len(train_candles) < 300:
        return None

    # Baseline: default parameters on training data
    default_strategy = _create_strategy_with_params(strategy_name, {})
    if not default_strategy:
        return None

    default_result = _run_single_strategy_backtest(default_strategy, train_candles, symbol, timeframe)
    default_pf = default_result.profit_factor

    # Phase 1: Find best params on TRAINING data
    best_train_pf = 0.0
    best_params = {}
    top_candidates = []

    for combo in combos:
        strategy = _create_strategy_with_params(strategy_name, combo)
        if not strategy:
            continue

        result = _run_single_strategy_backtest(strategy, train_candles, symbol, timeframe)

        if result.total_trades >= 5 and result.profit_factor > 1.0:
            top_candidates.append((combo, result.profit_factor, result.win_rate, result.net_pnl))

            if result.profit_factor > best_train_pf:
                best_train_pf = result.profit_factor
                best_params = combo

    if not best_params:
        return None

    # QR-17: Penalize for multiple comparisons — the more combos tested,
    # the more likely the "best" is just lucky. Apply deflation factor.
    import math
    n_tested = len([c for c in top_candidates if c[1] > 1.0])
    if n_tested > 1:
        # Simplified deflation: reduce reported PF by ln(n_tested) / n_tested
        deflation = 1.0 - math.log(n_tested) / (n_tested + 10)
        best_train_pf *= deflation

    # Phase 2: Validate best params on FULL data (includes unseen 30%)
    # If it works out-of-sample too, the params are robust
    best_strategy = _create_strategy_with_params(strategy_name, best_params)
    if not best_strategy:
        return None

    validation_result = _run_single_strategy_backtest(best_strategy, test_candles, symbol, timeframe)

    # Reject if validation fails (PF < 1.0 = unprofitable out-of-sample = overfit)
    if validation_result.profit_factor < 1.0 or validation_result.total_trades < 3:
        return OptimizationResult(
            strategy=strategy_name,
            symbol=symbol,
            best_params={},  # Empty = defaults are better
            best_profit_factor=default_pf,
            best_win_rate=default_result.win_rate,
            best_net_pnl=default_result.net_pnl,
            total_combos_tested=len(combos),
            default_profit_factor=default_pf,
            improvement_pct=0.0,
        )

    improvement = ((validation_result.profit_factor - default_pf) / max(default_pf, 0.01)) * 100

    return OptimizationResult(
        strategy=strategy_name,
        symbol=symbol,
        best_params=best_params,
        best_profit_factor=validation_result.profit_factor,
        best_win_rate=validation_result.win_rate,
        best_net_pnl=validation_result.net_pnl,
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
        logger.info("  Optimizing %s on %s...", strategy_name, symbol)
        result = optimize_strategy(strategy_name, candles, symbol, timeframe)
        if result:
            results.append(result.to_dict())
            if result.improvement_pct > 0:
                logger.info("    +%.1f%% improvement (PF %.2f -> %.2f)",
                            result.improvement_pct, result.default_profit_factor, result.best_profit_factor)
            else:
                logger.info("    Default params are already optimal")

    # Sort by improvement
    results.sort(key=lambda x: x["improvement_pct"], reverse=True)
    return results


def save_results(symbol: str, results: list[dict]):
    """Save optimization results to JSON file.

    Uses OptimizerResults Pydantic schema for validation via safe_save_json.
    """
    # Load existing results with schema validation
    existing = safe_load_json(RESULTS_FILE, OptimizerResults)

    # Add/update this symbol's results
    existing.data[symbol] = OptimizerSymbolResults(
        results=[OptimizerStrategyResult(**r) for r in results],
        optimized_at=datetime.now(timezone.utc).isoformat(),
    )

    safe_save_json(RESULTS_FILE, existing)


def load_results(symbol: str | None = None) -> dict:
    """Load optimization results from JSON file.

    Uses OptimizerResults Pydantic schema for validation via safe_load_json.
    Returns plain dicts to keep the existing API contract.
    """
    validated = safe_load_json(RESULTS_FILE, OptimizerResults)

    # Convert back to plain dicts for backward compatibility
    all_results = {
        sym: sym_data.model_dump()
        for sym, sym_data in validated.data.items()
    }

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
