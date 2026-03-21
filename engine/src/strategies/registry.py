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
from .camarilla_pivots import CamarillaPivotsStrategy
from .ema_gold import EMAGoldStrategy
from .london_breakout import LondonBreakoutStrategy
from .ny_open_range import NYOpenRangeStrategy
from .break_retest import BreakRetestStrategy
from .momentum_breakout import MomentumBreakoutStrategy


def get_all_strategies() -> list[BaseStrategy]:
    """
    Returns all registered strategies.

    Current: 14 strategies across 5 categories
    - Scalping: EMA Crossover, RSI Divergence, Bollinger Bands, Stochastic,
                Camarilla Pivots, EMA 200/1000 Gold
    - Volume: VWAP Scalping
    - Fibonacci: Golden Zone (50-61.8%)
    - ICT/SMC: Kill Zone + Asian Range, Order Blocks + FVGs,
               London Breakout, NY Open Range
    - Breakout: Break & Retest, Momentum Breakout + ATR
    """
    return [
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

        # ICT / Smart Money
        SessionKillZoneStrategy(),        # #3/#13: Kill Zone + Asian Range Sweep
        OrderBlockFVGStrategy(),          # #1:  Order Blocks + Fair Value Gaps
        LondonBreakoutStrategy(),         # #14: London first-hour range breakout
        NYOpenRangeStrategy(),            # #15: NY 9:26-9:30 pre-open range breakout

        # Breakout (new category)
        BreakRetestStrategy(),            # #22: Break consolidation + retest entry
        MomentumBreakoutStrategy(),       # #9:  Strong candle breaks S/R with ATR stops
    ]


def get_strategies_by_category(category: str) -> list[BaseStrategy]:
    """Get all strategies in a specific category."""
    return [s for s in get_all_strategies() if s.category == category]
