"""
Strategy #1: ICT Order Blocks + Fair Value Gaps.

ORDER BLOCKS:
- An order block is the LAST opposite-colored candle before a strong move
- Bullish OB: The last RED candle before a big green impulse up
  → Institutions were accumulating (buying) during that red candle
  → When price returns to that zone, they buy more = support
- Bearish OB: The last GREEN candle before a big red impulse down
  → Institutions were distributing (selling) during that green candle

FAIR VALUE GAPS (FVG):
- A 3-candle pattern where there's a GAP between candle 1 and candle 3 wicks
- Bullish FVG: Candle1.high < Candle3.low (gap between them = imbalance)
  → Price moved so fast that it left an "unfair" gap
  → Price tends to come back and fill this gap before continuing
- Bearish FVG: Candle1.low > Candle3.high

COMBINED ENTRY:
- Find an Order Block
- Confirm there's an FVG at the same level
- Enter when price returns to this confluence zone
- This is ICT's highest-probability setup

BEST FOR: Gold, BTC, major forex during London/NY sessions
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


def detect_order_blocks(
    candles: list[Candle], min_impulse_atr_mult: float = 1.5
) -> list[dict]:
    """
    Find order blocks — the last opposite candle before a strong impulse.

    An OB is valid when:
    1. There's a candle of opposite color (e.g., red candle in an uptrend)
    2. Followed by a strong impulse move (>= 1.5x ATR)
    3. The impulse candle has a large body (>= 60% of its range)
    """
    if len(candles) < 20:
        return []

    # Calculate ATR for reference
    true_ranges = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i - 1].close),
            abs(candles[i].low - candles[i - 1].close),
        )
        true_ranges.append(tr)
    atr = sum(true_ranges[-14:]) / min(14, len(true_ranges))

    order_blocks = []
    for i in range(1, len(candles) - 1):
        ob_candle = candles[i]
        impulse_candle = candles[i + 1]
        impulse_range = impulse_candle.high - impulse_candle.low

        # Bullish OB: Red candle followed by strong green impulse
        if (not ob_candle.is_bullish and impulse_candle.is_bullish
                and impulse_candle.body_size >= atr * min_impulse_atr_mult
                and impulse_candle.body_ratio >= 0.6):
            order_blocks.append({
                "type": "bullish",
                "index": i,
                "high": ob_candle.high,
                "low": ob_candle.low,
                "midpoint": (ob_candle.high + ob_candle.low) / 2,
                "impulse_size": impulse_candle.body_size,
                "atr_multiple": impulse_candle.body_size / atr if atr > 0 else 0,
            })

        # Bearish OB: Green candle followed by strong red impulse
        if (ob_candle.is_bullish and not impulse_candle.is_bullish
                and impulse_candle.body_size >= atr * min_impulse_atr_mult
                and impulse_candle.body_ratio >= 0.6):
            order_blocks.append({
                "type": "bearish",
                "index": i,
                "high": ob_candle.high,
                "low": ob_candle.low,
                "midpoint": (ob_candle.high + ob_candle.low) / 2,
                "impulse_size": impulse_candle.body_size,
                "atr_multiple": impulse_candle.body_size / atr if atr > 0 else 0,
            })

    return order_blocks


def detect_fvgs(candles: list[Candle], min_gap_pct: float = 0.001) -> list[dict]:
    """
    Find Fair Value Gaps — 3-candle imbalance patterns.

    Bullish FVG: Candle[i].high < Candle[i+2].low (gap in between)
    Bearish FVG: Candle[i].low > Candle[i+2].high
    """
    fvgs = []
    for i in range(len(candles) - 2):
        c1 = candles[i]
        c3 = candles[i + 2]

        # Bullish FVG
        if c1.high < c3.low:
            gap = c3.low - c1.high
            gap_pct = gap / c1.high
            if gap_pct >= min_gap_pct:
                fvgs.append({
                    "type": "bullish",
                    "index": i + 1,
                    "top": c3.low,      # Upper edge of gap
                    "bottom": c1.high,   # Lower edge of gap
                    "midpoint": (c3.low + c1.high) / 2,
                    "gap_size": gap,
                    "gap_pct": gap_pct,
                })

        # Bearish FVG
        if c1.low > c3.high:
            gap = c1.low - c3.high
            gap_pct = gap / c3.high
            if gap_pct >= min_gap_pct:
                fvgs.append({
                    "type": "bearish",
                    "index": i + 1,
                    "top": c1.low,
                    "bottom": c3.high,
                    "midpoint": (c1.low + c3.high) / 2,
                    "gap_size": gap,
                    "gap_pct": gap_pct,
                })

    return fvgs


class OrderBlockFVGStrategy(BaseStrategy):
    """
    ICT Order Block + Fair Value Gap confluence strategy.

    Highest probability when both align at the same price zone.
    Falls back to OB-only or FVG-only signals with lower scores.
    """

    def __init__(
        self,
        impulse_atr_mult: float = 1.5,
        min_fvg_pct: float = 0.001,
        proximity_pct: float = 0.003,  # OB and FVG must be within 0.3% to count as confluence
    ):
        self.impulse_atr_mult = impulse_atr_mult
        self.min_fvg_pct = min_fvg_pct
        self.proximity_pct = proximity_pct

    @property
    def name(self) -> str:
        return "order_block_fvg"

    @property
    def category(self) -> str:
        return "ict"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < 30:
            return self._no_signal("Not enough candles")

        current_price = candles[-1].close
        obs = detect_order_blocks(candles[:-5], self.impulse_atr_mult)  # Exclude last 5 for recent OBs
        fvgs = detect_fvgs(candles[:-3], self.min_fvg_pct)

        if not obs and not fvgs:
            return self._no_signal("No order blocks or FVGs detected")

        # Look for BULLISH setups: price returning to a bullish OB or FVG
        for ob in reversed(obs):
            if ob["type"] != "bullish":
                continue
            # Is price currently AT the order block zone?
            if ob["low"] <= current_price <= ob["high"]:
                # Check for FVG confluence near this OB
                has_fvg = any(
                    fvg["type"] == "bullish"
                    and abs(fvg["midpoint"] - ob["midpoint"]) / current_price < self.proximity_pct
                    for fvg in fvgs
                )

                # Need a bullish candle (rejection from the zone)
                if not candles[-1].is_bullish:
                    continue

                confluence_bonus = 20 if has_fvg else 0
                score = min(90, 55 + ob["atr_multiple"] * 5 + confluence_bonus)

                stop_loss = ob["low"] - (ob["high"] - ob["low"]) * 0.3
                risk = current_price - stop_loss
                take_profit = current_price + risk * 2.5

                return Signal(
                    strategy_name=self.name,
                    direction=Direction.LONG,
                    strength=SignalStrength.STRONG if has_fvg else SignalStrength.MODERATE,
                    score=score,
                    entry_price=current_price,
                    stop_loss=round(stop_loss, 2),
                    take_profit=round(take_profit, 2),
                    metadata={
                        "ob_high": round(ob["high"], 2),
                        "ob_low": round(ob["low"], 2),
                        "impulse_atr_mult": round(ob["atr_multiple"], 1),
                        "has_fvg_confluence": has_fvg,
                        "setup_type": "OB+FVG" if has_fvg else "OB only",
                    },
                    reason=f"Bullish Order Block {'+ FVG confluence' if has_fvg else ''} at {ob['low']:.2f}-{ob['high']:.2f}. Impulse: {ob['atr_multiple']:.1f}x ATR",
                )

        # Look for BEARISH setups
        for ob in reversed(obs):
            if ob["type"] != "bearish":
                continue
            if ob["low"] <= current_price <= ob["high"]:
                has_fvg = any(
                    fvg["type"] == "bearish"
                    and abs(fvg["midpoint"] - ob["midpoint"]) / current_price < self.proximity_pct
                    for fvg in fvgs
                )

                if candles[-1].is_bullish:
                    continue

                confluence_bonus = 20 if has_fvg else 0
                score = min(90, 55 + ob["atr_multiple"] * 5 + confluence_bonus)

                stop_loss = ob["high"] + (ob["high"] - ob["low"]) * 0.3
                risk = stop_loss - current_price
                take_profit = current_price - risk * 2.5

                return Signal(
                    strategy_name=self.name,
                    direction=Direction.SHORT,
                    strength=SignalStrength.STRONG if has_fvg else SignalStrength.MODERATE,
                    score=score,
                    entry_price=current_price,
                    stop_loss=round(stop_loss, 2),
                    take_profit=round(take_profit, 2),
                    metadata={
                        "ob_high": round(ob["high"], 2),
                        "ob_low": round(ob["low"], 2),
                        "impulse_atr_mult": round(ob["atr_multiple"], 1),
                        "has_fvg_confluence": has_fvg,
                        "setup_type": "OB+FVG" if has_fvg else "OB only",
                    },
                    reason=f"Bearish Order Block {'+ FVG confluence' if has_fvg else ''} at {ob['low']:.2f}-{ob['high']:.2f}. Impulse: {ob['atr_multiple']:.1f}x ATR",
                )

        # Check standalone FVGs (no OB confluence — lower score)
        for fvg in reversed(fvgs):
            if fvg["type"] == "bullish" and fvg["bottom"] <= current_price <= fvg["top"]:
                if candles[-1].is_bullish:
                    stop_loss = fvg["bottom"] - fvg["gap_size"] * 0.5
                    risk = current_price - stop_loss
                    take_profit = current_price + risk * 2.0

                    return Signal(
                        strategy_name=self.name,
                        direction=Direction.LONG,
                        strength=SignalStrength.MODERATE,
                        score=min(65, 40 + fvg["gap_pct"] * 5000),
                        entry_price=current_price,
                        stop_loss=round(stop_loss, 2),
                        take_profit=round(take_profit, 2),
                        metadata={"fvg_top": round(fvg["top"], 2), "fvg_bottom": round(fvg["bottom"], 2), "setup_type": "FVG only"},
                        reason=f"Bullish FVG fill at {fvg['bottom']:.2f}-{fvg['top']:.2f} (gap: {fvg['gap_pct']*100:.2f}%)",
                    )

            if fvg["type"] == "bearish" and fvg["bottom"] <= current_price <= fvg["top"]:
                if not candles[-1].is_bullish:
                    stop_loss = fvg["top"] + fvg["gap_size"] * 0.5
                    risk = stop_loss - current_price
                    take_profit = current_price - risk * 2.0

                    return Signal(
                        strategy_name=self.name,
                        direction=Direction.SHORT,
                        strength=SignalStrength.MODERATE,
                        score=min(65, 40 + fvg["gap_pct"] * 5000),
                        entry_price=current_price,
                        stop_loss=round(stop_loss, 2),
                        take_profit=round(take_profit, 2),
                        metadata={"fvg_top": round(fvg["top"], 2), "fvg_bottom": round(fvg["bottom"], 2), "setup_type": "FVG only"},
                        reason=f"Bearish FVG fill at {fvg['bottom']:.2f}-{fvg['top']:.2f} (gap: {fvg['gap_pct']*100:.2f}%)",
                    )

        return self._no_signal(f"OBs: {len(obs)}, FVGs: {len(fvgs)} — none at current price")
