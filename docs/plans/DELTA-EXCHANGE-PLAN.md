# Delta Exchange Integration Plan

**Created:** 2026-03-26
**Status:** Ready to implement
**Goal:** Replace flaky Binance Demo with Delta Exchange testnet for development, CoinDCX for eventual live trading

---

## Why This Change

Binance Demo has been unreliable:
- Rejects `STOP_MARKET` orders (-4120) — SL/TP must be managed locally
- Returns `avgPrice=0` for market orders
- No server-side stop loss = zero protection when engine is down

Delta Exchange testnet solves all of this:
- Server-side SL/TP (bracket orders: SL + TP auto-cancel opposing)
- Working testnet with 0.5 BTC demo balance
- Official Python client (`delta-rest-client`)
- API parity between testnet and production

## Platform Strategy

| Phase | Platform | Purpose |
|-------|----------|---------|
| Development + Learning | **Delta Exchange testnet** | Free, safe, working SL/TP, 0.5 BTC demo |
| Live trading (India) | **CoinDCX** | Safer exchange, proven fund protection, INR |
| Prop firm (later) | **MT5 on Windows VPS** | FundingPips requires MT5 |

**Delta Exchange safety note:** Testnet is safe (no real money). For LIVE trading, Delta has withdrawal complaints (Dec 2025-Jan 2026, Trustpilot 2.6/5). Use CoinDCX for real money instead. Delta testnet is fine for development.

---

## Delta Testnet Setup

### Step 1: Create Testnet Account
1. Go to https://testnet.delta.exchange/
2. Sign up (separate from production account)
3. You get **0.5 testnet BTC** automatically

### Step 2: Generate API Keys
1. Login to testnet.delta.exchange
2. Profile icon -> "API Keys"
3. Create key, whitelist IP (or leave open for development)
4. Save `api_key` and `api_secret`

### Step 3: Add to .env
```bash
# engine/.env
DELTA_TESTNET_KEY=your_testnet_api_key
DELTA_TESTNET_SECRET=your_testnet_api_secret
BROKER=delta_testnet
```

### Step 4: Install Python Client
```bash
pip install delta-rest-client
```

---

## API Technical Reference

### Endpoints

| Environment | REST Base URL | WebSocket |
|-------------|--------------|-----------|
| **Testnet India** | `https://cdn-ind.testnet.deltaex.org` | `wss://socket.testnet.delta.exchange` |
| Production India | `https://api.india.delta.exchange` | `wss://socket.india.delta.exchange` |

### Authentication

HMAC-SHA256 with 3 headers. Signatures valid for 5 seconds only.

```python
import hmac, hashlib, time, json

def generate_signature(api_secret, method, timestamp, path, query_string="", body=""):
    signature_data = method + timestamp + path + query_string + body
    return hmac.new(
        api_secret.encode(), signature_data.encode(), hashlib.sha256
    ).hexdigest()

headers = {
    "api-key": api_key,
    "timestamp": str(int(time.time())),
    "signature": generate_signature(...),
    "Content-Type": "application/json",
}
```

### Python Client Usage

```python
from delta_rest_client import DeltaRestClient

client = DeltaRestClient(
    base_url='https://cdn-ind.testnet.deltaex.org',
    api_key='YOUR_KEY',
    api_secret='YOUR_SECRET',
)
```

### Key API Calls

**Get Balance:**
```python
product = client.get_product(product_id)
settling_asset = product['settling_asset']
balance = client.get_wallet(settling_asset['id'])
```

**Place Market Order:**
```python
order = client.place_order(
    product_id=27,          # BTCUSDT — use /v2/products to get IDs
    size=1,
    side='buy',             # 'buy' or 'sell'
    order_type='market_order',
)
```

**Place Stop Loss (server-side!):**
```python
sl = client.place_stop_order(
    product_id=27,
    size=1,
    side='sell',
    stop_order_type='stop_loss_order',
    stop_price='49000',
    order_type='market_order',
)
```

**Place Take Profit:**
```python
tp = client.place_stop_order(
    product_id=27,
    size=1,
    side='sell',
    stop_order_type='take_profit_order',
    stop_price='51000',
    order_type='market_order',
)
```

**Bracket Order (SL + TP together, auto-cancel opposing):**
```python
# POST /v2/orders/bracket
bracket = {
    "product_id": 27,
    "product_symbol": "BTCUSDT",
    "bracket_stop_trigger_method": "last_traded_price",
    "stop_loss_order": {"order_type": "market_order", "stop_price": "49000"},
    "take_profit_order": {"order_type": "market_order", "stop_price": "51000"},
}
```
When SL fills, TP auto-cancels (and vice versa). This is the killer feature vs Binance Demo.

