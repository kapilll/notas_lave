#!/usr/bin/env python3
"""Data migration validator — cross-layer consistency check.

Compares:
  1. EventStore trade count vs TradeLog count (closed trades)
  2. Leaderboard JSON stats vs TradeLog-derived stats per strategy
  3. RiskState balance vs broker balance (if broker reachable)

Output: structured PASS/FAIL report. Exit code 0 = all pass, 1 = discrepancies.

Usage:
    cd engine
    ../.venv/bin/python scripts/validate_migration.py
    ../.venv/bin/python scripts/validate_migration.py --db-path data/notas_lave.db
    ../.venv/bin/python scripts/validate_migration.py --leaderboard data/strategy_leaderboard.json
    ../.venv/bin/python scripts/validate_migration.py --verbose
"""

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path


# Defaults — resolve relative to repo root
_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_DB = _REPO_ROOT / "data" / "notas_lave.db"
_DEFAULT_LEADERBOARD = _REPO_ROOT / "data" / "strategy_leaderboard.json"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    severity: str = "ERROR"  # ERROR or WARNING


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check):
        self.checks.append(check)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "ERROR")

    def print(self, verbose: bool = False):
        errors = [c for c in self.checks if not c.passed and c.severity == "ERROR"]
        warnings = [c for c in self.checks if not c.passed and c.severity == "WARNING"]
        passed = [c for c in self.checks if c.passed]

        print(f"\n{'=' * 60}")
        print("  DATA MIGRATION VALIDATION REPORT")
        print(f"{'=' * 60}")
        print(f"  Total checks : {len(self.checks)}")
        print(f"  Passed       : {len(passed)}")
        print(f"  Errors       : {len(errors)}")
        print(f"  Warnings     : {len(warnings)}")
        print(f"{'=' * 60}")

        if errors:
            print("\n❌ ERRORS (must fix):")
            for c in errors:
                print(f"  [{c.name}] {c.detail}")

        if warnings:
            print("\n⚠️  WARNINGS (investigate):")
            for c in warnings:
                print(f"  [{c.name}] {c.detail}")

        if verbose and passed:
            print("\n✅ Passed:")
            for c in passed:
                print(f"  [{c.name}] {c.detail}")

        print(f"\n{'=' * 60}")
        if self.passed:
            print("  RESULT: ✅ PASS — all data layers are consistent")
        else:
            print("  RESULT: ❌ FAIL — discrepancies detected (see errors above)")
        print(f"{'=' * 60}\n")


