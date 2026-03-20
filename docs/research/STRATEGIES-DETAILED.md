# Notas Lave - Detailed Strategy Reference

**Date:** 2026-03-20
**Purpose:** Complete algorithmic rules for all 23+ trading strategies
**Usage:** Reference when implementing each strategy module

---

## Strategy Index (by Implementation Priority)

### Tier 1: Easiest to Automate (Start Here)
| # | Strategy | Category | Win Rate | R:R |
|---|----------|----------|----------|-----|
| 8 | Triple EMA Crossover (9/21/50 + 200 filter) | Trend Following | 55-65% | 1:2 |
| 11 | VWAP Scalping | Mean Reversion | 65-70% | 1:1.5 |
| 10 | Bollinger Bands Mean Reversion | Mean Reversion | 65-75% | 1:1 |
| 12 | RSI Divergence (7-period fast) | Momentum | 55-65% | 1:2 |
| 19 | Stochastic Scalping (5,3,3) | Oscillator | 70-80% ranging | 1:1 |
| 18 | Camarilla Pivot Points | Pivot Points | 70-80% | 1:1.5 |

### Tier 2: Moderate Complexity
| # | Strategy | Category | Win Rate | R:R |
|---|----------|----------|----------|-----|
| 16 | Fibonacci Golden Zone (50-61.8%) | Fibonacci | 60-70% | 1:2-3 |
| 22 | Break and Retest (Multi-TF) | Breakout | 65-75% | 1:2-3 |
| 9 | Momentum Breakout + ATR | Volatility | 50-60% | 1:3+ |
| 13 | Asian Range Breakout | Session | 60-70% | 1:2 |
| 14 | London Breakout | Session | 55-65% | 1:2-3 |
| 15 | NY Open Range Breakout | Session | 60-70% | 1:2-3 |
| 7 | EMA 200/1000 Gold Scalping | Trend | 60-70% | 1:1.5-2 |

### Tier 3: Advanced (Pattern Recognition Required)
| # | Strategy | Category | Win Rate | R:R |
|---|----------|----------|----------|-----|
| 1 | Order Block + FVG + Liquidity Sweep | ICT/SMC | 55-65% | 1:2 |
| 2 | Premium/Discount Zones (OTE) | ICT | 60-70% | 1:2 |
| 3 | ICT Silver Bullet (Time-Based) | ICT | 65-75% | 1:3 |
| 4 | Delta Divergence (Footprint) | Order Flow | 60-70% | 1:2 |
| 5 | Volume Profile POC | Volume | 55-65% | 1:2 |
| 6 | Absorption/Iceberg Detection | Order Flow | 70-80% | 1:1.5 |
| 17 | Fibonacci Extensions | Fibonacci | 50-60% | 1:3+ |
| 21 | Institutional Candle Patterns | Price Action | 50-70% | 1:2 |
| 23 | High-Impact News Breakout | Event-Driven | 50-60% | 1:2-4 |

### Tier 4: Expert (Hybrid Algo-Discretionary)
| # | Strategy | Category | Win Rate | R:R |
|---|----------|----------|----------|-----|
| 20 | Wyckoff Accumulation/Distribution | Institutional | 60-70% | 1:3+ |

---

## Instrument-Specific Recommendations

