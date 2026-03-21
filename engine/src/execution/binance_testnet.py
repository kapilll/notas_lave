"""
Binance Demo Trading — paper trading on Binance with VISIBLE trades.

SETUP:
1. Go to https://demo.binance.com
2. Log in → API Management → Create API Key (HMAC)
3. Add to engine/.env:
   BINANCE_TESTNET_KEY=your_key
   BINANCE_TESTNET_SECRET=your_secret
   BROKER=binance_testnet
4. Start engine — trades appear on demo.binance.com/en/futures

Demo endpoint: https://demo-fapi.binance.com
Uses direct REST calls (CCXT's sapi calls don't work on demo).

You get 5,000 USDT + 0.01 BTC free balance.
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

DEMO_FAPI = "https://demo-fapi.binance.com"


class BinanceTestnetBroker(BaseBroker):
    """
    Binance Demo Trading — real exchange, fake money, visible trades.

    Uses direct REST API calls to demo-fapi.binance.com.
    Trades appear on demo.binance.com/en/futures for you to watch.
    """

    def __init__(self):
        self._key = config.binance_testnet_key
        self._secret = config.binance_testnet_secret
        self._connected = False
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "binance_testnet"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _sign(self, params: dict) -> str:
        """Generate HMAC SHA256 signature for Binance API."""
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return hmac.new(
            self._secret.encode(), query.encode(), hashlib.sha256,
        ).hexdigest()

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self._key}

    async def _get(self, path: str, params: dict | None = None) -> dict | list | None:
        """Signed GET request to demo-fapi."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=15.0)

        p = params or {}
        p["timestamp"] = int(time.time() * 1000)
        p["signature"] = self._sign(p)

        url = f"{DEMO_FAPI}{path}"
        try:
            resp = await self._client.get(url, params=p, headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
            print(f"[BinanceDemo] GET {path} → {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"[BinanceDemo] GET {path} error: {e}")
        return None

    async def _post(self, path: str, params: dict | None = None) -> dict | list | None:
        """Signed POST request to demo-fapi."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=15.0)

        p = params or {}
        p["timestamp"] = int(time.time() * 1000)
        p["signature"] = self._sign(p)

        url = f"{DEMO_FAPI}{path}"
        try:
            resp = await self._client.post(url, params=p, headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
            print(f"[BinanceDemo] POST {path} → {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"[BinanceDemo] POST {path} error: {e}")
        return None

    async def connect(self) -> bool:
        """Verify connection by fetching balance."""
        if not self._key or not self._secret:
            print("[BinanceDemo] API keys not configured.")
            print("[BinanceDemo] Get keys from https://demo.binance.com → API Management")
            return False

        data = await self._get("/fapi/v2/balance")
        if data:
            usdt = next((a for a in data if a["asset"] == "USDT"), {})
            balance = float(usdt.get("balance", 0))
            self._connected = True
            print(f"[BinanceDemo] Connected! Balance: {balance:.2f} USDT")
            return True

        print("[BinanceDemo] Connection failed")
        return False

    async def disconnect(self):
        self._connected = False
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_balance(self) -> dict:
        if not self._connected:
            return {"currency": "USDT", "available": 0, "total": 0}

        data = await self._get("/fapi/v2/balance")
        if not data:
            return {"currency": "USDT", "available": 0, "total": 0}

        result = {"currency": "USDT"}
        for asset in data:
            name = asset["asset"]
            bal = float(asset.get("balance", 0))
            if bal > 0:
                result[name.lower()] = round(bal, 4)
                if name == "USDT":
                    result["available"] = round(float(asset.get("availableBalance", 0)), 2)
                    result["total"] = round(bal, 2)

        return result

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
        """Place an order on Binance Demo. Visible at demo.binance.com."""
        order_id = str(uuid.uuid4())[:8]
        order = BrokerOrder(
            order_id=order_id, symbol=symbol, side=side,
            order_type=order_type, quantity=quantity, price=price,
            stop_loss=stop_loss, take_profit=take_profit,
            leverage=leverage, created_at=datetime.now(timezone.utc),
        )

        if not self._connected:
            order.status = OrderStatus.REJECTED
            return order

        # Map symbol: BTCUSD/BTCUSDT → BTCUSDT (Binance format)
        binance_sym = symbol.replace("USD", "USDT") if not symbol.endswith("USDT") else symbol

        # Set leverage
        if leverage > 1:
            await self._post("/fapi/v1/leverage", {
                "symbol": binance_sym,
                "leverage": int(leverage),
            })

        # Place the order
        params = {
            "symbol": binance_sym,
            "side": "BUY" if side == OrderSide.BUY else "SELL",
            "type": "MARKET" if order_type == OrderType.MARKET else "LIMIT",
            "quantity": str(quantity),
        }
        if order_type == OrderType.LIMIT and price > 0:
            params["price"] = str(price)
            params["timeInForce"] = "GTC"

        result = await self._post("/fapi/v1/order", params)

        if result and "orderId" in result:
            order.broker_order_id = str(result["orderId"])
            order.status = OrderStatus.FILLED
            order.filled_price = float(result.get("avgPrice", 0) or price)
            order.filled_quantity = float(result.get("executedQty", quantity))
            print(f"[BinanceDemo] FILLED: {side.value} {quantity} {binance_sym} @ {order.filled_price}")

            # Place SL as stop-market
            if stop_loss > 0:
                sl_side = "SELL" if side == OrderSide.BUY else "BUY"
                await self._post("/fapi/v1/order", {
                    "symbol": binance_sym,
                    "side": sl_side,
                    "type": "STOP_MARKET",
                    "stopPrice": str(round(stop_loss, 2)),
                    "closePosition": "true",
                })

            # Place TP as take-profit-market
            if take_profit > 0:
                tp_side = "SELL" if side == OrderSide.BUY else "BUY"
                await self._post("/fapi/v1/order", {
                    "symbol": binance_sym,
                    "side": tp_side,
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": str(round(take_profit, 2)),
                    "closePosition": "true",
                })
        else:
            order.status = OrderStatus.REJECTED
            print(f"[BinanceDemo] REJECTED: {side.value} {quantity} {binance_sym}")

        return order

    async def cancel_order(self, order_id: str) -> bool:
        result = await self._post("/fapi/v1/order", {
            "orderId": order_id,
        })
        return result is not None

    async def get_positions(self) -> list[BrokerPosition]:
        if not self._connected:
            return []

        data = await self._get("/fapi/v2/positionRisk")
        if not data:
            return []

        positions = []
        for pos in data:
            qty = float(pos.get("positionAmt", 0))
            if qty == 0:
                continue

            positions.append(BrokerPosition(
                symbol=pos.get("symbol", ""),
                side=OrderSide.BUY if qty > 0 else OrderSide.SELL,
                quantity=abs(qty),
                entry_price=float(pos.get("entryPrice", 0)),
                current_price=float(pos.get("markPrice", 0)),
                unrealized_pnl=float(pos.get("unRealizedProfit", 0)),
                leverage=float(pos.get("leverage", 1)),
                liquidation_price=float(pos.get("liquidationPrice", 0)),
                margin_used=float(pos.get("isolatedMargin", 0) or pos.get("initialMargin", 0)),
            ))

        return positions

    async def close_position(self, symbol: str) -> BrokerOrder | None:
        positions = await self.get_positions()
        for pos in positions:
            if symbol.replace("USD", "USDT") in pos.symbol or symbol in pos.symbol:
                close_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                return await self.place_order(
                    symbol=pos.symbol, side=close_side,
                    quantity=pos.quantity, order_type=OrderType.MARKET,
                )
        return None
