"""
Learning Engine Recommendations — turns analysis into action.

Takes the analysis from analyzer.py and produces:
1. Strategy weight adjustments per regime
2. Strategy enable/disable suggestions per instrument
3. Optimal score threshold recommendation
4. Best trading hours recommendation
5. Risk parameter suggestions

These recommendations can be:
- Displayed on the dashboard for the trader to review
- Auto-applied to the confluence scorer (with user approval)
- Sent as a Telegram summary (weekly review)
"""

from datetime import datetime, timezone
from ..confluence.scorer import REGIME_WEIGHTS, DEFAULT_WEIGHTS
from .analyzer import (
    analyze_strategy_by_instrument,
    analyze_strategy_by_regime,
    analyze_by_hour,
    analyze_by_score_bucket,
    analyze_overall,
)


# Minimum trades needed for a recommendation to be statistically meaningful
MIN_TRADES_FOR_RECOMMENDATION = 10


def recommend_strategy_blacklist() -> dict[str, list[dict]]:
    """
    Recommend which strategies to disable per instrument.

    A strategy should be blacklisted on an instrument if:
    - It has 10+ trades with < 35% win rate, OR
    - It has negative total P&L with 20+ trades (enough sample size)

    Returns: {instrument: [{strategy, reason, trades, win_rate, pnl}]}
    """
    by_instrument = analyze_strategy_by_instrument()
    recommendations: dict[str, list[dict]] = {}

    for instrument, strategies in by_instrument.items():
        recs = []
        for strat_name, stats in strategies.items():
            trades = stats["trades"]
            wr = stats["win_rate"]
            pnl = stats["total_pnl"]

            if trades < MIN_TRADES_FOR_RECOMMENDATION:
                continue

            reasons = []
            if wr < 35:
                reasons.append(f"Low win rate ({wr:.1f}% on {trades} trades)")
            if pnl < 0 and trades >= 20:
                reasons.append(f"Net negative P&L (${pnl:.2f} on {trades} trades)")

            if reasons:
                recs.append({
                    "strategy": strat_name,
                    "reason": "; ".join(reasons),
                    "trades": trades,
                    "win_rate": round(wr, 1),
                    "pnl": round(pnl, 2),
                    "action": "BLACKLIST",
                })

        if recs:
            recommendations[instrument] = sorted(recs, key=lambda x: x["pnl"])

    return recommendations


def recommend_weight_adjustments() -> dict[str, dict[str, float]]:
    """
    Recommend new confluence weights per regime based on category performance.

    Strategy categories that perform well in a regime should get higher weight.
    Categories that underperform should get lower weight.

    Uses relative P&L per category within each regime to compute new weights.
    Weights always sum to 1.0.

    Returns: {regime: {category: suggested_weight}}
    """
    by_regime = analyze_strategy_by_regime()

    # Map strategy names to categories (must match registry)
    STRATEGY_CATEGORIES = {
        "ema_crossover": "scalping", "rsi_divergence": "scalping",
        "bollinger_bands": "scalping", "stochastic_scalping": "scalping",
        "camarilla_pivots": "scalping", "ema_gold": "scalping",
        "vwap_scalping": "volume",
        "fibonacci_golden_zone": "fibonacci",
        "session_killzone": "ict", "order_block_fvg": "ict",
        "london_breakout": "ict", "ny_open_range": "ict",
        "break_retest": "breakout", "momentum_breakout": "breakout",
    }

    all_categories = {"scalping", "ict", "fibonacci", "volume", "breakout"}
    suggested_weights: dict[str, dict[str, float]] = {}

    for regime, strategies in by_regime.items():
        # Compute total P&L per category in this regime
        cat_pnl: dict[str, float] = {c: 0.0 for c in all_categories}
        cat_trades: dict[str, int] = {c: 0 for c in all_categories}

        for strat_name, stats in strategies.items():
            cat = STRATEGY_CATEGORIES.get(strat_name)
            if cat:
                cat_pnl[cat] += stats["total_pnl"]
                cat_trades[cat] += stats["trades"]

        # Convert to weights: categories with positive P&L get more weight
        # Use softmax-like approach: shift all values positive, then normalize
        min_pnl = min(cat_pnl.values()) if cat_pnl else 0
        shifted = {c: pnl - min_pnl + 1.0 for c, pnl in cat_pnl.items()}
        total = sum(shifted.values())

        if total > 0:
            weights = {c: round(v / total, 3) for c, v in shifted.items()}
            # Clamp: no category below 0.05 or above 0.50
            for c in weights:
                weights[c] = max(0.05, min(0.50, weights[c]))
            # Re-normalize to sum to 1.0
            w_total = sum(weights.values())
            weights = {c: round(v / w_total, 3) for c, v in weights.items()}
            suggested_weights[regime] = weights

    return suggested_weights


