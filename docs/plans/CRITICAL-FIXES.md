# Critical Fixes Plan — Notas Lave

**Created:** 2026-03-21
**Priority:** Must fix before any paper trading
**Status:** Not started

---

## Fix #1: Replace yfinance with Real-Time Broker APIs

**Severity:** CRITICAL
**Problem:** yfinance gives delayed data (15-30 min), wrong instruments (GC=F futures vs XAUUSD spot), 30s cache, no bid/ask spread.
**Solution:** Oanda (free practice account) for Gold/Silver + Alpaca (free paper) for BTC/ETH.

### Implementation Steps

1. **Sign up for free accounts:**
   - Oanda: https://www.oanda.com/apply/demo (practice account, no credit card)
   - Alpaca: https://alpaca.markets (paper trading, no credit card)

2. **Install SDKs:**
   ```bash
   pip install oandapyV20 alpaca-py
   ```

3. **Refactor `market_data.py`:**
   - Create `OandaProvider` class — streaming REST API for XAUUSD, XAGUSD
   - Create `AlpacaProvider` class — WebSocket for BTCUSD, ETHUSD
   - Keep `YFinanceProvider` as fallback (historical data / backtesting only)
   - Route by symbol: `XAUUSD/XAGUSD → Oanda`, `BTCUSD/ETHUSD → Alpaca`

4. **Key changes:**
   - Get **bid AND ask** prices (not just close)
   - Stream real-time prices via WebSocket (not polling every 30s)
   - Store proper OHLCV with correct timestamps in instrument's timezone
   - Cache should be per-tick, not time-based

5. **Config additions:**
   ```python
   oanda_account_id: str  # from .env
   oanda_api_token: str   # from .env
   alpaca_api_key: str    # from .env
   alpaca_secret_key: str # from .env
   ```

### Files to modify:
- `engine/src/data/market_data.py` — full rewrite
- `engine/src/config.py` — add broker credentials
- `engine/.env.example` — add new env vars

---

## Fix #2: Position Sizing with Proper Pip Values

**Severity:** CRITICAL
**Problem:** `position_size = risk_amount / price_risk` doesn't account for pip values, lot sizes, or contract specifications. Could risk 50x intended amount.

### Implementation Steps

1. **Create instrument specifications:**
   ```python
   INSTRUMENT_SPECS = {
       "XAUUSD": {
           "pip_size": 0.01,        # 1 pip = $0.01
           "pip_value_per_lot": 1.0, # $1 per pip per 1.0 lot (100 oz)
           "min_lot": 0.01,
           "max_lot": 100.0,
           "lot_step": 0.01,
           "contract_size": 100,     # 100 oz per standard lot
           "spread_typical": 0.30,   # Typical spread in price units
       },
       "XAGUSD": {
           "pip_size": 0.001,
           "pip_value_per_lot": 5.0, # $5 per pip per lot (5000 oz)
           "min_lot": 0.01,
           "max_lot": 100.0,
           "lot_step": 0.01,
           "contract_size": 5000,
           "spread_typical": 0.03,
       },
       "BTCUSD": {
           "pip_size": 0.01,
           "pip_value_per_lot": 1.0, # 1 BTC per lot
           "min_lot": 0.001,
           "max_lot": 10.0,
           "lot_step": 0.001,
           "contract_size": 1,
           "spread_typical": 5.0,
       },
       "ETHUSD": {
           "pip_size": 0.01,
           "pip_value_per_lot": 1.0,
           "min_lot": 0.01,
           "max_lot": 100.0,
           "lot_step": 0.01,
           "contract_size": 1,
           "spread_typical": 1.0,
       },
   }
   ```

2. **Fix position sizing formula:**
   ```python
   def calculate_position_size(entry, stop_loss, symbol, account_balance, risk_pct=0.01):
       spec = INSTRUMENT_SPECS[symbol]
       risk_amount = account_balance * risk_pct
       price_risk_pips = abs(entry - stop_loss) / spec["pip_size"]
       risk_per_lot = price_risk_pips * spec["pip_value_per_lot"]
       lots = risk_amount / risk_per_lot
       # Round to lot step
       lots = round(lots / spec["lot_step"]) * spec["lot_step"]
       return max(spec["min_lot"], min(lots, spec["max_lot"]))
   ```

3. **Add spread deduction to entry price:**
   - LONG entry: use ask price (entry + half spread)
   - SHORT entry: use bid price (entry - half spread)

