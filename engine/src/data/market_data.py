"""
Market data provider — fetches price data from various sources.

Phase 1: Uses yfinance (free, no API key needed, works on Mac).
Phase 2: Add Oanda, Alpaca, MT5 connectors.

This module abstracts the data source so strategies don't care
WHERE the data comes from — they just get Candles.
"""

from datetime import datetime, timedelta, timezone
from ..data.models import Candle
import pandas as pd

# yfinance ticker mapping
# Gold, Silver use futures tickers; crypto uses direct symbols
SYMBOL_MAP = {
    "XAUUSD": "GC=F",      # Gold futures (close proxy to spot XAUUSD)
    "XAGUSD": "SI=F",      # Silver futures
    "BTCUSD": "BTC-USD",   # Bitcoin
    "ETHUSD": "ETH-USD",   # Ethereum
}

# yfinance interval mapping
INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "1h",   # yfinance doesn't have 4h — we'll resample from 1h
    "1d": "1d",
}

# yfinance limits how far back you can go for intraday data
# 1m: 7 days, 5m: 60 days, 15m/30m: 60 days, 1h: 730 days
PERIOD_MAP = {
    "1m": "5d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "1h": "60d",
    "4h": "60d",
    "1d": "365d",
}


class MarketDataProvider:
    """
    Fetches and caches market data. Strategies call this to get candles.

    Usage:
        provider = MarketDataProvider()
        candles = await provider.get_candles("XAUUSD", "5m", limit=200)
    """

    def __init__(self):
        # In-memory cache: {(symbol, timeframe): (candles, last_fetch_time)}
        self._cache: dict[tuple[str, str], tuple[list[Candle], datetime]] = {}
        self._cache_ttl = timedelta(seconds=30)  # Refresh every 30s for live feel

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> list[Candle]:
        """
        Get the most recent candles for a symbol/timeframe pair.

        Returns a list of Candle objects, oldest first.
        Caches results for 30 seconds to avoid hammering the API.
        """
        cache_key = (symbol, timeframe)
        now = datetime.now(timezone.utc)

        # Return cached data if fresh
        if cache_key in self._cache:
            cached_candles, fetch_time = self._cache[cache_key]
            if now - fetch_time < self._cache_ttl:
                return cached_candles[-limit:]

        # Fetch fresh data
        candles = await self._fetch_yfinance(symbol, timeframe)

        # Cache it
        self._cache[cache_key] = (candles, now)
        return candles[-limit:]

    async def _fetch_yfinance(
        self, symbol: str, timeframe: str
    ) -> list[Candle]:
        """
        Fetch data from yfinance. This runs in a thread since yfinance is sync.
        """
        import yfinance as yf
        import asyncio

        ticker = SYMBOL_MAP.get(symbol, symbol)
        interval = INTERVAL_MAP.get(timeframe, timeframe)
        period = PERIOD_MAP.get(timeframe, "60d")

        # yfinance is synchronous — run in thread pool to not block async
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: yf.download(
                ticker,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            ),
        )

        if df.empty:
            return []

        # Handle MultiIndex columns (yfinance sometimes returns these)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Resample to 4h if needed (yfinance doesn't support 4h directly)
        if timeframe == "4h":
            df = df.resample("4h").agg({
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }).dropna()

        # Convert DataFrame to list of Candle objects
        candles = []
        for idx, row in df.iterrows():
            try:
                candles.append(Candle(
                    timestamp=idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx,
                    open=float(row.get("Open", 0)),
                    high=float(row.get("High", 0)),
                    low=float(row.get("Low", 0)),
                    close=float(row.get("Close", 0)),
                    volume=float(row.get("Volume", 0)),
                ))
            except (ValueError, TypeError):
                continue

        return candles

    async def get_current_price(self, symbol: str) -> float | None:
        """Get the latest price for a symbol (last close from 1m candle)."""
        candles = await self.get_candles(symbol, "1m", limit=1)
        if candles:
            return candles[-1].close
        return None

    async def get_multi_timeframe(
        self, symbol: str, timeframes: list[str], limit: int = 200
    ) -> dict[str, list[Candle]]:
        """
        Fetch candles for multiple timeframes at once.
        Used for multi-timeframe analysis (e.g., 5m entry + 4h context).
        """
        result = {}
        for tf in timeframes:
            result[tf] = await self.get_candles(symbol, tf, limit)
        return result


# Singleton instance
market_data = MarketDataProvider()
