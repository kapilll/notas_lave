"""MT5 Broker — IBroker stub for MetaTrader 5 (FundingPips).

Requires Windows + MetaTrader5 package. On macOS/Linux all methods
return empty/False gracefully — never crashes.
"""

import logging
import os

from ..core.models import (
    BalanceInfo,
    Direction,
    ExchangePosition,
    OrderResult,
    TradeSetup,
)
from .registry import register_broker

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


@register_broker("mt5")
class MT5Broker:
    """MetaTrader 5 — FundingPips prop firm trading. Windows only."""

    def __init__(self) -> None:
        self._connected = False

    @property
    def name(self) -> str:
        return "mt5"

    @property
    def is_connected(self) -> bool:
        return self._connected and MT5_AVAILABLE

    async def connect(self) -> bool:
        if not MT5_AVAILABLE:
            logger.warning("MetaTrader5 not available (requires Windows)")
            return False

        login = os.environ.get("MT5_LOGIN", "")
        password = os.environ.get("MT5_PASSWORD", "")
        server = os.environ.get("MT5_SERVER", "")

        if not all([login, password, server]):
            logger.error("MT5 credentials not configured")
            return False

        try:
            if not mt5.initialize():
                return False
            if not mt5.login(int(login), password=password, server=server):
                mt5.shutdown()
                return False
            self._connected = True
            return True
        except Exception as e:
            logger.error("MT5 connection error: %s", e)
            return False

    async def disconnect(self) -> None:
        if MT5_AVAILABLE and self._connected:
            mt5.shutdown()
        self._connected = False

    async def get_balance(self) -> BalanceInfo:
        if not self.is_connected:
            return BalanceInfo(total=0, available=0, currency="USD")

        info = mt5.account_info()
        return BalanceInfo(
            total=round(info.balance, 2),
            available=round(info.margin_free, 2),
            currency="USD",
        )

    async def get_positions(self) -> list[ExchangePosition]:
        if not self.is_connected:
            return []

        mt5_pos = mt5.positions_get()
        if not mt5_pos:
            return []

        return [
            ExchangePosition(
                symbol=p.symbol,
                direction=Direction.LONG if p.type == 0 else Direction.SHORT,
                quantity=p.volume,
                entry_price=p.price_open,
                current_price=p.price_current,
                unrealized_pnl=p.profit,
            )
            for p in mt5_pos
        ]

    async def get_order_status(self, order_id: str) -> OrderResult:
        return OrderResult(order_id=order_id, success=self.is_connected)

    async def place_order(self, setup: TradeSetup) -> OrderResult:
        if not self.is_connected:
            return OrderResult(success=False, error="MT5 not available")

        mt5_type = mt5.ORDER_TYPE_BUY if setup.direction == Direction.LONG else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(setup.symbol)
        if not tick:
            return OrderResult(success=False, error=f"No tick data for {setup.symbol}")

        price = tick.ask if setup.direction == Direction.LONG else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": setup.symbol,
            "volume": setup.position_size,
            "type": mt5_type,
            "price": price,
            "deviation": 20,
            "magic": 234000,
            "comment": "notas_lave_v2",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if setup.stop_loss > 0:
            request["sl"] = setup.stop_loss
        if setup.take_profit > 0:
            request["tp"] = setup.take_profit

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return OrderResult(
                order_id=str(result.order),
                success=True,
                filled_price=result.price,
                filled_quantity=setup.position_size,
            )

        error = result.comment if result else "Unknown"
        return OrderResult(success=False, error=error)

    async def close_position(self, symbol: str) -> OrderResult:
        if not self.is_connected:
            return OrderResult(success=False, error="MT5 not available")

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return OrderResult(success=False, error=f"No position for {symbol}")

        pos = positions[0]
        close_dir = Direction.SHORT if pos.type == 0 else Direction.LONG
        setup = TradeSetup(
            symbol=symbol, direction=close_dir,
            entry_price=0, stop_loss=0, take_profit=0,
            position_size=pos.volume,
        )
        return await self.place_order(setup)

    async def cancel_all_orders(self, symbol: str) -> bool:
        return True
