/**
 * Strategy information for the dashboard.
 * Displayed as tooltips and info panels so you can learn while trading.
 */

export interface StrategyInfo {
  name: string;
  displayName: string;
  category: string;
  description: string;
  howItWorks: string;
  bestFor: string;
  avoid: string;
  winRate: string;
  riskReward: string;
}

export const STRATEGY_INFO: Record<string, StrategyInfo> = {
  ema_crossover: {
    name: "ema_crossover",
    displayName: "EMA Crossover",
    category: "Scalping",
    description: "Triple EMA (9/21/50) crossover with 200 EMA trend filter.",
    howItWorks: "BUY when fast EMA (9) crosses above medium EMA (21) and all 4 EMAs are stacked bullish (9>21>50>200). SELL when reversed. The 200 EMA filters out counter-trend trades.",
    bestFor: "Trending markets — Gold and BTC during strong directional moves.",
    avoid: "Ranging/sideways markets. EMAs whipsaw and generate false signals in chop.",
    winRate: "55-65%",
    riskReward: "1:2",
  },
  rsi_divergence: {
    name: "rsi_divergence",
    displayName: "RSI Divergence",
    category: "Scalping",
    description: "Detects momentum divergence using fast RSI (7-period).",
    howItWorks: "BULLISH: Price makes a lower low but RSI makes a higher low — sellers are weakening. BEARISH: Price makes a higher high but RSI makes a lower high — buyers are weakening. These divergences often precede reversals.",
    bestFor: "Gold (extremely responsive), volatile crypto. Works at range extremes.",
    avoid: "Strong trends where divergence can persist for a long time before reversing.",
    winRate: "55-65%",
    riskReward: "1:2",
  },
  bollinger_bands: {
    name: "bollinger_bands",
    displayName: "Bollinger Bands",
    category: "Scalping",
    description: "Mean reversion when price touches and re-enters the bands.",
    howItWorks: "BUY when price closes below lower band then the next candle closes back inside (bounce). SELL when price closes above upper band then re-enters. Target: middle band (20 SMA). ~95% of price stays within the bands.",
    bestFor: "Ranging markets, Asian session, consolidation periods.",
    avoid: "Strong trends — overbought can stay overbought. The band touch becomes a breakout, not a reversal.",
    winRate: "65-75% in ranges",
    riskReward: "1:1 to 1:1.5",
  },
  stochastic_scalping: {
    name: "stochastic_scalping",
    displayName: "Stochastic",
    category: "Scalping",
    description: "Fast Stochastic (5,3,3) crossover in overbought/oversold zones.",
    howItWorks: "BUY when %K crosses above %D below 20 (oversold bounce). SELL when %K crosses below %D above 80 (overbought rejection). Measures where price is relative to its recent range.",
    bestFor: "Ranging markets. 70-80% win rate in consolidation.",
    avoid: "Trends! In a strong uptrend, Stochastic stays overbought for days. Never fight the trend with this.",
    winRate: "70-80% ranging, 40-50% trending",
    riskReward: "1:1 to 1:1.5",
  },
  vwap_scalping: {
    name: "vwap_scalping",
    displayName: "VWAP Scalping",
    category: "Volume",
    description: "Bounce/rejection from Volume-Weighted Average Price.",
    howItWorks: "VWAP = average price weighted by volume. Institutions use it as a benchmark. BUY when price is above VWAP, pulls back TO it, and bounces with volume. SELL when below VWAP, rallies to it, and rejects.",
    bestFor: "First 1-2 hours of a session. Indices, liquid forex, Gold during London/NY.",
    avoid: "End of session (VWAP becomes unreliable). Low-volume periods.",
    winRate: "60-70%",
    riskReward: "1:1.5",
  },
  fibonacci_golden_zone: {
    name: "fibonacci_golden_zone",
    displayName: "Fibonacci Golden Zone",
    category: "Fibonacci",
    description: "Entry at the 50%-61.8% retracement of an impulse move.",
    howItWorks: "After a strong move up, price often retraces to 50-61.8% before continuing. This 'Golden Zone' is where institutions reload positions. Enter on a reversal candle (hammer, engulfing) within the zone. Stop below 78.6%.",
    bestFor: "All trending markets. Gold, crypto, forex during clear impulse moves.",
    avoid: "Choppy markets with no clear swings. Needs a strong impulse to draw fibs from.",
    winRate: "60-70%",
    riskReward: "1:2 to 1:3",
  },
  session_killzone: {
    name: "session_killzone",
    displayName: "ICT Kill Zone",
    category: "ICT / Smart Money",
    description: "Asian range liquidity sweep during London/NY sessions.",
    howItWorks: "Asian session (00-08 UTC) builds a range. London/NY sessions sweep above/below that range to grab stop losses, then reverse. We wait for the sweep + reversal, not the initial breakout (which is usually fake).",
    bestFor: "Gold (responds extremely well), GBPUSD, EURUSD. London open is most powerful.",
    avoid: "Trading the initial breakout — it's usually a trap. Wait for the reversal.",
    winRate: "60-70%",
    riskReward: "1:2 to 1:3",
  },
  order_block_fvg: {
    name: "order_block_fvg",
    displayName: "Order Blocks + FVG",
    category: "ICT / Smart Money",
    description: "Institutional order blocks with Fair Value Gap confluence.",
    howItWorks: "ORDER BLOCK: The last opposite candle before a strong impulse (where institutions placed orders). FVG: A 3-candle gap showing imbalance. When price returns to an OB that overlaps with an FVG, it's the highest probability ICT setup.",
    bestFor: "Gold, BTC, major forex during active sessions. Needs volatility for FVGs to form.",
    avoid: "Low-volatility quiet markets where no impulse moves occur.",
    winRate: "55-65% (OB+FVG), 45-55% (standalone)",
    riskReward: "1:2.5",
  },
};

export const REGIME_INFO: Record<string, { description: string; bestStrategies: string; avoid: string }> = {
  TRENDING: {
    description: "Market is making higher highs/lower lows with directional momentum.",
    bestStrategies: "EMA Crossover, Fibonacci, ICT Order Blocks, Kill Zone",
    avoid: "Bollinger Bands, Stochastic (mean-reversion fails in trends)",
  },
  RANGING: {
    description: "Market is moving sideways within a range, no clear direction.",
    bestStrategies: "Bollinger Bands, Stochastic, VWAP, RSI Divergence",
    avoid: "EMA Crossover (whipsaws in ranges), breakout strategies",
  },
  VOLATILE: {
    description: "Large price swings with expanding ATR. Uncertain direction.",
    bestStrategies: "VWAP (volume confirms real moves), Order Blocks, reduce position size",
    avoid: "Tight stop strategies (will get stopped out by volatility)",
  },
  QUIET: {
    description: "Low volatility, small price movements, ATR contracting.",
    bestStrategies: "Scalping small moves (Stochastic, BB), wait for breakout",
    avoid: "Breakout strategies (no momentum to sustain them)",
  },
};
