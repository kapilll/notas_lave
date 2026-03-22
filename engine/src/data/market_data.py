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
import logging
from datetime import datetime, timedelta, timezone
from .models import Candle
from ..config import config

logger = logging.getLogger(__name__)


# Timeframe to expected interval in seconds (for continuity checks)
TF_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}

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
CRYPTO = {"BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD", "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD"}

# CCXT symbol mapping (Binance format)
CCXT_SYMBOL_MAP = {
    "BTCUSD": "BTC/USDT",
    "ETHUSD": "ETH/USDT",
    "SOLUSD": "SOL/USDT",
    "XRPUSD": "XRP/USDT",
    "BNBUSD": "BNB/USDT",
    "DOGEUSD": "DOGE/USDT",
    "ADAUSD": "ADA/USDT",
    "AVAXUSD": "AVAX/USDT",
    "LINKUSD": "LINK/USDT",
    "DOTUSD": "DOT/USDT",
}

# yfinance fallback mapping
YFINANCE_MAP = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F",
    "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
    "SOLUSD": "SOL-USD", "XRPUSD": "XRP-USD",
    "BNBUSD": "BNB-USD", "DOGEUSD": "DOGE-USD",
    "ADAUSD": "ADA-USD", "AVAXUSD": "AVAX-USD",
    "LINKUSD": "LINK-USD", "DOTUSD": "DOT-USD",
}


