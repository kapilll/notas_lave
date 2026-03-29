"""Ports — contracts that ALL adapters must implement.

Rules:
- Business logic imports ONLY from core/ (never from execution/, data/, etc.)
- Adding a new broker = implementing IBroker in a new file
- Adding a new data source = implementing IDataProvider in a new file
- ZERO changes to any existing file
"""

from typing import Protocol, runtime_checkable

from .models import (
    BalanceInfo,
    Candle,
    ExchangePosition,
    OrderResult,
    Signal,
    TradeSetup,
)


@runtime_checkable
class IBroker(Protocol):
    """Exchange operations — read and write separated."""

    @property
    def name(self) -> str: ...

    @property
    def is_connected(self) -> bool: ...

    # Lifecycle
    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...

    # Read (safe, no side effects)
    async def get_balance(self) -> BalanceInfo: ...
    async def get_positions(self) -> list[ExchangePosition]: ...
    async def get_order_status(self, order_id: str) -> OrderResult: ...

    # Write (side effects, requires caution)
    async def place_order(self, setup: TradeSetup) -> OrderResult: ...
    async def close_position(self, symbol: str) -> OrderResult: ...
    async def cancel_all_orders(self, symbol: str) -> bool: ...


@runtime_checkable
class IDataProvider(Protocol):
    """Market data — candles and prices."""

    async def get_candles(
        self, symbol: str, timeframe: str, limit: int = 250,
    ) -> list[Candle]: ...

    async def get_current_price(self, symbol: str) -> float: ...


@runtime_checkable
class IRiskManager(Protocol):
    """Pre-trade validation — decoupled from execution."""

    def check_trade(self, setup: TradeSetup) -> tuple[bool, list[str]]: ...


@runtime_checkable
class ITradeJournal(Protocol):
    """Append-only trade journal. Never updates — only inserts events."""

    def record_signal(self, signal: Signal) -> int: ...
    def record_open(self, trade_id: int, setup: TradeSetup, context: dict | None = None) -> None: ...
    def record_close(
        self, trade_id: int, exit_price: float, reason: str, pnl: float,
    ) -> None: ...
    def record_grade(self, trade_id: int, grade: str, lesson: str) -> None: ...
    def get_closed_trades(self, limit: int = 50) -> list[dict]: ...
    def get_open_trades(self) -> list[dict]: ...


@runtime_checkable
class IStrategy(Protocol):
    """Trading strategy — stateless, testable."""

    @property
    def name(self) -> str: ...

    @property
    def category(self) -> str: ...

    def analyze(self, candles: list[Candle], symbol: str) -> Signal: ...


@runtime_checkable
class IAlerter(Protocol):
    """Notification channel."""

    async def send(self, message: str) -> bool: ...
