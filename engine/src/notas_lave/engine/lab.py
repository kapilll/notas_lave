"""v3 Lab Engine — Strategy Arena.

ARCHITECTURE:
  Each strategy independently scans the market and proposes trades.
  Strategies COMPETE — the best proposal on each symbol wins.
  Trust scores evolve: winners earn more opportunities, losers get suspended.

  Broker = source of truth for LIVE state (positions, balance)
  Journal = source of truth for HISTORY (closed trades, grades)
  Leaderboard = source of truth for STRATEGY TRUST (who's earning the right to trade)

FLOW:
  For each instrument:
    For each timeframe:
      Run EACH strategy independently → collect proposals
    Filter: proposal score ≥ strategy's dynamic threshold
    If multiple proposals on same symbol → highest score wins
    Risk Manager validates → Execute → Log with proposing strategy
    On close → update leaderboard (win/loss affects trust score)

PACE CONTROL:
  "conservative": 1h only, score>=70, rr>=3.0
  "balanced":      15m+1h, score>=65, rr>=2.0
  "aggressive":    15m+30m+1h, score>=55, rr>=2.0
"""

import asyncio
import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from ..core.events import TradeClosed, TradeOpened
from ..core.models import Direction, Signal, TradeSetup
from ..core.ports import IBroker, ITradeJournal
from ..engine.event_bus import EventBus
from ..engine.leaderboard import StrategyLeaderboard
from ..engine.pnl import PnLResult, PnLService

logger = logging.getLogger(__name__)

LAB_INSTRUMENTS = [
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD",
    "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD", "LTCUSD", "NEARUSD",
    "SUIUSD", "ARBUSD", "PEPEUSD", "WIFUSD", "FTMUSD", "ATOMUSD",
]

CONTEXT_TIMEFRAMES = ["4h", "1d"]

PACE_PRESETS = {
    "conservative": {
        "entry_tfs": ["1h"],
        "min_rr": 3.0,
        "max_concurrent": 3, "cooldown": 300, "scan_interval": 60,
    },
    "balanced": {
        "entry_tfs": ["15m", "1h"],
        "min_rr": 2.0,
        "max_concurrent": 5, "cooldown": 120, "scan_interval": 45,
    },
    "aggressive": {
        "entry_tfs": ["15m", "30m", "1h"],
        "min_rr": 2.0,
        "max_concurrent": 8, "cooldown": 60, "scan_interval": 30,
    },
}

RISK_PER_TRADE = 0.05  # 5% risk per trade — demo account, positions need room to breathe


@dataclass
class TradeProposal:
    """A strategy's proposal to trade a symbol."""
    strategy_name: str
    symbol: str
    timeframe: str
    signal: Signal
    score: float
    factors: list[str]
    # Computed fields for decision-making and display
    risk_reward: float = 0.0
    risk_pct: float = 0.0      # % of entry price at risk
    profit_pct: float = 0.0    # % profit if TP hit
    arena_score: float = 0.0   # composite score for winner selection