### Gold (XAUUSD) - Top 5
1. EMA 200/1000 Scalping (#7) - specifically designed for gold
2. Asian Range Breakout (#13) - gold responds extremely well
3. ICT Silver Bullet (#3) - powerful during kill zones
4. NY Open Range (#15) - extremely effective for gold
5. RSI Divergence (#12) - gold is highly responsive

### Crypto (BTC/ETH) - Top 5
1. Order Block + FVG + Liquidity Sweep (#1)
2. Premium/Discount Zones (#2)
3. Fibonacci Golden Zone (#16)
4. Volume Profile POC (#5)
5. Wyckoff Accumulation (#20) - crypto shows clear accumulation patterns

### Silver (XAGUSD) - Top 5
1. EMA 200/1000 Scalping (#7)
2. Fibonacci Golden Zone (#16)
3. Break and Retest (#22)
4. VWAP Scalping (#11)
5. Bollinger Bands (#10)

---

## Market Condition Strategy Router

| Condition | Use These | Avoid These |
|-----------|-----------|-------------|
| **Strong Trend** | #8 EMA Cross, #9 Momentum, #17 Fib Ext | #10 BB, #19 Stoch |
| **Ranging** | #10 BB, #19 Stoch, #18 Camarilla, #11 VWAP | Breakout strategies |
| **High Volatility** | #9 ATR Momentum, #23 News, reduce size | Tight-stop strategies |
| **Low Volatility** | Mean reversion (#10, #11, #19) | Breakout strategies |
| **Session Open** | #13 Asian, #14 London, #15 NY | Mean reversion early |
| **News Events** | #23 News Breakout or STAY OUT | Everything else |

---

## Confluence Combination Matrix

| Primary | Best Add-Ons | Win Rate Boost |
|---------|-------------|----------------|
| Order Blocks + FVG | + Liquidity Sweep + Session Time | +15-20% |
| VWAP Scalping | + S/R + Volume | +10-15% |
| Fibonacci Golden Zone | + Order Block + RSI Divergence | +15-20% |
| Asian Range Breakout | + FVG + Market Structure Shift | +10-15% |
| EMA Crossover | + RSI + Volume + Trend Filter | +10-15% |
| Camarilla Pivots | + VWAP + Session Open | +10-12% |
| Break and Retest | + 200 EMA + Engulfing | +15-18% |

---

## Prop Firm Success Factors

### Why 90% Fail Prop Firm Challenges
1. Risk management violations (largest cause)
2. Emotional decision-making
3. Inconsistent execution
4. Chasing "home run" trades

### Winning Approach
- **Consistency over complexity**: Simple strategies executed perfectly
- **Process-focused**: Not outcome-focused
- **2-4 trades per day maximum**: Quality over quantity
- **Protect drawdown limits**: More important than hitting profit target
- **Best challenge strategies**: Asian Range (#13), VWAP (#11), Fibonacci (#16), Break & Retest (#22)

---

## Detailed Strategy Rules

(Each strategy below contains exact entry/exit rules, indicator parameters, timeframes, and risk management rules ready for coding)

### Strategy 1: Order Block + FVG + Liquidity Sweep

**Entry (Long):**
1. Identify liquidity sweep below recent swing low (price goes 5-10 pips beyond then reverses)
2. Locate order block (last bearish candle before bullish impulse >= 2x ATR)
3. Confirm Fair Value Gap exists (3-candle pattern: C1.high < C3.low)
4. Place limit order at 50% fill of FVG within order block zone
5. Confirmation: rejection candle (wick, engulfing, pin bar)

**Exit:** Opposite liquidity zone. Trail using order block levels.
**Stop:** Beyond order block (10-20 pips for gold)
**Timeframes:** Structure on 4H/Daily, entry on 5M/15M
**Best during:** London and NY kill zones

### Strategy 3: ICT Silver Bullet

**Entry:**
1. Only trade during kill zones: London 02:00-05:00 EST, NY 07:00-10:00 EST, PM 13:30-16:00 EST
2. Within kill zone, identify liquidity sweep
3. Wait for FVG creation after sweep
4. Enter on 50% FVG fill
5. FVG minimum: 5 pips forex, 20 pips gold

**Exit:** Opposite session high/low. Time-based: close if no target within 1 hour.
**Stop:** Beyond kill zone high/low (10-15 pips)
**R:R:** Minimum 1:2, typically 1:3

### Strategy 7: EMA 200/1000 Gold Scalping

**Entry (Long):**
1. EMA 200 > EMA 1000 (confirmed uptrend)
2. Wait for pullback to EMA 200 (price within +-2 pips)
3. Bullish candle closes in trend direction at EMA 200
4. Confirm with support level confluence

**Exit:** TP 15-30 pips. Trail: move SL to breakeven after 10 pips.
**Stop:** 10-15 pips below EMA 200
**Timeframe:** 1M (ultra-fast), 5M (standard), 15M (conservative)
**Best hours:** London-NY overlap

### Strategy 8: Triple EMA Crossover

**Entry (Long):**
1. 9 EMA crosses above 21 EMA (primary signal)
2. 21 EMA > 50 EMA > 200 EMA (all aligned = strong trend)
3. Enter on close of crossover candle
4. Minimum 5 pip separation between EMAs (avoid chop)

**Exit:** 9 EMA crosses back below 21 EMA. Target: 2-3x risk.
**Stop:** 20-30 pips below 50 EMA

### Strategy 9: Momentum Breakout + ATR

**Entry:**
1. Identify key S/R level
2. Candle with range >= 2x ATR(14) breaks level
3. Close beyond level + (0.5 x ATR) buffer
4. Volume > 1.5x average
5. Candle body > 70% of total range

**Position Sizing:** If ATR > ATR(20): reduce 25-50%. If ATR < ATR(20): normal or +25%.
**Stop:** 1.0-2.0 x ATR. **Target:** 2-3x ATR from entry.

### Strategy 10: Bollinger Bands Mean Reversion

**Entry (Long):**
1. Price closes below lower BB
2. Next candle closes INSIDE bands (confirmation)
3. Enter on close of confirmation candle
4. RSI < 30 adds confluence

**Settings:** Scalping BB(9,2.0), Standard BB(20,2.0), Conservative BB(20,2.5)
**Target:** Middle band (20 SMA). Aggressive: opposite band.
**Stop:** 5 pips beyond entry band. Exit after 20 candles if no target.

### Strategy 11: VWAP Scalping

**Entry (Long):**
1. Price above VWAP = bullish bias
2. Wait for pullback to VWAP (within +-5 pips)
3. Strong green candle bounces from VWAP
4. Volume spike confirms (>1.5x average)

**Target:** 0.3-0.5% or previous session high. **Stop:** 10-15 pips beyond VWAP.
**Best:** First 1-2 hours after market open. 2-4 setups per day max.

### Strategy 12: RSI Divergence (Fast)

**Entry (Long - Bullish Divergence):**
1. Price makes lower low
2. RSI(7) makes higher low
3. RSI < 40 (oversold zone)
4. Enter when RSI crosses back above 40
5. Confirmation: bullish engulfing or hammer candle

**Settings:** Scalping RSI(7, 20/80), Ultra-fast RSI(2, 10/90), Standard RSI(14, 30/70)
**Gold-specific:** SL 11 pips, TP 33 pips (1:3)

### Strategy 13: Asian Range Breakout

**Setup:**
1. Mark Asian session high/low (00:00-08:00 GMT)
2. Wait for London open (08:00 GMT)
3. Watch for liquidity sweep above/below Asian range (5-15 pips)
4. Wait for Market Structure Shift (MSS) after sweep
5. Enter on 15M pullback after MSS
6. CRITICAL: Avoid chasing first breakout (often fake)

**Target:** Previous session high/low. **Stop:** Beyond Asian range extreme.

### Strategy 14: London Breakout

**Setup:**
1. Mark first 1-hour range after London open (08:00-09:00 GMT)
2. Wait for strong breakout candle (body >70% of range, volume >2x average)
3. Enter on retest of broken level as new S/R
4. Wait for retest increases win rate by 10-15%

**Target:** 1.5-2x initial range height. **Stop:** Opposite range + 5 pips.

### Strategy 15: NY Open Range

**Setup:**
1. Mark 9:26-9:30 AM EST range (5-minute pre-NY squeeze)
2. Look for: overlapping candles, small bodies, big wicks (tightness)
3. First 5M candle after 9:30 that breaks range = breakout
4. Entry on close of breakout candle or pullback

**Target:** 2-3x range height. Golden hour: 9:30-10:30 AM.
**Note:** Institutional algorithms trigger at NY open — not random.

### Strategy 16: Fibonacci Golden Zone

**Entry (Long):**
1. Identify clear swing low to swing high
2. Draw Fibonacci retracement
3. Wait for pullback into 50%-61.8% ("Golden Zone")
4. Enter on bullish reversal candle in zone
5. Need +2 confirmations: RSI div, MACD cross, MA confluence, or OB

**Stop:** Just beyond 78.6% level. **Targets:** 100% (swing), 127.2%, 161.8%.

### Strategy 18: Camarilla Pivot Points

**Range Trading (most common):**
1. Calculate daily Camarilla levels from previous day H/L/C
2. If open between S3 and R3: range mode
3. Long at S3 with rejection, target central pivot
4. Short at R3 with rejection, target central pivot
5. R3/S3 = most reliable reversal zones (70%+ accuracy)

**Breakout:** If price breaks R4 (strong bullish) or S4 (strong bearish), enter after retest.
**Stop:** 5-10 pips beyond entry level.

### Strategy 19: Stochastic Scalping

**Entry (Long):**
1. Stochastic below 20 (oversold)
2. %K crosses above %D
3. Enter on close of crossover candle
4. Price at support adds confluence

**Settings:** 1M: (5,3,3), 5M: (8,3,3), Standard: (14,3,3)
**Warning:** In strong trends, overbought stays overbought. Don't fight trends.

### Strategy 20: Wyckoff Accumulation

**Entry:**
1. Phase A: Identify trading range (accumulation zone)
2. Phase B: Multiple tests of S/R (up to 9 tests)
3. Phase C: Spring occurs (liquidity sweep below support)
4. Phase D: Last Point of Support (LPS) = ENTRY
5. Volume decreases on LPS pullback, increases on breakout

**Target:** Measured move from trading range height. **Stop:** Below spring low.

### Strategy 22: Break and Retest

**Entry:**
1. (4H) Identify consolidation zone (minimum 20 candles)
2. Wait for breakout: body >= 70%, close beyond level + 5 pips, volume >= 1.5x
3. (15M/5M) Wait for retest of broken level
4. Enter on engulfing candle at retest
5. 200 EMA must confirm trend direction

**Target:** 2x consolidation range. **Stop:** Beyond retested level.

### Strategy 23: News Breakout

**Setup:**
1. Identify high-impact news (NFP, CPI, Interest Rates, GDP)
2. Mark 5-15 minute range BEFORE news
3. Conservative: Wait 5 min after news, enter on retest
4. Actual vs Forecast deviation must be significant (>= 0.2%)

**Risk:** Widen stops 2-3x normal, reduce position 50%. Avoid low-liquidity sessions.
**Target:** 2-3x pre-news range. Close within 30-60 minutes.
