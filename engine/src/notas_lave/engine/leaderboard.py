"""Strategy Leaderboard — tracks per-strategy performance in the arena.

Each strategy competes independently. The leaderboard tracks:
- Win rate, P&L, profit factor, Sharpe ratio
- Trust score (earned from results, not given)
- Dynamic threshold (proven strategies get more opportunities)
- Streak tracking (consecutive wins/losses)

Trust score determines if a strategy is allowed to trade:
- Start at 50 (neutral)
- Win: +3 (max 100)
- Loss: -5 (asymmetric — losses hurt more)
- < 20: SUSPENDED
- > 70: gets lower threshold (more chances)
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Trust score adjustments
TRUST_WIN_BOOST = 3.0
TRUST_LOSS_PENALTY = 5.0
TRUST_MAX = 100.0
TRUST_MIN = 0.0
TRUST_SUSPEND_THRESHOLD = 20.0

# Dynamic threshold tiers
THRESHOLD_BASE = 65.0
THRESHOLD_PROVEN = 55.0      # trust > 80
THRESHOLD_STANDARD = 65.0    # trust 50-80
THRESHOLD_CAUTION = 75.0     # trust 30-50
# trust < 30: SUSPENDED


@dataclass
class StrategyRecord:
    """Performance record for a single strategy."""
    name: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    current_streak: int = 0  # positive = wins, negative = losses
    trust_score: float = 50.0
    is_active: bool = True
    last_trade_at: str = ""

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades * 100

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return self.gross_profit if self.gross_profit > 0 else 0.0
        return abs(self.gross_profit / self.gross_loss)

    @property
    def expectancy(self) -> float:
        """Average P&L per trade."""
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl / self.total_trades

    @property
    def min_signal_score(self) -> float:
        """Dynamic threshold based on trust score."""
        if self.trust_score >= 80:
            return THRESHOLD_PROVEN
        elif self.trust_score >= 50:
            return THRESHOLD_STANDARD
        elif self.trust_score >= 30:
            return THRESHOLD_CAUTION
        else:
            return 100.0  # effectively suspended

    @property
    def status(self) -> str:
        if not self.is_active:
            return "suspended"
        if self.trust_score >= 80:
            return "proven"
        elif self.trust_score >= 50:
            return "standard"
        elif self.trust_score >= 30:
            return "caution"
        else:
            return "suspended"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["win_rate"] = round(self.win_rate, 1)
        d["profit_factor"] = round(self.profit_factor, 2)
        d["expectancy"] = round(self.expectancy, 4)
        d["min_signal_score"] = self.min_signal_score
        d["status"] = self.status
        return d


class StrategyLeaderboard:
    """Manages all strategy records and persists to disk."""

    def __init__(self, persist_path: str | None = None):
        self._records: dict[str, StrategyRecord] = {}
        self._persist_path = persist_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "data", "strategy_leaderboard.json",
        )
        self._load()

    def _load(self):
        """Load leaderboard from disk."""
        try:
            if os.path.exists(self._persist_path):
                with open(self._persist_path) as f:
                    data = json.load(f)
                for name, record_data in data.items():
                    self._records[name] = StrategyRecord(**record_data)
                logger.info("Loaded leaderboard: %d strategies", len(self._records))
        except Exception as e:
            logger.warning("Failed to load leaderboard: %s", e)

    def _save(self):
        """Persist leaderboard to disk — atomic write (temp + rename).

        C7 FIX: Prevents JSON corruption on crash. If process dies mid-write,
        only the .tmp file is damaged — the real file is untouched.
        """
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            data = {name: asdict(rec) for name, rec in self._records.items()}
            tmp_path = self._persist_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._persist_path)
        except Exception as e:
            logger.warning("Failed to save leaderboard: %s", e)

    def get_or_create(self, name: str) -> StrategyRecord:
        """Get existing record or create new one for a strategy."""
        if name not in self._records:
            self._records[name] = StrategyRecord(name=name)
        return self._records[name]

    def record_win(self, name: str, pnl: float):
        """Record a winning trade for a strategy."""
        rec = self.get_or_create(name)
        rec.total_trades += 1
        rec.wins += 1
        rec.total_pnl += pnl
        rec.gross_profit += pnl
        rec.best_trade = max(rec.best_trade, pnl)

        # Update averages
        rec.avg_win = rec.gross_profit / rec.wins if rec.wins > 0 else 0

        # Streak
        if rec.current_streak >= 0:
            rec.current_streak += 1
        else:
            rec.current_streak = 1
        rec.consecutive_wins = max(rec.consecutive_wins, rec.current_streak)
        rec.consecutive_losses = 0  # reset on win

        # Trust score
        rec.trust_score = min(TRUST_MAX, rec.trust_score + TRUST_WIN_BOOST)
        if rec.trust_score >= TRUST_SUSPEND_THRESHOLD:
            rec.is_active = True

        rec.last_trade_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def record_loss(self, name: str, pnl: float):
        """Record a losing trade for a strategy."""
        rec = self.get_or_create(name)
        rec.total_trades += 1
        rec.losses += 1
        rec.total_pnl += pnl  # pnl is negative
        rec.gross_loss += pnl  # accumulates as negative
        rec.worst_trade = min(rec.worst_trade, pnl)

        # Update averages
        rec.avg_loss = rec.gross_loss / rec.losses if rec.losses > 0 else 0

        # Streak
        if rec.current_streak <= 0:
            rec.current_streak -= 1
        else:
            rec.current_streak = -1
        rec.consecutive_losses = max(rec.consecutive_losses, abs(rec.current_streak))

        # Trust score
        rec.trust_score = max(TRUST_MIN, rec.trust_score - TRUST_LOSS_PENALTY)
        if rec.trust_score < TRUST_SUSPEND_THRESHOLD:
            rec.is_active = False
            logger.warning("Strategy %s SUSPENDED (trust=%.0f)", name, rec.trust_score)

        rec.last_trade_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def can_trade(self, name: str, signal_score: float) -> bool:
        """Check if a strategy is allowed to trade with this signal score."""
        rec = self.get_or_create(name)
        if not rec.is_active:
            return False
        return signal_score >= rec.min_signal_score

    def get_leaderboard(self, sort_by: str = "trust_score") -> list[dict]:
        """Get all strategies sorted by metric."""
        records = [rec.to_dict() for rec in self._records.values()]
        reverse = True  # higher is better for most metrics
        if sort_by == "consecutive_losses":
            reverse = False
        records.sort(key=lambda r: r.get(sort_by, 0), reverse=reverse)
        return records

    def get_strategy(self, name: str) -> dict | None:
        """Get single strategy record."""
        if name in self._records:
            return self._records[name].to_dict()
        return None

    def get_active_strategies(self) -> list[str]:
        """Get names of all active (non-suspended) strategies."""
        return [name for name, rec in self._records.items() if rec.is_active]

    def set_trust(self, name: str, trust: float) -> float:
        """Directly set a strategy's trust score (admin action).

        Useful for manually rehabilitating a strategy that was locked out by
        variance (e.g. 3 consecutive losses dropping trust below the trading threshold)
        when historical data shows it still has positive expectancy.
        """
        rec = self.get_or_create(name)
        rec.trust_score = max(TRUST_MIN, min(TRUST_MAX, trust))
        rec.is_active = rec.trust_score >= TRUST_SUSPEND_THRESHOLD
        self._save()
        logger.info("Admin set trust: %s → %.1f (is_active=%s)", name, rec.trust_score, rec.is_active)
        return rec.trust_score

    def reset_strategy(self, name: str):
        """Reset a strategy's record (admin action)."""
        if name in self._records:
            self._records[name] = StrategyRecord(name=name)
            self._save()

    def seed_from_backtest(self, backtest_result) -> dict[str, float]:
        """Seed trust scores from a backtest result's strategy_stats.

        Trust = win_rate (base 0-100)
          +10 if profit_factor > 2.0
          +5  if profit_factor > 1.5
          +5  if total_trades >= 50
          -20 if net_pnl < 0
        Clamped to 0-100.

        Returns: {strategy_name: seeded_trust_score}
        """
        seeded: dict[str, float] = {}
        for name, stats in backtest_result.strategy_stats.items():
            trust = stats.get("win_rate", 50.0)

            pf = stats.get("profit_factor", 0.0)
            if pf > 2.0:
                trust += 10
            elif pf > 1.5:
                trust += 5

            if stats.get("trades", 0) >= 50:
                trust += 5

            if stats.get("pnl", 0) < 0:
                trust -= 20

            trust = max(TRUST_MIN, min(TRUST_MAX, trust))

            rec = self.get_or_create(name)
            rec.trust_score = trust
            rec.is_active = trust >= TRUST_SUSPEND_THRESHOLD
            seeded[name] = trust

        self._save()
        logger.info("Seeded trust scores from backtest: %s",
                     {k: round(v, 1) for k, v in seeded.items()})
        return seeded
