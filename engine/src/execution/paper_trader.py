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
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field

from ..data.models import Direction, TradeStatus
from ..data.market_data import market_data
from ..data.instruments import get_instrument
from ..risk.manager import risk_manager
from ..journal.database import log_trade, close_trade
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

    # Leverage tracking (personal/CoinDCX mode)
    leverage: float = 1.0
    margin_used: float = 0.0         # Margin locked for this position
    liquidation_price: float = 0.0   # Price at which position gets liquidated
    entry_fee: float = 0.0           # Trading fee paid on entry
    currency: str = "USD"            # Quote currency

    # Trailing stop management
    breakeven_activated: bool = False    # SL moved to entry after 1:1 R
    trailing_active: bool = False

    @property
    def risk_amount(self) -> float:
        """Dollar risk on this trade."""
        return abs(self.entry_price - self.stop_loss) * self.position_size

    @property
    def duration_seconds(self) -> int:
        """How long the position has been open."""
        end = self.closed_at or datetime.now(timezone.utc)
        return int((end - self.opened_at).total_seconds())

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
                return "sl_hit"
            # TP triggered if price wicked UP to TP level
            if high >= self.take_profit:
                return "tp_hit"
        else:  # SHORT
            # SL triggered if price wicked UP to SL level
            if high >= self.stop_loss:
                return "sl_hit"
            # TP triggered if price wicked DOWN to TP level
            if low <= self.take_profit:
                return "tp_hit"

        return None

    def move_to_breakeven(self):
        """
        Move stop loss to TRUE breakeven (entry + spread, not just entry).

        Moving SL to exact entry_price loses you the spread on exit.
        True breakeven = entry_price + spread for longs.
        """
        if self.breakeven_activated:
            return

        spec = get_instrument(self.symbol)
        initial_risk = abs(self.entry_price - self.stop_loss)
        favorable_move = abs(self.current_price - self.entry_price)

        # Activate after 1:1 R move in your favor
        if favorable_move >= initial_risk:
            # True breakeven accounts for spread
            self.stop_loss = spec.breakeven_price(self.entry_price, self.direction.value)
            self.breakeven_activated = True

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
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
            "max_favorable": round(self.max_favorable, 2),
            "max_adverse": round(self.max_adverse, 2),
            "confluence_score": self.confluence_score,
            "claude_confidence": self.claude_confidence,
            "status": self.status.value,
            "breakeven": self.breakeven_activated,
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

    def __init__(self):
        self.positions: dict[str, Position] = {}  # id → Position
        self.closed_positions: list[Position] = []
        self._monitor_task: asyncio.Task | None = None
        self._running = False

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
        pos_id = str(uuid.uuid4())[:8]

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

        # Update risk manager
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

        pnl_pct = (pos.exit_price - pos.entry_price) / pos.entry_price * 100
        if pos.direction == Direction.SHORT:
            pnl_pct = -pnl_pct

        # Update trade journal
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

        # Update risk manager
        risk_manager.record_trade_result(final_pnl)
        today_stats = risk_manager._get_today_stats()
        today_stats.open_positions = max(0, today_stats.open_positions - 1)

        self.closed_positions.append(pos)
        return pos

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
                # Get latest candle for high/low (not just close)
                candles = await market_data.get_candles(pos.symbol, "1m", limit=1)
                if not candles:
                    continue

                c = candles[-1]
                pos.update_price(c.close, candle_high=c.high, candle_low=c.low)
                pos.move_to_breakeven()

                exit_reason = pos.check_exit()
                if exit_reason:
                    self.close_position(pos_id, reason=exit_reason, exit_price=price)

            except Exception:
                continue

    async def start_monitoring(self, interval: int = 10):
        """
        Start background monitoring of open positions.
        Checks prices every `interval` seconds.
        """
        if self._running:
            return

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
