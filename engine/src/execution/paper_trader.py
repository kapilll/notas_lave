"""
Paper Trading Executor — simulates real trading without risking money.

This is the core loop that turns signals into trades:
1. Accept a trade setup (from Claude evaluation)
2. Open a simulated position
3. Monitor price against SL and TP
4. Close when SL/TP hit, or manually
5. Record everything in the trade journal
6. Update the risk manager's P&L

Every position tracks:
- Entry price, current price, unrealized P&L
- Max Favorable Excursion (MFE): best unrealized P&L during the trade
- Max Adverse Excursion (MAE): worst unrealized P&L during the trade
- MFE and MAE are critical for the learning engine — they tell you
  if your stops are too tight or your targets too ambitious

The executor runs a background check every few seconds to monitor
open positions against live prices.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from ..data.models import Direction, TradeStatus
from ..data.market_data import market_data
from ..data.instruments import get_instrument
from ..risk.manager import risk_manager
from ..journal.database import log_trade, close_trade, get_db, use_db, TradeLog
from ..config import config


@dataclass
class Position:
    """A single open position being tracked."""
    id: str
    signal_log_id: int           # Links back to the signal that created it
    symbol: str
    timeframe: str
    direction: Direction
    regime: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    confluence_score: float
    claude_confidence: int
    strategies_agreed: list[str]
    trade_log_id: int = 0        # Set after logging to journal

    # Live tracking
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    max_favorable: float = 0.0   # Best unrealized P&L (how good could it have been?)
    max_adverse: float = 0.0     # Worst unrealized P&L (how bad did it get?)

    # State
    status: TradeStatus = TradeStatus.OPEN
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None
    exit_price: float = 0.0
    exit_reason: str = ""        # tp_hit, sl_hit, manual, breakeven, trailing
    pnl: float = 0.0            # Realized P&L (set on close)

    # Leverage tracking (personal/CoinDCX mode)
    leverage: float = 1.0
    margin_used: float = 0.0         # Margin locked for this position
    liquidation_price: float = 0.0   # Price at which position gets liquidated
    entry_fee: float = 0.0           # Trading fee paid on entry
    currency: str = "USD"            # Quote currency

    # Trailing stop management
    breakeven_activated: bool = False    # SL moved to entry after 1:1 R
    trailing_active: bool = False        # ATR trail phase active
    original_stop_loss: float = 0.0     # SL at trade open (before any moves)
    original_take_profit: float = 0.0   # TP at trade open (before extensions)
    trail_step_count: int = 0           # How many times SL was trailed
    tp_extensions: int = 0              # How many times TP was extended
    entry_atr: float = 0.0             # ATR at entry time (for trail distance)

    # Smart position health (computed from RSI + volume + candle quality)
    health_momentum: str = "NEUTRAL"           # STRONG/NEUTRAL/FADING/REVERSING
    health_trail_adjustment: float = 1.0       # Multiplier for trail distance
    health_can_extend_tp: bool = True           # Whether TP extension allowed
    health_should_exit: bool = False            # Exit at current price NOW
    health_reason: str = ""                     # Why (for logging + learning)

    @property
    def risk_amount(self) -> float:
        """Dollar risk on this trade."""
        return abs(self.entry_price - self.stop_loss) * self.position_size

    @property
    def duration_seconds(self) -> int:
        """How long the position has been open."""
        end = self.closed_at or datetime.now(timezone.utc)
        opened = self.opened_at
        # Normalize: DB-loaded timestamps may be naive
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return int((end - opened).total_seconds())

    def update_price(self, price: float, candle_high: float = 0, candle_low: float = 0):
        """
        Update current price and recalculate P&L.

        Uses instrument contract_size for proper P&L calculation.
        Also tracks MFE and MAE for the learning engine.
        """
        self.current_price = price
        spec = get_instrument(self.symbol)

        # P&L uses contract_size: Gold 1 lot = 100 oz, so $1 move = $100/lot
        if self.direction == Direction.LONG:
            self.unrealized_pnl = (price - self.entry_price) * spec.contract_size * self.position_size
        else:
            self.unrealized_pnl = (self.entry_price - price) * spec.contract_size * self.position_size

        if self.entry_price > 0:
            self.unrealized_pnl_pct = (price - self.entry_price) / self.entry_price * 100
            if self.direction == Direction.SHORT:
                self.unrealized_pnl_pct = -self.unrealized_pnl_pct

        # Track extremes
        if self.unrealized_pnl > self.max_favorable:
            self.max_favorable = self.unrealized_pnl
        if self.unrealized_pnl < self.max_adverse:
            self.max_adverse = self.unrealized_pnl

        # Store candle extremes for SL/TP checking
        self._candle_high = candle_high if candle_high > 0 else price
        self._candle_low = candle_low if candle_low > 0 else price

    def check_exit(self) -> str | None:
        """
        Check if SL or TP has been hit using candle HIGH/LOW, not just close.

        In real trading, a wick that touches your SL stops you out even if
        the candle closes above your SL. We simulate this by checking
        against the candle's high and low, not just the closing price.
        """
        if self.current_price <= 0:
            return None

        high = getattr(self, '_candle_high', self.current_price)
        low = getattr(self, '_candle_low', self.current_price)

        if self.direction == Direction.LONG:
            # SL triggered if price wicked DOWN to SL level
            if low <= self.stop_loss:
                return "trailing_sl" if self.trailing_active else "sl_hit"
            # TP triggered if price wicked UP to TP level
            if high >= self.take_profit:
                return "extended_tp" if self.tp_extensions > 0 else "tp_hit"
        else:  # SHORT
            # SL triggered if price wicked UP to SL level
            if high >= self.stop_loss:
                return "trailing_sl" if self.trailing_active else "sl_hit"
            # TP triggered if price wicked DOWN to TP level
            if low <= self.take_profit:
                return "extended_tp" if self.tp_extensions > 0 else "tp_hit"

        return None

    def move_to_breakeven(self):
        """
        Move stop loss to TRUE breakeven (entry + spread + fees).

        Moving SL to exact entry_price loses you the spread AND fees.
        True breakeven = entry + spread + round-trip fees for the position.
        """
        if self.breakeven_activated:
            return

        spec = get_instrument(self.symbol)
        initial_risk = abs(self.entry_price - self.stop_loss)
        favorable_move = abs(self.current_price - self.entry_price)

        # Activate after 1:1 R move in your favor
        if favorable_move >= initial_risk:
            # True breakeven: accounts for spread + entry/exit fees
            be_price = spec.breakeven_price(self.entry_price, self.direction.value)
            # Add fee buffer (entry fee already paid, need to cover exit fee)
            exit_fee_per_unit = spec.taker_fee_pct * self.entry_price
            if self.direction == Direction.LONG:
                be_price += exit_fee_per_unit
            else:
                be_price -= exit_fee_per_unit
            self.stop_loss = be_price
            self.breakeven_activated = True

    # --- Health computation helpers ---

    @staticmethod
    def _compute_rsi(candles: list, period: int = 14) -> float:
        """Simple RSI from candle closes. Returns 50.0 if not enough data."""
        if len(candles) < period + 1:
            return 50.0
        changes = [candles[i].close - candles[i - 1].close for i in range(1, len(candles))]
        recent = changes[-period:]
        avg_gain = sum(c for c in recent if c > 0) / period
        avg_loss = sum(-c for c in recent if c < 0) / period
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _volume_ratio(candles: list, recent: int = 3, lookback: int = 14) -> float:
        """Ratio of recent volume to average. >1 means above-average volume."""
        if len(candles) < lookback:
            return 1.0
        vols = [c.volume for c in candles[-lookback:] if c.volume > 0]
        if not vols:
            return 1.0
        avg_vol = sum(vols) / len(vols)
        if avg_vol <= 0:
            return 1.0
        recent_vols = [c.volume for c in candles[-recent:] if c.volume > 0]
        return (sum(recent_vols) / max(len(recent_vols), 1)) / avg_vol

    @staticmethod
    def _candle_alignment(candles: list, direction, count: int = 5) -> float:
        """Fraction of recent candles aligned with direction. 0.0 to 1.0."""
        if len(candles) < count:
            return 0.5
        recent = candles[-count:]
        if direction == Direction.LONG:
            return sum(1 for c in recent if c.close > c.open) / count
        return sum(1 for c in recent if c.close < c.open) / count

    def compute_health(self, candles: list) -> None:
        """
        Compute position health from recent 1m candles. Sets health_* fields.

        Reads RSI, volume, and candle quality to determine:
        - STRONG: trend healthy, trail wider (1.3x), extend TP
        - NEUTRAL: normal conditions, trail normal (1.0x)
        - FADING: momentum exhausted, trail tighter (0.7x), don't extend TP
        - REVERSING: momentum flipped, exit immediately (only if in profit)
        """
        if len(candles) < 15:
            return  # Not enough data, keep defaults

        rsi = self._compute_rsi(candles, 14)
        vol_ratio = self._volume_ratio(candles, recent=3, lookback=14)
        alignment = self._candle_alignment(candles, self.direction, 5)

        # Determine momentum state based on direction
        if self.direction == Direction.LONG:
            if rsi > 75:
                momentum = "FADING"       # Overbought, move is stretched
            elif rsi > 55 and alignment >= 0.6:
                momentum = "STRONG"       # Healthy uptrend
            elif rsi < 40:
                momentum = "REVERSING"    # Momentum shifted against us
            else:
                momentum = "NEUTRAL"
        else:  # SHORT
            if rsi < 25:
                momentum = "FADING"       # Oversold, move is stretched
            elif rsi < 45 and alignment >= 0.6:
                momentum = "STRONG"       # Healthy downtrend
            elif rsi > 60:
                momentum = "REVERSING"    # Momentum shifted against us
            else:
                momentum = "NEUTRAL"

        # Trail adjustment: strong=wider, fading=tighter, reversing=very tight
        if momentum == "STRONG" and vol_ratio >= 1.0:
            trail_adj = 1.3
        elif momentum == "FADING":
            trail_adj = 0.7
        elif momentum == "REVERSING":
            trail_adj = 0.5
        else:
            trail_adj = 1.0

        # TP extension: only when momentum supports it
        can_extend = momentum in ("STRONG", "NEUTRAL") and vol_ratio >= 0.8

        # Smart exit: reversed momentum + candles against us + already in profit
        should_exit = (
            momentum == "REVERSING"
            and alignment < 0.3            # Most recent candles against our direction
            and vol_ratio > 0.8            # Decent volume on the reversal
            and self.breakeven_activated   # Only exit early if already in profit
        )

        self.health_momentum = momentum
        self.health_trail_adjustment = trail_adj
        self.health_can_extend_tp = can_extend
        if should_exit and not self.health_should_exit:
            # Only set exit flag, don't clear it (caller handles clearing)
            self.health_should_exit = True
            self.health_reason = (
                f"Momentum reversed: RSI={rsi:.0f}, "
                f"candles={alignment:.0%} aligned, vol={vol_ratio:.1f}x"
            )
        elif not self.health_should_exit:
            self.health_reason = f"RSI={rsi:.0f}, vol={vol_ratio:.1f}x" if momentum != "NEUTRAL" else ""

    def trail_stop(self, trail_multiplier: float = 1.5, min_step_r: float = 0.5) -> bool:
        """
        ATR-based step trailing stop. Only runs after breakeven is activated.

        How it works:
        1. Compute trail_distance = entry_atr * trail_multiplier (or 1R if no ATR)
        2. new_sl = current_price - trail_distance (for longs)
        3. Only move SL if the step is >= min_step_r * initial_risk
        4. SL only ratchets (locks in more profit, never moves back)

        Returns True if SL was trailed this tick.
        """
        if not self.breakeven_activated or self.current_price <= 0:
            return False

        # Initial risk = distance from entry to original SL
        initial_risk = abs(self.entry_price - self.original_stop_loss) if self.original_stop_loss > 0 else 0
        if initial_risk <= 0:
            return False

        # Trail distance: how far behind price the SL sits
        if self.entry_atr > 0:
            trail_distance = self.entry_atr * trail_multiplier
        else:
            trail_distance = initial_risk  # Fallback: trail at 1R behind price

        # Minimum step size to avoid micro-movements from noise
        min_step = initial_risk * min_step_r

        if self.direction == Direction.LONG:
            new_sl = self.current_price - trail_distance
            # Only move UP, and only if step is meaningful
            if new_sl > self.stop_loss + min_step:
                # Safety: SL must stay below current price and below TP
                if new_sl < self.current_price and new_sl < self.take_profit:
                    self.stop_loss = round(new_sl, 8)
                    self.trailing_active = True
                    self.trail_step_count += 1
                    return True
        else:  # SHORT
            new_sl = self.current_price + trail_distance
            # Only move DOWN, and only if step is meaningful
            if new_sl < self.stop_loss - min_step:
                # Safety: SL must stay above current price and above TP
                if new_sl > self.current_price and new_sl > self.take_profit:
                    self.stop_loss = round(new_sl, 8)
                    self.trailing_active = True
                    self.trail_step_count += 1
                    return True

        return False

    def extend_take_profit(self, max_extensions: int = 3, threshold: float = 0.75) -> bool:
        """
        Extend TP when price covers threshold% of the TP distance.

        Each extension pushes TP out by 1R (original risk distance).
        This lets winning trades run further while trailing SL protects profit.

        Returns True if TP was extended this tick.
        """
        if self.tp_extensions >= max_extensions or self.current_price <= 0:
            return False

        initial_risk = abs(self.entry_price - self.original_stop_loss) if self.original_stop_loss > 0 else 0
        if initial_risk <= 0:
            return False

        if self.direction == Direction.LONG:
            total_distance = self.take_profit - self.entry_price
            covered = self.current_price - self.entry_price
        else:
            total_distance = self.entry_price - self.take_profit
            covered = self.entry_price - self.current_price

        if total_distance <= 0 or covered <= 0:
            return False

        progress = covered / total_distance
        if progress >= threshold:
            if self.direction == Direction.LONG:
                self.take_profit = round(self.take_profit + initial_risk, 8)
            else:
                self.take_profit = round(self.take_profit - initial_risk, 8)
            self.tp_extensions += 1
            return True

        return False

    def to_dict(self) -> dict:
        """Convert to dict for API responses."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "regime": self.regime,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_size": self.position_size,
            "pnl": round(self.pnl, 2) if self.pnl != 0 else round(self.unrealized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
            "max_favorable": round(self.max_favorable, 2),
            "max_adverse": round(self.max_adverse, 2),
            "confluence_score": self.confluence_score,
            "claude_confidence": self.claude_confidence,
            "status": self.status.value,
            "breakeven": self.breakeven_activated,
            "trailing_active": self.trailing_active,
            "trail_steps": self.trail_step_count,
            "tp_extensions": self.tp_extensions,
            "original_stop_loss": self.original_stop_loss,
            "original_take_profit": self.original_take_profit,
            "health_momentum": self.health_momentum,
            "health_reason": self.health_reason,
            "duration_seconds": self.duration_seconds,
            "opened_at": self.opened_at.isoformat(),
            "exit_reason": self.exit_reason,
            "leverage": self.leverage,
            "margin_used": round(self.margin_used, 2),
            "liquidation_price": round(self.liquidation_price, 2),
            "currency": self.currency,
        }