### Files to modify:
- `engine/src/risk/manager.py` — rewrite `calculate_position_size()`
- New file: `engine/src/data/instruments.py` — instrument specifications

---

## Fix #3: Paper Trader Realistic Execution

**Severity:** HIGH
**Problem:** No slippage, no spread, SL/TP checked against close (not bid/ask), breakeven ignores spread.

### Implementation Steps

1. **Add spread simulation:**
   - Entry LONG = price + half_spread
   - Entry SHORT = price - half_spread
   - SL check LONG = bid price (not close)
   - SL check SHORT = ask price (not close)

2. **Add slippage model:**
   ```python
   def apply_slippage(price, direction, volatility_factor=1.0):
       # Random slippage 0-2 pips, higher during volatile periods
       import random
       slip_pips = random.uniform(0, 2) * volatility_factor
       if direction == "LONG":
           return price + slip_pips * pip_size  # Filled worse for buys
       else:
           return price - slip_pips * pip_size  # Filled worse for sells
   ```

3. **Fix breakeven calculation:**
   - Breakeven SL for LONG = entry_price + spread (not just entry_price)
   - Otherwise "breakeven" is actually a small loss

4. **Check SL/TP using high/low, not close:**
   - If candle LOW <= SL for a LONG → stopped out (even if close is above SL)
   - If candle HIGH >= SL for a SHORT → stopped out
   - This is how real brokers work — wicks trigger stops

### Files to modify:
- `engine/src/execution/paper_trader.py` — major rewrite of Position.check_exit() and PaperTrader.update_positions()
- `engine/src/data/instruments.py` — spread data used here

---

## Fix #4: Confluence Scorer Weight Normalization

**Severity:** HIGH
**Problem:** 4 scalping strategies contribute 4x the signal mass vs 1 fibonacci strategy. Weights should be per-category, not per-signal.

### Implementation Steps

1. **Group signals by category, then weight:**
   ```python
   # Instead of weighting each signal individually:
   # BAD:  score += signal.score * category_weight  (x4 for scalping)
   #
   # Weight the AVERAGE score of each category:
   # GOOD: category_avg = mean(signals in category)
   #       score += category_avg * category_weight  (x1 per category)
   ```

2. **Implementation:**
   ```python
   category_scores = {}  # {"scalping": [sig1.score, sig2.score], "ict": [...]}
   for signal in signals:
       cat = get_category(signal.strategy_name)
       category_scores.setdefault(cat, []).append(signal.score)

   weighted_score = 0
   for cat, scores in category_scores.items():
       avg = sum(scores) / len(scores)
       weighted_score += (avg / 100) * 10 * weights[cat]
   ```

### Files to modify:
- `engine/src/confluence/scorer.py` — rewrite scoring loop

---

## Fix #5: Multi-Timeframe Analysis

**Severity:** HIGH
**Problem:** Strategies see only one timeframe. A 5M buy signal into a 4H downtrend is a losing trade.

### Implementation Steps

1. **Add higher-timeframe trend filter:**
   ```python
   async def get_htf_bias(symbol: str) -> Direction | None:
       """Get trend direction from 4H chart."""
       candles_4h = await market_data.get_candles(symbol, "4h", 50)
       ema_50 = compute_ema([c.close for c in candles_4h], 50)
       if ema_50[-1] > ema_50[-5]:  # 4H EMA rising
           return Direction.LONG
       elif ema_50[-1] < ema_50[-5]:
           return Direction.SHORT
       return None
   ```

2. **Apply filter in confluence scorer:**
   - If HTF bias is LONG, reject SHORT signals (or reduce score by 50%)
   - If HTF bias is SHORT, reject LONG signals
   - If HTF bias is None (unclear), allow both but reduce scores by 20%

3. **Add to ConfluenceResult:**
   ```python
   htf_bias: Direction | None  # Higher timeframe trend
   htf_aligned: bool           # Does signal match HTF trend?
   ```

### Files to modify:
- `engine/src/confluence/scorer.py` — add HTF filter call
- `engine/src/data/models.py` — add htf fields to ConfluenceResult

---

## Fix #6: Kill Zone Timezone Bug

**Severity:** MEDIUM
**Problem:** Candle timestamps may be in exchange timezone (US/Eastern for futures), not UTC. Session range pulls from ALL days, not just today.

### Implementation Steps

