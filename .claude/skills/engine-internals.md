---
name: engine-internals
description: Lab engine, broker execution, database storage, and risk management internals for Notas Lave
---

Use this skill when working on the trading engine, brokers, database, or risk management.

# Engine Internals

## Lab Engine (engine/lab.py)

Main trading loop as an asyncio background task.

**Pace presets:**
| Pace | Entry TFs | Min Score | Min R:R | Max Concurrent | Scan Interval |
|------|-----------|-----------|---------|----------------|---------------|
| conservative | 1h | 4.0 | 3.0 | 3 | 60s |
| balanced | 15m, 1h | 3.5 | 2.0 | 5 | 45s |
| aggressive | 15m, 30m, 1h | 2.5 | 2.0 | 8 | 30s |

**Tick cycle:** fetch candles -> run confluence -> if score+R:R meet thresholds -> place order -> monitor SL/TP -> reconcile journal

**Features:** RiskManager.validate_trade() before every trade, loss streak throttle (halves risk after 3 losses), error backoff (5min pause after 10 errors), graceful shutdown, dual-write to EventStore + SQLAlchemy

## Delta Broker (execution/delta.py)

- URL: `https://cdn-ind.testnet.deltaex.org`
- Auth: HMAC-SHA256 (api-key + timestamp + signature)
- Symbols: `BTCUSD`, `ETHUSD`, `SOLUSD` (NOT BTCUSDT)
- Bracket orders for server-side SL/TP
- Balance cached on API failure
- 3 retries with [1, 2, 4]s backoff, no retry on 400/401/403
- IP whitelist required

## Database

Two SQLite databases bridged by Lab Engine:

1. **EventStore** (`notas_lave_lab_v2.db`) -- append-only journal, raw sqlite3
   - Tables: trade_events, trade_id_seq
   - Events: signal -> opened -> closed -> graded
   - NEVER UPDATE, only INSERT

2. **SQLAlchemy** (`notas_lave.db`) -- structured ORM tables
   - signal_logs, trade_logs, prediction_logs, ab_tests, risk_state, token_usage
   - WAL mode, hourly checkpoint + backup

## Risk Manager (risk/manager.py)

**Prop Mode (FundingPips):** 5% daily DD, 10% total DD (static from original balance), 45% consistency, 1% risk/trade, max 3 concurrent, min 2:1 R:R, news blackout mandatory

**Personal Mode:** 6% daily DD, 20% total DD, 2% risk/trade, max 2 concurrent, min 1.5:1 R:R

Key: Daily DD = realized + unrealized. Total DD is STATIC from original balance.

## Rules

- Risk Manager called before EVERY trade
- Broker-first: place on broker, then journal
- Never hardcode symbols -- use InstrumentRegistry
- All imports: `from notas_lave.X import Y`
- Never UPDATE EventStore
- Use `get_db()` or `get_session()` for database access
