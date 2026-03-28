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
from ..core.models import OrderFlowSnapshot
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
CRYPTO = {
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD",
    "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD",
    "LTCUSD", "NEARUSD", "SUIUSD", "ARBUSD",
    "PEPEUSD", "WIFUSD", "FTMUSD", "ATOMUSD",
}

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
    "LTCUSD": "LTC/USDT",
    "NEARUSD": "NEAR/USDT",
    "SUIUSD": "SUI/USDT",
    "ARBUSD": "ARB/USDT",
    "PEPEUSD": "PEPE/USDT",
    "WIFUSD": "WIF/USDT",
    "FTMUSD": "FTM/USDT",
    "ATOMUSD": "ATOM/USDT",
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
        """DE-16: Save rate limit state so restarts don't reset the daily counter.

        Uses RateLimitState Pydantic schema for validation via safe_save_json.
        """
        import os
        from ..journal.schemas import safe_save_json, RateLimitState
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "rate_limit_state.json")
        try:
            state = RateLimitState(
                daily_calls=self._td_daily_calls,
                date=self._td_daily_reset.date().isoformat(),
            )
            safe_save_json(path, state)
        except Exception as e:
            logger.warning("Failed to persist rate limit state: %s", e)

    def _load_rate_limit(self):
        """DE-16: Load rate limit state on startup.

        Uses RateLimitState Pydantic schema for validation via safe_load_json.
        """
        import os
        from ..journal.schemas import safe_load_json, RateLimitState
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "rate_limit_state.json")
        try:
            state = safe_load_json(path, RateLimitState)
            if state.date == datetime.now(timezone.utc).date().isoformat():
                self._td_daily_calls = state.daily_calls
        except Exception as e:
            logger.warning("Failed to load rate limit state: %s", e)

    def _check_staleness(self, candles: list[Candle], timeframe: str = "") -> list[Candle]:
        """
        Check if candle data is stale (too old).
        Threshold is timeframe-aware: a 4h candle that's 3h old is normal, not stale.
        Returns candles if fresh, empty list if stale.
        Disabled when max_stale_minutes = 0 (backtesting mode).
        """
        if not candles or self.max_stale_minutes <= 0:
            return candles

        latest = candles[-1].timestamp
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)

        age = (datetime.now(timezone.utc) - latest).total_seconds() / 60

        # Threshold = max(configured limit, 2x the timeframe interval)
        # A closed 4h candle can naturally be up to 4h old
        tf_minutes = TF_SECONDS.get(timeframe, 300) / 60
        threshold = max(self.max_stale_minutes, tf_minutes * 2)

        if age > threshold:
            logger.warning("Stale data detected: %s latest candle is %.1f min old (limit: %.0f)",
                          timeframe, age, threshold)
            return []

        return candles

    def get_cached_candles(self, symbol: str, timeframe: str) -> list[Candle] | None:
        """ML-A03 FIX: Public API to read cached candles without triggering a fetch.

        Returns cached candles if available and fresh, None otherwise.
        Used by accuracy.py to resolve predictions without async calls.
        """
        cache_key = (symbol, timeframe)
        if cache_key in self._cache:
            cached, fetch_time = self._cache[cache_key]
            if datetime.now(timezone.utc) - fetch_time < timedelta(minutes=5):
                return cached
        return None

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
        candles = self._check_staleness(candles, timeframe)

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
        # DE-02 FIX: Acquire CCXT lock for fetch_ticker (not just fetch_ohlcv)
        if symbol in CRYPTO or symbol.endswith("USDT"):
            try:
                ccxt_sym = CCXT_SYMBOL_MAP.get(symbol) or CCXT_SYMBOL_MAP.get(symbol.replace("USDT", "USD"))
                if ccxt_sym:
                    async with self._ccxt_lock:
                        exchange = self._get_ccxt_exchange()
                        ticker = await asyncio.get_running_loop().run_in_executor(
                            None, lambda: exchange.fetch_ticker(ccxt_sym)
                        )
                    if ticker and "bid" in ticker and "ask" in ticker:
                        return (float(ticker["bid"]), float(ticker["ask"]))
            except Exception as e:
                logger.warning("Failed to fetch real bid/ask for %s: %s", symbol, e)

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

    # ---------------------------------------------------------------
    # Phase 0: Order Flow Data — beyond OHLCV
    # These methods use CCXT functions that were always available
    # but never called. They provide real order flow data for free.
    # ---------------------------------------------------------------

    async def get_orderbook_imbalance(
        self, symbol: str, levels: int = 20,
    ) -> dict:
        """Fetch order book and calculate bid/ask imbalance.

        Returns dict with imbalance (-1 to +1), spread, walls, and depth ratio.
        Positive imbalance = buyer-dominated, negative = seller-dominated.
        """
        ccxt_symbol = CCXT_SYMBOL_MAP.get(symbol)
        if not ccxt_symbol:
            return {"imbalance": 0.0, "spread_pct": 0.0, "bid_walls": [], "ask_walls": []}

        try:
            async with self._ccxt_lock:
                exchange = self._get_ccxt_exchange()
                book = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: exchange.fetch_order_book(ccxt_symbol, limit=levels)
                )

            bids = book.get("bids", [])[:levels]
            asks = book.get("asks", [])[:levels]

            if not bids or not asks:
                return {"imbalance": 0.0, "spread_pct": 0.0, "bid_walls": [], "ask_walls": []}

            bid_volume = sum(amount for _, amount in bids)
            ask_volume = sum(amount for _, amount in asks)
            total = bid_volume + ask_volume
            imbalance = (bid_volume - ask_volume) / total if total > 0 else 0.0

            best_bid = bids[0][0]
            best_ask = asks[0][0]
            spread_pct = (best_ask - best_bid) / best_bid * 100 if best_bid > 0 else 0.0

            # Wall detection: orders > 5x average size at that level
            avg_bid = bid_volume / len(bids) if bids else 0
            avg_ask = ask_volume / len(asks) if asks else 0
            bid_walls = [price for price, amount in bids if amount > avg_bid * 5]
            ask_walls = [price for price, amount in asks if amount > avg_ask * 5]

            depth_ratio = bid_volume / ask_volume if ask_volume > 0 else 1.0

            return {
                "imbalance": round(imbalance, 4),
                "spread_pct": round(spread_pct, 6),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "bid_volume": round(bid_volume, 4),
                "ask_volume": round(ask_volume, 4),
                "bid_walls": bid_walls[:3],
                "ask_walls": ask_walls[:3],
                "depth_ratio": round(depth_ratio, 4),
            }
        except Exception as e:
            logger.warning("Order book fetch failed for %s: %s", symbol, e)
            return {"imbalance": 0.0, "spread_pct": 0.0, "bid_walls": [], "ask_walls": []}

    async def get_real_delta(
        self, symbol: str, limit: int = 500,
    ) -> dict:
        """Fetch recent trades and calculate REAL volume delta.

        Unlike the OHLCV approximation (volume * (close-open)/(high-low)),
        this uses actual trade-by-trade data where each trade has a 'side'
        field indicating whether the buyer or seller was the aggressor.

        Also detects large trades (whale activity).
        """
        ccxt_symbol = CCXT_SYMBOL_MAP.get(symbol)
        if not ccxt_symbol:
            return {"delta": 0.0, "buy_volume": 0.0, "sell_volume": 0.0}

        try:
            async with self._ccxt_lock:
                exchange = self._get_ccxt_exchange()
                trades = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: exchange.fetch_trades(ccxt_symbol, limit=limit)
                )

            if not trades:
                return {"delta": 0.0, "buy_volume": 0.0, "sell_volume": 0.0}

            buy_vol = sum(t["amount"] for t in trades if t.get("side") == "buy")
            sell_vol = sum(t["amount"] for t in trades if t.get("side") == "sell")
            delta = buy_vol - sell_vol

            # Large trade detection (whale activity)
            amounts = [t["amount"] for t in trades]
            avg_size = sum(amounts) / len(amounts) if amounts else 0
            large_threshold = avg_size * 10
            large_trades = [t for t in trades if t["amount"] > large_threshold]
            large_bias = sum(
                1 if t.get("side") == "buy" else -1
                for t in large_trades
            )

            # Trade intensity (trades per minute)
            if len(trades) >= 2:
                time_span_s = (trades[-1]["timestamp"] - trades[0]["timestamp"]) / 1000
                intensity = len(trades) / (time_span_s / 60) if time_span_s > 0 else 0
            else:
                intensity = 0

            return {
                "delta": round(delta, 6),
                "buy_volume": round(buy_vol, 6),
                "sell_volume": round(sell_vol, 6),
                "total_trades": len(trades),
                "large_trade_count": len(large_trades),
                "large_trade_bias": large_bias,
                "trade_intensity": round(intensity, 1),
                "avg_trade_size": round(avg_size, 6),
            }
        except Exception as e:
            logger.warning("Trade fetch failed for %s: %s", symbol, e)
            return {"delta": 0.0, "buy_volume": 0.0, "sell_volume": 0.0}

    def _get_ccxt_futures_exchange(self):
        """Lazy-init Binance Futures exchange via CCXT for derivatives data."""
        if not hasattr(self, "_ccxt_futures") or self._ccxt_futures is None:
            import ccxt
            self._ccxt_futures = ccxt.binance({
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            })
        return self._ccxt_futures

    async def get_funding_rate(self, symbol: str) -> dict:
        """Fetch current funding rate for perpetual contracts.

        Extreme positive funding = everyone is long (reversal risk).
        Extreme negative funding = everyone is short (squeeze risk).
        """
        ccxt_symbol = CCXT_SYMBOL_MAP.get(symbol)
        if not ccxt_symbol:
            return {"funding_rate": 0.0, "sentiment": "neutral"}

        # Convert spot symbol to perp format: BTC/USDT → BTC/USDT:USDT
        perp_symbol = ccxt_symbol + ":USDT"

        try:
            async with self._ccxt_lock:
                exchange = self._get_ccxt_futures_exchange()
                funding = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: exchange.fetch_funding_rate(perp_symbol)
                )

            rate = funding.get("fundingRate", 0.0) or 0.0

            # Classify sentiment from funding rate
            if rate > 0.0005:
                sentiment = "extreme_greed"
            elif rate > 0.0001:
                sentiment = "greed"
            elif rate < -0.0005:
                sentiment = "extreme_fear"
            elif rate < -0.0001:
                sentiment = "fear"
            else:
                sentiment = "neutral"

            return {
                "funding_rate": round(rate, 6),
                "funding_rate_pct": round(rate * 100, 4),
                "sentiment": sentiment,
                "mark_price": funding.get("markPrice", 0.0),
                "index_price": funding.get("indexPrice", 0.0),
            }
        except Exception as e:
            logger.warning("Funding rate fetch failed for %s: %s", symbol, e)
            return {"funding_rate": 0.0, "sentiment": "neutral"}

    async def get_open_interest(self, symbol: str) -> dict:
        """Fetch open interest for perpetual contracts.

        OI rising + price rising = new money entering (real trend).
        OI falling + price rising = shorts closing (weak, reversal risk).
        """
        ccxt_symbol = CCXT_SYMBOL_MAP.get(symbol)
        if not ccxt_symbol:
            return {"open_interest": 0.0, "oi_change_pct": 0.0}

        perp_symbol = ccxt_symbol + ":USDT"

        try:
            async with self._ccxt_lock:
                exchange = self._get_ccxt_futures_exchange()
                oi = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: exchange.fetch_open_interest(perp_symbol)
                )

            oi_value = oi.get("openInterestAmount", 0.0) or 0.0
            oi_value_usd = oi.get("openInterestValue", 0.0) or 0.0

            return {
                "open_interest": round(oi_value, 4),
                "open_interest_usd": round(oi_value_usd, 2),
            }
        except Exception as e:
            logger.warning("Open interest fetch failed for %s: %s", symbol, e)
            return {"open_interest": 0.0, "open_interest_usd": 0.0}

    async def get_order_flow_snapshot(self, symbol: str) -> OrderFlowSnapshot:
        """Fetch ALL order flow data and return a unified snapshot.

        This is the main entry point for strategies that want rich data
        beyond OHLCV candles. Fetches order book, trades, funding, and OI
        in parallel and combines them into one OrderFlowSnapshot.
        """
        if symbol not in CRYPTO:
            return OrderFlowSnapshot()

        # Fetch all data sources in parallel
        results = await asyncio.gather(
            self.get_orderbook_imbalance(symbol),
            self.get_real_delta(symbol),
            self.get_funding_rate(symbol),
            self.get_open_interest(symbol),
            return_exceptions=True,
        )

        book = results[0] if not isinstance(results[0], Exception) else {}
        delta = results[1] if not isinstance(results[1], Exception) else {}
        funding = results[2] if not isinstance(results[2], Exception) else {}
        oi = results[3] if not isinstance(results[3], Exception) else {}

        # Determine flow direction from real delta
        real_delta = delta.get("delta", 0.0)
        buy_vol = delta.get("buy_volume", 0.0)
        sell_vol = delta.get("sell_volume", 0.0)
        total_vol = buy_vol + sell_vol
        if total_vol > 0:
            delta_ratio = real_delta / total_vol
            if delta_ratio > 0.15:
                flow = "buying"
            elif delta_ratio < -0.15:
                flow = "selling"
            else:
                flow = "neutral"
        else:
            flow = "neutral"

        return OrderFlowSnapshot(
            bid_ask_imbalance=book.get("imbalance", 0.0),
            spread_pct=book.get("spread_pct", 0.0),
            bid_wall_prices=book.get("bid_walls", []),
            ask_wall_prices=book.get("ask_walls", []),
            book_depth_ratio=book.get("depth_ratio", 1.0),
            real_delta=real_delta,
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            large_trade_count=delta.get("large_trade_count", 0),
            large_trade_bias=delta.get("large_trade_bias", 0),
            trade_intensity=delta.get("trade_intensity", 0.0),
            funding_rate=funding.get("funding_rate", 0.0),
            open_interest=oi.get("open_interest", 0.0),
            sentiment=funding.get("sentiment", "neutral"),
            flow_direction=flow,
            institutional_activity=delta.get("large_trade_count", 0) >= 3,
        )


# Singleton
market_data = MarketDataProvider()
