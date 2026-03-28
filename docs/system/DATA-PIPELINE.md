# Data Pipeline

> Last verified against code: v1.1.0 (2026-03-28)

## Overview

Market data flows from external APIs → in-memory cache → strategies.

```
TwelveData API ──→ Metals (XAUUSD, XAGUSD)
CCXT (Binance public data) → Crypto (18 symbols) → Cache (15s TTL) → Strategies
yfinance ────────→ Fallback (delayed)
```

**No persistent candle storage.** All data is in-memory. Lost on restart.

## Source Routing (`data/market_data.py`)

| Symbol Type | Primary Source | Fallback |
|-------------|---------------|----------|
| Metals (XAUUSD, XAGUSD) | TwelveData API | yfinance REFUSED (futures ≠ spot) |
| Crypto (BTCUSD, ETHUSD, ...) | CCXT (Binance public data, no API key) | yfinance (delayed) |
| CoinDCX symbols (BTCUSDT) | CCXT (mapped to BTC/USDT) | yfinance |

## TwelveData (Metals)

- **Free tier:** 800 calls/day, 8 calls/min
- **Rate limiting:** Tracked with daily + per-minute counters, persisted across restarts
- **Symbol format:** `XAU/USD` (converted from internal `XAUUSD`)
- **Interval mapping:** `1m`→`1min`, `5m`→`5min`, `1h`→`1h`, `4h`→`4h`, `1d`→`1day`

## CCXT (Binance Public Data)

- **No API key needed** — public market data only (no Binance broker)
- **Exchange object:** Singleton, lazy-initialized, protected by asyncio.Lock (partial — see DE-02)
- **Symbol mapping:** Internal `BTCUSD` → CCXT `BTC/USDT`
- **18 crypto symbols** mapped in `CCXT_SYMBOL_MAP`
- **Uses `run_in_executor`** for sync CCXT calls

## Cache

- **TTL:** 15 seconds
- **Key:** `(symbol, timeframe)` — normalized (`BTCUSDT` → `BTCUSD`)
- **Max entries:** 50 (LRU eviction)
- **Empty results are NOT cached** — preserves previous good data

## Data Quality

| Check | Implementation | Location |
|-------|---------------|----------|
| OHLC consistency | high >= low, high >= max(open,close), volume >= 0 | `_validate_candles()` |
| Staleness | Reject candles older than max(15min, 2× timeframe) | `_check_staleness()` |
| Continuity | Warn on gaps > 2× expected interval | `_check_continuity()` |
| NaN/Inf | Candle model validator rejects invalid values | `Candle.validate_ohlc()` |
| Positive prices | All OHLC must be > 0 | `Candle.validate_ohlc()` |

## Health Tracking

```python
self._last_fetch_success: dict[str, datetime]    # source → last success
self._consecutive_failures: dict[str, int]        # source → failure count
```

Source is "healthy" if: failures < 3 AND last success within 5 minutes.

## Instruments

**Single registry (QR-03 merged).** `data/instruments.py` is the single source of truth. `core/instruments.py` is a thin re-export for backward compatibility.

### `data/instruments.py` — Single Source of Truth
```python
InstrumentSpec(symbol="BTCUSD", pip_size=0.01, contract_size=1,
               spread_typical=15.0, min_lot=0.01,
               exchange_symbols={"delta": "BTCUSD"}, ...)
```

Key methods on `InstrumentSpec`:
- `calculate_position_size(entry, sl, balance, risk_pct, leverage)`
- `calculate_pnl(entry, exit, lots, direction)`
- `calculate_trading_fee(price, lots)`
- `get_spread(hour_utc, day_of_week)` — session-adjusted
- `breakeven_price(entry, direction)` — accounts for spread
- `calculate_liquidation_price(entry, lots, balance, leverage, direction)`

## Rules

- **Never use yfinance for metals in live trading.** GC=F is futures, not spot XAUUSD.
- **Always validate candles** via `_validate_candles()` before caching.
- **Respect TwelveData rate limits.** Leave 50-call buffer (use 750 of 800 daily limit).
- **CCXT calls must be in `_ccxt_lock`** — the exchange object is NOT thread-safe.
- **Cache only non-empty results** — prevents caching API failures.
- **Staleness can be disabled** via `max_stale_minutes = 0` (backtesting mode).
