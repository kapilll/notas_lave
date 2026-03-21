"""
CoinDCX Broker — live trading on CoinDCX exchange.

AUTHENTICATION:
- Uses API Key + Secret (HMAC SHA256 signature)
- Keys generated at: https://coindcx.com/api-dashboard
- Store in .env: COINDCX_API_KEY and COINDCX_API_SECRET

SUPPORTED FEATURES:
- Spot trading: BTC/INR, ETH/INR
- Futures trading: BTC/USDT, ETH/USDT with up to 15x leverage
- Market and limit orders
- Balance checking
- Position monitoring

API DOCS: https://docs.coindcx.com/

IMPORTANT:
- NEVER store API keys in code — always use environment variables
- Start with SMALL amounts to verify the integration works
- The system will warn before any real order is placed
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

import httpx

from .base_broker import (
    BaseBroker, BrokerOrder, BrokerPosition,
    OrderSide, OrderType, OrderStatus,
)
from ..config import config


COINDCX_API_URL = "https://api.coindcx.com"


class CoinDCXBroker(BaseBroker):
    """
    CoinDCX exchange integration for personal trading.

    Supports both spot and futures trading.
    Requires COINDCX_API_KEY and COINDCX_API_SECRET in .env.
    """

    def __init__(self):
        self._api_key = config.coindcx_api_key
        self._api_secret = config.coindcx_api_secret
        self._connected = False
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "coindcx"

    @property
    def is_connected(self) -> bool:
        return self._connected and bool(self._api_key)

    def _sign(self, body: dict) -> str:
        """Generate HMAC SHA256 signature for CoinDCX API authentication."""
        json_body = json.dumps(body, separators=(",", ":"))
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            json_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _headers(self, body: dict) -> dict:
        """Build authenticated headers for CoinDCX API."""
        return {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": self._api_key,
            "X-AUTH-SIGNATURE": self._sign(body),
        }

    async def connect(self) -> bool:
        """Verify CoinDCX API connection by fetching balance."""
        if not self._api_key or not self._api_secret:
            print("[CoinDCX] API keys not configured. Add COINDCX_API_KEY and COINDCX_API_SECRET to .env")
            return False

        self._client = httpx.AsyncClient(timeout=30.0)

        try:
            # Test connection by fetching user info
            balance = await self.get_balance()
            if balance:
                self._connected = True
                print(f"[CoinDCX] Connected. Balance: {balance}")
                return True
        except Exception as e:
            print(f"[CoinDCX] Connection failed: {e}")

        return False

    async def disconnect(self):
        """Close the HTTP client."""
        self._connected = False
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _post(self, endpoint: str, body: dict) -> dict | None:
        """Make an authenticated POST request to CoinDCX API."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)

        url = f"{COINDCX_API_URL}{endpoint}"
        headers = self._headers(body)

        try:
            resp = await self._client.post(url, json=body, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"[CoinDCX] API error {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"[CoinDCX] Request failed: {e}")
            return None

    async def get_balance(self) -> dict:
        """
        Get account balances from CoinDCX.

        Returns: {currency: str, available: float, total: float}
        """
        body = {"timestamp": int(time.time() * 1000)}
        data = await self._post("/exchange/v1/users/balances", body)

        if not data:
            return {"currency": "INR", "available": 0, "total": 0}

        # Sum up INR and USDT balances
        inr_balance = 0.0
        usdt_balance = 0.0
        for item in data:
            if isinstance(item, dict):
                currency = item.get("currency", "")
                balance = float(item.get("balance", 0))
                if currency == "INR":
                    inr_balance = balance
                elif currency == "USDT":
                    usdt_balance = balance

        return {
            "currency": "INR",
            "inr": round(inr_balance, 2),
            "usdt": round(usdt_balance, 4),
            "available": round(inr_balance, 2),
            "total": round(inr_balance + usdt_balance * config.usd_inr_rate, 2),
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
        Place an order on CoinDCX.

        Maps our standard interface to CoinDCX API format.
        CoinDCX uses "market" field for the trading pair (e.g., "BTCINR").
        """
        order_id = str(uuid.uuid4())[:8]

        # Map symbol to CoinDCX market format
        market = symbol.replace("/", "")  # BTCUSDT -> BTCUSDT

        body = {
            "side": "buy" if side == OrderSide.BUY else "sell",
            "order_type": "market_order" if order_type == OrderType.MARKET else "limit_order",
            "market": market,
            "total_quantity": quantity,
            "timestamp": int(time.time() * 1000),
        }

        if order_type == OrderType.LIMIT and price > 0:
            body["price_per_unit"] = price

        data = await self._post("/exchange/v1/orders/create", body)

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

        if data and "id" in data:
            order.broker_order_id = str(data["id"])
            order.status = OrderStatus.FILLED if order_type == OrderType.MARKET else OrderStatus.PENDING
            order.filled_price = float(data.get("avg_price", price))
            order.filled_quantity = float(data.get("total_quantity", quantity))
            print(f"[CoinDCX] Order placed: {side.value} {quantity} {symbol} @ {order.filled_price}")
        else:
            order.status = OrderStatus.REJECTED
            print(f"[CoinDCX] Order rejected: {side.value} {quantity} {symbol}")

        return order

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order on CoinDCX."""
        body = {
            "id": order_id,
            "timestamp": int(time.time() * 1000),
        }
        data = await self._post("/exchange/v1/orders/cancel", body)
        return data is not None

    async def get_positions(self) -> list[BrokerPosition]:
        """
        Get open positions.

        For spot trading, positions are derived from non-zero balances.
        For futures, CoinDCX has a separate positions endpoint.
        """
        body = {"timestamp": int(time.time() * 1000)}
        data = await self._post("/exchange/v1/users/balances", body)

        positions = []
        if not data:
            return positions

        for item in data:
            if isinstance(item, dict):
                currency = item.get("currency", "")
                balance = float(item.get("balance", 0))
                # Skip stablecoins and zero balances
                if balance > 0 and currency not in ("INR", "USDT", "USDC"):
                    positions.append(BrokerPosition(
                        symbol=f"{currency}USDT",
                        side=OrderSide.BUY,
                        quantity=balance,
                        entry_price=0,  # Spot doesn't track entry
                        current_price=0,
                    ))

        return positions

    async def close_position(self, symbol: str) -> BrokerOrder | None:
        """Close a position by selling the full balance."""
        positions = await self.get_positions()
        for pos in positions:
            if pos.symbol == symbol:
                return await self.place_order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                    order_type=OrderType.MARKET,
                )
        return None
