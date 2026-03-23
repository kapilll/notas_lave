"""
A/B Testing Framework (ML-12) — Shadow-mode parameter comparison.

Simple shadow-mode A/B testing:
- Variant A (current params) is used for actual trading
- Variant B (candidate params) runs in shadow mode (logged, not traded)
- After N predictions, compare accuracy/P&L with confidence level

CQ-02 FIX: Uses the shared SQLAlchemy database via get_db() from journal.database
instead of a separate raw sqlite3 connection and database file.
"""

import json
from datetime import datetime, timezone

from ..journal.database import get_db, ABTest, ABTestResult


def create_test(name: str, param_a: dict, param_b: dict, description: str = "") -> dict:
    """
    Create a new A/B test.

    Args:
        name: Unique test name (e.g., "rsi_period_14_vs_21")
        param_a: Current parameters (control)
        param_b: Candidate parameters (treatment)
        description: Human-readable description

    Returns:
        Test configuration dict.
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    # Check if test already exists
    existing = db.query(ABTest).filter(ABTest.test_name == name).first()
    if existing:
        # Update existing test
        existing.variant_a_value = json.dumps(param_a)
        existing.variant_b_value = json.dumps(param_b)
        existing.description = description
        existing.status = "active"
    else:
        db.add(ABTest(
            test_name=name,
            param_name=name,
            variant_a_value=json.dumps(param_a),
            variant_b_value=json.dumps(param_b),
            description=description,
            created_at=now,
            status="active",
        ))
    db.commit()

    return {
        "name": name,
        "param_a": param_a,
        "param_b": param_b,
        "description": description,
        "status": "active",
        "created_at": now.isoformat(),
    }


def record_result(
    test_name: str,
    variant: str,
    prediction: str,
    outcome: str,
    pnl: float = 0.0,
    metadata: dict | None = None,
) -> int:
    """
    Log a prediction result for a variant.

    Args:
        test_name: Name of the A/B test
        variant: "A" or "B"
        prediction: What was predicted (e.g., "LONG", "SHORT", "SKIP")
        outcome: What actually happened (e.g., "WIN", "LOSS", "BREAKEVEN")
        pnl: Actual or virtual P&L
        metadata: Additional context

    Returns:
        Row ID of the inserted record.
    """
    if variant not in ("A", "B"):
        raise ValueError("variant must be 'A' or 'B'")

    db = get_db()

    # Look up the test to get its ID
    test = db.query(ABTest).filter(ABTest.test_name == test_name).first()
    if not test:
        raise ValueError(f"Test '{test_name}' not found. Create it first with create_test().")

    result = ABTestResult(
        test_id=test.id,
        variant=variant,
        prediction=prediction,
        outcome=outcome,
        pnl=pnl,
        won=(outcome == "WIN"),
        metadata_json=json.dumps(metadata or {}),
    )
    db.add(result)
    db.commit()
    return result.id


def get_test_results(test_name: str) -> dict:
    """
    Compare variant A vs B for a given test.

    Returns accuracy, total P&L, win rate, and a confidence assessment.
    """
    db = get_db()

    # Get test config
    test = db.query(ABTest).filter(ABTest.test_name == test_name).first()
    if not test:
        return {"error": f"Test '{test_name}' not found"}

    results = {}
    for variant in ("A", "B"):
        rows = db.query(ABTestResult).filter(
            ABTestResult.test_id == test.id,
            ABTestResult.variant == variant,
        ).all()

        total = len(rows)
        if total == 0:
            results[variant] = {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
            }
            continue

        wins = sum(1 for r in rows if r.outcome == "WIN")
        losses = sum(1 for r in rows if r.outcome == "LOSS")
        total_pnl = sum(r.pnl for r in rows)

        results[variant] = {
            "total": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total, 2) if total > 0 else 0.0,
        }

    # Determine winner and confidence
    a = results.get("A", {})
    b = results.get("B", {})
    a_total = a.get("total", 0)
    b_total = b.get("total", 0)
    min_samples = min(a_total, b_total)

    winner = "inconclusive"
    confidence = "low"

    if min_samples >= 5:
        a_wr = a.get("win_rate", 0)
        b_wr = b.get("win_rate", 0)
        a_pnl = a.get("total_pnl", 0)
        b_pnl = b.get("total_pnl", 0)

        # Simple heuristic: B wins if it beats A on both win rate AND PnL
        if b_wr > a_wr and b_pnl > a_pnl:
            winner = "B"
        elif a_wr > b_wr and a_pnl > b_pnl:
            winner = "A"
        elif b_pnl > a_pnl:
            winner = "B (by PnL)"
        elif a_pnl > b_pnl:
            winner = "A (by PnL)"

        # ML-26/TP-11: Use two-proportion z-test for statistical significance
        # instead of heuristic sample-size thresholds. Falls back to heuristic
        # if scipy is not available or samples are too few.
        if min_samples >= 10:
            try:
                from scipy.stats import norm
                import math

                a_wr_f = a_wr / 100  # Convert percentage to fraction
                b_wr_f = b_wr / 100
                pooled = (a_wr_f * a_total + b_wr_f * b_total) / (a_total + b_total) if (a_total + b_total) > 0 else 0.5

                if 0 < pooled < 1:
                    se = math.sqrt(pooled * (1 - pooled) * (1 / max(a_total, 1) + 1 / max(b_total, 1)))
                    z = (b_wr_f - a_wr_f) / se if se > 0 else 0
                    p_value = 2 * (1 - norm.cdf(abs(z)))  # Two-tailed

                    if p_value < 0.05:
                        confidence = "high"
                        winner = "B" if b_wr_f > a_wr_f else "A"
                    elif p_value < 0.10:
                        confidence = "medium"
                    else:
                        confidence = "low"
                else:
                    # Degenerate case (0% or 100% pooled), fall back to heuristic
                    confidence = "high" if min_samples >= 30 else ("medium" if min_samples >= 15 else "low")
            except ImportError:
                # scipy not available — fall back to sample-size heuristic
                confidence = "high" if min_samples >= 30 else ("medium" if min_samples >= 15 else "low")
        else:
            confidence = "low"

    return {
        "test_name": test_name,
        "param_a": json.loads(test.variant_a_value) if test.variant_a_value else {},
        "param_b": json.loads(test.variant_b_value) if test.variant_b_value else {},
        "description": test.description or "",
        "status": test.status,
        "results": results,
        "winner": winner,
        "confidence": confidence,
        "recommendation": _build_recommendation(winner, confidence, min_samples),
    }


def get_all_tests() -> list[dict]:
    """Get results for all active tests."""
    db = get_db()
    tests = db.query(ABTest).order_by(ABTest.created_at.desc()).all()
    return [get_test_results(t.test_name) for t in tests]


def _build_recommendation(winner: str, confidence: str, samples: int) -> str:
    """Generate a human-readable recommendation."""
    if samples < 5:
        return f"Need more data — only {samples} samples per variant (minimum 5)."
    if confidence == "low":
        return f"Tentative: {winner} looks better but only {samples} samples. Keep running."
    if confidence == "medium":
        return f"{winner} is ahead with {samples} samples. Consider running to 30 for high confidence."
    # high confidence
    if winner == "inconclusive":
        return f"No clear winner after {samples} samples. Parameters perform similarly."
    return f"{winner} is the winner with high confidence ({samples} samples). Consider promoting B to production." if "B" in winner else f"Current params (A) are better. Keep them."
