"""
Binance Testnet Broker — paper trading on a REAL exchange with FAKE money.

WHY BINANCE TESTNET:
- Our internal paper trader is invisible — just numbers in a database
- Binance Testnet is a real exchange simulation with a real interface
- You can LOG IN to testnet.binancefuture.com and SEE every trade
- Watch trades appear on the Binance chart while checking TradingView
- Real order book, real fills, real slippage — but fake money (zero risk)

SETUP:
1. Go to https://testnet.binancefuture.com
2. Log in with GitHub account (free)
3. Get API key and secret from the testnet dashboard
4. Add to .env:
   BINANCE_TESTNET_KEY=your_testnet_key
   BINANCE_TESTNET_SECRET=your_testnet_secret
   BROKER=binance_testnet
5. You'll get 100,000 USDT free balance
6. Start the engine — trades will appear on the testnet interface

HOW TO VERIFY TRADES:
- Log into testnet.binancefuture.com in your browser
- Go to Futures → Positions tab
- You'll see trades appear as the agent opens/closes them
- Compare entry prices with TradingView chart
- This proves the system is actually working
"""

import uuid
from datetime import datetime, timezone

from .base_broker import (
    BaseBroker, BrokerOrder, BrokerPosition,
    OrderSide, OrderType, OrderStatus,
)
from ..config import config


