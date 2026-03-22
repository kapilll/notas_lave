"""Lab Risk Manager -- permissive, log-only, never blocks trades.

The Lab's job is to LEARN, not protect capital. Every qualifying signal
should result in a trade so we generate maximum learning data.
Risk is logged for analysis but never enforced.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class LabDailyStats:
    date: str = ""
    trades: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


class LabRiskManager:
    """Never blocks a trade. Logs everything for analysis."""

    def __init__(self, starting_balance: float = 100_000.0):
        self.starting_balance = starting_balance
        self.original_starting_balance = starting_balance
        self.current_balance = starting_balance
        self.total_pnl = 0.0
        self.peak_balance = starting_balance
        self.daily_stats: dict[str, LabDailyStats] = {}
        self._unrealized_pnl = 0.0

    def validate_trade(self, setup, open_positions=None) -> tuple[bool, list[str]]:
        """Always approves. Logs what production would have said."""
        from ..data.instruments import get_instrument
        spec = get_instrument(setup.symbol)
        potential_loss = abs(setup.entry_price - setup.stop_loss) * setup.position_size * spec.contract_size

        warnings = []
        # Log what would have been rejected in production
        if self.total_pnl - potential_loss < -(self.starting_balance * 0.10):
            warnings.append("WOULD_REJECT_PROD: Total DD would breach 10%")

        logger.info(
            "[LAB RISK] APPROVED: %s %s size=%s potential_loss=$%.2f %s",
            setup.symbol, setup.direction.value,
            setup.position_size, potential_loss,
            f"(prod would reject: {'; '.join(warnings)})" if warnings else "",
        )
        return True, []  # Always approve

    def update_unrealized_pnl(self, unrealized: float):
        self._unrealized_pnl = unrealized

    def record_trade_result(self, pnl: float):
        self.total_pnl += pnl
        self.current_balance += pnl
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

        today = datetime.now(timezone.utc).date().isoformat()
        if today not in self.daily_stats:
            self.daily_stats[today] = LabDailyStats(date=today)
        self.daily_stats[today].trades += 1
        self.daily_stats[today].realized_pnl += pnl

    def _get_today_stats(self):
        today = datetime.now(timezone.utc).date().isoformat()
        if today not in self.daily_stats:
            self.daily_stats[today] = LabDailyStats(date=today)
        return self.daily_stats[today]

    def get_status(self) -> dict:
        today = self._get_today_stats()
        return {
            "mode": "lab",
            "balance": round(self.current_balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "daily_pnl": round(today.realized_pnl, 2),
            "trades_today": today.trades,
            "can_trade": True,  # Always
            "is_halted": False,  # Never
        }
