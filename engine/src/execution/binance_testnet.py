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
import logging
import time
import uuid
from datetime import datetime, timezone

import httpx

import math

logger = logging.getLogger(__name__)

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
            logger.warning("Received %s from exchange, using default %s", val, default)
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
    "SOLUSD": "SOLUSDT",
    "XRPUSD": "XRPUSDT",
    "BNBUSD": "BNBUSDT",
    "DOGEUSD": "DOGEUSDT",
    "ADAUSD": "ADAUSDT",
    "AVAXUSD": "AVAXUSDT",
    "LINKUSD": "LINKUSDT",
    "DOTUSD": "DOTUSDT",
    "LTCUSD": "LTCUSDT",
    "NEARUSD": "NEARUSDT",
    "SUIUSD": "SUIUSDT",
    "ARBUSD": "ARBUSDT",
    "PEPEUSD": "PEPEUSDT",
    "WIFUSD": "WIFUSDT",
    "FTMUSD": "FTMUSDT",
    "ATOMUSD": "ATOMUSDT",
    # Pass-through for USDT variants
    "BTCUSDT": "BTCUSDT",
    "ETHUSDT": "ETHUSDT",
    "SOLUSDT": "SOLUSDT",
    "XRPUSDT": "XRPUSDT",
    "BNBUSDT": "BNBUSDT",
    "DOGEUSDT": "DOGEUSDT",
    "ADAUSDT": "ADAUSDT",
    "AVAXUSDT": "AVAXUSDT",
    "LINKUSDT": "LINKUSDT",
    "DOTUSDT": "DOTUSDT",
    "LTCUSDT": "LTCUSDT",
    "NEARUSDT": "NEARUSDT",
    "SUIUSDT": "SUIUSDT",
    "ARBUSDT": "ARBUSDT",
    "PEPEUSDT": "PEPEUSDT",
    "WIFUSDT": "WIFUSDT",
    "FTMUSDT": "FTMUSDT",
    "ATOMUSDT": "ATOMUSDT",
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
    "SOLUSDT": 0.010,
    "XRPUSDT": 0.0001,
    "BNBUSDT": 0.010,
    "DOGEUSDT": 0.000010,
    "ADAUSDT": 0.00010,
    "AVAXUSDT": 0.010,
    "LINKUSDT": 0.0010,
    "DOTUSDT": 0.0010,
    "LTCUSDT": 0.01,
    "NEARUSDT": 0.001,
    "SUIUSDT": 0.0001,
    "ARBUSDT": 0.0001,
    "PEPEUSDT": 0.0000001,
    "WIFUSDT": 0.0001,
    "FTMUSDT": 0.0001,
    "ATOMUSDT": 0.001,
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
        # SE-22: Use .get_secret_value() to extract the actual secret string
        # from SecretStr. This prevents accidental logging/serialization of the secret.
        self._secret = config.binance_testnet_secret.get_secret_value()
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
            logger.warning("Connection lost — attempting auto-reconnect...")
            reconnected = await self.connect()
            if not reconnected:
                logger.warning("Auto-reconnect failed. Will retry on next call.")

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
            logger.warning("%d requests in current minute — approaching rate limit", self._request_count)
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

                # SEC-07: Sanitize error logging — extract error code instead of raw response body
                try:
                    err = resp.json()
                    err_msg = f"code={err.get('code')}, msg={err.get('msg', 'unknown')}"
                except Exception:
                    err_msg = f"status={resp.status_code}"

                # Client error — do not retry
                if resp.status_code in self.NO_RETRY_STATUSES:
                    logger.warning("%s %s -> %d: %s", method.upper(), path, resp.status_code, err_msg)
                    self._consecutive_failures = 0  # Client errors aren't connectivity issues
                    return None

                # Retryable server error (429, 5xx)
                logger.warning("%s %s -> %d (attempt %d/%d): %s",
                               method.upper(), path, resp.status_code,
                               attempt + 1, self.MAX_RETRIES, err_msg)

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                logger.warning("%s %s network error (attempt %d/%d): %s",
                               method.upper(), path, attempt + 1, self.MAX_RETRIES, e)
            except Exception as e:
                logger.error("%s %s unexpected error: %s", method.upper(), path, e)
                self._consecutive_failures += 1
                return None  # Unknown errors — don't retry

            # Wait before next retry (skip sleep on last attempt)
            if attempt < self.MAX_RETRIES - 1:
                delay = self.BACKOFF_SECONDS[attempt]
                logger.info("Retrying in %ds...", delay)
                await asyncio.sleep(delay)

        # All retries exhausted
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.MAX_RETRIES:
            self._connected = False
            logger.error("%d consecutive failures — marking connection as LOST. Will auto-reconnect on next call.",
                         self._consecutive_failures)
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
            logger.error("API keys not configured.")
            logger.error("Get keys from https://demo.binance.com -> API Management")
            return False

        data = await self._get("/fapi/v2/balance")
        if data:
            usdt = next((a for a in data if a["asset"] == "USDT"), {})
            balance = float(usdt.get("balance", 0))
            self._connected = True
            logger.info("Connected! Balance: %.2f USDT", balance)
            return True

        logger.error("Connection failed")
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
            order.filled_price = safe_float(result.get("avgPrice"), 0.0)
            order.filled_quantity = float(result.get("executedQty", quantity))

            # Binance Demo often returns avgPrice=0 for market orders.
            # Query the actual fill price from the order or recent trades.
            if order.filled_price <= 0:
                try:
                    fill = await self.get_order_fill_price(symbol, order.broker_order_id)
                    if fill and fill > 0:
                        order.filled_price = fill
                except Exception:
                    pass

            # Last resort: use the price we intended
            if order.filled_price <= 0:
                order.filled_price = price

            logger.info("FILLED: %s %s %s @ %s", side.value, quantity, binance_sym, order.filled_price)

            # Place SL/TP as stop-market orders on exchange.
            # Binance Demo may reject these (-4120) — if so, SL/TP will be
            # managed locally by the caller (paper_trader monitors prices
            # and closes via market order when levels are hit).
            if stop_loss > 0:
                sl_side = "SELL" if side == OrderSide.BUY else "BUY"
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
                    logger.info("SL placed: %s @ %s (orderId=%s)", sl_side, stop_loss, order.sl_order_id)
                else:
                    # SL not supported on this endpoint — caller manages SL locally
                    logger.info("SL managed locally for %s (exchange doesn't support stop orders)", binance_sym)

            if take_profit > 0:
                tp_side = "SELL" if side == OrderSide.BUY else "BUY"
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
                    logger.info("TP placed: %s @ %s (orderId=%s)", tp_side, take_profit, order.tp_order_id)
                else:
                    logger.info("TP managed locally for %s (exchange doesn't support stop orders)", binance_sym)
        else:
            order.status = OrderStatus.REJECTED
            logger.warning("REJECTED: %s %s %s", side.value, quantity, binance_sym)

        return order

    async def cancel_order(self, order_id: str, symbol: str = "") -> bool:
        """Cancel a pending order using DELETE /fapi/v1/order.

        Args:
            order_id: The broker's orderId to cancel.
            symbol: Binance symbol (e.g. BTCUSDT). Required by the API.
        """
        if not symbol:
            logger.warning("cancel_order requires symbol parameter")
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

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """SEC-04: Constant-time HMAC verification for webhook payloads."""
        expected = hmac.new(
            self._secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def get_order_fill_price(self, symbol: str, order_id: str) -> float | None:
        """AT-41: Query the actual fill price for a specific order.

        Used by _detect_exchange_fills() to get the real exit price
        when an exchange-side SL/TP fires, instead of relying on the
        last polled price which may differ from the actual fill.

        Returns the average fill price, or None if the query fails.
        """
        try:
            binance_sym = _map_symbol(symbol)
            result = await self._get("/fapi/v1/order", {
                "symbol": binance_sym,
                "orderId": order_id,
            })
            if result and result.get("status") == "FILLED":
                avg_price = safe_float(result.get("avgPrice"), 0.0)
                if avg_price > 0:
                    return avg_price
        except Exception as e:
            logger.debug("AT-41: Could not fetch fill price for order %s: %s", order_id, e)
        return None

    async def get_recent_fills(self, symbol: str, limit: int = 10) -> list[dict]:
        """AT-41: Get recent trade fills for a symbol.

        Fallback method when we don't have the specific order ID.
        Returns the most recent fills sorted by time descending.
        """
        try:
            binance_sym = _map_symbol(symbol)
            result = await self._get("/fapi/v1/userTrades", {
                "symbol": binance_sym,
                "limit": limit,
            })
            if result and isinstance(result, list):
                return result
        except Exception as e:
            logger.debug("AT-41: Could not fetch recent fills for %s: %s", symbol, e)
        return []

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
                    logger.info("Cancelled all open orders for %s", pos.symbol)
                except Exception as e:
                    logger.warning("Failed to cancel orders: %s", e)

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
