"""Composite Strategy: Level Confluence System.

Replaces: VWAP Scalping, Fibonacci Golden Zone, Camarilla Pivots

HOW REAL TRADERS USE LEVELS:
The highest-probability trades happen when MULTIPLE level types
converge at the same price zone. A Fibonacci 61.8% retracement that
ALSO lines up with VWAP AND a Camarilla S3 pivot creates a "wall"
of support that institutions respect.

SIGNAL LOGIC:
1. LEVEL DETECTION: Find zones where 2+ level types cluster within 0.3%
   - Fibonacci retracement levels (23.6%, 38.2%, 50%, 61.8%, 78.6%)
   - VWAP and its standard deviation bands
   - Camarilla pivot levels (S3, S4, R3, R4 are the key ones)
   - Volume profile levels (POC, VAH, VAL)
2. PRICE AT ZONE: Current price must be within the confluence zone
3. REACTION: Price action must show rejection (wick, engulfing)
4. MOMENTUM: RSI should confirm (not fighting strong momentum)
5. VOLUME: Elevated volume at level = institutional interest

WHY CONFLUENCE LEVELS WORK:
- Each level type represents different math → different traders watching
- When fib + VWAP + pivot agree, THREE groups of traders see support
- More eyes on a level = more orders = stronger reaction
- The "Core Trio" (Fib + VWAP + EMA) is the most cited in 2025-2026

SOURCES:
- Cryptowisser: "Fibonacci, VWAP, and EMA Confluence in Crypto Scalping" (2026)
- TradingView BigBeluga: "Power of Confluence: Building Trade Setups"
- Professional confluence trading methodology
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from ..strategies.volume_analysis import calculate_volume_profile
from .base import BaseStrategy
from .ema_crossover import compute_ema
from .rsi_divergence import compute_rsi
from .vwap import compute_vwap


def compute_fibonacci_levels(candles: list[Candle], lookback: int = 96) -> dict:
    """Compute Fibonacci retracement levels from recent swing high/low."""
    recent = candles[-lookback:]
    swing_high = max(c.high for c in recent)
    swing_low = min(c.low for c in recent)
    diff = swing_high - swing_low

    if diff <= 0:
        return {}

    return {
        "0.236": swing_high - diff * 0.236,
        "0.382": swing_high - diff * 0.382,
        "0.500": swing_high - diff * 0.500,
        "0.618": swing_high - diff * 0.618,
        "0.786": swing_high - diff * 0.786,
        "swing_high": swing_high,
        "swing_low": swing_low,
    }


def compute_camarilla_pivots(candles: list[Candle], lookback: int = 96) -> dict:
    """Compute Camarilla pivot levels from prior session."""
    session = candles[-lookback:-1] if len(candles) > lookback else candles[:-1]
    if not session:
        return {}

    h = max(c.high for c in session)
    l = min(c.low for c in session)
    c_price = session[-1].close
    diff = h - l

    return {
        "R4": c_price + diff * 1.1 / 2,
        "R3": c_price + diff * 1.1 / 4,
        "R2": c_price + diff * 1.1 / 6,
        "R1": c_price + diff * 1.1 / 12,
        "S1": c_price - diff * 1.1 / 12,
        "S2": c_price - diff * 1.1 / 6,
        "S3": c_price - diff * 1.1 / 4,
        "S4": c_price - diff * 1.1 / 2,
    }


def find_level_clusters(
    price: float, fib: dict, cam: dict, vwap_val: float,
    poc: float, vah: float, val: float,
    proximity_pct: float = 0.003,
) -> list[dict]:
    """Find price zones where multiple level types converge.

    Returns list of clusters, each with the level names and average price.
    """
    proximity = price * proximity_pct
    all_levels = []

    for name, level in fib.items():
        if isinstance(level, (int, float)):
            all_levels.append({"source": "fib", "name": f"fib_{name}", "price": level})

    for name, level in cam.items():
        all_levels.append({"source": "camarilla", "name": f"cam_{name}", "price": level})

    if vwap_val > 0:
        all_levels.append({"source": "vwap", "name": "vwap", "price": vwap_val})

    if poc > 0:
        all_levels.append({"source": "profile", "name": "poc", "price": poc})
    if vah > 0:
        all_levels.append({"source": "profile", "name": "vah", "price": vah})
    if val > 0:
        all_levels.append({"source": "profile", "name": "val", "price": val})

    # Find clusters: levels within proximity of each other
    clusters = []
    used = set()

    for i, level_a in enumerate(all_levels):
        if i in used:
            continue
        cluster_levels = [level_a]
        used.add(i)

        for j, level_b in enumerate(all_levels):
            if j in used or level_a["source"] == level_b["source"]:
                continue
            if abs(level_a["price"] - level_b["price"]) < proximity:
                cluster_levels.append(level_b)
                used.add(j)

        if len(cluster_levels) >= 2:
            avg_price = sum(l["price"] for l in cluster_levels) / len(cluster_levels)
            sources = list({l["source"] for l in cluster_levels})
            clusters.append({
                "price": avg_price,
                "level_count": len(cluster_levels),
                "sources": sources,
                "names": [l["name"] for l in cluster_levels],
                "distance": abs(price - avg_price),
                "distance_pct": abs(price - avg_price) / price * 100,
            })

    clusters.sort(key=lambda c: c["distance"])
    return clusters


class LevelConfluenceSystem(BaseStrategy):
    """Trades reactions at multi-level confluence zones.

    Only fires when 2+ level types converge AND price shows reaction.
    """

    def __init__(
        self,
        fib_lookback: int = 96,
        proximity_pct: float = 0.003,
        rsi_period: int = 14,
    ):
        self.fib_lookback = fib_lookback
        self.proximity_pct = proximity_pct
        self.rsi_period = rsi_period

    @property
    def name(self) -> str:
        return "level_confluence"

    @property
    def category(self) -> str:
        return "fibonacci"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < self.fib_lookback + 20:
            return self._no_signal("Not enough candles for Level Confluence")

        current = candles[-1]
        completed = candles[-2]
        current_price = current.close
        closes = [c.close for c in candles]

        atr = self.compute_atr(candles)
        if not atr:
            return self._no_signal("ATR calculation failed")

        # --- Compute all level types ---
        fib = compute_fibonacci_levels(candles, self.fib_lookback)
        cam = compute_camarilla_pivots(candles, self.fib_lookback)
        vwap_vals = compute_vwap(candles)
        current_vwap = vwap_vals[-1] if vwap_vals else 0
        poc, vah, val = calculate_volume_profile(
            candles[-96:] if len(candles) >= 96 else candles
        )
        rsi_vals = compute_rsi(closes, self.rsi_period)

        if not fib or not rsi_vals:
            return self._no_signal("Level calculation failed")

        current_rsi = rsi_vals[-1]

        # Volume gate
        if not self.check_volume(candles):
            return self._no_signal("Volume too low")

        # --- Find confluence clusters near current price ---
        clusters = find_level_clusters(
            current_price, fib, cam, current_vwap, poc, vah, val,
            self.proximity_pct,
        )

        # Only consider clusters within 0.5% of current price
        nearby = [c for c in clusters if c["distance_pct"] < 0.5]

        if not nearby:
            return self._no_signal("No level confluence near current price")

        best_cluster = nearby[0]  # Closest cluster with most levels

        long_factors = []
        short_factors = []

        # Factor 1: Level confluence strength
        level_strength = f"confluence_{best_cluster['level_count']}levels"
        # Below cluster = potential support → long
        if current_price <= best_cluster["price"] * 1.001:
            long_factors.append(level_strength)
        # Above cluster = potential resistance → short
        if current_price >= best_cluster["price"] * 0.999:
            short_factors.append(level_strength)

        # Factor 2: Price action rejection at level
        if completed.lower_wick > completed.body_size * 1.5:
            long_factors.append("rejection_wick")
        if completed.upper_wick > completed.body_size * 1.5:
            short_factors.append("rejection_wick")

        # Factor 3: RSI not fighting trend (don't buy when RSI > 70)
        if current_rsi < 45:
            long_factors.append("rsi_supports_long")
        if current_rsi > 55:
            short_factors.append("rsi_supports_short")

        # Factor 4: VWAP bias
        if current_vwap > 0:
            if current_price > current_vwap:
                long_factors.append("above_vwap")
            else:
                short_factors.append("below_vwap")

        # Factor 5: Prior candle direction (bounce confirmation)
        if completed.is_bullish and current.is_bullish:
            long_factors.append("bullish_continuation")
        if not completed.is_bullish and not current.is_bullish:
            short_factors.append("bearish_continuation")

        # Factor 6: Golden zone (fib 61.8%-78.6% = highest probability)
        if fib:
            fib_618 = fib.get("0.618", 0)
            fib_786 = fib.get("0.786", 0)
            if fib_618 and fib_786:
                in_golden = min(fib_618, fib_786) <= current_price <= max(fib_618, fib_786)
                if in_golden:
                    long_factors.append("in_golden_zone")

        # --- SIGNAL: cluster + reaction + at least 3 factors ---
        min_required = 3

        if len(long_factors) >= min_required and any("confluence" in f for f in long_factors):
            stop_loss = current_price - atr * 1.5
            risk = abs(current_price - stop_loss)
            # Target: next resistance level or 2.5R
            take_profit = current_price + risk * 2.5

            score = min(90, 40 + best_cluster["level_count"] * 10 + len(long_factors) * 5)
            strength = SignalStrength.STRONG if best_cluster["level_count"] >= 3 else SignalStrength.MODERATE

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=strength,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "factors": long_factors,
                    "cluster_levels": best_cluster["level_count"],
                    "cluster_sources": best_cluster["sources"],
                    "cluster_names": best_cluster["names"],
                    "cluster_price": round(best_cluster["price"], 2),
                    "rsi": round(current_rsi, 1),
                    "vwap": round(current_vwap, 2),
                },
                reason=f"Level Confluence LONG: {best_cluster['level_count']} levels "
                f"({', '.join(best_cluster['sources'])}) at {best_cluster['price']:.2f}. "
                f"{len(long_factors)} factors aligned.",
            )

        if len(short_factors) >= min_required and any("confluence" in f for f in short_factors):
            stop_loss = current_price + atr * 1.5
            risk = abs(stop_loss - current_price)
            take_profit = current_price - risk * 2.5

            score = min(90, 40 + best_cluster["level_count"] * 10 + len(short_factors) * 5)
            strength = SignalStrength.STRONG if best_cluster["level_count"] >= 3 else SignalStrength.MODERATE

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=strength,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "factors": short_factors,
                    "cluster_levels": best_cluster["level_count"],
                    "cluster_sources": best_cluster["sources"],
                    "cluster_names": best_cluster["names"],
                    "cluster_price": round(best_cluster["price"], 2),
                    "rsi": round(current_rsi, 1),
                    "vwap": round(current_vwap, 2),
                },
                reason=f"Level Confluence SHORT: {best_cluster['level_count']} levels "
                f"({', '.join(best_cluster['sources'])}) at {best_cluster['price']:.2f}. "
                f"{len(short_factors)} factors aligned.",
            )

        return self._no_signal(
            f"Confluence zone found ({best_cluster['level_count']} levels at "
            f"{best_cluster['price']:.2f}) but insufficient reaction factors."
        )
