#!/usr/bin/env python3
"""
Migration: Remove 'unknown' strategy from leaderboard.

The 'unknown' strategy contains 9 trades from before we implemented
proposing_strategy tracking. Since we can't reliably attribute these
to specific strategies, we remove the entry to clean up the leaderboard.

Run on VM: python3 scripts/migrate_unknown_strategy.py
"""

import json
import os
from pathlib import Path

def main():
    # Find leaderboard file
    repo_root = Path(__file__).parent.parent.parent
    leaderboard_path = repo_root / "engine" / "data" / "strategy_leaderboard.json"

    if not leaderboard_path.exists():
        print(f"Leaderboard file not found at {leaderboard_path}")
        return

    # Load current leaderboard
    with open(leaderboard_path) as f:
        data = json.load(f)

    # Check if 'unknown' exists
    if "unknown" not in data:
        print("No 'unknown' strategy found in leaderboard. Nothing to migrate.")
        return

    unknown = data["unknown"]
    print(f"Found 'unknown' strategy:")
    print(f"  Trades: {unknown['total_trades']}")
    print(f"  W/L: {unknown['wins']}/{unknown['losses']}")
    print(f"  PnL: ${unknown['total_pnl']:.2f}")
    print(f"  Trust Score: {unknown['trust_score']}")

    # Backup
    backup_path = leaderboard_path.with_suffix(".json.bak")
    with open(backup_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nBackup created: {backup_path}")

    # Remove unknown
    del data["unknown"]

    # Save updated leaderboard
    with open(leaderboard_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n✅ Removed 'unknown' strategy from leaderboard")
    print(f"   Remaining strategies: {len(data)}")

if __name__ == "__main__":
    main()