1. **Normalize all timestamps to UTC on ingestion:**
   ```python
   # In market_data.py, when creating Candle:
   timestamp = idx.to_pydatetime()
   if timestamp.tzinfo is None:
       timestamp = timestamp.replace(tzinfo=timezone.utc)
   else:
       timestamp = timestamp.astimezone(timezone.utc)
   ```

2. **Filter session range to TODAY only:**
   ```python
   def get_session_range(candles, start_hour, end_hour):
       today = datetime.now(timezone.utc).date()
       session_candles = [
           c for c in candles
           if c.timestamp.date() == today and start_hour <= c.timestamp.hour < end_hour
       ]
   ```

### Files to modify:
- `engine/src/data/market_data.py` — normalize timestamps
- `engine/src/strategies/session_killzone.py` — filter by today's date

---

## Fix #7: Order Block Mitigation (Expiry)

**Severity:** MEDIUM
**Problem:** Order blocks never expire and can trigger repeatedly.

### Implementation Steps

1. **Mark OBs as mitigated when price touches them:**
   - First touch = valid (trade it)
   - Second touch = mitigated (ignore it)

2. **Add age decay:**
   - OBs older than 100 candles get score reduced by 50%
   - OBs older than 200 candles are discarded

3. **Track in metadata:**
   ```python
   "age_candles": current_index - ob["index"],
   "times_tested": count_touches(candles, ob),
   ```

### Files to modify:
- `engine/src/strategies/order_blocks.py` — add mitigation and age logic

---

## Fix #8: State Persistence

**Severity:** MEDIUM
**Problem:** Engine restart loses all positions, balance, and daily P&L.

### Implementation Steps

1. **On startup:** Read last known state from SQLite
   - Load unclosed trades from `trade_logs` table
   - Reconstruct `current_balance` from initial + sum of all closed P&L
   - Reconstruct `daily_stats` from today's trades

2. **Save risk state periodically:**
   - Write `current_balance` and `daily_stats` to a `risk_state` table every trade

### Files to modify:
- `engine/src/risk/manager.py` — add load/save state
- `engine/src/execution/paper_trader.py` — restore positions on startup
- `engine/src/journal/database.py` — add `risk_state` table

---

## Fix #9: RSI Divergence Staleness

**Severity:** MEDIUM
**Problem:** Swing detection can't see current forming swings (requires future candles).

### Implementation Steps

1. **For the most recent swing, relax the "both sides" requirement:**
   - Historical swings: need `lookback` candles on both sides (confirmed)
   - Most recent swing: only need `lookback` candles on the LEFT side (forming)

2. **Add recency bonus:**
   - Divergence within last 10 candles: score +15
   - Divergence 10-20 candles ago: no bonus
   - Divergence 20+ candles ago: score -10

### Files to modify:
- `engine/src/strategies/rsi_divergence.py` — modify `find_swing_lows/highs`

---

## Fix #10: Regime Detection Improvements

**Severity:** MEDIUM
**Problem:** Arbitrary thresholds, no instrument-specific tuning, no volume consideration.

### Implementation Steps

1. **Make thresholds relative to instrument:**
   ```python
   # Instead of fixed 1% price change threshold:
   trend_threshold = atr_14 * 3 / current_price  # Dynamic based on volatility
   ```

2. **Add volume to regime detection:**
   - Rising volume + directional move = TRENDING (confirmed)
   - Rising volume + no direction = VOLATILE
   - Falling volume + no direction = QUIET

3. **Increase lookback to 50 candles** for more stable regime classification

### Files to modify:
- `engine/src/confluence/scorer.py` — rewrite `detect_regime()`

---

## Implementation Order

```
Session 2:
  Fix #1: Real-time data (Oanda + Alpaca)     ← foundation, everything depends on this
  Fix #2: Position sizing with pip values      ← safety critical
  Fix #3: Paper trader realistic execution     ← must be accurate before trading

Session 3:
  Fix #4: Confluence weight normalization      ← affects signal quality
  Fix #5: Multi-timeframe analysis             ← major accuracy improvement
  Fix #6: Kill zone timezone bug               ← correctness

Session 4:
  Fix #7: Order block mitigation               ← strategy refinement
  Fix #8: State persistence                    ← reliability
  Fix #9: RSI divergence staleness             ← strategy refinement
  Fix #10: Regime detection improvements       ← accuracy
```

## Prerequisites Before Session 2

User needs to:
1. Create Oanda practice account at https://www.oanda.com/apply/demo
2. Create Alpaca paper account at https://alpaca.markets
3. Save API keys in `engine/.env` (DO NOT commit to git)