class LabEngine:
    def __init__(self, broker: IBroker, journal: ITradeJournal,
                 bus: EventBus, pnl: PnLService) -> None:
        self.broker = broker
        self.journal = journal
        self.bus = bus
        self.pnl = pnl
        self.leaderboard = StrategyLeaderboard()
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_trade: dict[str, datetime] = {}
        self._closing_trades: set[int] = set()
        self._last_known_prices: dict[str, float] = {}

        # Load persisted pace or default to balanced
        self._pace_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "data", "lab_pace.txt",
        )
        saved = self._load_pace()
        self._pace = saved if saved in PACE_PRESETS else "balanced"
        self._settings = PACE_PRESETS[self._pace].copy()

        # Stats
        self._total_trades = 0
        self._total_wins = 0

        # Cache last proposals for the dashboard
        self._last_proposals: list[dict] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def pace(self) -> str:
        return self._pace

    def set_pace(self, pace: str) -> bool:
        if pace not in PACE_PRESETS:
            return False
        self._pace = pace
        self._settings = PACE_PRESETS[pace].copy()
        self._save_pace(pace)
        logger.info("[LAB] Pace -> %s: entry=%s rr>=%.1f",
                     pace, self._settings["entry_tfs"], self._settings["min_rr"])
        return True

    def _load_pace(self) -> str | None:
        try:
            with open(self._pace_file) as f:
                return f.read().strip()
        except Exception:
            return None

    def _save_pace(self, pace: str) -> None:
        try:
            os.makedirs(os.path.dirname(self._pace_file), exist_ok=True)
            with open(self._pace_file, "w") as f:
                f.write(pace)
        except Exception:
            pass

    async def start(self) -> None:
        if self._running:
            return
        if not self.broker.is_connected:
            if not await self.broker.connect():
                logger.error("[LAB] Could not connect to broker")
                return

        self._running = True
        balance = await self.broker.get_balance()
        s = self._settings
        logger.info("[LAB] Started ARENA MODE — %s pace, broker=%s, balance=%.2f",
                     self._pace, self.broker.name, balance.total)
        logger.info("[LAB] Entry: %s | Context: %s | rr>=%.1f max=%d",
                     s["entry_tfs"], CONTEXT_TIMEFRAMES, s["min_rr"], s["max_concurrent"])
        logger.info("[LAB] Active strategies: %s",
                     [s.name for s in self._get_strategies()])
        self._task = asyncio.create_task(self._loop())
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

        try:
            positions = await self.broker.get_positions()
            if positions:
                logger.warning("[LAB] Shutting down with %d open positions:", len(positions))
                for p in positions:
                    logger.warning("[LAB]   %s %s qty=%.4f entry=%.2f pnl=%.4f",
                                   p.direction.value, p.symbol, p.quantity,
                                   p.entry_price, p.unrealized_pnl)
        except Exception as e:
            logger.warning("[LAB] Could not read positions on shutdown: %s", e)

        # Log arena summary
        lb = self.leaderboard.get_leaderboard()
        if lb:
            logger.info("[LAB] === ARENA SUMMARY ===")
            for s in lb:
                logger.info("[LAB]   %s: %dW/%dL (%.0f%% WR) P&L=%.4f trust=%.0f [%s]",
                            s["name"], s["wins"], s["losses"], s["win_rate"],
                            s["total_pnl"], s["trust_score"], s["status"])
        logger.info("[LAB] Stopped")

    async def _loop(self) -> None:
        consecutive_errors = 0
        while self._running:
            try:
                await self._tick()
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                logger.error("[LAB] Tick error (%d consecutive): %s", consecutive_errors, e)
                if consecutive_errors >= 10:
                    logger.error("[LAB] 10 consecutive errors — backing off for 5 minutes")
                    try:
                        from ..alerts.telegram import send_telegram
                        await send_telegram(
                            f"[LAB] ENGINE DEGRADED: {consecutive_errors} consecutive tick errors. "
                            f"Backing off 5 min. Last error: {str(e)[:100]}"
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(300)
                    consecutive_errors = 0
                    continue
            await asyncio.sleep(self._settings["scan_interval"])

    async def _maintenance_loop(self) -> None:
        while self._running:
            await asyncio.sleep(3600)
            try:
                from ..journal.database import run_db_maintenance
                run_db_maintenance()
                logger.info("[LAB] DB maintenance completed")
            except Exception as e:
                logger.warning("[LAB] DB maintenance failed: %s", e)

    def _get_strategies(self):
        """Get all registered strategies."""
        from ..strategies.registry import get_all_strategies
        return get_all_strategies()

    async def _tick(self) -> None:
        """Arena tick: each strategy independently proposes trades, best wins."""
        from ..data.market_data import market_data
        from ..confluence.scorer import detect_regime

        market_data.max_stale_minutes = 0
        s = self._settings

        broker_positions = await self.broker.get_positions()
        open_count = len(broker_positions)
        open_syms = set()
        for bp in broker_positions:
            key = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
            open_syms.add(key)

        strategies = self._get_strategies()
        all_proposals: list[TradeProposal] = []
        scanned = 0

        for symbol in LAB_INSTRUMENTS:
            if open_count >= s["max_concurrent"]:
                break
            if symbol in open_syms:
                continue

            last = self._last_trade.get(symbol)
            if last and (datetime.now(timezone.utc) - last).total_seconds() < s["cooldown"]:
                continue

            # Collect proposals from ALL strategies on ALL timeframes
            symbol_proposals: list[TradeProposal] = []

            for tf in s["entry_tfs"]:
                try:
                    candles = await market_data.get_candles(symbol, tf, limit=250)
                    if not candles or len(candles) < 50:
                        continue

                    scanned += 1

                    # Run each strategy independently
                    for strategy in strategies:
                        try:
                            signal = strategy.analyze(candles, symbol)

                            # Skip empty signals
                            if (signal.direction is None or signal.score <= 0
                                    or not signal.entry_price or not signal.stop_loss
                                    or not signal.take_profit):
                                continue

                            # Check R:R
                            risk = abs(signal.entry_price - signal.stop_loss)
                            reward = abs(signal.take_profit - signal.entry_price)
                            if risk <= 0 or reward / risk < s["min_rr"]:
                                continue

                            # Check if strategy is allowed to trade with this score
                            if not self.leaderboard.can_trade(strategy.name, signal.score):
                                continue

                            factors = signal.metadata.get("factors", [])
                            if isinstance(factors, str):
                                factors = [factors]

                            # Compute trade metrics
                            rr = reward / risk
                            risk_pct = (risk / signal.entry_price) * 100
                            profit_pct = (reward / signal.entry_price) * 100

                            # Composite arena score for winner selection:
                            # 40% signal score + 25% R:R + 20% strategy trust + 15% win rate
                            rec = self.leaderboard.get_or_create(strategy.name)
                            arena_score = (
                                (signal.score / 100) * 40 +          # signal quality (0-40)
                                min(rr / 5, 1.0) * 25 +              # R:R capped at 5:1 (0-25)
                                (rec.trust_score / 100) * 20 +       # trust earned (0-20)
                                (rec.win_rate / 100) * 15             # historical WR (0-15)
                            )

                            symbol_proposals.append(TradeProposal(
                                strategy_name=strategy.name,
                                symbol=symbol,
                                timeframe=tf,
                                signal=signal,
                                score=signal.score,
                                factors=factors,
                                risk_reward=round(rr, 2),
                                risk_pct=round(risk_pct, 3),
                                profit_pct=round(profit_pct, 3),
                                arena_score=round(arena_score, 1),
                            ))

                        except Exception as e:
                            logger.debug("[LAB] %s/%s/%s error: %s",
                                        strategy.name, symbol, tf, e)

                except Exception as e:
                    logger.debug("[LAB] %s/%s candle error: %s", symbol, tf, e)

            # Pick the BEST proposal using composite arena_score (not just signal score)
            if symbol_proposals:
                best = max(symbol_proposals, key=lambda p: p.arena_score)
                all_proposals.append(best)

                if len(symbol_proposals) > 1:
                    competitors = ", ".join(
                        f"{p.strategy_name}(arena={p.arena_score:.0f},sig={p.score:.0f})"
                        for p in sorted(symbol_proposals, key=lambda p: -p.arena_score)
                    )
                    logger.info("[LAB] ARENA %s: %d proposals → winner: %s "
                                "(arena=%.0f, sig=%.0f, rr=%.1f, trust=%.0f). All: %s",
                                symbol, len(symbol_proposals), best.strategy_name,
                                best.arena_score, best.score, best.risk_reward,
                                self.leaderboard.get_or_create(best.strategy_name).trust_score,
                                competitors)

        # Cache ALL proposals (winners + losers) for dashboard visibility
        all_symbol_proposals = []
        for proposal in all_proposals:
            all_symbol_proposals.append(proposal)

        now = datetime.now(timezone.utc)
        # Proposals expire after 2× the scan interval — after that the setup is stale
        expires_at = (now.timestamp() + s["scan_interval"] * 2)
        self._last_proposals = [
            {
                "strategy": p.strategy_name,
                "symbol": p.symbol,
                "timeframe": p.timeframe,
                "direction": p.signal.direction.value if p.signal.direction else None,
                "score": round(p.score, 1),
                "arena_score": p.arena_score,
                "entry": p.signal.entry_price,
                "stop_loss": p.signal.stop_loss,
                "take_profit": p.signal.take_profit,
                "risk_reward": p.risk_reward,
                "risk_pct": p.risk_pct,
                "profit_pct": p.profit_pct,
                "factors": p.factors,
                "reason": p.signal.reason,
                "trust_score": self.leaderboard.get_or_create(p.strategy_name).trust_score,
                "win_rate": self.leaderboard.get_or_create(p.strategy_name).win_rate,
                "generated_at": now.isoformat(),
                "expires_at": expires_at,
            }
            for p in all_proposals
        ]

        # Execute winning proposals
        trades_placed = 0
        for proposal in all_proposals:
            if open_count >= s["max_concurrent"]:
                break

            signal = proposal.signal
            from ..data.instruments import get_instrument
            spec = get_instrument(proposal.symbol)
            balance = await self.broker.get_balance()

            # Loss streak throttle from leaderboard
            rec = self.leaderboard.get_or_create(proposal.strategy_name)
            effective_risk = RISK_PER_TRADE
            if rec.current_streak <= -3:
                effective_risk = RISK_PER_TRADE / 2.0
                logger.info("[LAB] %s loss streak throttle: risk halved",
                            proposal.strategy_name)

            pos_size = spec.calculate_position_size(
                entry=signal.entry_price,
                stop_loss=signal.stop_loss,
                account_balance=balance.total,
                risk_pct=effective_risk,
            )
            if pos_size <= 0:
                continue

            risk = abs(signal.entry_price - signal.stop_loss)
            reward = abs(signal.take_profit - signal.entry_price)
            rr = reward / risk if risk > 0 else 0

            setup = TradeSetup(
                symbol=proposal.symbol,
                direction=signal.direction,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                position_size=pos_size,
                risk_reward_ratio=rr,
                confluence_score=signal.score,
                signals_snapshot=[signal],
            )

            # Risk Manager
            from ..risk.manager import RiskManager
            risk_mgr = RiskManager(starting_balance=balance.total)
            passed, rejections = risk_mgr.validate_trade(setup)
            if not passed:
                logger.info("[LAB] RISK REJECT %s by %s: %s",
                            proposal.symbol, proposal.strategy_name, rejections)
                continue

            # Count competing proposals for this symbol
            competing = sum(1 for p in all_proposals if p.symbol == proposal.symbol) - 1

            context = {
                "timeframe": proposal.timeframe,
                "proposing_strategy": proposal.strategy_name,
                "strategy_score": proposal.score,
                "strategy_factors": proposal.factors,
                "competing_proposals": competing,
            }

            trade_id = await self.execute_trade(setup, context)
            if trade_id > 0:
                self._last_trade[proposal.symbol] = datetime.now(timezone.utc)
                open_count += 1
                open_syms.add(proposal.symbol)
                trades_placed += 1
                logger.info(
                    "[LAB] TRADE #%d by [%s]: %s %s %s score=%.0f rr=%.1f "
                    "factors=%s",
                    trade_id, proposal.strategy_name,
                    signal.direction.value, proposal.symbol, proposal.timeframe,
                    proposal.score, rr, proposal.factors,
                )

        if trades_placed > 0 or scanned > 0:
            wr = (self._total_wins / self._total_trades * 100) if self._total_trades > 0 else 0
            logger.info("[LAB] Tick [%s]: scanned=%d proposals=%d placed=%d open=%d | "
                         "%d trades %.0f%% WR",
                         self._pace, scanned, len(all_proposals), trades_placed,
                         open_count, self._total_trades, wr)

        await self._check_positions()
        await self._reconcile()

    async def _reconcile(self) -> None:
        """Reconcile journal with broker."""
        broker_positions = await self.broker.get_positions()
        broker_syms = set()
        for bp in broker_positions:
            key = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
            broker_syms.add(key)
            if bp.current_price > 0:
                self._last_known_prices[key] = bp.current_price

        journal_open = self.journal.get_open_trades()
        closed = 0

        for trade in journal_open:
            sym = trade.get("symbol", "")
            if sym in broker_syms:
                continue

            trade_id = trade.get("trade_id", 0)
            entry = trade.get("entry_price", 0)
            direction = trade.get("direction", "LONG")
            size = trade.get("position_size", 0)
            exit_price = self._last_known_prices.get(sym, entry)
            strategy_name = trade.get("proposing_strategy", "unknown")

            pnl = ((exit_price - entry) if direction == "LONG"
                   else (entry - exit_price)) * size

            self.journal.record_close(trade_id, exit_price, "exchange_close", pnl)
            self.journal.record_grade(trade_id, "A" if pnl > 0 else "D", "exchange_close")

            # Update leaderboard
            if pnl > 0:
                self.leaderboard.record_win(strategy_name, pnl)
                self._total_wins += 1
            else:
                self.leaderboard.record_loss(strategy_name, pnl)
            self._total_trades += 1

            logger.info("[LAB] RECONCILE #%d [%s]: %s %s pnl=%.4f",
                         trade_id, strategy_name, direction, sym, pnl)
            closed += 1

        # Close duplicates
        remaining = self.journal.get_open_trades()
        seen: set[str] = set()
        for trade in sorted(remaining, key=lambda t: t.get("trade_id", 0), reverse=True):
            sym = trade.get("symbol", "")
            if sym in seen:
                self.journal.record_close(trade.get("trade_id", 0),
                                          exit_price=trade.get("entry_price", 0),
                                          reason="dup_cleanup", pnl=0)
                closed += 1
            else:
                seen.add(sym)

        if closed > 0:
            logger.info("[LAB] Reconciled: %d entries", closed)

    async def get_live_positions(self) -> list[dict]:
        """Get positions from BROKER, enriched with journal data."""
        broker_positions = await self.broker.get_positions()
        journal_open = self.journal.get_open_trades()
        journal_by_sym = {t.get("symbol", ""): t for t in journal_open}

        result = []
        for bp in broker_positions:
            sym = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
            j = journal_by_sym.get(sym, {})
            result.append({
                "symbol": sym,
                "direction": bp.direction.value,
                "quantity": bp.quantity,
                "entry_price": bp.entry_price,
                "current_price": bp.current_price,
                "unrealized_pnl": round(bp.unrealized_pnl, 4),
                "pnl": round(bp.unrealized_pnl, 4),
                "leverage": bp.leverage,
                "stop_loss": j.get("stop_loss", 0),
                "take_profit": j.get("take_profit", 0),
                "confluence_score": j.get("confluence_score", 0),
                "trade_id": j.get("trade_id", 0),
                "proposing_strategy": j.get("proposing_strategy", ""),
            })
        return result

    async def _check_positions(self) -> None:
        """Monitor SL/TP using broker positions."""
        from ..data.market_data import market_data

        broker_positions = await self.broker.get_positions()
        journal_open = self.journal.get_open_trades()
        journal_by_sym = {t.get("symbol", ""): t for t in journal_open}

        for bp in broker_positions:
            sym = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
            journal = journal_by_sym.get(sym, {})
            sl = journal.get("stop_loss", 0)
            tp = journal.get("take_profit", 0)
            trade_id = journal.get("trade_id", 0)
            direction = bp.direction.value

            if not sl and not tp:
                continue

            price = bp.current_price
            if price <= 0:
                try:
                    candles = await market_data.get_candles(sym, "1m", limit=1)
                    price = candles[-1].close if candles else 0
                except Exception:
                    continue
            if price <= 0:
                continue

            try:
                candles = await market_data.get_candles(sym, "1m", limit=1)
                high = candles[-1].high if candles else price
                low = candles[-1].low if candles else price
            except Exception:
                high = low = price

            hit = None
            exit_price = price
            if direction == "LONG":
                if sl > 0 and low <= sl:
                    hit, exit_price = "sl_hit", sl
                elif tp > 0 and high >= tp:
                    hit, exit_price = "tp_hit", tp
            elif direction == "SHORT":
                if sl > 0 and high >= sl:
                    hit, exit_price = "sl_hit", sl
                elif tp > 0 and low <= tp:
                    hit, exit_price = "tp_hit", tp

            if hit and trade_id > 0:
                await self.close_trade(trade_id, exit_price=exit_price, reason=hit)

    async def execute_trade(self, setup: TradeSetup, context: dict | None = None) -> int:
        """Execute: place on broker FIRST, only journal if confirmed."""
        ctx = context or {}

        result = await self.broker.place_order(setup)
        if not result.success:
            logger.warning("[LAB] Broker rejected %s %s: %s",
                           setup.direction.value, setup.symbol, result.error)
            return 0

        strategy_name = ctx.get("proposing_strategy", "unknown")

        signal = Signal(
            strategy_name=strategy_name,
            direction=setup.direction,
            score=setup.confluence_score,
            metadata={
                "timeframe": ctx.get("timeframe", ""),
                "strategy_score": ctx.get("strategy_score", 0),
                "strategy_factors": ctx.get("strategy_factors", []),
                "competing_proposals": ctx.get("competing_proposals", 0),
                "proposing_strategy": strategy_name,
            },
        )
        trade_id = self.journal.record_signal(signal)
        self.journal.record_open(trade_id, setup)

        # Mirror to SQLAlchemy for Learning Engine
        try:
            from ..journal.database import log_trade
            log_trade(
                signal_log_id=0,
                symbol=setup.symbol,
                timeframe=ctx.get("timeframe", ""),
                direction=setup.direction.value,
                regime="",
                entry_price=result.filled_price or setup.entry_price,
                stop_loss=setup.stop_loss,
                take_profit=setup.take_profit,
                position_size=result.filled_quantity or setup.position_size,
                confluence_score=setup.confluence_score,
                claude_confidence=0,
                strategies_agreed=[strategy_name],
                proposing_strategy=strategy_name,
                strategy_score=ctx.get("strategy_score", 0),
                strategy_factors=json.dumps(ctx.get("strategy_factors", [])),
                competing_proposals=ctx.get("competing_proposals", 0),
            )
        except Exception as e:
            logger.warning("[LAB] Failed to mirror trade to SQLAlchemy: %s", e)

        now = datetime.now(timezone.utc)
        await self.bus.publish(TradeOpened(
            trade_id=str(trade_id), symbol=setup.symbol,
            direction=setup.direction.value,
            entry_price=result.filled_price or setup.entry_price,
            position_size=result.filled_quantity or setup.position_size,
            stop_loss=setup.stop_loss, take_profit=setup.take_profit,
            timestamp=now,
        ))
        return trade_id

    async def close_trade(self, trade_id: int, exit_price: float, reason: str) -> None:
        if trade_id in self._closing_trades:
            return
        self._closing_trades.add(trade_id)

        open_trades = self.journal.get_open_trades()
        trade_info = next(
            (t for t in open_trades if t.get("trade_id") == trade_id), None)
        if not trade_info:
            self._closing_trades.discard(trade_id)
            return

        symbol = trade_info.get("symbol", "")
        direction = trade_info.get("direction", "LONG")
        entry_price = trade_info.get("entry_price", 0)
        position_size = trade_info.get("position_size", 0)
        strategy_name = trade_info.get("proposing_strategy", "unknown")

        # Try to get strategy name from signal metadata if not in trade_info
        if strategy_name == "unknown":
            # The signal metadata might have it
            signal_data = trade_info.get("signal_data", {})
            if isinstance(signal_data, dict):
                strategy_name = signal_data.get("proposing_strategy", signal_data.get("strategy_name", "unknown"))

        pnl = ((exit_price - entry_price) if direction == "LONG"
               else (entry_price - exit_price)) * position_size

        grade = ("A" if reason == "tp_hit" and pnl > 0
                 else "B" if pnl > 0
                 else "D" if reason == "sl_hit"
                 else "C")

        if symbol:
            await self.broker.close_position(symbol)

        self.journal.record_close(trade_id, exit_price, reason, pnl)
        self.journal.record_grade(trade_id, grade, reason)

        # Mirror close to SQLAlchemy
        try:
            from ..journal.database import get_db, TradeLog
            db = get_db()
            sql_trade = db.query(TradeLog).filter(
                TradeLog.symbol == symbol,
                TradeLog.exit_price.is_(None),
            ).order_by(TradeLog.id.desc()).first()
            if sql_trade:
                sql_trade.exit_price = exit_price
                sql_trade.exit_reason = reason
                sql_trade.pnl = pnl
                sql_trade.pnl_pct = (pnl / entry_price * 100) if entry_price > 0 else 0
                sql_trade.outcome_grade = grade
                sql_trade.closed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception as e:
            logger.warning("[LAB] Failed to mirror close to SQLAlchemy: %s", e)

        # UPDATE LEADERBOARD — the core of the arena
        self._total_trades += 1
        if pnl > 0:
            self._total_wins += 1
            self.leaderboard.record_win(strategy_name, pnl)
        elif pnl < 0:
            self.leaderboard.record_loss(strategy_name, pnl)

        rec = self.leaderboard.get_or_create(strategy_name)
        wr = self._total_wins / self._total_trades * 100

        logger.info("[LAB] CLOSED #%d [%s]: %s %s %s pnl=%.4f grade=%s | "
                     "Strategy trust=%.0f WR=%.0f%% | Overall WR=%.0f%%",
                     trade_id, strategy_name, direction, symbol, reason,
                     pnl, grade, rec.trust_score, rec.win_rate, wr)

        now = datetime.now(timezone.utc)
        await self.bus.publish(TradeClosed(
            trade_id=str(trade_id), symbol=symbol, direction=direction,
            entry_price=entry_price, exit_price=exit_price,
            pnl=pnl, reason=reason, timestamp=now,
        ))

        self._closing_trades.discard(trade_id)

    async def get_status(self) -> dict:
        balance = await self.broker.get_balance()
        broker_positions = await self.broker.get_positions()
        closed_trades = self.journal.get_closed_trades(limit=1000)
        wr = (self._total_wins / self._total_trades * 100) if self._total_trades > 0 else 0
        return {
            "running": self._running, "pace": self._pace,
            "mode": "arena",
            "entry_tfs": self._settings["entry_tfs"],
            "context_tfs": CONTEXT_TIMEFRAMES,
            "balance": balance.total,
            "open_trades": len(broker_positions),
            "closed_trades": len(closed_trades),
            "broker": self.broker.name,
            "broker_connected": self.broker.is_connected,
            "win_rate": round(wr, 1),
            "total_trades": self._total_trades,
            "active_strategies": len(self.leaderboard.get_active_strategies()),
            "total_strategies": len(self._get_strategies()),
        }

    def get_arena_status(self) -> dict:
        """Get the full arena state for the dashboard."""
        return {
            "leaderboard": self.leaderboard.get_leaderboard(),
            "active_proposals": self._last_proposals,
            "active_strategies": self.leaderboard.get_active_strategies(),
        }

    def get_pnl(self, current_balance: float) -> PnLResult:
        return self.pnl.calculate(current_balance)
