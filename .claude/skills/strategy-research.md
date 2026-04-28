---
name: strategy-research
description: Trading strategy research, backtesting methodology, and strategy details for Notas Lave
---

Use this skill when working on strategies, backtesting, or trading logic.

To get the full strategy research document, read: `docs/research/STRATEGIES-DETAILED.md`
To get the full trading system research, read: `docs/research/TRADING-SYSTEM-RESEARCH.md`

# Quick Strategy Reference

## 12 Active Strategies

All inherit from `BaseStrategy` in `strategies/base.py`. Stateless: `analyze(candles, symbol)` has no side effects.

**Trend:** EMA Cross, MACD, SuperTrend, Ichimoku
**Momentum:** RSI Divergence, Stochastic, Bollinger Bands
**Volume:** Volume Profile, OBV
**Volatility:** ATR Breakout, Keltner Channel
**Pattern:** Harmonic Patterns

## Confluence Scoring (confluence/scorer.py)

1. Run all strategies on candles
2. Group by category (trend, momentum, volume, volatility, pattern)
3. Apply regime weights (trending/ranging/volatile)
4. Multiply by volume analysis multiplier (0.6x weak -> 1.5x strong)
5. Output: ConfluenceResult with composite score, direction, agreeing strategies

## Volume Analysis (strategies/volume_analysis.py)

Multiplies confluence score. Uses last completed candle (not forming).
- Delta volume, cumulative volume delta (CVD)
- Volume profile (value area, POC)
- Spike detection
- Output: multiplier 0.6 (weak) to 1.5 (strong)

## Backtester (backtester/engine.py)

Walk-forward backtesting with 10 risk levers. Monte Carlo permutation test for robustness.
