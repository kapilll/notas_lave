"""DeltaBroker — standalone IBroker for Delta Exchange Testnet/Production.

Self-contained: HTTP client, HMAC-SHA256 signing, retry with backoff.
Uses InstrumentRegistry for symbol mapping.
Key feature: Server-side SL/TP via bracket orders (auto-cancel opposing).

Endpoint (testnet India): https://cdn-ind.testnet.deltaex.org
"""

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import time

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

TESTNET_URL = "https://cdn-ind.testnet.deltaex.org"


def _safe_float(val, default: float = 0.0) -> float:
    try:
        result = float(val)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


@register_broker("delta_testnet")
class DeltaBroker:
    """Delta Exchange Testnet — server-side SL/TP, bracket orders."""

    MAX_RETRIES = 3
    BACKOFF_SECONDS = [1, 2, 4]
    NO_RETRY_STATUSES = {400, 401, 403}

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        base_url: str = "",
    ) -> None:
        self._key = api_key or os.environ.get("DELTA_TESTNET_KEY", "")
        self._secret = api_secret or os.environ.get("DELTA_TESTNET_SECRET", "")
        self._base_url = base_url or os.environ.get("DELTA_TESTNET_URL", TESTNET_URL)
        self._connected = False
        self._client: httpx.AsyncClient | None = None
        # symbol -> product_id mapping, populated on connect()
        self._product_ids: dict[str, int] = {}
        # Cache last known good balance so transient API failures don't report 0
        self._last_balance: BalanceInfo | None = None

    @property
    def name(self) -> str:
        return "delta_testnet"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _sign(self, method: str, timestamp: str, path: str,
              query_string: str = "", body: str = "") -> str:
        """HMAC-SHA256 signature per Delta API spec."""
        signature_data = method + timestamp + path + query_string + body
        return hmac.new(
            self._secret.encode(), signature_data.encode(), hashlib.sha256,
        ).hexdigest()

    def _auth_headers(self, method: str, path: str,
                      query_string: str = "", body: str = "") -> dict:
        """Generate Delta authentication headers."""
        timestamp = str(int(time.time()))
        signature = self._sign(method, timestamp, path, query_string, body)
        return {
            "api-key": self._key,
            "timestamp": timestamp,
            "signature": signature,
            "Content-Type": "application/json",
        }

    async def _ensure_client(self) -> None:
        if not self._client or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)

    def _exchange_symbol(self, symbol: str) -> str:
        """Map internal symbol to Delta via InstrumentRegistry."""
        try:
            inst = get_instrument(symbol)
            return inst.exchange_symbol("delta")
        except (KeyError, ValueError):
            return symbol

    def _product_id(self, symbol: str) -> int | None:
        """Get Delta product_id for a symbol. Returns None if not found."""
        delta_sym = self._exchange_symbol(symbol)
        return self._product_ids.get(delta_sym)

    async def _request(
        self, method: str, path: str,
        params: dict | None = None,
        body: dict | None = None,
    ) -> dict | list | None:
        """Make an authenticated request to Delta API with retry."""
        await self._ensure_client()

        for attempt in range(self.MAX_RETRIES):
            query_string = ""
            if params:
                query_string = "?" + "&".join(f"{k}={v}" for k, v in params.items())

            body_str = ""
            if body:
                body_str = json.dumps(body, separators=(",", ":"))

            headers = self._auth_headers(method.upper(), path, query_string, body_str)
            url = f"{self._base_url}{path}{query_string}"

            try:
                if method == "get":
                    resp = await self._client.get(url, headers=headers)
                elif method == "post":
                    resp = await self._client.post(url, headers=headers, content=body_str)
                elif method == "put":
                    resp = await self._client.put(url, headers=headers, content=body_str)
                elif method == "delete":
                    resp = await self._client.delete(url, headers=headers)
                else:
                    return None

                if resp.status_code == 200:
                    data = resp.json()
                    # Delta wraps responses in {"result": ..., "success": true}
                    if isinstance(data, dict) and "result" in data:
                        return data["result"]
                    return data

                if resp.status_code in self.NO_RETRY_STATUSES:
                    logger.warning("Delta %s %s -> %d: %s",
                                   method.upper(), path, resp.status_code,
                                   resp.text[:200])
                    return None

                logger.warning("Delta %s %s -> %d (attempt %d/%d)",
                               method.upper(), path, resp.status_code,
                               attempt + 1, self.MAX_RETRIES)

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.warning("Delta %s %s network error (attempt %d/%d): %s",
                               method.upper(), path, attempt + 1, self.MAX_RETRIES, e)
            except Exception:
                return None

            if attempt < self.MAX_RETRIES - 1:
                await asyncio.sleep(self.BACKOFF_SECONDS[attempt])

        self._connected = False
        return None

    async def _load_products(self) -> bool:
        """Fetch /v2/products and cache symbol -> product_id mapping."""
        data = await self._request("get", "/v2/products")
        if not data:
            return False

        self._product_ids = {}
        products = data if isinstance(data, list) else []
        for p in products:
            symbol = p.get("symbol", "")
            pid = p.get("id")
            if symbol and pid is not None:
                self._product_ids[symbol] = int(pid)

        logger.info("Delta: loaded %d products", len(self._product_ids))
        return len(self._product_ids) > 0

    # -- IBroker implementation --

    async def connect(self) -> bool:
        if not self._key or not self._secret:
            logger.error("Delta API keys not configured")
            return False

        # Load product ID mappings
        if not await self._load_products():
            logger.error("Delta: failed to load products")
            return False

        # Verify connection by fetching wallet balance
        data = await self._request("get", "/v2/wallet/balances")
        if data is not None:
            self._connected = True
            logger.info("Connected to Delta Exchange. Products: %d",
                        len(self._product_ids))
            return True

        logger.error("Delta connection failed")
        return False

    async def disconnect(self) -> None:
        self._connected = False
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_balance(self) -> BalanceInfo:
        if not self._connected:
            if self._last_balance:
                return self._last_balance
            return BalanceInfo(total=0, available=0, currency="USD")

        data = await self._request("get", "/v2/wallet/balances")
        if not data or not isinstance(data, list):
            # API failed — return last known good balance instead of 0
            if self._last_balance:
                logger.warning("Delta wallet API failed, using cached balance")
                return self._last_balance
            return BalanceInfo(total=0, available=0, currency="USD")

        # Prefer USD (testnet settling asset), then USDT, then BTC
        for preferred in ("USD", "USDT", "BTC"):
            for asset in data:
                if asset.get("asset_symbol") == preferred:
                    bal = _safe_float(asset.get("balance"))
                    avail = _safe_float(asset.get("available_balance"))
                    if bal > 0 or avail > 0:
                        result = BalanceInfo(
                            total=round(bal, 2),
                            available=round(avail, 2),
                            currency=preferred,
                        )
                        self._last_balance = result
                        return result

        if self._last_balance:
            return self._last_balance
        return BalanceInfo(total=0, available=0, currency="USD")

    async def get_positions(self) -> list[ExchangePosition]:
        if not self._connected:
            return []

        # Delta requires product_id — query margined positions instead
        data = await self._request(
            "get", "/v2/positions/margined",
        )
        if not data or not isinstance(data, list):
            return []

        positions = []
        for pos in data:
            size = _safe_float(pos.get("size"))
            if size == 0:
                continue

            product = pos.get("product", {})
            symbol = product.get("symbol", "") if isinstance(product, dict) else ""

            positions.append(ExchangePosition(
                symbol=symbol,
                direction=Direction.LONG if size > 0 else Direction.SHORT,
                quantity=abs(size),
                entry_price=_safe_float(pos.get("entry_price")),
                current_price=_safe_float(pos.get("mark_price")),
                unrealized_pnl=_safe_float(pos.get("unrealized_pnl")),
                leverage=_safe_float(pos.get("leverage"), 1.0),
            ))
        return positions

    async def get_order_status(self, order_id: str) -> OrderResult:
        if not self._connected:
            return OrderResult(order_id=order_id, success=False, error="Not connected")

        data = await self._request("get", f"/v2/orders/{order_id}")
        if data and isinstance(data, dict):
            state = data.get("state", "")
            return OrderResult(
                order_id=str(data.get("id", order_id)),
                success=state in ("closed", "filled"),
                filled_price=_safe_float(data.get("average_fill_price")),
                filled_quantity=_safe_float(data.get("size")),
            )
        return OrderResult(order_id=order_id, success=False, error="Order not found")

    async def place_order(self, setup: TradeSetup) -> OrderResult:
        if not self._connected:
            return OrderResult(success=False, error="Not connected")

        delta_sym = self._exchange_symbol(setup.symbol)
        product_id = self._product_ids.get(delta_sym)
        if product_id is None:
            return OrderResult(
                success=False,
                error=f"Unknown Delta product: {delta_sym}",
            )

        side = "buy" if setup.direction == Direction.LONG else "sell"

        # Place main market order
        order_body = {
            "product_id": product_id,
            "size": int(setup.position_size) if setup.position_size >= 1 else setup.position_size,
            "side": side,
            "order_type": "market_order",
        }

        result = await self._request("post", "/v2/orders", body=order_body)

        if not result or not isinstance(result, dict):
            return OrderResult(success=False, error="Order rejected by Delta")

        order_id = str(result.get("id", ""))
        filled_price = _safe_float(result.get("average_fill_price"))
        if filled_price <= 0:
            filled_price = setup.entry_price

        # Place bracket order for SL/TP (the killer feature)
        if setup.stop_loss > 0 or setup.take_profit > 0:
            bracket_body: dict = {
                "product_id": product_id,
                "product_symbol": delta_sym,
                "bracket_stop_trigger_method": "last_traded_price",
            }
            if setup.stop_loss > 0:
                bracket_body["stop_loss_order"] = {
                    "order_type": "market_order",
                    "stop_price": str(round(setup.stop_loss, 8)),
                }
            if setup.take_profit > 0:
                bracket_body["take_profit_order"] = {
                    "order_type": "market_order",
                    "stop_price": str(round(setup.take_profit, 8)),
                }

            bracket_result = await self._request(
                "post", "/v2/orders/bracket", body=bracket_body,
            )
            if not bracket_result:
                logger.warning("Delta: bracket order failed for %s (main order OK)",
                               delta_sym)

        return OrderResult(
            order_id=order_id,
            success=True,
            filled_price=filled_price,
            filled_quantity=_safe_float(
                result.get("size", setup.position_size),
            ),
        )

    async def close_position(self, symbol: str) -> OrderResult:
        if not self._connected:
            return OrderResult(success=False, error="Not connected")

        positions = await self.get_positions()
        delta_sym = self._exchange_symbol(symbol)

        for pos in positions:
            if pos.symbol == delta_sym or pos.symbol == symbol:
                close_side = "sell" if pos.direction == Direction.LONG else "buy"
                product_id = self._product_ids.get(pos.symbol)
                if product_id is None:
                    continue

                # Cancel all open orders for this product first
                await self.cancel_all_orders(symbol)

                order_body = {
                    "product_id": product_id,
                    "size": int(pos.quantity) if pos.quantity >= 1 else pos.quantity,
                    "side": close_side,
                    "order_type": "market_order",
                    "reduce_only": True,
                }

                result = await self._request("post", "/v2/orders", body=order_body)
                if result and isinstance(result, dict):
                    return OrderResult(
                        order_id=str(result.get("id", "")),
                        success=True,
                        filled_price=_safe_float(result.get("average_fill_price")),
                        filled_quantity=pos.quantity,
                    )

        return OrderResult(success=False, error=f"No position for {symbol}")

    async def cancel_all_orders(self, symbol: str) -> bool:
        if not self._connected:
            return False

        delta_sym = self._exchange_symbol(symbol)
        product_id = self._product_ids.get(delta_sym)
        if product_id is None:
            return False

        result = await self._request(
            "delete", "/v2/orders/all",
            params={"product_id": str(product_id)},
        )
        return result is not None