def recommend_score_threshold() -> dict:
    """
    Recommend the optimal minimum confluence score.

    Analyzes win rate and profit factor at each score bucket.
    The optimal threshold is where profit factor is maximized
    without sacrificing too many trades.

    Returns: {recommended_min_score, analysis_by_bucket}
    """
    by_score = analyze_by_score_bucket()

    best_bucket = None
    best_pf = 0.0

    for bucket, stats in by_score.items():
        if stats["trades"] >= 5 and stats["profit_factor"] > best_pf:
            best_pf = stats["profit_factor"]
            best_bucket = bucket

    # Parse bucket to get lower bound as recommended threshold
    recommended = 60  # Default
    if best_bucket:
        try:
            lower = best_bucket.replace("+", "").split("-")[0]
            recommended = int(lower)
        except (ValueError, IndexError):
            pass

    return {
        "recommended_min_score": recommended,
        "best_bucket": best_bucket,
        "best_profit_factor": round(best_pf, 2),
        "analysis": by_score,
    }


def recommend_trading_hours() -> dict:
    """
    Recommend the best and worst trading hours.

    Identifies hours with highest win rate and profit factor,
    and hours that should be avoided.

    Returns: {best_hours, worst_hours, by_hour}
    """
    by_hour = analyze_by_hour()

    best_hours = []
    worst_hours = []

    for hour, stats in by_hour.items():
        if stats["trades"] < 5:
            continue
        if stats["win_rate"] >= 55 and stats["profit_factor"] >= 1.2:
            best_hours.append({"hour_utc": hour, **stats})
        elif stats["win_rate"] < 40 or stats["profit_factor"] < 0.8:
            worst_hours.append({"hour_utc": hour, **stats})

    best_hours.sort(key=lambda x: x["profit_factor"], reverse=True)
    worst_hours.sort(key=lambda x: x["profit_factor"])

    return {
        "best_hours": best_hours[:5],
        "worst_hours": worst_hours[:5],
        "all_hours": by_hour,
    }


def generate_all_recommendations() -> dict:
    """
    Generate all recommendations in one call.

    This is the main entry point for the learning engine's
    recommendation system. Returns everything the dashboard
    and the trader need to make informed adjustments.
    """
    overall = analyze_overall()

    # Only generate recommendations if we have enough data
    total_trades = overall["overall"]["trades"]

    if total_trades < MIN_TRADES_FOR_RECOMMENDATION:
        return {
            "status": "insufficient_data",
            "message": f"Need at least {MIN_TRADES_FOR_RECOMMENDATION} trades for recommendations. "
                       f"Currently have {total_trades}.",
            "total_trades": total_trades,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    return {
        "status": "ready",
        "total_trades_analyzed": total_trades,
        "overall_performance": overall,
        "blacklist_suggestions": recommend_strategy_blacklist(),
        "weight_adjustments": recommend_weight_adjustments(),
        "score_threshold": recommend_score_threshold(),
        "trading_hours": recommend_trading_hours(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
