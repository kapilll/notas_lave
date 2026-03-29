# Broker Execution Layer

> Last verified against code: v2.0.6 (2026-03-30)

## Overview

Brokers implement `IBroker` protocol from `core/ports.py`. Auto-discovered via `@register_broker("name")` decorator.

```python
# Registration
@register_broker("delta_testnet")
class DeltaBroker:
    ...

# Usage
broker = create_broker("delta_testnet")
```

## Active Brokers

### Delta Exchange Testnet (`execution/delta.py`)
- **Status:** ACTIVE — primary broker
- **URL:** `https://cdn-ind.testnet.deltaex.org`
- **Auth:** HMAC-SHA256 signature (api-key + timestamp + signature headers)
- **Symbols:** All 11 testnet perpetuals (BTCUSD, ETHUSD, SOLUSD, XRPUSD, DOGEUSD, ADAUSD, PAXGUSD, ONDOUSD, NVDAXUSD, 1000SHIBUSD, COAIUSD)
- **Product IDs:** Fetched via `/v2/products` on `connect()`, cached
- **Key feature:** Server-side SL/TP via bracket orders (`/v2/orders/bracket`)
- **Balance:** Cached last known good value — API failures return cache, not 0
- **Positions:** `/v2/positions/margined` (not `/v2/positions`)
- **Retry:** 3 attempts with [1, 2, 4]s backoff. No retry on 400/401/403.
- **Rejection reason surfaced (v2.0.5):** `_last_request_error` captures the raw Delta API response body on 4xx/5xx. `place_order` appends it to `OrderResult.error` so logs and `trade.rejected` WebSocket events show the actual reason (e.g. `insufficient_margin`) rather than a generic message.
- **IP whitelist required** — changes with ISP

### Paper Broker (`execution/paper.py`)
- **Status:** ACTIVE — used for testing
- **Fills at requested price** — no spread, no slippage
- **In-memory only** — positions lost on restart
- **One position per symbol** — new order replaces existing

### CoinDCX (`execution/coindcx.py`)
- **Status:** STUB — not implemented

### MetaTrader 5 (`execution/mt5.py`)
- **Status:** STUB — not implemented (requires Windows VPS)

## IBroker Protocol

```python
class IBroker(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def is_connected(self) -> bool: ...
    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...
    async def get_balance(self) -> BalanceInfo: ...
    async def get_positions(self) -> list[ExchangePosition]: ...
    async def get_order_status(self, order_id: str) -> OrderResult: ...
    async def place_order(self, setup: TradeSetup) -> OrderResult: ...
    async def close_position(self, symbol: str) -> OrderResult: ...
    async def cancel_all_orders(self, symbol: str) -> bool: ...
```

## Order Flow (Delta)

```
1. place_order(setup)
   └─ POST /v2/orders (market_order)
      └─ On success: POST /v2/orders/bracket (SL/TP)

2. close_position(symbol)
   └─ cancel_all_orders(symbol) first
   └─ POST /v2/orders (market_order, reduce_only=True)
```

**Bracket orders** auto-cancel the opposing order when one fills. This is server-side — no client monitoring needed for SL/TP.

## Symbol Mapping

Single instrument registry at `data/instruments.py` (QR-03 merged). `core/instruments.py` is a thin re-export.

- **InstrumentSpec** (`data/instruments.py`): Exchange symbol mapping + pip/spread/sizing spec

The broker calls `get_instrument(symbol).exchange_symbol("delta")` to map internal symbols to Delta format.

## Rules

- **Broker-first architecture:** Place on broker, then journal. Never journal a trade the broker didn't confirm.
- **Never hardcode symbols.** Use `InstrumentRegistry.exchange_symbol()` for mapping.
- **Always handle API failures gracefully.** Return cached data or empty results, never crash.
- **Retry on transient errors only.** 400/401/403 = permanent failure, don't retry.
- **httpx client with 15s timeout.** Lazy-initialized in `_ensure_client()`.
- **Balance caching:** If API fails, return last known good balance (not zero).
