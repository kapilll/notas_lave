"""
Historical Data Downloader — fetch years of data for backtesting.

SOURCES:
1. Binance (free, via CCXT): BTC/ETH going back to 2017. No API key.
2. Twelve Data (paid upgrade): Gold/Silver with 10+ years history.
3. yfinance (free fallback): ~60 days for intraday, 5 years for daily.

USAGE:
    python -m engine.src.data.historical_downloader --symbol BTCUSD --timeframe 5m --days 365

Data is saved to engine/data/historical/ as CSV files.
These CSVs can be loaded directly by the backtester.

WHY LOCAL FILES:
- No API calls during backtesting = no rate limits
- Reproducible: same data every run
- Can backtest on years of data that APIs don't serve in one call
"""

import os
import asyncio
import csv
import logging
from datetime import datetime, timedelta, timezone
from ..data.models import Candle

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "historical")

# yfinance symbols for metals (futures, not spot — but patterns work for backtesting)
YFINANCE_METALS = {
    "XAUUSD": "GC=F",   # Gold futures (COMEX)
    "XAGUSD": "SI=F",   # Silver futures (COMEX)
}


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


async def download_binance_history(
    symbol: str,
    timeframe: str = "5m",
    days: int = 365,
) -> list[Candle]:
    """
    Download historical crypto data from Binance via CCXT.

    Binance provides free kline data back to 2017 for BTC/ETH.
    No API key needed. Paginates automatically.

    Example: download_binance_history("BTCUSD", "5m", 365)
    Downloads 1 year of 5M BTC candles (~105K candles).
    """
    import ccxt

    # Map our symbols to Binance format
    ccxt_map = {
        "BTCUSD": "BTC/USDT", "BTCUSDT": "BTC/USDT",
        "ETHUSD": "ETH/USDT", "ETHUSDT": "ETH/USDT",
    }

    binance_symbol = ccxt_map.get(symbol)
    if not binance_symbol:
        logger.error("Unknown symbol for Binance: %s", symbol)
        return []

    exchange = ccxt.binance({"enableRateLimit": True})

    # Calculate time range
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days)
    since_ms = int(start_time.timestamp() * 1000)

    # Timeframe to milliseconds for pagination
    tf_ms = {
        "1m": 60_000, "5m": 300_000, "15m": 900_000,
        "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
    }
    candle_ms = tf_ms.get(timeframe, 300_000)
    batch_size = 1000  # Binance max per request

    all_candles: list[Candle] = []
    current_since = since_ms

    logger.info("Fetching %s %s from %s to %s...", symbol, timeframe, start_time.date(), end_time.date())

    while current_since < int(end_time.timestamp() * 1000):
        try:
            ohlcv = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: exchange.fetch_ohlcv(
                    binance_symbol, timeframe, since=current_since, limit=batch_size,
                ),
            )

            if not ohlcv:
                break

            for row in ohlcv:
                ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
                all_candles.append(Candle(
                    timestamp=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                ))

            # Move to next batch
            current_since = ohlcv[-1][0] + candle_ms
            logger.info("  ... %d candles downloaded", len(all_candles))

        except Exception as e:
            logger.error("Error at %s: %s", datetime.fromtimestamp(current_since/1000), e)
            break

    # DE-08: Sort by timestamp and deduplicate overlapping batches
    seen = set()
    deduped = []
    for c in sorted(all_candles, key=lambda x: x.timestamp):
        if c.timestamp not in seen:
            seen.add(c.timestamp)
            deduped.append(c)
    if len(deduped) < len(all_candles):
        logger.info("Removed %d duplicate candles", len(all_candles) - len(deduped))
    all_candles = deduped

    logger.info("Complete: %d candles for %s %s", len(all_candles), symbol, timeframe)
    return all_candles


