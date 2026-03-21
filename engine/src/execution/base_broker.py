"""
Broker Abstraction Layer — unified interface for all execution backends.

Every broker (paper, CoinDCX, MT5) implements this interface.
The engine doesn't care WHERE the trade executes — it just calls
place_order(), get_positions(), get_balance().

This means switching from paper trading to CoinDCX live is a one-line
config change: BROKER=coindcx in .env.

SUPPORTED BROKERS:
- paper: Simulated trading (default, no real money)
- coindcx: CoinDCX exchange (Indian crypto, INR/USDT)
- mt5: MetaTrader 5 (FundingPips prop firm, requires Windows VPS)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class BrokerOrder:
    """Standardized order representation across all brokers."""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float = 0.0            # 0 = market order
    stop_loss: float = 0.0
    take_profit: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    filled_price: float = 0.0
    filled_quantity: float = 0.0
    fee: float = 0.0
    created_at: datetime | None = None
    filled_at: datetime | None = None
    broker_order_id: str = ""     # The broker's internal order ID
    leverage: float = 1.0
    sl_order_id: str = ""         # Broker order ID for stop-loss order
    tp_order_id: str = ""         # Broker order ID for take-profit order

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "status": self.status.value,
            "filled_price": self.filled_price,
            "fee": round(self.fee, 6),
            "leverage": self.leverage,
            "broker_order_id": self.broker_order_id,
            "sl_order_id": self.sl_order_id,
            "tp_order_id": self.tp_order_id,
        }


@dataclass
class BrokerPosition:
    """Standardized position representation."""
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    leverage: float = 1.0
    liquidation_price: float = 0.0
    margin_used: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealized_pnl": round(self.unrealized_pnl, 4),
            "leverage": self.leverage,
            "liquidation_price": round(self.liquidation_price, 2),
            "margin_used": round(self.margin_used, 4),
        }


class BaseBroker(ABC):
    """
    Abstract broker interface. All execution backends implement this.

    To add a new broker:
    1. Create a class that inherits BaseBroker
    2. Implement all abstract methods
    3. Add it to the broker factory in get_broker()
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Broker identifier (e.g., 'paper', 'coindcx', 'mt5')."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the broker connection is active."""
        ...

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the broker. Returns True if successful."""
        ...

    @abstractmethod
    async def disconnect(self):
        """Close the broker connection."""
        ...

    @abstractmethod
    async def get_balance(self) -> dict:
        """
        Get account balance.
        Returns: {currency: amount, available: amount, total: amount}
        """
        ...

    @abstractmethod
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
        """Place an order. Returns the order with broker_order_id set."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str = "") -> bool:
        """Cancel a pending order. Returns True if successful."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]:
        """Get all open positions."""
        ...

    @abstractmethod
    async def close_position(self, symbol: str) -> BrokerOrder | None:
        """Close an open position. Returns the closing order."""
        ...

    async def get_status(self) -> dict:
        """Get broker connection status for the dashboard."""
        balance = {}
        positions = []
        try:
            if self.is_connected:
                balance = await self.get_balance()
                positions = [p.to_dict() for p in await self.get_positions()]
        except Exception:
            pass

        return {
            "broker": self.name,
            "connected": self.is_connected,
            "balance": balance,
            "open_positions": len(positions),
            "positions": positions,
        }
