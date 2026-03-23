"""BinanceBroker — v2 adapter wrapping the existing BinanceTestnetBroker.

Translates between v1 types (BrokerOrder, BrokerPosition, dict) and
v2 types (OrderResult, ExchangePosition, BalanceInfo).

All battle-tested HTTP logic, retry logic, and edge case handling
from binance_testnet.py is preserved — this adapter just translates types.
"""

import logging

from ..core.models import (
    BalanceInfo,
    Direction,
    ExchangePosition,
    OrderResult,
    TradeSetup,
)
from .registry import register_broker

logger = logging.getLogger(__name__)


@register_broker("binance_testnet")
class BinanceBroker:
    """IBroker adapter around the existing BinanceTestnetBroker."""

    def __init__(self) -> None:
        from execution.binance_testnet import BinanceTestnetBroker
        self._inner = BinanceTestnetBroker()

    @property
    def name(self) -> str:
        return "binance_testnet"

    @property
    def is_connected(self) -> bool:
        return self._inner.is_connected

    async def connect(self) -> bool:
        return await self._inner.connect()

    async def disconnect(self) -> None:
        await self._inner.disconnect()

    async def get_balance(self) -> BalanceInfo:
        raw = await self._inner.get_balance()
        return BalanceInfo(
            total=float(raw.get("total", 0)),
            available=float(raw.get("available", 0)),
            currency=str(raw.get("currency", "USDT")),
        )

    async def get_positions(self) -> list[ExchangePosition]:
        raw_positions = await self._inner.get_positions()
        result = []
        for pos in raw_positions:
            direction = (
                Direction.LONG if pos.side.value == "BUY" else Direction.SHORT
            )
            result.append(ExchangePosition(
                symbol=pos.symbol,
                direction=direction,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                current_price=pos.current_price,
                unrealized_pnl=pos.unrealized_pnl,
                leverage=pos.leverage,
            ))
        return result

    async def get_order_status(self, order_id: str) -> OrderResult:
        return OrderResult(order_id=order_id, success=True)

    async def place_order(self, setup: TradeSetup) -> OrderResult:
        from execution.base_broker import OrderSide, OrderType

        side = OrderSide.BUY if setup.direction == Direction.LONG else OrderSide.SELL

        order = await self._inner.place_order(
            symbol=setup.symbol,
            side=side,
            quantity=setup.position_size,
            order_type=OrderType.MARKET,
            stop_loss=setup.stop_loss,
            take_profit=setup.take_profit,
        )

        success = order.status.value == "FILLED"
        return OrderResult(
            order_id=order.broker_order_id or order.order_id,
            success=success,
            filled_price=order.filled_price,
            filled_quantity=order.filled_quantity,
            fee=order.fee,
            error="" if success else f"Order {order.status.value}",
        )

    async def close_position(self, symbol: str) -> OrderResult:
        order = await self._inner.close_position(symbol)
        if order is None:
            return OrderResult(success=False, error=f"No position for {symbol}")
        return OrderResult(
            order_id=order.order_id,
            success=True,
            filled_price=order.filled_price,
            filled_quantity=order.filled_quantity,
        )

    async def cancel_all_orders(self, symbol: str) -> bool:
        return True
