"""
Market data provider — multi-source with automatic routing.

ROUTING:
- XAUUSD, XAGUSD → Twelve Data API (real-time spot forex/metals, free 800 calls/day)
- BTCUSD, ETHUSD → CCXT + Binance (real-time crypto, free, no API key needed)
- Fallback       → yfinance (delayed, for historical/backtesting only)

WHY NOT YFINANCE FOR LIVE:
- yfinance data is delayed 15-30 minutes
- GC=F is gold FUTURES, not spot XAUUSD (different prices by $5-20)
- No bid/ask spread data
- 30s cache is too slow for scalping

TWELVE DATA (free tier):
- 800 API calls/day (about 1 call per 2 minutes for 4 instruments × 5 timeframes)
- Real-time XAUUSD spot (exactly what FundingPips uses)
- Supports 1min to 1month timeframes
- Sign up: https://twelvedata.com (free, works in India)

CCXT + BINANCE (free):
- Real-time BTC, ETH spot data from Binance
- No API key needed for public market data
- WebSocket available for streaming
"""

import asyncio
from datetime import datetime, timedelta, timezone
from .models import Candle
from ..config import config


# Twelve Data interval mapping
TD_INTERVAL_MAP = {
    "1m": "1min", "5m": "5min", "15m": "15min",
    "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1day",
}

# CCXT/Binance interval mapping
CCXT_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d",
}

# Which symbols go to which provider
METALS = {"XAUUSD", "XAGUSD"}
CRYPTO = {"BTCUSD", "ETHUSD"}

# CCXT symbol mapping (Binance format)
CCXT_SYMBOL_MAP = {
    "BTCUSD": "BTC/USDT",
    "ETHUSD": "ETH/USDT",
}

# yfinance fallback mapping (for when APIs fail or for backtesting)
YFINANCE_MAP = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F",
    "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
}


