# Data Integrity Rework — Session Plan

**Problem:** Cascading bugs from local position tracker drifting from Binance. Every patch creates new issues. P&L is unreliable. Strategy lab barely works.

**Goal:** After this session, every number on the dashboard is verifiably correct.

---

## Phase 1: Binance as Single Source of Truth (Priority: CRITICAL)

### 1A: Position Tracking — Read from Binance, Don't Calculate

**Current problem:** We maintain our own position tracker (paper_trader.py) that drifts from Binance. Entry prices, directions, quantities don't match.

**Fix:** Open positions should read DIRECTLY from Binance every tick. No local position state for exchange-connected mode.

```
CURRENT (broken):
  Local tracker → calculates P&L → shows on dashboard
  Binance has different data → mismatch

AFTER:
  Binance API → positions with real entry/P&L → shows on dashboard
  Local tracker ONLY used for paper mode (no exchange)
```

**Implementation:**
- [ ] Add `get_exchange_positions()` to lab_trader that returns Binance positions mapped to our format
- [ ] `/api/lab/positions` calls this directly when broker is connected
- [ ] `/api/lab/markets` uses exchange positions for P&L
- [ ] Local paper_trader positions only used when `broker == "paper"`

### 1B: P&L on Close — Ask Binance, Never Calculate

**Current problem:** We calculate P&L with a formula that doesn't include fees, uses wrong exit prices.

**Fix:** After closing on exchange, query Binance balance change or income API. Store ONLY verified numbers.

```
CURRENT:
  Close locally → calculate P&L with formula → store
  (Formula misses: fees, slippage, funding, wrong exit price)

AFTER:
  Close on exchange → wait 3s → query Binance balance
  Balance before - balance after = TRUE P&L → store
  Also log: calculated P&L for comparison
```

**Implementation:**
- [ ] Record wallet balance BEFORE closing
- [ ] Close position on exchange
- [ ] Wait 3s, read wallet balance AFTER
- [ ] P&L = after - before (includes all fees, exact)
- [ ] Store both `verified_pnl` and `calculated_pnl` in DB
- [ ] Dashboard shows `verified_pnl` only

### 1C: Trade Logging — Create DB Entry at Open, Complete at Close

**Current problem:** Synced positions have `trade_log_id=0`, causing journal updates to silently fail.

**Fix:** Every position MUST have a DB entry. Verify at open time.

- [ ] `open_position()` must always return a position with `trade_log_id > 0`
- [ ] Sync-positions must create trade_log entries for synced positions
- [ ] Add assertion: `assert position.trade_log_id > 0` after every open

---

## Phase 2: Data Integrity Test Suite (Priority: HIGH)

### 2A: Automated Verification Tests

Tests that run on every commit to catch data bugs:

```python
# test_data_integrity.py

def test_all_closed_trades_have_valid_exit_price():
    """Exit price must be within 50% of entry price."""

def test_sl_tp_on_correct_side():
    """LONG: SL < Entry < TP. SHORT: TP < Entry < SL."""

def test_pnl_matches_exit_reason():
    """tp_hit → P&L > 0. sl_hit → P&L < 0 (or small positive from spread)."""

def test_pnl_magnitude_reasonable():
    """P&L cannot exceed position notional value."""

def test_no_zero_sl_tp():
    """No position should have SL=0 or TP=0."""

def test_all_positions_have_trade_log_id():
    """Every position must link to a trade_log entry."""

def test_exit_price_near_sl_or_tp():
    """If reason=tp_hit, exit should be near TP. If sl_hit, near SL."""
```

### 2B: Runtime Verification (runs every 5 minutes)

A background check that compares our DB against Binance and alerts on mismatch:

- [ ] Compare position count: local vs Binance
- [ ] Compare P&L per position: local vs Binance
- [ ] Compare wallet balance: risk_manager vs Binance
- [ ] If ANY mismatch > threshold → Telegram alert + auto-sync
- [ ] Log all verification results to `data/integrity_checks.json`

### 2C: Dashboard Verification Badge

Show a green/red badge on the dashboard:
- Green: "Verified ✓" — last check passed, all data matches Binance
- Red: "Mismatch ⚠" — data doesn't match, click to see details

