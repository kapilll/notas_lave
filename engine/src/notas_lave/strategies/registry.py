"""
Strategy Registry — manages all available strategies.

ARCHITECTURE CHANGE (v1.6.0):
The original 12 single-indicator strategies have been replaced by
6 composite systems. Each composite combines multiple indicators the way
real traders actually use them — requiring 3+ factors to align before
generating a signal.

Old (12 singles):                    → New (6 composites):
  EMA Crossover, RSI Divergence,      → Trend Momentum System
  EMA Gold, Stochastic
  Bollinger Bands                      → Mean Reversion System
  VWAP, Fibonacci, Camarilla           → Level Confluence System
  London/NY Breakout, Break&Retest,    → Breakout System
  Momentum Breakout
  (new) Larry Williams techniques      → Williams System
  (new) Order flow + Phase 0 data      → Order Flow System

ML-16 FIX: When optimizer_results.json exists, strategies are created
with optimized parameters instead of hardcoded defaults.
"""

import logging
import os

from .base import BaseStrategy
from .trend_momentum_system import TrendMomentumSystem
from .mean_reversion_system import MeanReversionSystem
from .level_confluence_system import LevelConfluenceSystem
from .breakout_system import BreakoutSystem
from .williams_system import WilliamsSystemStrategy
from .order_flow_system import OrderFlowSystemStrategy

logger = logging.getLogger(__name__)


# CQ-09 FIX: Cache strategy instances to avoid creating new objects on every call.
_cached_strategies: dict[str, list[BaseStrategy]] = {}

# 6 composite strategies — each is a multi-factor system.
# Names must match each strategy's .name property exactly.
_STRATEGY_REGISTRY: list[tuple[str, type]] = [
    # Composite systems — each combines multiple indicators with multi-factor confirmation
    ("trend_momentum",       TrendMomentumSystem),     # EMA stack + RSI + MACD + Stochastic + volume
    ("mean_reversion",       MeanReversionSystem),      # Bollinger + RSI + Stochastic + Z-score + volume profile
    ("level_confluence",     LevelConfluenceSystem),    # Fibonacci + VWAP + Camarilla + volume profile
    ("breakout_system",      BreakoutSystem),           # S/R + compression + volume + session + ATR + retest
    ("williams_system",      WilliamsSystemStrategy),   # %R + MACD + Smash Day + compression + volatility breakout
    ("order_flow_system",    OrderFlowSystemStrategy),  # Order book + real delta + funding + absorption + CVD
]

# Path to optimizer results file
_OPTIMIZER_RESULTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "optimizer_results.json",
)


def _load_optimized_params(symbol: str) -> dict[str, dict]:
    """
    Load optimized strategy parameters for a specific instrument.

    Uses OptimizerResults Pydantic schema for validation via safe_load_json.
    Returns: {strategy_name: {param: value, ...}} or {} if no file / no results.
    """
    from ..journal.schemas import safe_load_json, OptimizerResults
    validated = safe_load_json(_OPTIMIZER_RESULTS_PATH, OptimizerResults)

    if symbol not in validated.data:
        return {}

    symbol_data = validated.data[symbol]
    optimized = {}
    for result in symbol_data.results:
        if result.best_params and result.improvement_pct > 5:
            optimized[result.strategy] = result.best_params

    return optimized


def _build_strategies(optimized_params: dict[str, dict]) -> list[BaseStrategy]:
    """Build strategy instances, applying optimized params where available."""
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
                logger.warning(
                    "Optimized params for %s rejected (bad kwargs: %s), using defaults",
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

    Strategies listed in config.disabled_strategies (DISABLED_STRATEGIES env var)
    are excluded regardless of their trust score or leaderboard status.

    Current: 6 composite strategies across 4 categories
    - Scalping: Trend Momentum (EMA+RSI+MACD+Stochastic), Mean Reversion (BB+RSI+Z-score),
                Williams System (%R+Smash Day+compression)
    - Volume: Order Flow System (order book+delta+funding+absorption)
    - Fibonacci: Level Confluence (Fib+VWAP+Camarilla+volume profile)
    - Breakout: Breakout System (S/R+compression+volume+session+retest)
    """
    from ..config import config

    cache_key = symbol or "_default"

    if cache_key not in _cached_strategies:
        optimized = _load_optimized_params(symbol) if symbol else {}
        if optimized:
            logger.info(
                "ML-16: Loading optimized params for %s — %d strategies tuned: %s",
                symbol, len(optimized), list(optimized.keys()),
            )
        _cached_strategies[cache_key] = _build_strategies(optimized)

    disabled = {s.strip() for s in config.disabled_strategies.split(",") if s.strip()}
    if disabled:
        return [s for s in _cached_strategies[cache_key] if s.name not in disabled]
    return _cached_strategies[cache_key]


def clear_strategy_cache():
    """Clear ALL cached strategy instances, forcing re-creation on next call."""
    global _cached_strategies
    _cached_strategies = {}
    logger.info("Strategy cache cleared — next call will reload optimized params")


def get_strategies_by_category(category: str) -> list[BaseStrategy]:
    """Get all strategies in a specific category."""
    return [s for s in get_all_strategies() if s.category == category]
