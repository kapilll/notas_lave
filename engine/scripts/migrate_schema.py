#!/usr/bin/env python3
"""SQLite schema migration — adds columns introduced in v1.7.x and v2.0.0.

Safe to run multiple times (checks before adding each column).

Usage:
    cd engine
    ../.venv/bin/python scripts/migrate_schema.py
    ../.venv/bin/python scripts/migrate_schema.py --db-path /path/to/notas_lave.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path

_DEFAULT_DB = Path(__file__).parent.parent / "notas_lave.db"

MIGRATIONS = [
    # (column_name, DDL to add it)
    # Arena v3 columns (v1.7.0)
    ("proposing_strategy", "ALTER TABLE trade_logs ADD COLUMN proposing_strategy TEXT"),
    ("strategy_score",     "ALTER TABLE trade_logs ADD COLUMN strategy_score REAL DEFAULT 0.0"),
    ("strategy_factors",   "ALTER TABLE trade_logs ADD COLUMN strategy_factors TEXT"),
    ("competing_proposals","ALTER TABLE trade_logs ADD COLUMN competing_proposals INTEGER DEFAULT 0"),
    # Phase 2 broker-truth columns (v2.0.0)
    ("filled_price",       "ALTER TABLE trade_logs ADD COLUMN filled_price REAL"),
    ("filled_quantity",    "ALTER TABLE trade_logs ADD COLUMN filled_quantity REAL"),
    ("broker_order_id",    "ALTER TABLE trade_logs ADD COLUMN broker_order_id TEXT"),
    ("contract_size",      "ALTER TABLE trade_logs ADD COLUMN contract_size REAL DEFAULT 1.0"),
]


def migrate(db_path: Path) -> bool:
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        print("Nothing to migrate — will be created fresh on next engine start.")
        return True

    conn = sqlite3.connect(str(db_path))
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(trade_logs)").fetchall()}

        added, skipped = 0, 0
        for col_name, ddl in MIGRATIONS:
            if col_name in existing:
                print(f"  ✓ {col_name} (already exists)")
                skipped += 1
            else:
                conn.execute(ddl)
                conn.commit()
                print(f"  + {col_name} (added)")
                added += 1

        print(f"\nDone: {added} columns added, {skipped} already present.")
        return True
    except Exception as e:
        print(f"Migration failed: {e}", file=sys.stderr)
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate trade_logs schema")
    parser.add_argument("--db-path", default=str(_DEFAULT_DB))
    args = parser.parse_args()

    db_path = Path(args.db_path)
    print(f"Migrating: {db_path}\n")
    ok = migrate(db_path)
    sys.exit(0 if ok else 1)
