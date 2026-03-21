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

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

import httpx

import math

from .base_broker import (
    BaseBroker, BrokerOrder, BrokerPosition,
    OrderSide, OrderType, OrderStatus,
)
from ..config import config


def safe_float(val, default: float = 0.0) -> float:
    """
    SEC-05: Safely parse exchange response values to float.
    Handles NaN, Inf, empty strings, and None without crashing.
    Exchange APIs can return unexpected values during errors or maintenance.
    """
    try:
        result = float(val)
        if math.isnan(result) or math.isinf(result):
            print(f"[BinanceDemo] WARNING: Received {val} from exchange, using default {default}")
            return default
        return result
    except (ValueError, TypeError):
        return default

DEMO_FAPI = "https://demo-fapi.binance.com"

# Explicit symbol mapping — avoids fragile string replacement (AT-05).
# Add new pairs here as needed.
SYMBOL_MAP = {
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "BTCUSDT": "BTCUSDT",
    "ETHUSDT": "ETHUSDT",
}


def _map_symbol(symbol: str) -> str:
    """Map an internal symbol to the Binance futures symbol.

    Raises ValueError for unmapped symbols so callers get a clear error
    instead of a silently mangled string.
    AT-35: Gives clear error for metals (Gold/Silver) which Binance doesn't trade.
    """
    # AT-35: Metals are not tradeable on Binance — give a clear error
    METALS = {"XAUUSD", "XAGUSD", "GOLDUSD", "SILVERUSD"}
    if symbol.upper() in METALS:
        raise ValueError(
            f"'{symbol}' is not tradeable on Binance. "
            f"Metals (Gold/Silver) require a forex/CFD broker like MT5 or Oanda."
        )

    mapped = SYMBOL_MAP.get(symbol)
    if mapped is None:
        raise ValueError(
            f"Unmapped symbol '{symbol}'. Add it to SYMBOL_MAP in binance_testnet.py. "
            f"Known symbols: {list(SYMBOL_MAP.keys())}"
        )
    return mapped


# MM-03: Tick size per symbol — prices must be rounded to valid increments
# otherwise Binance rejects with "Filter failure: PRICE_FILTER"
TICK_SIZES = {
    "BTCUSDT": 0.10,
    "ETHUSDT": 0.01,
}


def _round_to_tick(price: float, tick_size: float) -> float:
    """
    MM-03: Round a price to the nearest valid tick size.
    Binance rejects orders with prices that aren't multiples of tick_size.
    E.g., BTCUSDT tick=0.10 → 65432.15 becomes 65432.10
    """
    if tick_size <= 0:
        return price
    return round(round(price / tick_size) * tick_size, 8)


