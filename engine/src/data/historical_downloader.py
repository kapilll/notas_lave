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
from datetime import datetime, timedelta, timezone
from ..data.models import Candle

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "historical")


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
        print(f"[Download] Unknown symbol for Binance: {symbol}")
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

    print(f"[Download] Fetching {symbol} {timeframe} from {start_time.date()} to {end_time.date()}...")

    while current_since < int(end_time.timestamp() * 1000):
        try:
            ohlcv = await asyncio.get_event_loop().run_in_executor(
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
            print(f"  ... {len(all_candles)} candles downloaded", end="\r")

        except Exception as e:
            print(f"[Download] Error at {datetime.fromtimestamp(current_since/1000)}: {e}")
            break

    print(f"[Download] Complete: {len(all_candles)} candles for {symbol} {timeframe}")
    return all_candles


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

    print(f"[Download] Saved to {filepath} ({len(candles)} candles)")
    return filepath


def load_candles_csv(symbol: str, timeframe: str) -> list[Candle]:
    """Load candles from a previously saved CSV file."""
    filepath = os.path.join(DATA_DIR, f"{symbol}_{timeframe}.csv")

    if not os.path.exists(filepath):
        print(f"[Download] No saved data found: {filepath}")
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

    print(f"[Download] Loaded {len(candles)} candles from {filepath}")
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
    parser.add_argument("--symbol", default="BTCUSD", help="Symbol (BTCUSD, ETHUSD)")
    parser.add_argument("--timeframe", default="5m", help="Timeframe (1m, 5m, 15m, 1h)")
    parser.add_argument("--days", type=int, default=365, help="Days of history to download")
    args = parser.parse_args()

    async def main():
        candles = await download_binance_history(args.symbol, args.timeframe, args.days)
        if candles:
            save_candles_csv(candles, args.symbol, args.timeframe)

    asyncio.run(main())