async def download_yfinance_history(
    symbol: str,
    timeframe: str = "1h",
    days: int = 60,
) -> list[Candle]:
    """
    Download historical Gold/Silver data from yfinance.

    yfinance limitations:
    - 1m: max 7 days
    - 5m/15m/30m: max 60 days
    - 1h: max 730 days (2 years!)
    - 1d: max 10+ years

    For Gold/Silver backtesting, use 1h timeframe for 2 years of data,
    or 1d for 10+ years. 5m is limited to 60 days.

    NOTE: yfinance gives FUTURES prices (GC=F), not spot (XAUUSD).
    Price patterns are very similar, but absolute prices differ by $5-20.
    This is fine for backtesting strategy LOGIC, not exact P&L.
    """
    import yfinance as yf
    import pandas as pd

    ticker = YFINANCE_METALS.get(symbol)
    if not ticker:
        # Also handle crypto via yfinance as fallback
        yf_crypto = {"BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
                     "BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD"}
        ticker = yf_crypto.get(symbol)

    if not ticker:
        logger.error("Unknown symbol for yfinance: %s", symbol)
        return []

    # yfinance period/interval limits
    yf_interval_map = {
        "1m": ("1m", "5d"), "5m": ("5m", "60d"), "15m": ("15m", "60d"),
        "30m": ("30m", "60d"), "1h": ("1h", f"{min(days, 729)}d"), "1d": ("1d", "max"),
    }

    if timeframe not in yf_interval_map:
        logger.error("Unsupported timeframe for yfinance: %s", timeframe)
        return []

    interval, period = yf_interval_map[timeframe]
    if period != "max" and not period.endswith("d"):
        period = f"{days}d"

    logger.info("Fetching %s (%s) %s via yfinance (period=%s)...", symbol, ticker, timeframe, period)

    def fetch_sync():
        return yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)

    try:
        df = await asyncio.get_running_loop().run_in_executor(None, fetch_sync)

        if df.empty:
            logger.warning("No data returned for %s", symbol)
            return []

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        candles = []
        for idx, row in df.iterrows():
            ts = idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)

            candles.append(Candle(
                timestamp=ts,
                open=float(row.get("Open", 0)),
                high=float(row.get("High", 0)),
                low=float(row.get("Low", 0)),
                close=float(row.get("Close", 0)),
                volume=float(row.get("Volume", 0)),
            ))

        logger.info("Complete: %d candles for %s %s", len(candles), symbol, timeframe)
        return candles

    except Exception as e:
        logger.error("yfinance error for %s: %s", symbol, e)
        return []


async def download_best_available(
    symbol: str,
    timeframe: str = "5m",
    days: int = 365,
) -> list[Candle]:
    """
    Download from the best available source for any symbol.

    Routes:
    - Crypto (BTC, ETH) → Binance (free, years of data)
    - Metals (XAU, XAG) → yfinance (free, 60 days for 5m, 2 years for 1h)

    Automatically picks the best source.
    """
    crypto_symbols = {"BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"}
    metal_symbols = {"XAUUSD", "XAGUSD"}

    if symbol in crypto_symbols:
        return await download_binance_history(symbol, timeframe, days)
    elif symbol in metal_symbols:
        return await download_yfinance_history(symbol, timeframe, days)
    else:
        # Try yfinance as generic fallback
        return await download_yfinance_history(symbol, timeframe, days)


def save_candles_csv(candles: list[Candle], symbol: str, timeframe: str) -> str:
    """Save candles to a CSV file. Returns the file path."""
    _ensure_dir()
    filename = f"{symbol}_{timeframe}.csv"
    filepath = os.path.join(DATA_DIR, filename)

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in candles:
            writer.writerow([
                c.timestamp.isoformat(),
                c.open, c.high, c.low, c.close, c.volume,
            ])

    logger.info("Saved to %s (%d candles)", filepath, len(candles))
    return filepath


def load_candles_csv(symbol: str, timeframe: str) -> list[Candle]:
    """Load candles from a previously saved CSV file."""
    filepath = os.path.join(DATA_DIR, f"{symbol}_{timeframe}.csv")

    if not os.path.exists(filepath):
        logger.warning("No saved data found: %s", filepath)
        return []

    candles = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = datetime.fromisoformat(row["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            candles.append(Candle(
                timestamp=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            ))

    logger.info("Loaded %d candles from %s", len(candles), filepath)
    return candles


def list_available_data() -> list[dict]:
    """List all saved historical data files."""
    _ensure_dir()
    files = []
    for f in os.listdir(DATA_DIR):
        if f.endswith(".csv"):
            parts = f.replace(".csv", "").split("_")
            filepath = os.path.join(DATA_DIR, f)
            size = os.path.getsize(filepath)
            # Count lines (= candle count + header)
            with open(filepath) as fh:
                lines = sum(1 for _ in fh) - 1

            files.append({
                "file": f,
                "symbol": parts[0] if parts else "unknown",
                "timeframe": parts[1] if len(parts) > 1 else "unknown",
                "candles": lines,
                "size_mb": round(size / 1024 / 1024, 2),
            })

    return files


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download historical trading data")
    parser.add_argument("--symbol", default="BTCUSD",
                        help="Symbol: BTCUSD, ETHUSD, XAUUSD, XAGUSD")
    parser.add_argument("--timeframe", default="5m",
                        help="Timeframe: 1m, 5m, 15m, 30m, 1h, 1d")
    parser.add_argument("--days", type=int, default=365,
                        help="Days of history (crypto: unlimited, metals 5m: 60, metals 1h: 729)")
    parser.add_argument("--all", action="store_true",
                        help="Download all instruments (BTC, ETH, Gold, Silver)")
    args = parser.parse_args()

    async def main():
        symbols = ["BTCUSD", "ETHUSD", "XAUUSD", "XAGUSD"] if args.all else [args.symbol]
        for sym in symbols:
            candles = await download_best_available(sym, args.timeframe, args.days)
            if candles:
                save_candles_csv(candles, sym, args.timeframe)
            logger.info("---")

    asyncio.run(main())
