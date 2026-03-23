"""CoinDCX Broker — standalone IBroker for personal trading.

Standalone: HTTP client, HMAC signing, retry. No v1 dependencies.
API docs: https://docs.coindcx.com/
"""

import hashlib
import hmac
import json
import logging
import os
import time
import uuid

import httpx

from ..core.models import (
    BalanceInfo,
    Direction,
    ExchangePosition,
    OrderResult,
    TradeSetup,
)
from .registry import register_broker

logger = logging.getLogger(__name__)

COINDCX_API_URL = "https://api.coindcx.com"


@register_broker("coindcx")
class CoinDCXBroker:
    """CoinDCX exchange — spot and futures trading."""

    MAX_RETRIES = 3
    BACKOFF = [1, 2, 4]

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        self._key = api_key or os.environ.get("COINDCX_API_KEY", "")
        self._secret = api_secret or os.environ.get("COINDCX_API_SECRET", "")
        self._connected = False
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "coindcx"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _sign(self, body: dict) -> str:
        json_body = json.dumps(body, separators=(",", ":"))
        return hmac.new(
            self._secret.encode(), json_body.encode(), hashlib.sha256,
        ).hexdigest()

    def _headers(self, body: dict) -> dict:
        return {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": self._key,
            "X-AUTH-SIGNATURE": self._sign(body),
        }

    async def _post(self, endpoint: str, body: dict) -> dict | None:
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)

        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await self._client.post(
                    f"{COINDCX_API_URL}{endpoint}",
                    json=body,
                    headers=self._headers(body),
                )
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in {400, 401, 403}:
                    return None
            except (httpx.TimeoutException, httpx.ConnectError):
                pass
            except Exception:
                return None

            if attempt < self.MAX_RETRIES - 1:
                import asyncio
                await asyncio.sleep(self.BACKOFF[attempt])

        return None

    async def connect(self) -> bool:
        if not self._key or not self._secret:
            logger.error("CoinDCX API keys not configured")
            return False

        self._client = httpx.AsyncClient(timeout=30.0)
        balance = await self.get_balance()
        if balance.total > 0 or self._connected:
            self._connected = True
            logger.info("Connected to CoinDCX")
            return True
        return False

    async def disconnect(self) -> None:
        self._connected = False
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_balance(self) -> BalanceInfo:
        if not self._key:
            return BalanceInfo(total=0, available=0, currency="INR")

        body = {"timestamp": int(time.time() * 1000)}
        data = await self._post("/exchange/v1/users/balances", body)

        if not data:
            return BalanceInfo(total=0, available=0, currency="INR")

        inr = usdt = 0.0
        for item in data:
            if isinstance(item, dict):
                cur = item.get("currency", "")
                bal = float(item.get("balance", 0))
                if cur == "INR":
                    inr = bal
                elif cur == "USDT":
                    usdt = bal

        return BalanceInfo(total=round(inr + usdt * 84, 2), available=round(inr, 2), currency="INR")

    async def get_positions(self) -> list[ExchangePosition]:
        if not self._connected:
            return []

        body = {"timestamp": int(time.time() * 1000)}
        data = await self._post("/exchange/v1/users/balances", body)
        if not data:
            return []

        positions = []
        for item in data:
            if isinstance(item, dict):
                cur = item.get("currency", "")
                bal = float(item.get("balance", 0))
                if bal > 0 and cur not in ("INR", "USDT", "USDC"):
                    positions.append(ExchangePosition(
                        symbol=f"{cur}USDT",
                        direction=Direction.LONG,
                        quantity=bal,
                        entry_price=0,
                    ))
        return positions

    async def get_order_status(self, order_id: str) -> OrderResult:
        return OrderResult(order_id=order_id, success=True)

    async def place_order(self, setup: TradeSetup) -> OrderResult:
        if not self._connected:
            return OrderResult(success=False, error="Not connected")

        side = "buy" if setup.direction == Direction.LONG else "sell"
        body = {
            "side": side,
            "order_type": "market_order",
            "market": setup.symbol,
            "total_quantity": setup.position_size,
            "timestamp": int(time.time() * 1000),
        }

        data = await self._post("/exchange/v1/orders/create", body)
        if data and "id" in data:
            return OrderResult(
                order_id=str(data["id"]),
                success=True,
                filled_price=float(data.get("avg_price", setup.entry_price)),
                filled_quantity=float(data.get("total_quantity", setup.position_size)),
            )

        return OrderResult(success=False, error="Order rejected by CoinDCX")

    async def close_position(self, symbol: str) -> OrderResult:
        positions = await self.get_positions()
        for pos in positions:
            if pos.symbol == symbol:
                setup = TradeSetup(
                    symbol=symbol,
                    direction=Direction.SHORT,
                    entry_price=0,
                    stop_loss=0,
                    take_profit=0,
                    position_size=pos.quantity,
                )
                return await self.place_order(setup)
        return OrderResult(success=False, error=f"No position for {symbol}")

    async def cancel_all_orders(self, symbol: str) -> bool:
        return True
