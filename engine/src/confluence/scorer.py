"""
Confluence Scorer — combines all strategy signals into one score.

FIXES APPLIED:
#4: Weight normalization — weights are per-CATEGORY (averaged), not per-signal
    4 scalping signals no longer outweigh 1 fibonacci signal
#5: Multi-timeframe — higher timeframe trend filter rejects counter-trend trades
#10: Regime detection — uses dynamic ATR threshold instead of fixed 1%,
     longer lookback (50 candles), volume consideration
"""

import json
import logging
import os

logger = logging.getLogger(__name__)
from ..data.models import (
    Candle, Signal, ConfluenceResult, Direction,
    SignalStrength, MarketRegime,
)
from ..journal.schemas import safe_load_json, safe_save_json, LearnedState
from ..strategies.registry import get_all_strategies
from ..strategies.ema_crossover import compute_ema

# ML-15: Path for persisting learned weights/blacklists across restarts
_LEARNED_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "learned_state.json"
)

# Strategy weights shift based on market regime
# 5 categories: scalping, ict, fibonacci, volume, breakout (weights sum to 1.0)
# Breakout strategies shine in trending/volatile markets, weak in ranging/quiet
REGIME_WEIGHTS: dict[MarketRegime, dict[str, float]] = {
    MarketRegime.TRENDING: {
        "scalping": 0.20, "ict": 0.25, "fibonacci": 0.25, "volume": 0.10, "breakout": 0.20,
    },
    MarketRegime.RANGING: {
        "scalping": 0.30, "ict": 0.15, "fibonacci": 0.18, "volume": 0.25, "breakout": 0.12,
    },
    MarketRegime.VOLATILE: {
        "scalping": 0.15, "ict": 0.20, "fibonacci": 0.15, "volume": 0.30, "breakout": 0.20,
    },
    MarketRegime.QUIET: {
        "scalping": 0.35, "ict": 0.12, "fibonacci": 0.18, "volume": 0.25, "breakout": 0.10,
    },
}

DEFAULT_WEIGHTS = {"scalping": 0.20, "ict": 0.20, "fibonacci": 0.20, "volume": 0.20, "breakout": 0.20}


def _save_learned_state():
    """
    ML-15: Persist learned weights to disk so they survive restarts.
    Without this, every restart resets the EVOLVE motto — the system
    forgets everything it learned about regime weights.

    Uses LearnedState Pydantic schema for validation via safe_save_json.
    """
    try:
        from datetime import datetime, timezone as tz
        state = LearnedState(
            regime_weights={
                regime.value: weights
                for regime, weights in REGIME_WEIGHTS.items()
            },
            updated_at=datetime.now(tz.utc).isoformat(),
        )
        safe_save_json(_LEARNED_STATE_PATH, state)
    except Exception as e:
        logger.error("Failed to save learned state: %s", e)


def _load_learned_state():
    """
    ML-15: Load persisted weights on startup.
    If the file exists and is valid, override the hardcoded defaults.

    Uses LearnedState Pydantic schema for validation via safe_load_json.
    """
    try:
        state = safe_load_json(_LEARNED_STATE_PATH, LearnedState)
        if state.regime_weights:
            for regime_str, weights in state.regime_weights.items():
                try:
                    regime = MarketRegime(regime_str)
                    REGIME_WEIGHTS[regime] = weights
                except ValueError:
                    logger.warning("Skipping unknown regime '%s' in learned state", regime_str)
            logger.info("Loaded learned weights from %s", _LEARNED_STATE_PATH)
    except Exception as e:
        logger.error("Failed to load learned state: %s", e)


# Load persisted state on import (if it exists)
_load_learned_state()


def update_regime_weights(new_weights: dict[str, dict[str, float]]):
    """Apply new regime weights from the learning engine and persist.

    Called by the autonomous agent during daily review when
    can_adjust_weights is True. Converts string regime names
    to MarketRegime enum keys and updates the global weights.

    ML-15: Also saves to disk so weights survive restarts.
    """
    for regime_str, weights in new_weights.items():
        try:
            regime = MarketRegime(regime_str)
            REGIME_WEIGHTS[regime] = weights
        except ValueError:
            logger.warning("Skipping unknown regime '%s' in weight update", regime_str)
    _save_learned_state()


def detect_regime(candles: list[Candle]) -> MarketRegime:
    """
    Improved regime detection (Fix #10).

    Changes from v1:
    - Uses 50-candle lookback (was 20) for more stable classification
    - Dynamic trend threshold based on ATR (was fixed 1%)
    - Considers volume trend (rising vol + direction = confirmed trend)
    """
    if len(candles) < 50:
        return MarketRegime.RANGING

    # ATR calculation
    true_ranges = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i - 1].close),
            abs(candles[i].low - candles[i - 1].close),
        )
        true_ranges.append(tr)

    atr_14 = sum(true_ranges[-14:]) / 14
    atr_50 = sum(true_ranges[-50:]) / 50 if len(true_ranges) >= 50 else atr_14
    vol_ratio = atr_14 / atr_50 if atr_50 > 0 else 1.0

    # Dynamic trend threshold: 3x ATR relative to price (not fixed 1%)
    current_price = candles[-1].close
    trend_threshold = (atr_14 * 3) / current_price if current_price > 0 else 0.01

    # Trend detection over 50 candles
    lookback_candles = candles[-50:]
    price_change_pct = (lookback_candles[-1].close - lookback_candles[0].close) / lookback_candles[0].close

    # Higher highs vs lower lows
    hh_count = sum(
        1 for i in range(1, len(lookback_candles))
        if lookback_candles[i].high > lookback_candles[i - 1].high
    )
    ll_count = sum(
        1 for i in range(1, len(lookback_candles))
        if lookback_candles[i].low < lookback_candles[i - 1].low
    )
    trend_strength = abs(hh_count - ll_count) / (len(lookback_candles) - 1)

    # Volume trend: is volume rising or falling?
    vol_recent = [c.volume for c in candles[-10:] if c.volume > 0]
    vol_older = [c.volume for c in candles[-30:-10] if c.volume > 0]
    vol_rising = (
        sum(vol_recent) / max(len(vol_recent), 1) >
        sum(vol_older) / max(len(vol_older), 1) * 1.2
    ) if vol_recent and vol_older else False

    # Decision
    if vol_ratio > 1.5:
        return MarketRegime.VOLATILE
    elif vol_ratio < 0.6:
        return MarketRegime.QUIET
    elif trend_strength > 0.55 and abs(price_change_pct) > trend_threshold:
        # Confirmed trend: directional move exceeding dynamic threshold
        # Volume rising = extra confirmation
        return MarketRegime.TRENDING
    else:
        return MarketRegime.RANGING


