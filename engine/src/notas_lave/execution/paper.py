"""PaperBroker — in-memory IBroker for testing and paper trading.

Fills at the requested price. No network, no database.
Fully deterministic — perfect for unit and integration tests.

Usage:
    broker = PaperBroker(initial_balance=10000.0)
    await broker.connect()
    result = await broker.place_order(setup)
"""

import uuid
from dataclasses import dataclass, field

from ..core.models import (
    BalanceInfo,
    Direction,
    ExchangePosition,
    OrderResult,
    TradeSetup,
)
from .registry import register_broker


@dataclass
class _Position:
    """Internal position tracking."""
    symbol: str
    direction: Direction
    quantity: float
    entry_price: float


@register_broker("paper")
class PaperBroker:
    """In-memory broker that simulates fills at requested prices."""

    def __init__(self, initial_balance: float = 10000.0) -> None:
        self._balance = initial_balance
        self._connected = False
        self._positions: dict[str, _Position] = {}  # symbol -> position
        self._orders: dict[str, OrderResult] = {}    # order_id -> result

    @property
    def name(self) -> str:
        return "paper"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_balance(self) -> BalanceInfo:
        return BalanceInfo(
            total=self._balance,
            available=self._balance,
            currency="USD",
        )

    async def get_positions(self) -> list[ExchangePosition]:
        return [
            ExchangePosition(
                symbol=pos.symbol,
                direction=pos.direction,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                current_price=pos.entry_price,
                unrealized_pnl=0.0,
            )
            for pos in self._positions.values()
        ]

    async def get_order_status(self, order_id: str) -> OrderResult:
        if order_id in self._orders:
            return self._orders[order_id]
        return OrderResult(order_id=order_id, success=False, error="Not found")

    async def place_order(self, setup: TradeSetup) -> OrderResult:
        order_id = uuid.uuid4().hex[:16]
        result = OrderResult(
            order_id=order_id,
            success=True,
            filled_price=setup.entry_price,
            filled_quantity=setup.position_size,
        )
        self._orders[order_id] = result

        # Track position (simple: one position per symbol)
        self._positions[setup.symbol] = _Position(
            symbol=setup.symbol,
            direction=setup.direction,
            quantity=setup.position_size,
            entry_price=setup.entry_price,
        )
        return result

    async def close_position(self, symbol: str) -> OrderResult:
        if symbol not in self._positions:
            return OrderResult(success=False, error=f"No position for {symbol}")

        pos = self._positions.pop(symbol)
        order_id = uuid.uuid4().hex[:16]
        result = OrderResult(
            order_id=order_id,
            success=True,
            filled_price=pos.entry_price,
            filled_quantity=pos.quantity,
        )
        self._orders[order_id] = result
        return result

    async def cancel_all_orders(self, symbol: str) -> bool:
        return True