class PaperTrader:
    """
    Paper trading engine that simulates real trading.

    Manages open positions, monitors prices, handles SL/TP,
    and records everything for the learning engine.
    """

    def __init__(self, track_risk: bool = True):
        self.positions: dict[str, Position] = {}  # id → Position
        self.closed_positions: list[Position] = []
        self._monitor_task: asyncio.Task | None = None
        self._running = False
        self._track_risk = track_risk

        # Trailing stop configuration (set by caller: lab_trader or autonomous_trader)
        self.trailing_enabled: bool = False
        self.trail_atr_multiplier: float = 1.5   # Trail at 1.5x ATR behind price
        self.trail_min_step_r: float = 0.5        # Min step = 0.5R
        self.tp_extension_enabled: bool = False
        self.max_tp_extensions: int = 3

    @property
    def open_count(self) -> int:
        return len(self.positions)

    def open_position(
        self,
        signal_log_id: int,
        symbol: str,
        timeframe: str,
        direction: Direction,
        regime: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        position_size: float,
        confluence_score: float,
        claude_confidence: int,
        strategies_agreed: list[str],
    ) -> Position:
        """
        Open a new paper trading position.

        This is called when:
        1. Claude says BUY/SELL with confidence >= 7
        2. Risk manager approves (all rules pass)
        3. You confirm (co-pilot mode)
        """
        pos_id = str(uuid.uuid4())[:16]

        # Apply spread to entry — you never get filled at the mid price
        # LONG: filled at ASK (higher). SHORT: filled at BID (lower).
        spec = get_instrument(symbol)
        realistic_entry = spec.apply_spread(entry_price, direction.value)

        # Calculate leverage, margin, and fees for personal mode
        leverage = config.leverage if config.is_personal_mode else 1.0
        notional = realistic_entry * spec.contract_size * position_size
        margin_used = notional / leverage if leverage > 1 else notional
        liq_price = spec.calculate_liquidation_price(
            realistic_entry, position_size, risk_manager.current_balance,
            leverage, direction.value,
        ) if leverage > 1 else 0.0
        entry_fee = spec.calculate_trading_fee(realistic_entry, position_size)

        position = Position(
            id=pos_id,
            signal_log_id=signal_log_id,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            regime=regime,
            entry_price=round(realistic_entry, 2),
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            confluence_score=confluence_score,
            claude_confidence=claude_confidence,
            strategies_agreed=strategies_agreed,
            current_price=realistic_entry,
            leverage=leverage,
            margin_used=round(margin_used, 2),
            liquidation_price=round(liq_price, 2),
            entry_fee=round(entry_fee, 4),
            currency=spec.currency,
            # Save originals for trailing stop calculations
            original_stop_loss=stop_loss,
            original_take_profit=take_profit,
        )

        # Log to trade journal
        trade_id = log_trade(
            signal_log_id=signal_log_id,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction.value,
            regime=regime,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            confluence_score=confluence_score,
            claude_confidence=claude_confidence,
            strategies_agreed=strategies_agreed,
        )
        position.trade_log_id = trade_id

        # Update risk manager (skip for Lab — it has its own)
        if self._track_risk:
            today_stats = risk_manager._get_today_stats()
            today_stats.open_positions += 1

        self.positions[pos_id] = position
        return position

    def close_position(self, pos_id: str, reason: str = "manual", exit_price: float | None = None):
        """
        Close a position and record the result.
        """
        if pos_id not in self.positions:
            return None

        pos = self.positions.pop(pos_id)
        pos.status = TradeStatus.CLOSED
        pos.exit_reason = reason
        pos.closed_at = datetime.now(timezone.utc)
        pos.exit_price = exit_price or pos.current_price

        # Calculate final P&L using instrument contract_size
        # Gold: 1 lot = 100 oz, so a $5 move on 1 lot = $500
        # CoinDCX: deduct entry + exit trading fees
        spec = get_instrument(pos.symbol)
        raw_pnl = spec.calculate_pnl(
            entry=pos.entry_price,
            exit=pos.exit_price,
            lots=pos.position_size,
            direction=pos.direction.value,
        )
        exit_fee = spec.calculate_trading_fee(pos.exit_price, pos.position_size)
        final_pnl = raw_pnl - pos.entry_fee - exit_fee
        pos.pnl = round(final_pnl, 2)  # Store realized P&L on the position

        pnl_pct = (pos.exit_price - pos.entry_price) / pos.entry_price * 100
        if pos.direction == Direction.SHORT:
            pnl_pct = -pnl_pct

        # Update trade journal
        if pos.trade_log_id > 0:
            close_trade(
                trade_id=pos.trade_log_id,
                exit_price=pos.exit_price,
                exit_reason=reason,
                pnl=round(final_pnl, 2),
                pnl_pct=round(pnl_pct, 2),
                duration_seconds=pos.duration_seconds,
                max_favorable=pos.max_favorable,
                max_adverse=pos.max_adverse,
            )
        else:
            # Position was created by sync (no DB entry exists) — create one
            import json as _json
            trade_id = log_trade(
                signal_log_id=0,
                symbol=pos.symbol,
                timeframe=pos.timeframe,
                direction=pos.direction.value,
                regime=pos.regime,
                entry_price=pos.entry_price,
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                position_size=pos.position_size,
                confluence_score=pos.confluence_score,
                claude_confidence=pos.claude_confidence,
                strategies_agreed=pos.strategies_agreed,
            )
            close_trade(
                trade_id=trade_id,
                exit_price=pos.exit_price,
                exit_reason=reason,
                pnl=round(final_pnl, 2),
                pnl_pct=round(pnl_pct, 2),
                duration_seconds=pos.duration_seconds,
                max_favorable=pos.max_favorable,
                max_adverse=pos.max_adverse,
            )
            pos.trade_log_id = trade_id

        # Update risk manager (skip for Lab — it has its own)
        if self._track_risk:
            risk_manager.record_trade_result(final_pnl)
            today_stats = risk_manager._get_today_stats()
            today_stats.open_positions = max(0, today_stats.open_positions - 1)

        self.closed_positions.append(pos)
        # AT-32: Cap closed_positions to avoid unbounded memory growth
        self.closed_positions = self.closed_positions[-500:]
        return pos, final_pnl

    async def update_positions(self):
        """
        Check all open positions against live prices.
        Called periodically by the monitoring loop.

        For each position:
        1. Get latest price
        2. Update P&L and MFE/MAE
        3. Check if breakeven should activate
        4. Check if SL or TP hit
        5. Close if triggered
        """
        for pos_id in list(self.positions.keys()):
            pos = self.positions.get(pos_id)
            if not pos:
                continue

            try:
                # Get 20 candles for health analysis (RSI, volume, candle quality)
                candles = await market_data.get_candles(pos.symbol, "1m", limit=20)
                if not candles:
                    continue

                c = candles[-1]
                pos.update_price(c.close, candle_high=c.high, candle_low=c.low)
                pos.move_to_breakeven()

                # Smart health check: read RSI, volume, candle quality
                pos.compute_health(candles)

                # Smart exit: momentum reversed, exit NOW at current price
                if pos.health_should_exit:
                    logger.info("SMART EXIT: %s %s — %s",
                                pos.symbol, pos.direction.value, pos.health_reason)
                    self.close_position(pos_id, reason="smart_exit", exit_price=c.close)
                    continue

                # Trailing stop: ratchet SL with health-adjusted multiplier
                if self.trailing_enabled:
                    adjusted_mult = self.trail_atr_multiplier * pos.health_trail_adjustment
                    trailed = pos.trail_stop(
                        trail_multiplier=adjusted_mult,
                        min_step_r=self.trail_min_step_r,
                    )
                    if trailed:
                        logger.info("TRAIL SL: %s %s SL→%.6f (step %d, %s ×%.1f)",
                                    pos.symbol, pos.direction.value,
                                    pos.stop_loss, pos.trail_step_count,
                                    pos.health_momentum, pos.health_trail_adjustment)

                # Dynamic TP: only extend when health confirms momentum
                if self.tp_extension_enabled and pos.health_can_extend_tp:
                    extended = pos.extend_take_profit(
                        max_extensions=self.max_tp_extensions,
                    )
                    if extended:
                        logger.info("EXTEND TP: %s %s TP→%.6f (ext %d/%d, %s)",
                                    pos.symbol, pos.direction.value,
                                    pos.take_profit, pos.tp_extensions,
                                    self.max_tp_extensions, pos.health_momentum)

                exit_reason = pos.check_exit()
                if exit_reason:
                    # AT-33: Apply slippage on SL fills — real markets slip past stops.
                    # TP fills are close to target (limit orders), so no slippage there.
                    if exit_reason in ("sl_hit", "trailing_sl"):
                        spec = get_instrument(pos.symbol)
                        slippage = spec.slippage_ticks * spec.pip_size
                        if pos.direction == Direction.LONG:
                            fill = pos.stop_loss - slippage  # Worse for longs
                        else:
                            fill = pos.stop_loss + slippage  # Worse for shorts
                    elif exit_reason in ("tp_hit", "extended_tp"):
                        fill = pos.take_profit  # TP fills are close to target
                    else:
                        fill = c.close
                    self.close_position(pos_id, reason=exit_reason, exit_price=fill)

            except Exception:
                continue

    def _reload_open_positions(self):
        """
        AT-24: Reload positions from DB where exit_price IS NULL.
        This ensures open positions survive engine restarts.
        """
        try:
            use_db("default")
            db = get_db()
            open_trades = db.query(TradeLog).filter(TradeLog.exit_price.is_(None)).all()
            reloaded = 0
            for t in open_trades:
                # Skip if already tracked in memory
                existing_ids = {p.trade_log_id for p in self.positions.values()}
                if t.id in existing_ids:
                    continue

                import json as _json
                strategies = _json.loads(t.strategies_agreed) if t.strategies_agreed else []
                direction = Direction.LONG if t.direction == "LONG" else Direction.SHORT

                pos = Position(
                    id=str(uuid.uuid4())[:16],
                    signal_log_id=t.signal_log_id or 0,
                    symbol=t.symbol,
                    timeframe=t.timeframe or "5m",
                    direction=direction,
                    regime=t.regime or "unknown",
                    entry_price=t.entry_price or 0.0,
                    stop_loss=t.stop_loss or 0.0,
                    take_profit=t.take_profit or 0.0,
                    position_size=t.position_size or 0.0,
                    confluence_score=t.confluence_score or 0.0,
                    claude_confidence=t.claude_confidence or 0,
                    strategies_agreed=strategies,
                    trade_log_id=t.id,
                    current_price=t.entry_price or 0.0,
                    opened_at=t.opened_at or datetime.now(timezone.utc),
                    # Restore originals for trailing stop (DB stores the initial values)
                    original_stop_loss=t.stop_loss or 0.0,
                    original_take_profit=t.take_profit or 0.0,
                )
                self.positions[pos.id] = pos
                reloaded += 1

            if reloaded > 0:
                logger.info("AT-24: Reloaded %d open positions from DB", reloaded)
                # RC-23: Sync risk manager's open_positions count so max concurrent
                # limit isn't bypassed after restart
                if self._track_risk:
                    today_stats = risk_manager._get_today_stats()
                    today_stats.open_positions = self.open_count
        except Exception as e:
            logger.error("AT-24: Failed to reload positions: %s", e)

    async def start_monitoring(self, interval: int = 10):
        """
        Start background monitoring of open positions.
        Checks prices every `interval` seconds.
        """
        if self._running:
            return

        # AT-24: Reload any open positions from DB on startup
        self._reload_open_positions()

        self._running = True

        async def monitor_loop():
            while self._running:
                if self.positions:
                    await self.update_positions()
                await asyncio.sleep(interval)

        self._monitor_task = asyncio.create_task(monitor_loop())

    def stop_monitoring(self):
        """Stop the background monitoring loop."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()

    def get_open_positions(self) -> list[dict]:
        """Get all open positions for the dashboard."""
        return [p.to_dict() for p in self.positions.values()]

    def get_closed_positions(self, limit: int = 50) -> list[dict]:
        """Get recent closed positions."""
        return [p.to_dict() for p in self.closed_positions[-limit:]]

    def get_summary(self) -> dict:
        """Get paper trading summary stats."""
        closed = self.closed_positions
        wins = [p for p in closed if p.unrealized_pnl > 0 or (p.exit_reason == "tp_hit")]
        losses = [p for p in closed if p not in wins and p.exit_reason != "breakeven"]

        total_pnl = 0.0
        for p in closed:
            if p.exit_price > 0:
                spec = get_instrument(p.symbol)
                total_pnl += spec.calculate_pnl(
                    p.entry_price, p.exit_price, p.position_size, p.direction.value
                )

        return {
            "open_positions": len(self.positions),
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / max(len(closed), 1) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_duration_seconds": round(
                sum(p.duration_seconds for p in closed) / max(len(closed), 1)
            ),
        }


# Singleton
paper_trader = PaperTrader()