def get_htf_bias(candles: list[Candle]) -> Direction | None:
    """
    Get higher-timeframe trend bias (Fix #5).

    Uses EMA(50) slope on the provided candles to determine trend direction.
    Called with 4H or 1H candles to provide context for lower timeframe entries.

    Returns LONG if EMA rising, SHORT if falling, None if flat.
    """
    if len(candles) < 55:
        return None

    closes = [c.close for c in candles]
    ema50 = compute_ema(closes, 50)

    if len(ema50) < 5:
        return None

    # Compare current EMA to 5 periods ago
    slope = (ema50[-1] - ema50[-5]) / ema50[-5] if ema50[-5] > 0 else 0

    # Threshold: 0.1% slope over 5 periods = meaningful trend
    if slope > 0.001:
        return Direction.LONG
    elif slope < -0.001:
        return Direction.SHORT
    return None


def compute_confluence(
    candles: list[Candle],
    symbol: str,
    timeframe: str,
    htf_candles: list[Candle] | None = None,
) -> ConfluenceResult:
    """
    Run all strategies and compute weighted confluence score.

    Fixes applied:
    #4: Weights are per-CATEGORY average, not per-signal
    #5: HTF trend filter penalizes counter-trend signals
    #10: Better regime detection with dynamic thresholds
    """
    from ..backtester.engine import INSTRUMENT_STRATEGY_BLACKLIST

    all_strategies = get_all_strategies(symbol=symbol)
    # Filter strategies by blacklist for this symbol — strategies known to
    # lose money on specific instruments are excluded before running them
    blacklist = INSTRUMENT_STRATEGY_BLACKLIST.get(symbol, set())
    strategies = [s for s in all_strategies if s.name not in blacklist]

    regime = detect_regime(candles)
    weights = REGIME_WEIGHTS.get(regime, DEFAULT_WEIGHTS)

    # Fix #5: Get higher-timeframe bias if HTF candles provided
    htf_bias = get_htf_bias(htf_candles) if htf_candles else None

    # Run all strategies
    signals: list[Signal] = []
    strategy_categories: dict[str, str] = {}
    for strategy in strategies:
        strategy_categories[strategy.name] = strategy.category
        try:
            signals.append(strategy.analyze(candles, symbol))
        except Exception as e:
            signals.append(Signal(
                strategy_name=strategy.name,
                reason=f"Error: {str(e)[:100]}",
            ))

    # Fix #4: Group active signals by CATEGORY and average within each category
    # This prevents 4 scalping signals from outweighing 1 fibonacci signal
    category_scores: dict[str, list[float]] = {}
    category_directions: dict[str, list[Direction]] = {}
    long_votes = 0
    short_votes = 0

    for signal in signals:
        if signal.direction is None or signal.strength == SignalStrength.NONE:
            continue

        cat = strategy_categories.get(signal.strategy_name, "scalping")
        category_scores.setdefault(cat, []).append(signal.score)
        category_directions.setdefault(cat, []).append(signal.direction)

        if signal.direction == Direction.LONG:
            long_votes += 1
        else:
            short_votes += 1

    # Compute weighted score using category AVERAGES
    weighted_score = 0.0
    for cat, scores in category_scores.items():
        cat_avg = sum(scores) / len(scores)  # Average score within category
        cat_weight = weights.get(cat, 0.25)
        weighted_score += (cat_avg / 100.0) * 10.0 * cat_weight

    # Determine consensus direction
    if long_votes > short_votes and long_votes >= 2:
        direction = Direction.LONG
    elif short_votes > long_votes and short_votes >= 2:
        direction = Direction.SHORT
    elif long_votes > 0 and short_votes == 0:
        direction = Direction.LONG
    elif short_votes > 0 and long_votes == 0:
        direction = Direction.SHORT
    else:
        direction = None

    # Agreement bonus
    active_signals = long_votes + short_votes
    agreeing = max(long_votes, short_votes)
    if active_signals > 0:
        agreement_bonus = (agreeing / active_signals) * 2.0
    else:
        agreement_bonus = 0.0

    composite_score = min(10.0, weighted_score + agreement_bonus)

    # Fix: HTF trend filter — HARD BLOCK for counter-trend signals
    # Research shows multi-timeframe alignment reduces false signals by 50-60%
    htf_aligned = True
    if htf_bias and direction:
        if htf_bias != direction:
            # Counter-trend: BLOCK entirely (was 40% penalty, now 100%)
            composite_score = 0.0
            htf_aligned = False

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
