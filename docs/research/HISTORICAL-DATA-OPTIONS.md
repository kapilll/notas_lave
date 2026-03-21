# Historical Data Options — 2+ Years for Strategy Validation

**Purpose:** RSI Divergence being the sole crypto survivor needs validation across bull/bear/range regimes. We need 2-3 years of 5-minute data.

---

## Crypto (BTC/ETH) — Already Have the Best Option

### Binance via CCXT (FREE, already built)
- **Coverage:** Back to 2017 for BTC, 2018 for ETH
- **Resolution:** 1m, 5m, 15m, 1h, 4h, 1d
- **Cost:** Free, no API key needed
- **Limit:** 1000 candles per request (auto-paginated in our downloader)
- **How:** `POST /api/data/download/BTCUSD?timeframe=5m&days=1095` (3 years)
- **Status:** ALREADY BUILT in `engine/src/data/historical_downloader.py`

**Action:** Just run the download for more days:
```bash
# Download 3 years of BTC 5M (≈315K candles)
curl -X POST "http://localhost:8000/api/data/download/BTCUSD?timeframe=5m&days=1095"

# Download 3 years of ETH 5M (≈315K candles)
curl -X POST "http://localhost:8000/api/data/download/ETHUSD?timeframe=5m&days=1095"
```

This covers: 2023 range-bound, 2024 Q4 bull run, 2025 current regime.

---

## Gold/Silver — Options Ranked

### Option 1: Twelve Data (BEST, requires upgrade)
- **Coverage:** 10+ years
- **Resolution:** 1m to 1d
- **Cost:** Free tier = 800 calls/day, 1-month history. Growth plan = $29/mo, full history
- **Format:** XAU/USD, XAG/USD (spot, not futures)
- **How:** Upgrade to Growth plan ($29/mo), download via our existing Twelve Data client
- **Pros:** Already integrated, spot data (matches FundingPips), reliable
- **Cons:** Costs money

### Option 2: Polygon.io
- **Coverage:** 10+ years for forex/metals
- **Resolution:** 1m to 1d
- **Cost:** Starter = $29/mo (includes forex), Free = stocks only
- **Format:** C:XAUUSD (forex pair format)
- **How:** New API client needed (REST, simple)
- **Pros:** Very reliable, institutional grade data
- **Cons:** Needs new integration, costs same as Twelve Data

### Option 3: OANDA API (free demo account)
- **Coverage:** 5+ years
- **Resolution:** 5s to 1M
- **Cost:** Free with demo account
- **Caveat:** Not available in India for live trading, but demo accounts work for data
- **How:** Register demo account, use oandapyV20 (already in requirements)
- **Pros:** Free, high quality, spot data
- **Cons:** India restrictions, demo account may have limits

### Option 4: yfinance Gold Futures (FREE, already built)
- **Coverage:** ~60 days intraday, 5+ years daily
- **Resolution:** 1m-60 days, 1d-5 years
- **Format:** GC=F (COMEX futures, NOT spot)
- **Limitation:** Futures ≠ Spot. Price patterns are similar but not identical
- **How:** Already built as fallback. Can download daily data for regime classification
- **Status:** ALREADY BUILT but limited to 60 days for 5M

### Option 5: MetaTrader 5 History (FREE with broker account)
- **Coverage:** 10+ years for XAUUSD
- **Resolution:** 1m to 1M
- **Cost:** Free with any MT5 broker account (even demo)
- **How:** Install MT5 on Windows, use `MetaTrader5` Python package to export history
- **Caveat:** Needs Windows (or Wine/VPS). MT5 stores history locally
- **Pros:** Free, exact FundingPips data source, spot CFD
- **Cons:** Needs Windows, manual export process

---

## Recommendation

| Instrument | Best Option | Cost | Action |
|-----------|------------|------|--------|
| **BTC** | Binance/CCXT | Free | `POST /api/data/download/BTCUSD?days=1095` |
| **ETH** | Binance/CCXT | Free | `POST /api/data/download/ETHUSD?days=1095` |
| **Gold** | Twelve Data upgrade | $29/mo | Upgrade plan, download 2-3 years |
| **Silver** | Twelve Data upgrade | $29/mo | Same plan covers both metals |

**Cheapest path:** Download 3 years crypto now (free), upgrade Twelve Data for 1 month ($29), download Gold/Silver history, cancel subscription.

**Free path:** Use OANDA demo for metals data, or accept 60-day yfinance data for Gold/Silver and focus validation on crypto (which is the primary trading target anyway).