**Get Positions:**
```python
positions = client.get_positions()
position = client.get_position(product_id=27)
```

**Cancel Order:**
```python
client.cancel_order(product_id=27, order_id='12345')
```

**Get Candles (OHLCV):**
```python
candles = client.get_ohlc(
    symbol='BTCUSDT',
    resolution='15m',       # 1m,3m,5m,15m,30m,1h,2h,4h,6h,1d,7d,30d
    start=unix_start,
    end=unix_end,
)
```

### Symbol Format

Delta uses `product_id` (integer) for orders and `product_symbol` (string) for display:
- BTCUSDT perpetual: product_id varies per environment (query `/v2/products`)
- Symbols: `BTCUSDT`, `ETHUSDT`, `XAUUSDT` (Gold), `XAGUSDT` (Silver)

**Important:** Product IDs are different between testnet and production. Always query dynamically.

### Rate Limits
- **500 operations/second per product**
- Cancellations exempt from rate limits
- Generous for our use case (we scan every 30-60s)

---

## What to Build: DeltaBroker

### Location
`engine/src/notas_lave/execution/delta.py` (v2 architecture)

### Interface
Must implement the same broker interface as `coindcx.py` and `binance.py`:
- `connect() -> bool`
- `disconnect() -> None`
- `get_balance() -> BalanceInfo`
- `get_positions() -> list[ExchangePosition]`
- `place_order(setup: TradeSetup) -> OrderResult`
- `close_position(symbol: str) -> OrderResult`
- `cancel_all_orders(symbol: str) -> bool`
- `get_order_status(order_id: str) -> OrderResult`

### Key Design Decisions

1. **Use `delta-rest-client`** — official client, less code to write
2. **Use bracket orders** for SL/TP — one API call, auto-cancel opposing
3. **Product ID mapping** — query `/v2/products` once at connect, cache the symbol->ID map
4. **Config via env vars** — `DELTA_TESTNET_KEY`, `DELTA_TESTNET_SECRET`, `BROKER=delta_testnet`
5. **Testnet vs production** — controlled by base URL in config, same code

### Symbol Mapping

Our internal symbols need to map to Delta symbols:
```
BTCUSD  -> BTCUSDT (query product_id from /v2/products)
ETHUSD  -> ETHUSDT
XAUUSD  -> XAUUSDT (Gold perpetual!)
XAGUSD  -> XAGUSDT (Silver perpetual!)
```

Delta supports Gold and Silver perpetuals — unlike Binance Demo where metals were impossible.

---

## What Changes in the Engine

### Minimal changes needed:
1. **New file:** `execution/delta.py` (the broker)
2. **Config:** Add `DELTA_TESTNET_KEY`, `DELTA_TESTNET_SECRET` to config.py
3. **Broker registry:** Register `delta_testnet` in the broker registry
4. **.env:** Set `BROKER=delta_testnet`

### What does NOT change:
- Strategies (they produce signals, don't care about broker)
- Confluence scorer (same)
- Risk manager (same)
- Learning engine (same)
- Dashboard (same)

The broker abstraction means the entire engine is broker-agnostic.

---

## Advantages Over Binance Demo

| Feature | Binance Demo | Delta Testnet |
|---------|-------------|---------------|
| Server-side SL | Rejected (-4120) | Works (bracket orders) |
| Stop orders | Broken | Full support |
| Average fill price | Returns 0 | Returns real price |
| Gold/Silver | Not tradeable | XAUUSDT, XAGUSDT available |
| Official Python lib | No | Yes (delta-rest-client) |
| API reliability | Flaky | Designed for algo trading |
| Demo balance | 5000 USDT | 0.5 BTC (~$43K) |

---

## Resources

- **Testnet signup:** https://testnet.delta.exchange/
- **API docs:** https://docs.delta.exchange/
- **Python client:** https://github.com/delta-exchange/python-rest-client
- **PyPI:** `pip install delta-rest-client`
- **Postman collection:** https://www.postman.com/derivative-engine/deltaexchange/
- **API FAQ:** https://www.delta.exchange/support/solutions/articles/80001153884
- **Bracket orders guide:** https://community.delta.exchange/t/how-to-place-bracket-orders-via-api/821/14