class MarketDataProvider:
    """
    Multi-source market data provider with automatic routing.

    Routes each symbol to the best data source:
    - Metals → Twelve Data (spot XAUUSD, not futures)
    - Crypto → CCXT/Binance (real-time, free)
    - Fallback → yfinance (delayed)

    Includes:
    - Rate limiting for Twelve Data (800 calls/day, 8/min)
    - Data staleness detection (rejects candles older than max_stale_minutes)
    """

    def __init__(self):
        self._cache: dict[tuple[str, str], tuple[list[Candle], datetime]] = {}
        self._cache_ttl = timedelta(seconds=15)  # 15s cache for real-time feel
        self._ccxt_exchange = None
        # DE-22: asyncio.Lock to make CCXT exchange object async-safe
        self._ccxt_lock = asyncio.Lock()
        # Rate limiting for Twelve Data (800/day, 8/min)
        self._td_daily_calls = 0
        self._td_daily_reset: datetime = datetime.now(timezone.utc)
        self._td_minute_calls: list[datetime] = []
        self._td_daily_limit = 750  # Leave 50 call buffer
        self._td_minute_limit = 7   # Leave 1 call buffer
        # Staleness: reject data older than this (0 = disabled for backtesting).
        # 15 min is practical — the agent's candle-freshness check handles per-trade
        # timing. This catches genuinely stale data (API outages, weekend metals).
        self.max_stale_minutes = 15
        # DE-23: Health tracking for data sources
        self._last_fetch_success: dict[str, datetime] = {}  # source -> last success time
        self._consecutive_failures: dict[str, int] = {}  # source -> failure count
        # DE-16: Load persisted rate limit state on startup
        self._load_rate_limit()

    @staticmethod
    def _check_continuity(candles: list[Candle], timeframe: str) -> None:
        """
        DE-17: Check that consecutive candles have the expected time interval.
        Logs a warning if gaps are found (missing candles in the data).
        """
        if len(candles) < 2 or timeframe not in TF_SECONDS:
            return

        expected_sec = TF_SECONDS[timeframe]
        gaps = 0
        for i in range(1, len(candles)):
            diff = (candles[i].timestamp - candles[i - 1].timestamp).total_seconds()
            # Allow up to 2x expected interval before flagging (accounts for weekends/holidays on metals)
            if diff > expected_sec * 2:
                gaps += 1

        if gaps > 0:
            logger.warning("%d gap(s) detected in %s candles (%d candles, expected interval %ds)",
                          gaps, timeframe, len(candles), expected_sec)

    def _check_td_rate_limit(self) -> bool:
        """
        Check if we can make another Twelve Data API call.
        Returns True if within limits, False if we should throttle.
        """
        now = datetime.now(timezone.utc)

        # Reset daily counter at midnight UTC
        if now.date() != self._td_daily_reset.date():
            self._td_daily_calls = 0
            self._td_daily_reset = now

        # Daily limit check
        if self._td_daily_calls >= self._td_daily_limit:
            logger.warning("Twelve Data daily limit reached (%d/%d)", self._td_daily_calls, self._td_daily_limit)
            return False

        # Per-minute limit: remove calls older than 60s
        self._td_minute_calls = [t for t in self._td_minute_calls if (now - t).total_seconds() < 60]
        if len(self._td_minute_calls) >= self._td_minute_limit:
            return False

        return True

    def _record_td_call(self):
        """Record a Twelve Data API call for rate tracking."""
        self._td_daily_calls += 1
        self._td_minute_calls.append(datetime.now(timezone.utc))
        self._persist_rate_limit()

    def _persist_rate_limit(self):
        """DE-16: Save rate limit state so restarts don't reset the daily counter."""
        import json, os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "rate_limit_state.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({
                    "daily_calls": self._td_daily_calls,
                    "date": self._td_daily_reset.date().isoformat(),
                }, f)
        except Exception:
            pass

    def _load_rate_limit(self):
        """DE-16: Load rate limit state on startup."""
        import json, os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "rate_limit_state.json")
        try:
            if os.path.exists(path):
                with open(path) as f:
                    state = json.load(f)
                if state.get("date") == datetime.now(timezone.utc).date().isoformat():
                    self._td_daily_calls = state.get("daily_calls", 0)
        except Exception:
            pass

    def _check_staleness(self, candles: list[Candle]) -> list[Candle]:
        """
        Check if candle data is stale (too old).
        Returns candles if fresh, empty list if stale.
        Disabled when max_stale_minutes = 0 (backtesting mode).
        """
        if not candles or self.max_stale_minutes <= 0:
            return candles

        latest = candles[-1].timestamp
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)

        age = (datetime.now(timezone.utc) - latest).total_seconds() / 60
        if age > self.max_stale_minutes:
            logger.warning("Stale data detected: latest candle is %.1f min old (limit: %d)", age, self.max_stale_minutes)
            return []

        return candles

    @staticmethod
    def _validate_candles(candles: list[Candle]) -> list[Candle]:
        """
        DE-25: Validate OHLC consistency. Drop candles that violate basic rules:
        - high >= low
        - high >= max(open, close)
        - low <= min(open, close)
        - volume >= 0
        - all prices > 0
        Logs a warning for each dropped candle. Does NOT attempt to fix data.
        """
        valid = []
        dropped = 0
        for c in candles:
            if c.high < c.low:
                dropped += 1
                continue
            if c.high < max(c.open, c.close):
                dropped += 1
                continue
            if c.low > min(c.open, c.close):
                dropped += 1
                continue
            if c.volume < 0:
                dropped += 1
                continue
            if c.open <= 0 or c.high <= 0 or c.low <= 0 or c.close <= 0:
                dropped += 1
                continue
            valid.append(c)
        if dropped:
            logger.warning("DE-25: Dropped %d invalid candle(s) out of %d (OHLC consistency)", dropped, len(candles))
        return valid

    def get_rate_limit_status(self) -> dict:
        """Get current rate limit usage for the dashboard."""
        return {
            "daily_calls": self._td_daily_calls,
            "daily_limit": self._td_daily_limit,
            "daily_remaining": max(0, self._td_daily_limit - self._td_daily_calls),
            "minute_calls": len([t for t in self._td_minute_calls
                                if (datetime.now(timezone.utc) - t).total_seconds() < 60]),
            "minute_limit": self._td_minute_limit,
        }

    def get_data_health(self) -> dict:
        """DE-23: Get health status of data sources."""
        now = datetime.now(timezone.utc)
        sources = {}
        for source in ["twelvedata", "ccxt", "yfinance"]:
            last = self._last_fetch_success.get(source)
            failures = self._consecutive_failures.get(source, 0)
            sources[source] = {
                "last_success": last.isoformat() if last else None,
                "seconds_since_success": (now - last).total_seconds() if last else None,
                "consecutive_failures": failures,
                "healthy": failures < 3 and (last is None or (now - last).total_seconds() < 300),
            }
        return sources

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
        # DE-26: Normalize cache key — BTCUSDT and BTCUSD map to the same
        # underlying data (BTC/USDT on Binance), so share one cache entry.
        cache_symbol = symbol.replace("USDT", "USD") if symbol.endswith("USDT") else symbol
        cache_key = (cache_symbol, timeframe)
        now = datetime.now(timezone.utc)

        if cache_key in self._cache:
            cached, fetch_time = self._cache[cache_key]
            if now - fetch_time < self._cache_ttl:
                return cached[-limit:]

        # Route to the right provider
        candles = []
        if symbol in METALS and config.twelvedata_api_key:
            if self._check_td_rate_limit():
                candles = await self._fetch_twelvedata(symbol, timeframe, limit)
                self._record_td_call()
            else:
                # Rate limited — try yfinance fallback
                candles = await self._fetch_yfinance(symbol, timeframe)
        elif symbol in CRYPTO:
            candles = await self._fetch_ccxt(symbol, timeframe, limit)
        # Also handle CoinDCX symbols (BTCUSDT, ETHUSDT → same as BTCUSD, ETHUSD)
        elif symbol.endswith("USDT"):
            base_symbol = symbol.replace("USDT", "USD")
            if base_symbol in CRYPTO:
                candles = await self._fetch_ccxt(base_symbol, timeframe, limit)

        # Fallback to yfinance if primary failed
        if not candles:
            candles = await self._fetch_yfinance(symbol, timeframe)

        # DE-17: Check for gaps in candle data
        self._check_continuity(candles, timeframe)

        # Staleness check (disabled for backtesting via max_stale_minutes=0)
        candles = self._check_staleness(candles)

        # DE-02/DE-10: Only cache non-empty results to preserve previous good data
        if candles:
            self._cache[cache_key] = (candles, now)
            # DE-14: LRU cache eviction — prevent unbounded memory growth
            if len(self._cache) > 50:  # Max 50 symbol/timeframe combos
                # Evict oldest entry
                oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
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
            df = await asyncio.get_running_loop().run_in_executor(None, fetch_sync)

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
            # DE-25: Validate OHLC consistency before returning
            candles = self._validate_candles(candles)
            # DE-23: Track success
            self._last_fetch_success["twelvedata"] = datetime.now(timezone.utc)
            self._consecutive_failures["twelvedata"] = 0
            return candles

        except Exception as e:
            logger.error("TwelveData error fetching %s: %s", symbol, e)
            # DE-23: Track failure
            self._consecutive_failures["twelvedata"] = self._consecutive_failures.get("twelvedata", 0) + 1
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
            # DE-22: Lock to make CCXT exchange object async-safe
            async with self._ccxt_lock:
                ohlcv = await asyncio.get_running_loop().run_in_executor(None, fetch_sync)

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

            # DE-25: Validate OHLC consistency before returning
            candles = self._validate_candles(candles)
            # DE-23: Track success
            self._last_fetch_success["ccxt"] = datetime.now(timezone.utc)
            self._consecutive_failures["ccxt"] = 0
            return candles

        except Exception as e:
            logger.error("CCXT error fetching %s: %s", symbol, e)
            # DE-23: Track failure
            self._consecutive_failures["ccxt"] = self._consecutive_failures.get("ccxt", 0) + 1
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

        # DE-09/AT-37: Warn that yfinance data may be delayed or use futures contracts
        # DE-24: yfinance maps metals to futures (GC=F, SI=F), NOT spot. Price differs
        # by $5-20. Refuse to return this data — metals must come from Twelve Data only.
        if symbol in METALS:
            logger.warning("Refusing yfinance fallback for %s — GC=F/SI=F are FUTURES, not spot XAUUSD/XAGUSD", symbol)
            return []
        else:
            logger.warning("Using yfinance fallback for %s — data may be delayed/futures", symbol)

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
            df = await asyncio.get_running_loop().run_in_executor(None, fetch_sync)

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

            # DE-25: Validate OHLC consistency before returning
            candles = self._validate_candles(candles)
            # DE-23: Track success
            self._last_fetch_success["yfinance"] = datetime.now(timezone.utc)
            self._consecutive_failures["yfinance"] = 0
            return candles
        except Exception as e:
            logger.error("yfinance error fetching %s: %s", symbol, e)
            # DE-23: Track failure
            self._consecutive_failures["yfinance"] = self._consecutive_failures.get("yfinance", 0) + 1
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

        # MM-10: Try real bid/ask from Binance for crypto
        if symbol in CRYPTO or symbol.endswith("USDT"):
            try:
                ccxt_sym = CCXT_SYMBOL_MAP.get(symbol) or CCXT_SYMBOL_MAP.get(symbol.replace("USDT", "USD"))
                if ccxt_sym:
                    exchange = self._get_ccxt_exchange()
                    ticker = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: exchange.fetch_ticker(ccxt_sym)
                    )
                    if ticker and "bid" in ticker and "ask" in ticker:
                        return (float(ticker["bid"]), float(ticker["ask"]))
            except Exception:
                pass

        # Fallback to spread estimation
        price = await self.get_current_price(symbol)
        if not price:
            return None

        spec = get_instrument(symbol)
        half_spread = spec.spread_typical / 2
        return (price - half_spread, price + half_spread)

    async def get_multi_timeframe(
        self, symbol: str, timeframes: list[str], limit: int = 200
    ) -> dict[str, list[Candle]]:
        """Fetch candles for multiple timeframes in parallel (DE-15)."""
        results = await asyncio.gather(
            *[self.get_candles(symbol, tf, limit) for tf in timeframes]
        )
        return dict(zip(timeframes, results))


# Singleton
market_data = MarketDataProvider()