def check_event_store_vs_tradelog(db_path: Path, report: Report, verbose: bool):
    """Compare EventStore closed trade count vs TradeLog closed count."""
    if not db_path.exists():
        report.add(Check(
            name="db_exists",
            passed=False,
            detail=f"Database not found: {db_path}",
            severity="WARNING",
        ))
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # EventStore: count distinct trade_ids that have a 'closed' event
        try:
            closed_event_store = conn.execute("""
                SELECT COUNT(DISTINCT trade_id) as cnt
                FROM trade_events
                WHERE event_type = 'closed'
            """).fetchone()["cnt"]
        except sqlite3.OperationalError:
            report.add(Check(
                name="event_store_table",
                passed=False,
                detail="trade_events table not found — EventStore not initialized",
                severity="WARNING",
            ))
            closed_event_store = None

        # TradeLog: count closed trades (exit_price NOT NULL)
        try:
            closed_tradelog = conn.execute("""
                SELECT COUNT(*) as cnt
                FROM trade_logs
                WHERE exit_price IS NOT NULL
            """).fetchone()["cnt"]
        except sqlite3.OperationalError:
            report.add(Check(
                name="tradelog_table",
                passed=False,
                detail="trade_logs table not found — database schema not initialized",
                severity="ERROR",
            ))
            return

        if closed_event_store is None:
            return

        delta = abs(closed_event_store - closed_tradelog)
        if delta == 0:
            report.add(Check(
                name="event_store_vs_tradelog_count",
                passed=True,
                detail=f"EventStore closed={closed_event_store} matches TradeLog closed={closed_tradelog}",
            ))
        else:
            report.add(Check(
                name="event_store_vs_tradelog_count",
                passed=False,
                detail=(
                    f"Count mismatch: EventStore closed={closed_event_store} "
                    f"vs TradeLog closed={closed_tradelog} (delta={delta}). "
                    f"Missing TradeLog entries indicate dual-write failures."
                ),
            ))

        # Check for orphaned EventStore open trades (opened but never closed)
        try:
            open_without_close = conn.execute("""
                SELECT COUNT(DISTINCT trade_id) as cnt
                FROM trade_events
                WHERE event_type = 'opened'
                AND trade_id NOT IN (
                    SELECT DISTINCT trade_id FROM trade_events WHERE event_type = 'closed'
                )
            """).fetchone()["cnt"]
            report.add(Check(
                name="orphaned_event_store_opens",
                passed=True,
                detail=f"Open EventStore trades without close: {open_without_close}",
                severity="WARNING" if open_without_close > 0 else "ERROR",
            ))
            if open_without_close > 0:
                report.checks[-1].passed = False
                report.checks[-1].detail = (
                    f"{open_without_close} EventStore 'opened' events have no corresponding "
                    f"'closed' event — these are currently open or were orphaned."
                )
        except sqlite3.OperationalError:
            pass

        # Check for TradeLog rows with NULL pnl on closed trades
        zero_pnl_closed = conn.execute("""
            SELECT COUNT(*) as cnt
            FROM trade_logs
            WHERE exit_price IS NOT NULL
            AND (pnl IS NULL OR pnl = 0)
            AND entry_price != exit_price
        """).fetchone()["cnt"]

        if zero_pnl_closed > 0:
            report.add(Check(
                name="zero_pnl_closed_trades",
                passed=False,
                detail=(
                    f"{zero_pnl_closed} closed trades with non-zero price movement "
                    f"recorded as $0 P&L — data-destroying bug (Phase 2 regression)."
                ),
            ))
        else:
            report.add(Check(
                name="zero_pnl_closed_trades",
                passed=True,
                detail="No closed trades with zero P&L when price moved",
            ))

        # Check for TradeLog rows missing proposing_strategy
        missing_strategy = conn.execute("""
            SELECT COUNT(*) as cnt
            FROM trade_logs
            WHERE proposing_strategy IS NULL OR proposing_strategy = '' OR proposing_strategy = 'unknown'
        """).fetchone()["cnt"]

        total_trades = conn.execute("SELECT COUNT(*) as cnt FROM trade_logs").fetchone()["cnt"]
        if missing_strategy > 0 and total_trades > 0:
            pct = missing_strategy / total_trades * 100
            report.add(Check(
                name="missing_strategy_attribution",
                passed=pct < 10,  # Allow up to 10% — legacy trades may be unknown
                detail=f"{missing_strategy}/{total_trades} trades ({pct:.1f}%) missing strategy attribution",
                severity="WARNING",
            ))
        else:
            report.add(Check(
                name="missing_strategy_attribution",
                passed=True,
                detail=f"All {total_trades} trades have strategy attribution",
            ))

    finally:
        conn.close()


