"""
Prediction Accuracy Tracker — measures how good our predictions are.

WHAT THIS DOES:
Every time the system generates a signal (LONG/SHORT), that's a PREDICTION.
We track whether the prediction was correct by checking what price did next.

This is like ML model accuracy — but for trading signals.

METRICS:
- Direction Accuracy: Did price move in the predicted direction? (over N candles)
- Target Accuracy: Did TP get hit before SL?
- Score Calibration: Do higher-score signals have higher accuracy?
- Per-Strategy Accuracy: Which strategies predict best?
- Rolling Accuracy: How is accuracy trending over time?

WHY THIS MATTERS:
Win rate tells you how many TRADES made money (affected by position sizing, fees, timing).
Accuracy tells you how many PREDICTIONS were correct (pure signal quality).
A system can have 40% win rate but 65% accuracy if entries are poorly timed.
Tracking accuracy separately reveals the true quality of the signal engine.
"""

from datetime import datetime, timezone, timedelta
from ..journal.database import get_db, PredictionLog


def log_prediction(
    symbol: str,
    timeframe: str,
    strategy_name: str,
    predicted_direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    confluence_score: float,
    regime: str,
) -> int:
    """
    Log a new prediction. Called whenever a signal fires.
    Returns the prediction ID.
    """
    db = get_db()
    pred = PredictionLog(
        symbol=symbol,
        timeframe=timeframe,
        strategy_name=strategy_name,
        predicted_direction=predicted_direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confluence_score=confluence_score,
        regime=regime,
    )
    db.add(pred)
    db.commit()
    return pred.id


def resolve_prediction(
    prediction_id: int,
    candles_after: list,
) -> dict | None:
    """
    Check a prediction against what actually happened.

    Takes the candles that occurred AFTER the prediction was made.
    Checks: did price hit TP, SL, or just move in the predicted direction?
    """
    db = get_db()
    pred = db.query(PredictionLog).filter(PredictionLog.id == prediction_id).first()
    if not pred or pred.resolved:
        return None

    if not candles_after or len(candles_after) < 2:
        return None

    entry = pred.entry_price
    sl = pred.stop_loss
    tp = pred.take_profit
    is_long = pred.predicted_direction == "LONG"

    max_fav = 0.0
    max_adv = 0.0
    outcome = "timeout"
    candles_count = 0

    for i, candle in enumerate(candles_after):
        candles_count = i + 1

        if is_long:
            unrealized = candle.close - entry
            max_fav = max(max_fav, candle.high - entry)
            max_adv = min(max_adv, candle.low - entry)

            if sl and candle.low <= sl:
                outcome = "sl_hit"
                break
            if tp and candle.high >= tp:
                outcome = "tp_hit"
                break
        else:
            unrealized = entry - candle.close
            max_fav = max(max_fav, entry - candle.low)
            max_adv = min(max_adv, entry - candle.high)

            if sl and candle.high >= sl:
                outcome = "sl_hit"
                break
            if tp and candle.low <= tp:
                outcome = "tp_hit"
                break

    # Determine if direction was correct
    final_price = candles_after[-1].close
    if is_long:
        direction_correct = final_price > entry
        actual_direction = "LONG" if final_price > entry else "SHORT"
    else:
        direction_correct = final_price < entry
        actual_direction = "SHORT" if final_price < entry else "LONG"

    target_hit = outcome == "tp_hit"

    # Update the prediction record
    pred.actual_direction = actual_direction
    pred.outcome = outcome
    pred.price_after_n = final_price
    pred.max_favorable = max_fav
    pred.max_adverse = max_adv
    pred.direction_correct = direction_correct
    pred.target_hit = target_hit
    pred.resolved = True
    pred.resolved_at = datetime.now(timezone.utc)
    pred.candles_to_resolve = candles_count
    db.commit()

    return {
        "id": pred.id,
        "direction_correct": direction_correct,
        "target_hit": target_hit,
        "outcome": outcome,
    }


