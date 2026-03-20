"""
Confluence Scorer — combines all strategy signals into one score.

This is the brain of the system. Each strategy produces a Signal.
The scorer weighs them, checks agreement, and produces a ConfluenceResult.

CONCEPT: "Confluence" means multiple independent signals agreeing.
If EMA says BUY, RSI says BUY, and BB says BUY — that's 3-way confluence.
More agreement = higher confidence = better trade.

Inspired by Temple-Stuart's convergence pipeline:
- Dynamic weights shift based on market regime
- In trending markets: trend-following strategies get more weight
- In ranging markets: mean-reversion strategies get more weight
"""

from ..data.models import (
    Candle, Signal, ConfluenceResult, Direction,
    SignalStrength, MarketRegime,
)
from ..strategies.registry import get_all_strategies

# Strategy weights shift based on what the market is doing
REGIME_WEIGHTS: dict[MarketRegime, dict[str, float]] = {
    # Trending: EMA crossovers and trend strategies dominate
    MarketRegime.TRENDING: {
        "scalping": 0.30,   # EMA, momentum strategies shine
        "ict": 0.30,        # ICT works well in trends
        "fibonacci": 0.25,  # Fib retracements are key in trends
        "volume": 0.15,
    },
    # Ranging: mean-reversion strategies dominate
    MarketRegime.RANGING: {
        "scalping": 0.35,   # BB, RSI, Stochastic excel in ranges
        "ict": 0.15,
        "fibonacci": 0.20,
        "volume": 0.30,     # Volume profile, VWAP great in ranges
    },
    # Volatile: volume and momentum signals matter most
    MarketRegime.VOLATILE: {
        "scalping": 0.20,
        "ict": 0.25,
        "fibonacci": 0.20,
        "volume": 0.35,     # Volume confirms real moves vs fakes
    },
    # Quiet: mean-reversion + scalping
    MarketRegime.QUIET: {
        "scalping": 0.40,   # Scalping small moves works in quiet markets
        "ict": 0.15,
        "fibonacci": 0.20,
        "volume": 0.25,
    },
}

DEFAULT_WEIGHTS = {"scalping": 0.25, "ict": 0.25, "fibonacci": 0.25, "volume": 0.25}


def detect_regime(candles: list[Candle]) -> MarketRegime:
    """
    Simple regime detection using ATR (Average True Range) and ADX-like logic.

    Phase 1: Basic detection using price action
    Phase 2: Will upgrade to HMM (Hidden Markov Model) for better accuracy

    ATR measures volatility. High ATR = volatile. Low ATR = quiet.
    Directional bias = are we making higher highs or lower lows?
    """
    if len(candles) < 20:
        return MarketRegime.RANGING

    # Calculate ATR (14-period)
    true_ranges = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i - 1].close),
            abs(candles[i].low - candles[i - 1].close),
        )
        true_ranges.append(tr)

    atr_14 = sum(true_ranges[-14:]) / 14 if len(true_ranges) >= 14 else sum(true_ranges) / len(true_ranges)
    atr_50 = sum(true_ranges[-50:]) / 50 if len(true_ranges) >= 50 else atr_14

    # Volatility ratio: current ATR vs longer-term ATR
    vol_ratio = atr_14 / atr_50 if atr_50 > 0 else 1.0

    # Check trend direction using last 20 candles
    recent_closes = [c.close for c in candles[-20:]]
    price_change_pct = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]

    # Count higher highs and lower lows (trend strength)
    higher_highs = sum(
        1 for i in range(1, len(candles[-20:]))
        if candles[-20 + i].high > candles[-20 + i - 1].high
    )
    lower_lows = sum(
        1 for i in range(1, len(candles[-20:]))
        if candles[-20 + i].low < candles[-20 + i - 1].low
    )
    trend_strength = abs(higher_highs - lower_lows) / 19  # Normalize to 0-1

    # Decision tree
    if vol_ratio > 1.5:
        return MarketRegime.VOLATILE  # ATR expanding = volatile
    elif vol_ratio < 0.6:
        return MarketRegime.QUIET     # ATR contracting = quiet
    elif trend_strength > 0.6 and abs(price_change_pct) > 0.01:
        return MarketRegime.TRENDING  # Strong directional bias
    else:
        return MarketRegime.RANGING   # No clear direction


def compute_confluence(
    candles: list[Candle],
    symbol: str,
    timeframe: str,
) -> ConfluenceResult:
    """
    Run all strategies on the candles and compute a weighted confluence score.

    Process:
    1. Detect market regime (trending/ranging/volatile/quiet)
    2. Run each strategy to get signals
    3. Weight signals based on regime
    4. Count agreeing strategies
    5. Compute composite score (0-10 scale)
    """
    strategies = get_all_strategies()

    # Step 1: Detect regime
    regime = detect_regime(candles)
    weights = REGIME_WEIGHTS.get(regime, DEFAULT_WEIGHTS)

    # Step 2: Run all strategies
    signals: list[Signal] = []
    for strategy in strategies:
        try:
            signal = strategy.analyze(candles, symbol)
            signals.append(signal)
        except Exception as e:
            # Strategy failed — log but don't crash
            signals.append(Signal(
                strategy_name=strategy.name,
                reason=f"Error: {str(e)[:100]}",
            ))

    # Step 3: Count direction votes and compute weighted score
    long_votes = 0
    short_votes = 0
    weighted_score = 0.0
    active_signals = 0

    for signal in signals:
        if signal.direction is None or signal.strength == SignalStrength.NONE:
            continue

        active_signals += 1
        # Get weight for this strategy's category
        category_weight = weights.get(
            # Find the strategy to get its category
            next((s.category for s in strategies if s.name == signal.strategy_name), "scalping"),
            0.25,
        )

        # Normalize signal score to 0-10 scale and apply weight
        normalized_score = (signal.score / 100.0) * 10.0
        weighted_score += normalized_score * category_weight

        if signal.direction == Direction.LONG:
            long_votes += 1
        elif signal.direction == Direction.SHORT:
            short_votes += 1

    # Step 4: Determine consensus direction
    if long_votes > short_votes and long_votes >= 2:
        direction = Direction.LONG
    elif short_votes > long_votes and short_votes >= 2:
        direction = Direction.SHORT
    elif long_votes > 0 and short_votes == 0:
        direction = Direction.LONG
    elif short_votes > 0 and long_votes == 0:
        direction = Direction.SHORT
    else:
        direction = None  # No consensus — conflicting signals

    # Step 5: Adjust score based on agreement level
    total_active = max(active_signals, 1)
    agreeing = max(long_votes, short_votes)
    agreement_bonus = (agreeing / total_active) * 2.0  # Up to +2 points for full agreement

    composite_score = min(10.0, weighted_score + agreement_bonus)

    return ConfluenceResult(
        symbol=symbol,
        timeframe=timeframe,
        direction=direction,
        composite_score=round(composite_score, 1),
        signals=signals,
        regime=regime,
        agreeing_strategies=agreeing,
        total_strategies=len(strategies),
    )
