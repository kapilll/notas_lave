"""
Strategy Registry — manages all available strategies.

New strategies are registered here. The confluence scorer iterates
through all registered strategies to compute the composite score.
"""

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


# CQ-09 FIX: Cache strategy instances to avoid creating new objects on every call.
# Strategies are stateless analyzers, so reusing the same instances is safe.
_cached_strategies: list[BaseStrategy] | None = None


def get_all_strategies() -> list[BaseStrategy]:
    """
    Returns all registered strategies (cached after first call).

    Current: 12 strategies across 4 categories
    - Scalping: EMA Crossover, RSI Divergence, Bollinger Bands, Stochastic, Camarilla, EMA Gold
    - Volume: VWAP Scalping
    - Fibonacci: Golden Zone
    - ICT/Structure: London Breakout, NY Open Range  (removed: Order Blocks, Session Kill Zone)
    - Breakout: Break & Retest, Momentum Breakout
    """
    global _cached_strategies
    if _cached_strategies is None:
        _cached_strategies = [
            # Scalping (Tier 1)
            EMAcrossoverStrategy(),           # #8:  Triple EMA Crossover
            RSIDivergenceStrategy(),          # #12: RSI Divergence (fast 7-period)
            BollingerBandsStrategy(),         # #10: Bollinger Bands Mean Reversion
            StochasticScalpingStrategy(),     # #19: Stochastic (5,3,3) Crossover
            CamarillaPivotsStrategy(),        # #18: Camarilla S3/R3 reversal + S4/R4 breakout
            EMAGoldStrategy(),                # #7:  EMA 200/1000 pullback (Gold-specific)

            # Volume
            VWAPScalpingStrategy(),           # #11: VWAP Bounce/Rejection

            # Fibonacci
            FibonacciGoldenZoneStrategy(),    # #16: Golden Zone (50-61.8%)

            # ICT / Structure (removed: Order Blocks, Session Kill Zone — broken implementations)
            LondonBreakoutStrategy(),         # #14: London first-hour range breakout
            NYOpenRangeStrategy(),            # #15: NY 9:26-9:30 pre-open range breakout

            # Breakout (new category)
            BreakRetestStrategy(),            # #22: Break consolidation + retest entry
            MomentumBreakoutStrategy(),       # #9:  Strong candle breaks S/R with ATR stops
        ]
    return _cached_strategies


def clear_strategy_cache():
    """Clear the cached strategy instances, forcing re-creation on next call."""
    global _cached_strategies
    _cached_strategies = None


def get_strategies_by_category(category: str) -> list[BaseStrategy]:
    """Get all strategies in a specific category."""
    return [s for s in get_all_strategies() if s.category == category]