def resolve_pending_predictions(candle_data_fn=None) -> int:
    """
    Resolve all unresolved predictions using cached market data.

    ML-18 FIX: The original implementation accepted an async candle_data_fn
    but never called it (sync/async mismatch). Now resolves predictions by
    reading directly from the MarketDataProvider's cache, which is populated
    by the autonomous trader's scan loop. This avoids the async problem
    entirely. Predictions older than 24h are expired as before.

    For proper async resolution, see CQ-12 (future refactoring).

    Called by the autonomous agent periodically.
    Returns count of predictions resolved.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    pending = db.query(PredictionLog).filter(
        PredictionLog.resolved == False,
        PredictionLog.timestamp < now - timedelta(minutes=30),
    ).all()

    # ML-18: Import the singleton market data provider to read from cache
    try:
        from ..data.market_data import market_data as _md
    except ImportError:
        _md = None

    resolved_count = 0
    for pred in pending:
        age = (now - pred.timestamp).total_seconds()

        if age > 86400:  # 24 hours — expire
            pred.resolved = True
            pred.resolved_at = now
            pred.outcome = "expired"
            pred.direction_correct = None
            pred.target_hit = False
            db.commit()
            resolved_count += 1

        elif age > 1800 and _md is not None:  # 30min+, try to resolve from cache
            cache_key = (pred.symbol, pred.timeframe)
            if cache_key in _md._cache:
                cached_candles, _ = _md._cache[cache_key]
                # Find candles that occurred AFTER the prediction timestamp
                pred_time = pred.timestamp
                if pred_time.tzinfo is None:
                    pred_time = pred_time.replace(tzinfo=timezone.utc)
                after_candles = [c for c in cached_candles if c.timestamp > pred_time]
                if len(after_candles) >= 3:
                    result = resolve_prediction(pred.id, after_candles)
                    if result is not None:
                        resolved_count += 1

    return resolved_count


def get_accuracy_score(max_age_days: int = 30) -> dict:
    """
    Compute the overall accuracy score and breakdowns.

    Returns a comprehensive accuracy report used by the dashboard.
    """
    db = get_db()

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    predictions = db.query(PredictionLog).filter(
        PredictionLog.resolved == True,
        PredictionLog.direction_correct.isnot(None),
        PredictionLog.timestamp >= cutoff,
    ).all()

    if not predictions:
        return {
            "status": "no_data",
            "message": "No resolved predictions yet. Start trading to build accuracy data.",
            "total_predictions": 0,
        }

    total = len(predictions)
    direction_correct = sum(1 for p in predictions if p.direction_correct)
    targets_hit = sum(1 for p in predictions if p.target_hit)
    sl_hits = sum(1 for p in predictions if p.outcome == "sl_hit")
    tp_hits = sum(1 for p in predictions if p.outcome == "tp_hit")
    timeouts = sum(1 for p in predictions if p.outcome == "timeout")

    direction_accuracy = direction_correct / total * 100 if total > 0 else 0
    target_accuracy = targets_hit / total * 100 if total > 0 else 0

    # Per-strategy accuracy
    strategy_acc: dict[str, dict] = {}
    for p in predictions:
        name = p.strategy_name or "unknown"
        if name not in strategy_acc:
            strategy_acc[name] = {"total": 0, "correct": 0, "tp_hit": 0}
        strategy_acc[name]["total"] += 1
        if p.direction_correct:
            strategy_acc[name]["correct"] += 1
        if p.target_hit:
            strategy_acc[name]["tp_hit"] += 1

    strategy_breakdown = {}
    for name, stats in sorted(strategy_acc.items(), key=lambda x: x[1]["correct"] / max(x[1]["total"], 1), reverse=True):
        strategy_breakdown[name] = {
            "total": stats["total"],
            "direction_accuracy": round(stats["correct"] / max(stats["total"], 1) * 100, 1),
            "target_accuracy": round(stats["tp_hit"] / max(stats["total"], 1) * 100, 1),
        }

    # Score calibration: group by score buckets, check accuracy per bucket
    calibration = {}
    buckets = [(0, 30, "0-30"), (30, 50, "30-50"), (50, 60, "50-60"),
               (60, 70, "60-70"), (70, 80, "70-80"), (80, 101, "80+")]
    for low, high, label in buckets:
        bucket_preds = [p for p in predictions if low <= (p.confluence_score or 0) < high]
        if bucket_preds:
            bc = sum(1 for p in bucket_preds if p.direction_correct)
            calibration[label] = {
                "predictions": len(bucket_preds),
                "direction_accuracy": round(bc / len(bucket_preds) * 100, 1),
                "target_accuracy": round(sum(1 for p in bucket_preds if p.target_hit) / len(bucket_preds) * 100, 1),
            }

    # Per-regime accuracy
    regime_acc: dict[str, dict] = {}
    for p in predictions:
        regime = p.regime or "UNKNOWN"
        if regime not in regime_acc:
            regime_acc[regime] = {"total": 0, "correct": 0}
        regime_acc[regime]["total"] += 1
        if p.direction_correct:
            regime_acc[regime]["correct"] += 1
    regime_breakdown = {
        r: {"total": s["total"], "accuracy": round(s["correct"] / max(s["total"], 1) * 100, 1)}
        for r, s in regime_acc.items()
    }

    return {
        "status": "ready",
        "total_predictions": total,
        "direction_accuracy": round(direction_accuracy, 1),
        "target_accuracy": round(target_accuracy, 1),
        "outcomes": {
            "tp_hit": tp_hits,
            "sl_hit": sl_hits,
            "timeout": timeouts,
        },
        "by_strategy": strategy_breakdown,
        "calibration": calibration,
        "by_regime": regime_breakdown,
        "period_days": max_age_days,
    }


def get_accuracy_history(window_size: int = 20) -> dict:
    """
    Get rolling accuracy over time for the improvement graph.

    Returns accuracy computed over sliding windows of `window_size` predictions.
    This shows whether the system's predictions are getting better.
    """
    db = get_db()
    predictions = db.query(PredictionLog).filter(
        PredictionLog.resolved == True,
        PredictionLog.direction_correct.isnot(None),
    ).order_by(PredictionLog.timestamp.asc()).all()

    if len(predictions) < window_size:
        return {
            "status": "insufficient_data",
            "message": f"Need at least {window_size} resolved predictions. Have {len(predictions)}.",
            "total": len(predictions),
            "points": [],
        }

    points = []
    for i in range(window_size, len(predictions) + 1):
        window = predictions[i - window_size:i]
        correct = sum(1 for p in window if p.direction_correct)
        targets = sum(1 for p in window if p.target_hit)
        acc = correct / window_size * 100
        tgt_acc = targets / window_size * 100

        points.append({
            "index": i,
            "timestamp": window[-1].timestamp.isoformat() if window[-1].timestamp else None,
            "direction_accuracy": round(acc, 1),
            "target_accuracy": round(tgt_acc, 1),
            "window_size": window_size,
        })

    # Trend: is accuracy improving?
    if len(points) >= 2:
        first_half = points[:len(points) // 2]
        second_half = points[len(points) // 2:]
        first_avg = sum(p["direction_accuracy"] for p in first_half) / len(first_half)
        second_avg = sum(p["direction_accuracy"] for p in second_half) / len(second_half)
        trend = "improving" if second_avg > first_avg + 2 else "declining" if second_avg < first_avg - 2 else "stable"
    else:
        trend = "insufficient_data"
        first_avg = 0
        second_avg = 0

    return {
        "status": "ready",
        "total_predictions": len(predictions),
        "window_size": window_size,
        "points": points,
        "trend": trend,
        "first_half_avg": round(first_avg, 1) if first_avg else 0,
        "second_half_avg": round(second_avg, 1) if second_avg else 0,
    }
