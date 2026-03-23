"""BinanceBroker — standalone IBroker for Binance Demo/Testnet.

Self-contained: HTTP client, HMAC signing, retry with backoff.
Uses InstrumentRegistry for symbol mapping (no hardcoded SYMBOL_MAP).

Endpoint: https://demo-fapi.binance.com
"""

import asyncio
import hashlib
import hmac
import logging
import math
import os
import time
import uuid

import httpx

from ..core.instruments import get_instrument
from ..core.models import (
    BalanceInfo,
    Direction,
    ExchangePosition,
    OrderResult,
    TradeSetup,
)
from .registry import register_broker

logger = logging.getLogger(__name__)

DEMO_FAPI = "https://demo-fapi.binance.com"


def _safe_float(val, default: float = 0.0) -> float:
    try:
        result = float(val)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


@register_broker("binance_testnet")
class BinanceBroker:
    """Binance Demo Futures — real exchange, fake money."""

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [1, 2, 4]
    NO_RETRY_STATUSES = {400, 401, 403}

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        self._key = api_key or os.environ.get("BINANCE_TESTNET_KEY", "")
        self._secret = api_secret or os.environ.get("BINANCE_TESTNET_SECRET", "")
        self._connected = False
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "binance_testnet"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _sign(self, params: dict) -> str:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return hmac.new(
            self._secret.encode(), query.encode(), hashlib.sha256,
        ).hexdigest()

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self._key}

    async def _ensure_client(self) -> None:
        if not self._client or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)

    def _exchange_symbol(self, symbol: str) -> str:
        """Map internal symbol to Binance via InstrumentRegistry."""
        try:
            inst = get_instrument(symbol)
            return inst.exchange_symbol("binance")
        except (KeyError, ValueError):
            # Pass-through for already-mapped symbols (e.g., BTCUSDT)
            return symbol

    async def _request(
        self, method: str, path: str, params: dict | None = None,
    ) -> dict | list | None:
        await self._ensure_client()

        for attempt in range(self.MAX_RETRIES):
            p = dict(params) if params else {}
            p["timestamp"] = int(time.time() * 1000)
            p["signature"] = self._sign(p)

            url = f"{DEMO_FAPI}{path}"
            try:
                dispatch = {"get": self._client.get, "post": self._client.post,
                            "delete": self._client.delete}
                resp = await dispatch[method](url, params=p, headers=self._headers())

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code in self.NO_RETRY_STATUSES:
                    return None

                logger.warning("%s %s -> %d (attempt %d/%d)",
                               method.upper(), path, resp.status_code,
                               attempt + 1, self.MAX_RETRIES)

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.warning("%s %s network error (attempt %d/%d): %s",
                               method.upper(), path, attempt + 1, self.MAX_RETRIES, e)
            except Exception:
                return None

            if attempt < self.MAX_RETRIES - 1:
                await asyncio.sleep(self.BACKOFF_SECONDS[attempt])

        self._connected = False
        return None

    # -- IBroker implementation --

    async def connect(self) -> bool:
        if not self._key or not self._secret:
            logger.error("Binance API keys not configured")
            return False

        data = await self._request("get", "/fapi/v2/balance")
        if data:
            usdt = next((a for a in data if a["asset"] == "USDT"), {})
            balance = float(usdt.get("balance", 0))
            self._connected = True
            logger.info("Connected to Binance Demo. Balance: %.2f USDT", balance)
            return True

        logger.error("Binance connection failed")
        return False

    async def disconnect(self) -> None:
        self._connected = False
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_balance(self) -> BalanceInfo:
        if not self._connected:
            return BalanceInfo(total=0, available=0, currency="USDT")

        data = await self._request("get", "/fapi/v2/balance")
        if not data:
            return BalanceInfo(total=0, available=0, currency="USDT")

        for asset in data:
            if asset["asset"] == "USDT":
                return BalanceInfo(
                    total=round(float(asset.get("balance", 0)), 2),
                    available=round(float(asset.get("availableBalance", 0)), 2),
                    currency="USDT",
                )
        return BalanceInfo(total=0, available=0, currency="USDT")

    async def get_positions(self) -> list[ExchangePosition]:
        if not self._connected:
            return []

        data = await self._request("get", "/fapi/v2/positionRisk")
        if not data:
            return []

        positions = []
        for pos in data:
            qty = float(pos.get("positionAmt", 0))
            if qty == 0:
                continue
            positions.append(ExchangePosition(
                symbol=pos.get("symbol", ""),
                direction=Direction.LONG if qty > 0 else Direction.SHORT,
                quantity=abs(qty),
                entry_price=_safe_float(pos.get("entryPrice")),
                current_price=_safe_float(pos.get("markPrice")),
                unrealized_pnl=_safe_float(pos.get("unRealizedProfit")),
                leverage=_safe_float(pos.get("leverage"), 1.0),
            ))
        return positions

    async def get_order_status(self, order_id: str) -> OrderResult:
        return OrderResult(order_id=order_id, success=True)

    def _round_quantity(self, symbol: str, qty: float) -> str:
        """Round quantity to Binance-acceptable precision per symbol."""
        # Step sizes per symbol (from Binance exchange info)
        steps = {
            "BTCUSDT": 3, "ETHUSDT": 3, "SOLUSDT": 1, "XRPUSDT": 1,
            "BNBUSDT": 2, "DOGEUSDT": 0, "ADAUSDT": 0, "AVAXUSDT": 1,
            "LINKUSDT": 1, "DOTUSDT": 1, "LTCUSDT": 2, "NEARUSDT": 1,
            "SUIUSDT": 1, "ARBUSDT": 1, "PEPEUSDT": 0, "WIFUSDT": 0,
            "FTMUSDT": 0, "ATOMUSDT": 1,
        }
        decimals = steps.get(symbol, 3)
        rounded = round(qty, decimals)
        if decimals == 0:
            rounded = int(rounded)
        return str(rounded)

    async def place_order(self, setup: TradeSetup) -> OrderResult:
        if not self._connected:
            return OrderResult(success=False, error="Not connected")

        binance_sym = self._exchange_symbol(setup.symbol)
        side = "BUY" if setup.direction == Direction.LONG else "SELL"
        qty_str = self._round_quantity(binance_sym, setup.position_size)

        params = {
            "symbol": binance_sym,
            "side": side,
            "type": "MARKET",
            "quantity": qty_str,
        }
        result = await self._request("post", "/fapi/v1/order", params)

        if result and "orderId" in result:
            filled_price = _safe_float(result.get("avgPrice"))
            if filled_price <= 0:
                filled_price = setup.entry_price

            # Place SL/TP as stop-market orders
            if setup.stop_loss > 0:
                sl_side = "SELL" if side == "BUY" else "BUY"
                await self._request("post", "/fapi/v1/order", {
                    "symbol": binance_sym, "side": sl_side,
                    "type": "STOP_MARKET",
                    "stopPrice": str(round(setup.stop_loss, 8)),
                    "closePosition": "true",
                })

            if setup.take_profit > 0:
                tp_side = "SELL" if side == "BUY" else "BUY"
                await self._request("post", "/fapi/v1/order", {
                    "symbol": binance_sym, "side": tp_side,
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": str(round(setup.take_profit, 8)),
                    "closePosition": "true",
                })

            return OrderResult(
                order_id=str(result["orderId"]),
                success=True,
                filled_price=filled_price,
                filled_quantity=float(result.get("executedQty", setup.position_size)),
            )

        return OrderResult(success=False, error="Order rejected by Binance")

    async def close_position(self, symbol: str) -> OrderResult:
        positions = await self.get_positions()
        binance_sym = self._exchange_symbol(symbol)

        for pos in positions:
            if pos.symbol == binance_sym or pos.symbol == symbol:
                close_side = "SELL" if pos.direction == Direction.LONG else "BUY"

                # Cancel all open orders first
                await self._request("delete", "/fapi/v1/allOpenOrders", {
                    "symbol": pos.symbol,
                })

                result = await self._request("post", "/fapi/v1/order", {
                    "symbol": pos.symbol,
                    "side": close_side,
                    "type": "MARKET",
                    "quantity": str(pos.quantity),
                    "reduceOnly": "true",
                })

                if result:
                    return OrderResult(
                        order_id=str(result.get("orderId", "")),
                        success=True,
                        filled_price=_safe_float(result.get("avgPrice")),
                        filled_quantity=pos.quantity,
                    )

        return OrderResult(success=False, error=f"No position for {symbol}")

    async def cancel_all_orders(self, symbol: str) -> bool:
        binance_sym = self._exchange_symbol(symbol)
        result = await self._request("delete", "/fapi/v1/allOpenOrders", {
            "symbol": binance_sym,
        })
        return result is not None