---

## Phase 3: Strategy Lab Fix (Priority: HIGH)

### 3A: Verify All 12 Strategies Produce Valid Signals

**Current problem:** Strategy lab shows only 1 strategy. Others aren't producing trades.

**Investigation:**
- [ ] Run each strategy on current candle data and check output
- [ ] Verify each strategy sets: direction, entry_price, stop_loss, take_profit
- [ ] Verify SL/TP are on correct side for each strategy
- [ ] Check which strategies are being blocked by the exchange conflict check

**Fix:**
- [ ] Fix any strategies that produce SL=0 or TP=0
- [ ] Fix any strategies with SL on wrong side
- [ ] Log rejection reasons: which strategies are filtered and why

### 3B: Strategy Leaderboard Data

**Current problem:** Leaderboard is empty or shows wrong data.

- [ ] Leaderboard reads from `/api/lab/strategies` which queries trade_logs
- [ ] After cleaning bad data, leaderboard is empty (no valid trades)
- [ ] Need: valid trades with strategies_agreed populated correctly
- [ ] Fix: ensure strategies_agreed JSON is always a non-empty list

### 3C: Strategy Performance Tracking

For each strategy, track:
- Signals fired (already tracked in _strategy_signals)
- Trades taken (needs: link trade to originating strategy)
- Win rate (needs: valid P&L on closed trades)
- Best timeframe (needs: timeframe logged on each trade)
- Best regime (needs: regime logged on each trade)

---

## Phase 4: Clean Slate Reset (Do this FIRST in the session)

Before implementing fixes, start with clean data:

1. Close ALL positions on Binance (start fresh)
2. Delete ALL trade_logs (history is corrupted beyond repair)
3. Reset risk manager balance to Binance wallet balance
4. Verify: DB is empty, Binance has no positions, balance matches

Then let the system trade with the new verified code and build REAL history.

---

## Verification Checklist (run after EVERY code change)

```bash
# 1. Tests pass
python -m pytest engine/tests/ -q

# 2. Dashboard builds
cd dashboard && npx next build

# 3. Data integrity (after engine runs for 1 minute)
curl -s localhost:8000/api/lab/verify | python3 -c "
import sys,json; d=json.load(sys.stdin)
print('PASS' if d.get('passed') else 'FAIL:', d.get('summary'))
"

# 4. P&L sanity (no impossible values)
python3 -c "
import sqlite3
conn = sqlite3.connect('engine/notas_lave_lab.db')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM trade_logs WHERE exit_price IS NOT NULL AND (exit_price < entry_price * 0.5 OR exit_price > entry_price * 2.0)')
bad = cur.fetchone()[0]
print(f'Bad exit prices: {bad}')
cur.execute('SELECT COUNT(*) FROM trade_logs WHERE stop_loss = 0 OR take_profit = 0')
bad2 = cur.fetchone()[0]
print(f'Missing SL/TP: {bad2}')
print('PASS' if bad == 0 and bad2 == 0 else 'FAIL')
"
```

---

## Time Estimate

| Phase | Effort | Impact |
|-------|--------|--------|
| Phase 4 (clean slate) | 10 min | Foundation |
| Phase 1A (positions from Binance) | 30 min | Fixes P&L display |
| Phase 1B (verified P&L on close) | 30 min | Fixes trade history |
| Phase 1C (trade logging) | 15 min | Fixes missing entries |
| Phase 2A (integrity tests) | 30 min | Prevents future bugs |
| Phase 2B (runtime verification) | 20 min | Auto-catches drift |
| Phase 3A (strategy validation) | 30 min | Fixes strategy lab |
| Phase 3B-C (leaderboard) | 15 min | Dashboard data |

**Total: ~3 hours for a proper, verified system.**

---

## Success Criteria

After this session, these must ALL be true:
1. Every P&L number on dashboard matches Binance within $1
2. No trade has SL=0, TP=0, or exit_price near 0
3. All 12 strategies produce valid signals with correct SL/TP side
4. Strategy leaderboard shows real data from real trades
5. `curl /api/lab/verify` returns `PASS` consistently
6. Automated tests catch any future P&L/data bugs