class MarketDataProvider:
    """
    Multi-source market data provider with automatic routing.

    Routes each symbol to the best data source:
    - Metals → Twelve Data (spot XAUUSD, not futures)
    - Crypto → CCXT/Binance (real-time, free)
    - Fallback → yfinance (delayed)
    """

    def __init__(self):
        self._cache: dict[tuple[str, str], tuple[list[Candle], datetime]] = {}
        self._cache_ttl = timedelta(seconds=15)  # 15s cache for real-time feel
        self._ccxt_exchange = None

    def _get_ccxt_exchange(self):
        """Lazy-init Binance exchange via CCXT."""
        if self._ccxt_exchange is None:
            import ccxt
            self._ccxt_exchange = ccxt.binance({"enableRateLimit": True})
        return self._ccxt_exchange

    async def get_candles(
        self, symbol: str, timeframe: str, limit: int = 200,
    ) -> list[Candle]:
        """
        Get candles from the best source for this symbol.
        Caches for 15 seconds.
        """
        cache_key = (symbol, timeframe)
        now = datetime.now(timezone.utc)

        if cache_key in self._cache:
            cached, fetch_time = self._cache[cache_key]
            if now - fetch_time < self._cache_ttl:
                return cached[-limit:]

        # Route to the right provider
        candles = []
        if symbol in METALS and config.twelvedata_api_key:
            candles = await self._fetch_twelvedata(symbol, timeframe, limit)
        elif symbol in CRYPTO:
            candles = await self._fetch_ccxt(symbol, timeframe, limit)

        # Fallback to yfinance if primary failed
        if not candles:
            candles = await self._fetch_yfinance(symbol, timeframe)

        self._cache[cache_key] = (candles, now)
        return candles[-limit:]

    async def _fetch_twelvedata(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> list[Candle]:
        """
        Fetch from Twelve Data — real-time spot forex/metals.

        This gives us ACTUAL XAUUSD spot price (not futures).
        Free tier: 800 API calls/day, 8 calls/minute.
        """
        from twelvedata import TDClient
        import asyncio

        td_interval = TD_INTERVAL_MAP.get(timeframe)
        if not td_interval:
            return []

        def fetch_sync():
            td = TDClient(apikey=config.twelvedata_api_key)
            # Twelve Data uses forex symbol format: XAU/USD
            td_symbol = symbol[:3] + "/" + symbol[3:]
            ts = td.time_series(
                symbol=td_symbol,
                interval=td_interval,
                outputsize=limit,
            )
            return ts.as_pandas()

        try:
            df = await asyncio.get_event_loop().run_in_executor(None, fetch_sync)

            if df is None or df.empty:
                return []

            candles = []
            for idx, row in df.iterrows():
                ts = idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)

                candles.append(Candle(
                    timestamp=ts,
                    open=float(row.get("open", 0)),
                    high=float(row.get("high", 0)),
                    low=float(row.get("low", 0)),
                    close=float(row.get("close", 0)),
                    volume=float(row.get("volume", 0) if "volume" in row else 0),
                ))

            # Twelve Data returns newest first — reverse to oldest first
            candles.reverse()
            return candles

        except Exception as e:
            print(f"[TwelveData] Error fetching {symbol}: {e}")
            return []

    async def _fetch_ccxt(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> list[Candle]:
        """
        Fetch from Binance via CCXT — real-time crypto data.
        No API key needed for public market data.
        """
        import asyncio

        ccxt_symbol = CCXT_SYMBOL_MAP.get(symbol)
        ccxt_tf = CCXT_INTERVAL_MAP.get(timeframe)
        if not ccxt_symbol or not ccxt_tf:
            return []

        def fetch_sync():
            exchange = self._get_ccxt_exchange()
            ohlcv = exchange.fetch_ohlcv(ccxt_symbol, ccxt_tf, limit=limit)
            return ohlcv

        try:
            ohlcv = await asyncio.get_event_loop().run_in_executor(None, fetch_sync)

            candles = []
            for row in ohlcv:
                # CCXT returns [timestamp_ms, open, high, low, close, volume]
                ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
                candles.append(Candle(
                    timestamp=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                ))

            return candles

        except Exception as e:
            print(f"[CCXT] Error fetching {symbol}: {e}")
            return []

    async def _fetch_yfinance(
        self, symbol: str, timeframe: str
    ) -> list[Candle]:
        """
        Fallback: yfinance for when primary sources fail.
        WARNING: Data is delayed. Gold uses futures (GC=F) not spot.
        Only use for historical/backtesting, not live trading decisions.
        """
        import yfinance as yf
        import pandas as pd

        ticker = YFINANCE_MAP.get(symbol, symbol)

        yf_interval_map = {
            "1m": "1m", "5m": "5m", "15m": "15m",
            "30m": "30m", "1h": "1h", "4h": "1h", "1d": "1d",
        }
        yf_period_map = {
            "1m": "5d", "5m": "60d", "15m": "60d", "30m": "60d",
            "1h": "60d", "4h": "60d", "1d": "365d",
        }

        interval = yf_interval_map.get(timeframe, timeframe)
        period = yf_period_map.get(timeframe, "60d")

        def fetch_sync():
            return yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)

        try:
            df = await asyncio.get_event_loop().run_in_executor(None, fetch_sync)

            if df.empty:
                return []

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            if timeframe == "4h":
                df = df.resample("4h").agg({
                    "Open": "first", "High": "max", "Low": "min",
                    "Close": "last", "Volume": "sum",
                }).dropna()

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

            return candles
        except Exception as e:
            print(f"[yfinance] Error fetching {symbol}: {e}")
            return []

    async def get_current_price(self, symbol: str) -> float | None:
        """Get latest price. Uses 1m candles for freshest data."""
        candles = await self.get_candles(symbol, "1m", limit=1)
        return candles[-1].close if candles else None

    async def get_bid_ask(self, symbol: str) -> tuple[float, float] | None:
        """
        Get bid/ask prices. Falls back to spread estimation if not available.
        Bid = what you get when selling. Ask = what you pay when buying.
        """
        from .instruments import get_instrument

        price = await self.get_current_price(symbol)
        if not price:
            return None

        spec = get_instrument(symbol)
        half_spread = spec.spread_typical / 2
        return (price - half_spread, price + half_spread)

    async def get_multi_timeframe(
        self, symbol: str, timeframes: list[str], limit: int = 200
    ) -> dict[str, list[Candle]]:
        """Fetch candles for multiple timeframes."""
        result = {}
        for tf in timeframes:
            result[tf] = await self.get_candles(symbol, tf, limit)
        return result


# Singleton
market_data = MarketDataProvider()
