"""
Strategy Registry — manages all available strategies.

New strategies are registered here. The confluence scorer iterates
through all registered strategies to compute the composite score.

ML-16 FIX: When optimizer_results.json exists, strategies are created
with optimized parameters instead of hardcoded defaults. The optimizer
runs walk-forward analysis and only saves params that pass out-of-sample
validation. The registry applies those params per-symbol when a symbol
is provided, falling back to defaults otherwise.
"""

import json
import logging
import os

from .base import BaseStrategy
from .ema_crossover import EMAcrossoverStrategy
from .rsi_divergence import RSIDivergenceStrategy
from .bollinger_bands import BollingerBandsStrategy
from .vwap import VWAPScalpingStrategy
from .stochastic import StochasticScalpingStrategy
from .fibonacci import FibonacciGoldenZoneStrategy
from .camarilla_pivots import CamarillaPivotsStrategy
from .ema_gold import EMAGoldStrategy
from .london_breakout import LondonBreakoutStrategy
from .ny_open_range import NYOpenRangeStrategy
from .break_retest import BreakRetestStrategy
from .momentum_breakout import MomentumBreakoutStrategy

logger = logging.getLogger(__name__)


# CQ-09 FIX: Cache strategy instances to avoid creating new objects on every call.
# Strategies are stateless analyzers, so reusing the same instances is safe.
# ML-16: Cache is now per-symbol to support optimized params per instrument.
_cached_strategies: dict[str, list[BaseStrategy]] = {}

# Strategy name -> constructor class mapping.
# Names must match each strategy's .name property exactly.
# Used by _build_strategies() to instantiate with optimized params.
_STRATEGY_REGISTRY: list[tuple[str, type]] = [
    # Scalping (Tier 1)
    ("ema_crossover",        EMAcrossoverStrategy),
    ("rsi_divergence",       RSIDivergenceStrategy),
    ("bollinger_bands",      BollingerBandsStrategy),
    ("stochastic_scalping",  StochasticScalpingStrategy),
    ("camarilla_pivots",     CamarillaPivotsStrategy),
    ("ema_gold",             EMAGoldStrategy),
    # Volume
    ("vwap_scalping",        VWAPScalpingStrategy),
    # Fibonacci
    ("fibonacci_golden_zone", FibonacciGoldenZoneStrategy),
    # ICT / Structure (removed: Order Blocks, Session Kill Zone — broken implementations)
    ("london_breakout",      LondonBreakoutStrategy),
    ("ny_open_range",        NYOpenRangeStrategy),
    # Breakout
    ("break_retest",         BreakRetestStrategy),
    ("momentum_breakout",    MomentumBreakoutStrategy),
]

# Path to optimizer results file
_OPTIMIZER_RESULTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "optimizer_results.json",
)


def _load_optimized_params(symbol: str) -> dict[str, dict]:
    """
    Load optimized strategy parameters for a specific instrument.

    Reads optimizer_results.json and returns params that passed validation:
    - improvement_pct > 5 (optimizer already filters for validation_pf > 1.0)
    - best_params is non-empty (empty means defaults were better)

    Returns: {strategy_name: {param: value, ...}} or {} if no file / no results.
    """
    if not os.path.exists(_OPTIMIZER_RESULTS_PATH):
        return {}
    try:
        with open(_OPTIMIZER_RESULTS_PATH) as f:
            all_results = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    symbol_data = all_results.get(symbol, {})
    if not symbol_data or "results" not in symbol_data:
        return {}

    optimized = {}
    for result in symbol_data["results"]:
        strategy_name = result.get("strategy", "")
        best_params = result.get("best_params", {})
        improvement = result.get("improvement_pct", 0)

        # Only apply params that showed meaningful improvement (>5%)
        # and have non-empty best_params (empty = defaults were optimal)
        if best_params and improvement > 5:
            optimized[strategy_name] = best_params

    return optimized


def _build_strategies(optimized_params: dict[str, dict]) -> list[BaseStrategy]:
    """
    Build strategy instances, applying optimized params where available.

    For each strategy:
    - If optimized params exist for it, pass them as constructor kwargs
    - Otherwise, use default constructor (hardcoded defaults)
    """
    strategies = []
    for strategy_name, constructor in _STRATEGY_REGISTRY:
        params = optimized_params.get(strategy_name, {})
        if params:
            try:
                strategy = constructor(**params)
                logger.info(
                    "Applied optimized params for %s: %s", strategy_name, params
                )
            except TypeError as e:
                # If optimized params don't match constructor signature,
                # fall back to defaults. This can happen if a strategy's
                # constructor was refactored after optimization ran.
                logger.warning(
                    "Optimized params for %s rejected (bad kwargs: %s), "
                    "using defaults",
                    strategy_name, e,
                )
                strategy = constructor()
        else:
            strategy = constructor()

        strategies.append(strategy)
    return strategies


def get_all_strategies(symbol: str | None = None) -> list[BaseStrategy]:
    """
    Returns all registered strategies (cached after first call per symbol).

    Args:
        symbol: Instrument symbol (e.g., "BTCUSD"). When provided, strategies
                are created with optimizer-tuned params for that instrument.
                When None, strategies use hardcoded defaults.

    Current: 12 strategies across 4 categories
    - Scalping: EMA Crossover, RSI Divergence, Bollinger Bands, Stochastic, Camarilla, EMA Gold
    - Volume: VWAP Scalping
    - Fibonacci: Golden Zone
    - ICT/Structure: London Breakout, NY Open Range  (removed: Order Blocks, Session Kill Zone)
    - Breakout: Break & Retest, Momentum Breakout
    """
    cache_key = symbol or "_default"

    if cache_key not in _cached_strategies:
        optimized = _load_optimized_params(symbol) if symbol else {}
        if optimized:
            logger.info(
                "ML-16: Loading optimized params for %s — %d strategies tuned: %s",
                symbol, len(optimized), list(optimized.keys()),
            )
        _cached_strategies[cache_key] = _build_strategies(optimized)

    return _cached_strategies[cache_key]


def clear_strategy_cache():
    """Clear ALL cached strategy instances, forcing re-creation on next call.

    Call this after the optimizer writes new results so strategies pick up
    the latest tuned parameters.
    """
    global _cached_strategies
    _cached_strategies = {}
    logger.info("Strategy cache cleared — next call will reload optimized params")


def get_strategies_by_category(category: str) -> list[BaseStrategy]:
    """Get all strategies in a specific category."""
    return [s for s in get_all_strategies() if s.category == category]