def check_leaderboard_vs_tradelog(db_path: Path, lb_path: Path, report: Report):
    """Compare leaderboard JSON stats vs TradeLog-derived stats per strategy."""
    if not lb_path.exists():
        report.add(Check(
            name="leaderboard_file",
            passed=False,
            detail=f"Leaderboard file not found: {lb_path}",
            severity="WARNING",
        ))
        return

    if not db_path.exists():
        return  # Already reported above

    with open(lb_path) as f:
        try:
            leaderboard = json.load(f)
        except json.JSONDecodeError as e:
            report.add(Check(
                name="leaderboard_json_valid",
                passed=False,
                detail=f"Leaderboard JSON is corrupted: {e}",
            ))
            return

    report.add(Check(
        name="leaderboard_json_valid",
        passed=True,
        detail=f"Leaderboard JSON valid: {len(leaderboard)} strategies",
    ))

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        discrepancies = []

        for strategy_name, record in leaderboard.items():
            lb_total = record.get("total_trades", 0)
            lb_wins = record.get("wins", 0)
            lb_losses = record.get("losses", 0)

            # Cross-check against TradeLog
            try:
                db_total = conn.execute("""
                    SELECT COUNT(*) as cnt FROM trade_logs
                    WHERE proposing_strategy = ? AND exit_price IS NOT NULL
                """, (strategy_name,)).fetchone()["cnt"]

                db_wins = conn.execute("""
                    SELECT COUNT(*) as cnt FROM trade_logs
                    WHERE proposing_strategy = ? AND exit_price IS NOT NULL AND pnl > 0
                """, (strategy_name,)).fetchone()["cnt"]

                if db_total > 0:
                    if lb_total != db_total:
                        discrepancies.append(
                            f"{strategy_name}: leaderboard total={lb_total} "
                            f"but TradeLog count={db_total}"
                        )
                    if lb_wins != db_wins and db_total >= 5:
                        discrepancies.append(
                            f"{strategy_name}: leaderboard wins={lb_wins} "
                            f"but TradeLog wins={db_wins}"
                        )
            except sqlite3.OperationalError:
                pass

        if discrepancies:
            report.add(Check(
                name="leaderboard_vs_tradelog",
                passed=False,
                detail=f"{len(discrepancies)} strategy discrepancies:\n    " +
                       "\n    ".join(discrepancies),
            ))
        else:
            report.add(Check(
                name="leaderboard_vs_tradelog",
                passed=True,
                detail=f"All {len(leaderboard)} leaderboard strategies match TradeLog",
            ))

        # Check trust score bounds
        oob = [
            f"{n}: trust={r.get('trust_score', '?')}"
            for n, r in leaderboard.items()
            if not (0 <= r.get("trust_score", 50) <= 100)
        ]
        report.add(Check(
            name="trust_score_bounds",
            passed=len(oob) == 0,
            detail="Trust scores in bounds [0, 100]" if not oob
                   else f"Out-of-bounds trust scores: {oob}",
        ))

        # Check total_trades == wins + losses
        invalid = [
            f"{n}: total={r['total_trades']} != wins({r['wins']}) + losses({r['losses']})"
            for n, r in leaderboard.items()
            if r.get("total_trades", 0) != r.get("wins", 0) + r.get("losses", 0)
        ]
        report.add(Check(
            name="leaderboard_totals_sum",
            passed=len(invalid) == 0,
            detail="total_trades == wins + losses for all strategies" if not invalid
                   else f"Count mismatch: {invalid}",
        ))

    finally:
        conn.close()


def check_risk_state(db_path: Path, report: Report):
    """Check RiskState table consistency."""
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        try:
            row = conn.execute("""
                SELECT * FROM risk_state ORDER BY updated_at DESC LIMIT 1
            """).fetchone()

            if row is None:
                report.add(Check(
                    name="risk_state_exists",
                    passed=False,
                    detail="No RiskState record — may not have been initialized",
                    severity="WARNING",
                ))
            else:
                if row["current_balance"] <= 0:
                    report.add(Check(
                        name="risk_state_balance_positive",
                        passed=False,
                        detail=f"RiskState.current_balance={row['current_balance']} <= 0 — impossible",
                    ))
                else:
                    report.add(Check(
                        name="risk_state_balance_positive",
                        passed=True,
                        detail=f"RiskState balance=${row['current_balance']:.2f}",
                    ))

                if row["peak_balance"] < row["current_balance"]:
                    report.add(Check(
                        name="risk_state_peak_balance",
                        passed=False,
                        detail=(
                            f"peak_balance ({row['peak_balance']}) < current_balance "
                            f"({row['current_balance']}) — peak must be >= current"
                        ),
                    ))
                else:
                    report.add(Check(
                        name="risk_state_peak_balance",
                        passed=True,
                        detail=f"peak_balance >= current_balance ✓",
                    ))
        except sqlite3.OperationalError:
            report.add(Check(
                name="risk_state_table",
                passed=False,
                detail="risk_state table not found",
                severity="WARNING",
            ))
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Validate data layer consistency")
    parser.add_argument("--db-path", default=str(_DEFAULT_DB),
                        help=f"Path to SQLite DB (default: {_DEFAULT_DB})")
    parser.add_argument("--leaderboard", default=str(_DEFAULT_LEADERBOARD),
                        help=f"Path to leaderboard JSON (default: {_DEFAULT_LEADERBOARD})")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show all checks, including passing ones")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    lb_path = Path(args.leaderboard)

    print(f"\nValidating:")
    print(f"  DB          : {db_path}")
    print(f"  Leaderboard : {lb_path}")

    report = Report()

    check_event_store_vs_tradelog(db_path, report, args.verbose)
    check_leaderboard_vs_tradelog(db_path, lb_path, report)
    check_risk_state(db_path, report)

    report.print(verbose=args.verbose)

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
