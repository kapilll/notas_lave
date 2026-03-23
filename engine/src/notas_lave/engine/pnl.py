"""PnLService — the only way to calculate P&L.

P&L = current_balance - original_deposit. Period.
No formula, no running counters, no sync needed.

The broker balance is the single source of truth. We just
subtract what was deposited to get the profit/loss.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PnLResult:
    pnl: float
    pnl_pct: float
    original_deposit: float
    current_balance: float
    drawdown_from_peak: float = 0.0
    drawdown_from_peak_pct: float = 0.0


class PnLService:
    def __init__(self, original_deposit: float) -> None:
        self._original_deposit = original_deposit
        self._peak_balance = original_deposit

    def update_peak(self, balance: float) -> None:
        if balance > self._peak_balance:
            self._peak_balance = balance

    def calculate(self, current_balance: float) -> PnLResult:
        pnl = current_balance - self._original_deposit
        pnl_pct = (
            (pnl / self._original_deposit * 100)
            if self._original_deposit > 0
            else 0.0
        )

        drawdown = max(0.0, self._peak_balance - current_balance)
        drawdown_pct = (
            (drawdown / self._peak_balance * 100)
            if self._peak_balance > 0
            else 0.0
        )

        return PnLResult(
            pnl=pnl,
            pnl_pct=pnl_pct,
            original_deposit=self._original_deposit,
            current_balance=current_balance,
            drawdown_from_peak=drawdown,
            drawdown_from_peak_pct=drawdown_pct,
        )
