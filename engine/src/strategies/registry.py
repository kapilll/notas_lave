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
from .session_killzone import SessionKillZoneStrategy
from .order_blocks import OrderBlockFVGStrategy


def get_all_strategies() -> list[BaseStrategy]:
    """
    Returns all registered strategies.

    Current: 8 strategies across 4 categories
    - Scalping: EMA Crossover, RSI Divergence, Bollinger Bands, Stochastic
    - Volume: VWAP Scalping
    - Fibonacci: Golden Zone (50-61.8%)
    - ICT/SMC: Kill Zone + Asian Range, Order Blocks + FVGs
    """
    return [
        # Scalping (Tier 1)
        EMAcrossoverStrategy(),           # #8:  Triple EMA Crossover
        RSIDivergenceStrategy(),          # #12: RSI Divergence (fast 7-period)
        BollingerBandsStrategy(),         # #10: Bollinger Bands Mean Reversion
        StochasticScalpingStrategy(),     # #19: Stochastic (5,3,3) Crossover

        # Volume
        VWAPScalpingStrategy(),           # #11: VWAP Bounce/Rejection

        # Fibonacci
        FibonacciGoldenZoneStrategy(),    # #16: Golden Zone (50-61.8%)

        # ICT / Smart Money
        SessionKillZoneStrategy(),        # #3/#13: Kill Zone + Asian Range Sweep
        OrderBlockFVGStrategy(),          # #1:  Order Blocks + Fair Value Gaps
    ]


def get_strategies_by_category(category: str) -> list[BaseStrategy]:
    """Get all strategies in a specific category."""
    return [s for s in get_all_strategies() if s.category == category]
