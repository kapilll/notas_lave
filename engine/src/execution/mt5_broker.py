"""
MetaTrader 5 Broker — connects to FundingPips for prop firm trading.

REQUIREMENTS:
- MetaTrader 5 terminal installed (Windows ONLY)
- Python MetaTrader5 package: pip install MetaTrader5
- FundingPips account credentials

WHY WINDOWS ONLY:
- The MetaTrader5 Python package uses COM/DLL bindings to the MT5 terminal
- There is NO macOS or Linux version of MT5
- Solution: Deploy on a Windows VPS (e.g., AWS EC2 Windows, Contabo VPS)
- The engine runs on the VPS, dashboard can be accessed remotely

GRACEFUL FALLBACK:
- On macOS/Linux, this module loads but all operations return False/empty
- It logs a warning but doesn't crash the engine
- This way the rest of the system works on any platform

SETUP (on Windows VPS):
1. Install MetaTrader 5 from FundingPips
2. pip install MetaTrader5
3. Set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env
4. The engine will auto-connect on startup
"""

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from .base_broker import (
    BaseBroker, BrokerOrder, BrokerPosition,
    OrderSide, OrderType, OrderStatus,
)
from ..config import config

# Try to import MetaTrader5 — only available on Windows
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


class MT5Broker(BaseBroker):
    """
    MetaTrader 5 integration for FundingPips prop firm trading.

    On macOS/Linux: all methods gracefully return empty results.
    On Windows with MT5 installed: full trading capability.
    """

    def __init__(self):
        self._connected = False

    @property
    def name(self) -> str:
        return "mt5"

    @property
    def is_connected(self) -> bool:
        if not MT5_AVAILABLE:
            return False
        return self._connected

    async def connect(self) -> bool:
        """
        Initialize MT5 terminal and login.

        Requires MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env.
        """
        if not MT5_AVAILABLE:
            logger.warning("MetaTrader5 package not available (requires Windows).")
            logger.warning("Install on Windows VPS: pip install MetaTrader5")
            return False

        login = config.mt5_login
        password = config.mt5_password
        server = config.mt5_server

        if not login or not password or not server:
            logger.error("Credentials not configured. Set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env")
            return False

        try:
            if not mt5.initialize():
                logger.error("Failed to initialize: %s", mt5.last_error())
                return False

            authorized = mt5.login(int(login), password=password, server=server)
            if not authorized:
                logger.error("Login failed: %s", mt5.last_error())
                mt5.shutdown()
                return False

            account_info = mt5.account_info()
            self._connected = True
            logger.info("Connected to %s. Balance: $%.2f", server, account_info.balance)
            return True

        except Exception as e:
            logger.error("Connection error: %s", e)
            return False

    async def disconnect(self):
        """Shutdown MT5 terminal connection."""
        if MT5_AVAILABLE and self._connected:
            mt5.shutdown()
        self._connected = False

    async def get_balance(self) -> dict:
        """Get MT5 account balance."""
        if not self.is_connected:
            return {"currency": "USD", "available": 0, "total": 0}

        info = mt5.account_info()
        return {
            "currency": "USD",
            "available": round(info.margin_free, 2),
            "total": round(info.balance, 2),
            "equity": round(info.equity, 2),
            "margin_used": round(info.margin, 2),
            "margin_level": round(info.margin_level, 2) if info.margin_level else 0,
        }

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: float = 0.0,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        leverage: float = 1.0,
    ) -> BrokerOrder:
        """
        Place an order via MT5 terminal.

        Maps our standard interface to MT5 order format.
        """
        order_id = str(uuid.uuid4())[:8]
        order = BrokerOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=leverage,
            created_at=datetime.now(timezone.utc),
        )

        if not self.is_connected:
            order.status = OrderStatus.REJECTED
            return order

        # Build MT5 order request
        mt5_type = mt5.ORDER_TYPE_BUY if side == OrderSide.BUY else mt5.ORDER_TYPE_SELL

        # Get current price for market orders
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            order.status = OrderStatus.REJECTED
            return order

        fill_price = tick.ask if side == OrderSide.BUY else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": quantity,
            "type": mt5_type,
            "price": fill_price,
            "deviation": 20,  # Max slippage in points
            "magic": 234000,  # Magic number to identify our trades
            "comment": "notas_lave",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if stop_loss > 0:
            request["sl"] = stop_loss
        if take_profit > 0:
            request["tp"] = take_profit

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            order.status = OrderStatus.FILLED
            order.broker_order_id = str(result.order)
            order.filled_price = result.price
            order.filled_quantity = quantity
            logger.info("Order filled: %s %s %s @ %s", side.value, quantity, symbol, result.price)
        else:
            order.status = OrderStatus.REJECTED
            error = result.comment if result else "Unknown error"
            logger.warning("Order rejected: %s", error)

        return order

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending MT5 order."""
        if not self.is_connected:
            return False

        try:
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": int(order_id),
            }
            result = mt5.order_send(request)
            return result and result.retcode == mt5.TRADE_RETCODE_DONE
        except Exception:
            return False

    async def get_positions(self) -> list[BrokerPosition]:
        """Get all open MT5 positions."""
        if not self.is_connected:
            return []

        mt5_positions = mt5.positions_get()
        if not mt5_positions:
            return []

        positions = []
        for pos in mt5_positions:
            positions.append(BrokerPosition(
                symbol=pos.symbol,
                side=OrderSide.BUY if pos.type == mt5.ORDER_TYPE_BUY else OrderSide.SELL,
                quantity=pos.volume,
                entry_price=pos.price_open,
                current_price=pos.price_current,
                unrealized_pnl=pos.profit,
            ))

        return positions

    async def close_position(self, symbol: str) -> BrokerOrder | None:
        """Close an MT5 position by placing an opposite market order."""
        if not self.is_connected:
            return None

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return None

        pos = positions[0]
        close_side = OrderSide.SELL if pos.type == mt5.ORDER_TYPE_BUY else OrderSide.BUY

        return await self.place_order(
            symbol=symbol,
            side=close_side,
            quantity=pos.volume,
            order_type=OrderType.MARKET,
        )
