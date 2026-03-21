"""
A/B Testing Framework (ML-12) — Shadow-mode parameter comparison.

Simple shadow-mode A/B testing:
- Variant A (current params) is used for actual trading
- Variant B (candidate params) runs in shadow mode (logged, not traded)
- After N predictions, compare accuracy/P&L with confidence level

Uses SQLite for persistence so results survive restarts.
"""

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass

# Database path — same directory as other data files
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "ab_tests.db"
_conn: sqlite3.Connection | None = None


def _get_db() -> sqlite3.Connection:
    """Get or create the SQLite connection and ensure table exists."""
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS ab_test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT NOT NULL,
                variant TEXT NOT NULL CHECK(variant IN ('A', 'B')),
                prediction TEXT NOT NULL,
                outcome TEXT NOT NULL,
                pnl REAL DEFAULT 0.0,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS ab_tests (
                name TEXT PRIMARY KEY,
                param_a TEXT NOT NULL,
                param_b TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL
            )
        """)
        _conn.commit()
    return _conn


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
    db = _get_db()
    now = datetime.now(timezone.utc).isoformat()

    try:
        db.execute(
            "INSERT INTO ab_tests (name, param_a, param_b, description, status, created_at) VALUES (?, ?, ?, ?, 'active', ?)",
            (name, json.dumps(param_a), json.dumps(param_b), description, now),
        )
        db.commit()
    except sqlite3.IntegrityError:
        # Test already exists — update it
        db.execute(
            "UPDATE ab_tests SET param_a=?, param_b=?, description=?, status='active' WHERE name=?",
            (json.dumps(param_a), json.dumps(param_b), description, name),
        )
        db.commit()

    return {
        "name": name,
        "param_a": param_a,
        "param_b": param_b,
        "description": description,
        "status": "active",
        "created_at": now,
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

    db = _get_db()
    now = datetime.now(timezone.utc).isoformat()
    cursor = db.execute(
        "INSERT INTO ab_test_results (test_name, variant, prediction, outcome, pnl, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (test_name, variant, prediction, outcome, pnl, json.dumps(metadata or {}), now),
    )
    db.commit()
    return cursor.lastrowid


def get_test_results(test_name: str) -> dict:
    """
    Compare variant A vs B for a given test.

    Returns accuracy, total P&L, win rate, and a confidence assessment.
    """
    db = _get_db()

    # Get test config
    test_row = db.execute("SELECT * FROM ab_tests WHERE name = ?", (test_name,)).fetchone()
    if not test_row:
        return {"error": f"Test '{test_name}' not found"}

    results = {}
    for variant in ("A", "B"):
        rows = db.execute(
            "SELECT prediction, outcome, pnl FROM ab_test_results WHERE test_name=? AND variant=?",
            (test_name, variant),
        ).fetchall()

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

        wins = sum(1 for r in rows if r["outcome"] == "WIN")
        losses = sum(1 for r in rows if r["outcome"] == "LOSS")
        total_pnl = sum(r["pnl"] for r in rows)

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

        # Confidence based on sample size and margin
        if min_samples >= 30:
            confidence = "high"
        elif min_samples >= 15:
            confidence = "medium"
        else:
            confidence = "low"

    return {
        "test_name": test_name,
        "param_a": json.loads(test_row["param_a"]),
        "param_b": json.loads(test_row["param_b"]),
        "description": test_row["description"],
        "status": test_row["status"],
        "results": results,
        "winner": winner,
        "confidence": confidence,
        "recommendation": _build_recommendation(winner, confidence, min_samples),
    }


def get_all_tests() -> list[dict]:
    """Get results for all active tests."""
    db = _get_db()
    tests = db.execute("SELECT name FROM ab_tests ORDER BY created_at DESC").fetchall()
    return [get_test_results(t["name"]) for t in tests]


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