class BinanceTestnetBroker(BaseBroker):
    """
    Binance Demo Trading — real exchange, fake money, visible trades.

    Uses direct REST API calls to demo-fapi.binance.com.
    Trades appear on demo.binance.com/en/futures for you to watch.
    """

    # Retry config
    MAX_RETRIES = 3
    BACKOFF_SECONDS = [1, 2, 4]  # Exponential backoff delays
    # HTTP status codes that should NOT be retried (client errors)
    NO_RETRY_STATUSES = {400, 401, 403}

    def __init__(self):
        self._key = config.binance_testnet_key
        self._secret = config.binance_testnet_secret
        self._connected = False
        self._client: httpx.AsyncClient | None = None
        self._consecutive_failures = 0  # AT-07: track for auto-reconnection
        self._request_count = 0  # AT-17: rate limit tracking
        self._request_window_start = time.time()  # AT-17: window start

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

    async def _ensure_client(self):
        """Ensure HTTP client exists. Auto-reconnect if previously disconnected."""
        # AT-07: If we lost connection due to consecutive failures, try reconnecting
        if not self._connected and self._consecutive_failures >= self.MAX_RETRIES:
            print("[BinanceDemo] Connection lost — attempting auto-reconnect...")
            reconnected = await self.connect()
            if not reconnected:
                print("[BinanceDemo] Auto-reconnect failed. Will retry on next call.")

        if not self._client:
            self._client = httpx.AsyncClient(timeout=15.0)
        elif self._client.is_closed:
            # CQ-21: Client was closed (e.g., after disconnect) — recreate it
            # Close first to release any lingering resources, then create fresh
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = httpx.AsyncClient(timeout=15.0)

    async def _request_with_retry(
        self, method: str, path: str, params: dict | None = None,
    ) -> dict | list | None:
        """
        AT-06: Execute a signed request with exponential backoff retry.

        Retries up to MAX_RETRIES times on:
        - HTTP 429 (rate limit), 5xx (server errors)
        - Timeout and connection errors
        Does NOT retry on 400, 401, 403 (client errors).

        AT-07: Marks connection as lost after MAX_RETRIES consecutive failures
        and auto-reconnects on the next call.
        """
        await self._ensure_client()

        # AT-17: Rate limit tracking — Binance allows 1200 weight/min
        now_ts = time.time()
        if now_ts - self._request_window_start >= 60:
            self._request_count = 0
            self._request_window_start = now_ts
        self._request_count += 1
        if self._request_count > 1000:
            print(f"[BinanceDemo] WARNING: {self._request_count} requests in current minute — approaching rate limit")
            await asyncio.sleep(1)

        for attempt in range(self.MAX_RETRIES):
            # Fresh timestamp + signature for each attempt (timestamps expire)
            p = dict(params) if params else {}
            p["timestamp"] = int(time.time() * 1000)
            p["signature"] = self._sign(p)

            url = f"{DEMO_FAPI}{path}"
            try:
                # SEC-06: Explicit dispatch instead of getattr to prevent
                # arbitrary method invocation if 'method' is tainted
                _dispatch = {
                    "get": self._client.get,
                    "post": self._client.post,
                    "delete": self._client.delete,
                }
                if method not in _dispatch:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                resp = await _dispatch[method](url, params=p, headers=self._headers())

                if resp.status_code == 200:
                    # Success — reset failure counter
                    self._consecutive_failures = 0
                    return resp.json()

                # Client error — do not retry
                if resp.status_code in self.NO_RETRY_STATUSES:
                    print(f"[BinanceDemo] {method.upper()} {path} → {resp.status_code}: {resp.text[:200]}")
                    self._consecutive_failures = 0  # Client errors aren't connectivity issues
                    return None

                # Retryable server error (429, 5xx)
                print(
                    f"[BinanceDemo] {method.upper()} {path} → {resp.status_code} "
                    f"(attempt {attempt + 1}/{self.MAX_RETRIES}): {resp.text[:200]}"
                )

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                print(
                    f"[BinanceDemo] {method.upper()} {path} network error "
                    f"(attempt {attempt + 1}/{self.MAX_RETRIES}): {e}"
                )
            except Exception as e:
                print(f"[BinanceDemo] {method.upper()} {path} unexpected error: {e}")
                self._consecutive_failures += 1
                return None  # Unknown errors — don't retry

            # Wait before next retry (skip sleep on last attempt)
            if attempt < self.MAX_RETRIES - 1:
                delay = self.BACKOFF_SECONDS[attempt]
                print(f"[BinanceDemo] Retrying in {delay}s...")
                await asyncio.sleep(delay)

        # All retries exhausted
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.MAX_RETRIES:
            self._connected = False
            print(
                f"[BinanceDemo] {self._consecutive_failures} consecutive failures — "
                f"marking connection as LOST. Will auto-reconnect on next call."
            )
        return None

    async def _get(self, path: str, params: dict | None = None) -> dict | list | None:
        """Signed GET request to demo-fapi with retry + auto-reconnect."""
        return await self._request_with_retry("get", path, params)

    async def _post(self, path: str, params: dict | None = None) -> dict | list | None:
        """Signed POST request to demo-fapi with retry + auto-reconnect."""
        return await self._request_with_retry("post", path, params)

    async def _delete(self, path: str, params: dict | None = None) -> dict | list | None:
        """Signed DELETE request to demo-fapi with retry + auto-reconnect."""
        return await self._request_with_retry("delete", path, params)

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
        order_id = str(uuid.uuid4())[:16]
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
        binance_sym = _map_symbol(symbol)

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

            # Place SL as stop-market — CRITICAL for position safety
            if stop_loss > 0:
                sl_side = "SELL" if side == OrderSide.BUY else "BUY"
                # MM-03: Round SL to valid tick size
                tick = TICK_SIZES.get(binance_sym, 0.01)
                sl_price = _round_to_tick(stop_loss, tick)
                sl_result = await self._post("/fapi/v1/order", {
                    "symbol": binance_sym,
                    "side": sl_side,
                    "type": "STOP_MARKET",
                    "stopPrice": str(sl_price),
                    "closePosition": "true",
                })
                if sl_result and "orderId" in sl_result:
                    order.sl_order_id = str(sl_result["orderId"])
                    print(f"[BinanceDemo] SL placed: {sl_side} @ {stop_loss} (orderId={order.sl_order_id})")
                else:
                    # SL failed — position is UNPROTECTED, close immediately
                    print(f"[BinanceDemo] ERROR: SL placement FAILED for {binance_sym}. Closing position to avoid unprotected exposure.")
                    close_side = "SELL" if side == OrderSide.BUY else "BUY"
                    await self._post("/fapi/v1/order", {
                        "symbol": binance_sym,
                        "side": close_side,
                        "type": "MARKET",
                        "quantity": str(quantity),
                    })
                    order.status = OrderStatus.CANCELLED
                    return order

            # Place TP as take-profit-market
            if take_profit > 0:
                tp_side = "SELL" if side == OrderSide.BUY else "BUY"
                # MM-03: Round TP to valid tick size
                tick = TICK_SIZES.get(binance_sym, 0.01)
                tp_price = _round_to_tick(take_profit, tick)
                tp_result = await self._post("/fapi/v1/order", {
                    "symbol": binance_sym,
                    "side": tp_side,
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": str(tp_price),
                    "closePosition": "true",
                })
                if tp_result and "orderId" in tp_result:
                    order.tp_order_id = str(tp_result["orderId"])
                    print(f"[BinanceDemo] TP placed: {tp_side} @ {take_profit} (orderId={order.tp_order_id})")
                else:
                    print(f"[BinanceDemo] WARNING: TP placement failed for {binance_sym}. Position has SL but no TP.")
        else:
            order.status = OrderStatus.REJECTED
            print(f"[BinanceDemo] REJECTED: {side.value} {quantity} {binance_sym}")

        return order

    async def cancel_order(self, order_id: str, symbol: str = "") -> bool:
        """Cancel a pending order using DELETE /fapi/v1/order.

        Args:
            order_id: The broker's orderId to cancel.
            symbol: Binance symbol (e.g. BTCUSDT). Required by the API.
        """
        if not symbol:
            print("[BinanceDemo] cancel_order requires symbol parameter")
            return False

        binance_sym = _map_symbol(symbol)
        result = await self._delete("/fapi/v1/order", {
            "symbol": binance_sym,
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
        """
        AT-25 FIX: Close a position AND cancel any orphaned SL/TP orders.
        AT-34 FIX: Uses direct market order instead of routing through place_order()
        to avoid inadvertently placing SL/TP on a closing trade.
        """
        positions = await self.get_positions()
        binance_symbol = _map_symbol(symbol)

        for pos in positions:
            if binance_symbol == pos.symbol or symbol == pos.symbol:
                close_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY

                # AT-25: Cancel ALL open orders on this symbol first.
                # This removes orphaned SL/TP orders that could trigger
                # on future positions if left active.
                try:
                    await self._delete("/fapi/v1/allOpenOrders", {
                        "symbol": pos.symbol,
                    })
                    print(f"[BinanceDemo] Cancelled all open orders for {pos.symbol}")
                except Exception as e:
                    print(f"[BinanceDemo] Warning: Failed to cancel orders: {e}")

                # AT-34: Place closing market order directly (not through place_order)
                side_str = "BUY" if close_side == OrderSide.BUY else "SELL"
                result = await self._post("/fapi/v1/order", {
                    "symbol": pos.symbol,
                    "side": side_str,
                    "type": "MARKET",
                    "quantity": str(pos.quantity),
                    "reduceOnly": "true",
                })

                if result:
                    return BrokerOrder(
                        order_id=str(result.get("orderId", "")),
                        symbol=symbol,
                        side=close_side,
                        quantity=pos.quantity,
                        filled_price=float(result.get("avgPrice", 0) or 0),
                        status=OrderStatus.FILLED,
                    )
        return None
