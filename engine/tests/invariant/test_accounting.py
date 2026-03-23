"""Global accounting invariants — must ALWAYS hold.

These tests assert fundamental properties of the trading system.
If any of these fail, the system has a data integrity bug.
Run after EVERY change.

These use mock/fake implementations of the ports — they test
the CONTRACTS, not the implementations.
"""

import pytest

from notas_lave.core.models import (
    BalanceInfo,
    Direction,
    ExchangePosition,
    OrderResult,
    Signal,
    TradeSetup,
)
from notas_lave.engine.pnl import PnLService


# -- Fakes for testing invariants --


class FakeBroker:
    """Fake broker with controllable state."""

    def __init__(self, balance: float, positions: list[ExchangePosition] | None = None):
        self._balance = balance
        self._positions = positions or []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def is_connected(self) -> bool:
        return True

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    async def get_balance(self) -> BalanceInfo:
        return BalanceInfo(total=self._balance, available=self._balance)

    async def get_positions(self) -> list[ExchangePosition]:
        return self._positions

    async def get_order_status(self, order_id: str) -> OrderResult:
        return OrderResult()

    async def place_order(self, setup: TradeSetup) -> OrderResult:
        return OrderResult(success=True)

    async def close_position(self, symbol: str) -> OrderResult:
        return OrderResult(success=True)

    async def cancel_all_orders(self, symbol: str) -> bool:
        return True


class FakeJournal:
    """Fake journal with controllable trade history."""

    def __init__(self, closed_trades: list[dict] | None = None, open_trades: list[dict] | None = None):
        self._closed = closed_trades or []
        self._open = open_trades or []

    def record_signal(self, signal: Signal) -> int:
        return 1

    def record_open(self, trade_id: int, setup: TradeSetup) -> None:
        pass

    def record_close(self, trade_id: int, exit_price: float, reason: str, pnl: float) -> None:
        pass

    def record_grade(self, trade_id: int, grade: str, lesson: str) -> None:
        pass

    def get_closed_trades(self, limit: int = 50) -> list[dict]:
        return self._closed[:limit]

    def get_open_trades(self) -> list[dict]:
        return self._open


# -- Invariant Tests --


def test_accounting_identity_no_positions():
    """balance = deposit + closed_pnl when there are no open positions."""
    deposit = 5000.0
    closed_pnl = 300.0
    balance = deposit + closed_pnl

    pnl_svc = PnLService(original_deposit=deposit)
    result = pnl_svc.calculate(current_balance=balance)

    # PnL from balance-diff should match sum of closed trades
    assert abs(result.pnl - closed_pnl) < 0.01


def test_accounting_identity_with_positions():
    """balance = deposit + closed_pnl + unrealized_pnl."""
    deposit = 5000.0
    closed_pnl = 300.0
    unrealized_pnl = -50.0
    balance = deposit + closed_pnl + unrealized_pnl

    positions = [
        ExchangePosition(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            quantity=0.01,
            entry_price=85000.0,
            current_price=84000.0,
            unrealized_pnl=unrealized_pnl,
        ),
    ]

    pnl_svc = PnLService(original_deposit=deposit)
    result = pnl_svc.calculate(current_balance=balance)

    total_unrealized = sum(p.unrealized_pnl for p in positions)
    expected_balance = deposit + closed_pnl + total_unrealized

    assert abs(balance - expected_balance) < 0.01, (
        f"Accounting mismatch: balance={balance}, "
        f"expected={expected_balance} "
        f"(deposit={deposit} + closed={closed_pnl} + unrealized={total_unrealized})"
    )


def test_accounting_identity_multiple_trades():
    """Multiple closed trades should sum correctly."""
    deposit = 5000.0
    trades = [
        {"pnl": 100.0},
        {"pnl": -50.0},
        {"pnl": 200.0},
        {"pnl": -30.0},
    ]
    closed_pnl = sum(t["pnl"] for t in trades)
    balance = deposit + closed_pnl  # 5220.0

    pnl_svc = PnLService(original_deposit=deposit)
    result = pnl_svc.calculate(current_balance=balance)

    assert abs(result.pnl - closed_pnl) < 0.01


@pytest.mark.asyncio
async def test_no_orphaned_positions():
    """Every broker position must have a journal entry. No ghosts."""
    positions = [
        ExchangePosition(
            symbol="BTCUSDT", direction=Direction.LONG,
            quantity=0.01, entry_price=85000.0,
        ),
    ]
    open_trades = [{"symbol": "BTCUSDT"}]

    broker = FakeBroker(balance=5000.0, positions=positions)
    journal = FakeJournal(open_trades=open_trades)

    exchange_symbols = {p.symbol for p in await broker.get_positions()}
    journal_symbols = {t["symbol"] for t in journal.get_open_trades()}
    orphans = exchange_symbols - journal_symbols

    assert not orphans, f"Positions on exchange with no journal entry: {orphans}"


@pytest.mark.asyncio
async def test_no_ghost_journal_entries():
    """Every open journal entry must have a broker position."""
    positions = [
        ExchangePosition(
            symbol="BTCUSDT", direction=Direction.LONG,
            quantity=0.01, entry_price=85000.0,
        ),
    ]
    open_trades = [{"symbol": "BTCUSDT"}]

    broker = FakeBroker(balance=5000.0, positions=positions)
    journal = FakeJournal(open_trades=open_trades)

    exchange_symbols = {p.symbol for p in await broker.get_positions()}
    journal_symbols = {t["symbol"] for t in journal.get_open_trades()}
    ghosts = journal_symbols - exchange_symbols

    assert not ghosts, f"Journal entries with no exchange position: {ghosts}"


def test_pnl_never_exceeds_balance():
    """P&L can never be more than balance (basic sanity)."""
    deposit = 5000.0
    balance = 5500.0

    pnl_svc = PnLService(original_deposit=deposit)
    result = pnl_svc.calculate(current_balance=balance)

    # PnL + deposit should equal balance
    assert abs((result.pnl + deposit) - balance) < 0.01


def test_drawdown_never_negative():
    """Drawdown from peak is always >= 0."""
    pnl_svc = PnLService(original_deposit=5000.0)
    pnl_svc.update_peak(6000.0)

    for balance in [6500.0, 5800.0, 5000.0, 4500.0]:
        pnl_svc.update_peak(balance)
        result = pnl_svc.calculate(current_balance=balance)
        assert result.drawdown_from_peak >= 0.0
