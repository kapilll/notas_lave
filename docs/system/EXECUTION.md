# Broker Execution Layer

> Last verified against code: v2.0.16 (2026-03-30)

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
- **Symbols:** BTCUSD, ETHUSD, SOLUSD, XRPUSD, ADAUSD, PAXGUSD, ONDOUSD, NVDAXUSD, 1000SHIBUSD, COAIUSD (DOGEUSD removed v2.0.14 — consistent losses, slow movement, blocked position slots)
- **Product IDs:** Fetched via `/v2/products` on `connect()`, cached
- **Key feature:** Server-side SL/TP via bracket orders (`/v2/orders/bracket`)
- **Balance:** Cached last known good value — API failures return cache, not 0
- **Positions:** `/v2/positions/margined` (not `/v2/positions`)
- **Retry:** 3 attempts with [1, 2, 4]s backoff. No retry on 400/401/403.
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
   └─ POST /v2/orders (market_order, NO reduce_only)
      # reduce_only triggers Delta's bankruptcy-price check on isolated margin,
      # rejecting valid closes near liquidation. Plain opposite-side market works.
```

**Bracket orders** auto-cancel the opposing order when one fills. This is server-side — no client monitoring needed for SL/TP.

## Symbol Mapping

Single instrument registry at `data/instruments.py`. `core/instruments.py` is a thin re-export.

- **InstrumentSpec** (`data/instruments.py`): Exchange symbol mapping + pip/spread/sizing spec

The broker calls `get_instrument(symbol).exchange_symbol("delta")` to map internal symbols to Delta format.

## Rejection Reason Surfacing (v2.0.5 + v2.0.9)

### How rejection reasons flow

```
Delta API → 4xx response → _request() stores resp.text in _last_request_error
  → place_order() appends it to OrderResult.error
  → execute_trade() logs it and returns (0, error_str)
  → tick loop stores error in exec_log entry {"reason": error_str, ...}
  → _ws_broadcast("trade.rejected", entry) sends it to dashboard
  → Dashboard toast parses JSON and shows human-readable fields
```

### _last_request_error (v2.0.5)

`DeltaBroker` stores the raw Delta API response body on every 4xx/5xx:

```python
# In _request() — captures the actual Delta error JSON
if resp.status_code in self.NO_RETRY_STATUSES:
    self._last_request_error = resp.text[:400]
    return None

# In place_order() — appends it to the OrderResult error
raw = self._last_request_error or "no response body"
error = f"Order rejected by Delta (size={contract_count}, product={delta_sym}): {raw}"
```

### trade.rejected WebSocket event fields (v2.0.9+)

```json
{
  "symbol": "XRPUSD",
  "result": "broker_rejected",
  "reason": "Order rejected by Delta (size=920, product=XRPUSD): {\"error\":{\"code\":\"insufficient_margin\",...}}",
  "strategy": "level_confluence",
  "direction": "LONG"
}
```

The dashboard parses the JSON in `reason` and displays: symbol, error code (e.g. "Insufficient Margin"), available balance, required balance, margin mode.

## P&L Computation (v2.0.11)

**Rule: Never trust `unrealized_pnl` from the Delta API.** For low-price assets like DOGE, the API field returns the negative cost basis (e.g. -$232 instead of +$0.87).

Always compute from first principles:

```python
if entry > 0 and mark > 0:
    raw_pnl = (mark - entry) * qty   # LONG
    # or (entry - mark) * qty        # SHORT
else:
    raw_pnl = api_unrealized_pnl     # fallback only if prices unavailable
```

This is reliable for all instruments and contract types.

## Rules

- **Broker-first architecture:** Broker close happens BEFORE journal update. If broker rejects, journal stays open and error surfaces to UI. Previously journal was closed first, then broker error was swallowed — position showed closed in dashboard but stayed open on Delta.
- **Force-close endpoint:** `POST /api/lab/force-close/{symbol}` closes on broker directly, bypassing journal. Use when position is stuck on exchange with no matching journal entry.
- **Never hardcode symbols.** Use `InstrumentRegistry.exchange_symbol()` for mapping.
- **Always handle API failures gracefully.** Return cached data or empty results, never crash.
- **Retry on transient errors only.** 400/401/403 = permanent failure, don't retry.

## Known Bugs and Post-Mortems

### v2.0.14–15 — Close position silent failure + bankruptcy limit error

**Symptom:** Clicking Close in dashboard showed no error; journal marked trade closed but Delta position stayed open. Separately, Delta's own UI showed "order price is out of current position bankruptcy limits".

**Root causes:**
1. Journal was updated *before* broker close. Broker error was swallowed in `except: pass`. Result: journal=closed, Delta=still open.
2. `reduce_only=True` on market close orders triggers Delta's bankruptcy-price check on isolated-margin positions near liquidation.

**Fix:** Broker close now happens first. If it fails (and position isn't already gone), error is returned and journal is NOT updated. Removed `reduce_only` from close orders. Added `POST /api/lab/force-close/{symbol}` + Force button on dashboard for positions stuck on exchange with no journal entry.
- **httpx client with 15s timeout.** Lazy-initialized in `_ensure_client()`.
- **Balance caching:** If API fails, return last known good balance (not zero).
- **P&L from first principles.** Never trust `unrealized_pnl` from the API — compute from mark/entry/qty.