class BinanceTestnetBroker(BaseBroker):
    """
    Binance Futures Testnet — real exchange, fake money.

    Uses CCXT with sandbox mode enabled. All our existing CCXT
    code works — we just flip the testnet flag.
    """

    def __init__(self):
        self._exchange = None
        self._connected = False

    @property
    def name(self) -> str:
        return "binance_testnet"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _create_exchange(self):
        """Create CCXT Binance exchange with testnet mode."""
        import ccxt

        self._exchange = ccxt.binance({
            "apiKey": config.binance_testnet_key,
            "secret": config.binance_testnet_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",  # Use futures (supports leverage)
            },
        })
        # Enable testnet/sandbox mode
        self._exchange.set_sandbox_mode(True)
        return self._exchange

    async def connect(self) -> bool:
        """Connect to Binance Testnet and verify credentials."""
        if not config.binance_testnet_key or not config.binance_testnet_secret:
            print("[Binance Testnet] API keys not configured.")
            print("[Binance Testnet] 1. Go to https://testnet.binancefuture.com")
            print("[Binance Testnet] 2. Get API key from dashboard")
            print("[Binance Testnet] 3. Add BINANCE_TESTNET_KEY and BINANCE_TESTNET_SECRET to .env")
            return False

        try:
            import asyncio
            exchange = self._create_exchange()

            # Test connection by fetching balance
            balance = await asyncio.get_event_loop().run_in_executor(
                None, exchange.fetch_balance
            )

            usdt = balance.get("USDT", {}).get("free", 0)
            self._connected = True
            print(f"[Binance Testnet] Connected. Balance: {usdt:.2f} USDT")
            return True

        except Exception as e:
            print(f"[Binance Testnet] Connection failed: {e}")
            return False

    async def disconnect(self):
        """Disconnect from testnet."""
        self._connected = False
        self._exchange = None

    async def get_balance(self) -> dict:
        """Get testnet account balance."""
        if not self._exchange:
            return {"currency": "USDT", "available": 0, "total": 0}

        try:
            import asyncio
            balance = await asyncio.get_event_loop().run_in_executor(
                None, self._exchange.fetch_balance
            )
            usdt = balance.get("USDT", {})
            return {
                "currency": "USDT",
                "available": round(float(usdt.get("free", 0)), 2),
                "total": round(float(usdt.get("total", 0)), 2),
                "used": round(float(usdt.get("used", 0)), 2),
            }
        except Exception as e:
            print(f"[Binance Testnet] Balance error: {e}")
            return {"currency": "USDT", "available": 0, "total": 0}

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
        Place a real order on Binance Testnet.

        This order will appear on testnet.binancefuture.com.
        You can see it in the Positions tab.
        """
        order_id = str(uuid.uuid4())[:8]
        order = BrokerOrder(
            order_id=order_id, symbol=symbol, side=side,
            order_type=order_type, quantity=quantity, price=price,
            stop_loss=stop_loss, take_profit=take_profit,
            leverage=leverage, created_at=datetime.now(timezone.utc),
        )

        if not self._exchange:
            order.status = OrderStatus.REJECTED
            return order

        try:
            import asyncio

            # Map symbol format: BTCUSD/BTCUSDT → BTC/USDT
            ccxt_symbol = symbol.replace("BTCUSD", "BTC/USDT").replace("ETHUSD", "ETH/USDT")
            if not ccxt_symbol.count("/"):
                ccxt_symbol = ccxt_symbol.replace("USDT", "/USDT")

            # Set leverage
            if leverage > 1:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._exchange.set_leverage(int(leverage), ccxt_symbol),
                )

            # Place order
            ccxt_side = "buy" if side == OrderSide.BUY else "sell"
            ccxt_type = "market" if order_type == OrderType.MARKET else "limit"

            params = {}
            if order_type == OrderType.LIMIT:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._exchange.create_order(
                        ccxt_symbol, ccxt_type, ccxt_side, quantity, price, params,
                    ),
                )
            else:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._exchange.create_order(
                        ccxt_symbol, ccxt_type, ccxt_side, quantity, None, params,
                    ),
                )

            order.broker_order_id = str(result.get("id", ""))
            order.status = OrderStatus.FILLED
            order.filled_price = float(result.get("average", result.get("price", 0)) or 0)
            order.filled_quantity = float(result.get("filled", quantity))
            order.fee = float(result.get("fee", {}).get("cost", 0) or 0)

            print(f"[Binance Testnet] Order filled: {ccxt_side} {quantity} {ccxt_symbol} @ {order.filled_price}")

            # Place SL/TP as separate orders if provided
            if stop_loss > 0:
                sl_side = "sell" if side == OrderSide.BUY else "buy"
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._exchange.create_order(
                            ccxt_symbol, "stop_market", sl_side, quantity,
                            None, {"stopPrice": stop_loss, "reduceOnly": True},
                        ),
                    )
                except Exception as e:
                    print(f"[Binance Testnet] SL order warning: {e}")

            if take_profit > 0:
                tp_side = "sell" if side == OrderSide.BUY else "buy"
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._exchange.create_order(
                            ccxt_symbol, "take_profit_market", tp_side, quantity,
                            None, {"stopPrice": take_profit, "reduceOnly": True},
                        ),
                    )
                except Exception as e:
                    print(f"[Binance Testnet] TP order warning: {e}")

        except Exception as e:
            order.status = OrderStatus.REJECTED
            print(f"[Binance Testnet] Order error: {e}")

        return order

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a testnet order."""
        if not self._exchange:
            return False
        try:
            import asyncio
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._exchange.cancel_order(order_id),
            )
            return True
        except Exception:
            return False

    async def get_positions(self) -> list[BrokerPosition]:
        """Get open positions from Binance Testnet."""
        if not self._exchange:
            return []

        try:
            import asyncio
            positions = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._exchange.fetch_positions(),
            )

            result = []
            for pos in positions:
                qty = float(pos.get("contracts", 0) or 0)
                if qty == 0:
                    continue

                result.append(BrokerPosition(
                    symbol=pos.get("symbol", ""),
                    side=OrderSide.BUY if pos.get("side") == "long" else OrderSide.SELL,
                    quantity=abs(qty),
                    entry_price=float(pos.get("entryPrice", 0) or 0),
                    current_price=float(pos.get("markPrice", 0) or 0),
                    unrealized_pnl=float(pos.get("unrealizedPnl", 0) or 0),
                    leverage=float(pos.get("leverage", 1) or 1),
                    liquidation_price=float(pos.get("liquidationPrice", 0) or 0),
                    margin_used=float(pos.get("initialMargin", 0) or 0),
                ))

            return result

        except Exception as e:
            print(f"[Binance Testnet] Positions error: {e}")
            return []

    async def close_position(self, symbol: str) -> BrokerOrder | None:
        """Close a testnet position."""
        positions = await self.get_positions()
        for pos in positions:
            if symbol in pos.symbol:
                close_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                return await self.place_order(
                    symbol=symbol, side=close_side,
                    quantity=pos.quantity, order_type=OrderType.MARKET,
                )
        return None
