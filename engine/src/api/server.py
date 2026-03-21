"""
FastAPI server — REST API for the Next.js dashboard.

Endpoints:
- GET /api/scan/{symbol}     → Run all strategies on a symbol, return confluence score
- GET /api/prices            → Get current prices for all instruments
- GET /api/risk/status       → Get current risk manager status
- GET /api/signals           → Get latest signals across all instruments
- WebSocket /ws/live         → Real-time price and signal updates (Phase 2)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone

from ..data.market_data import market_data
from ..data.models import Direction
from ..confluence.scorer import compute_confluence
from ..claude_engine.decision import evaluate_setup
from ..risk.manager import risk_manager
from ..execution.paper_trader import paper_trader
from ..backtester.engine import Backtester
from ..alerts.scanner import alert_scanner
from ..alerts.telegram import send_telegram, format_trade_opened, format_trade_closed
from ..journal.database import log_signal, get_recent_signals, get_recent_trades, get_strategy_performance
from ..config import config

app = FastAPI(
    title="Notas Lave Trading Engine",
    description="AI-powered trading decision engine for scalping",
    version="0.1.0",
)

# Allow Next.js dashboard to connect (runs on localhost:3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    """Start position monitoring and alert scanner when engine boots."""
    await paper_trader.start_monitoring(interval=10)
    await alert_scanner.start()


@app.on_event("shutdown")
async def shutdown():
    paper_trader.stop_monitoring()
    alert_scanner.stop()


@app.get("/api/health")
async def health_check():
    """Simple health check endpoint."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine_version": "0.1.0",
    }


@app.get("/api/prices")
async def get_prices():
    """
    Get current prices for all tracked instruments.
    Returns the latest price for Gold, Silver, BTC, ETH.
    """
    prices = {}
    for symbol in config.instruments:
        price = await market_data.get_current_price(symbol)
        prices[symbol] = {
            "price": price,
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    return {"prices": prices}


@app.get("/api/scan/all")
async def scan_all_symbols(timeframe: str = "5m"):
    """Scan all instruments at once. Dashboard overview."""
    results = []
    for symbol in config.instruments:
        try:
            candles = await market_data.get_candles(symbol, timeframe, limit=250)
            if candles:
                confluence = compute_confluence(candles, symbol, timeframe)
                results.append({
                    "symbol": symbol,
                    "price": candles[-1].close,
                    "regime": confluence.regime.value,
                    "score": confluence.composite_score,
                    "direction": confluence.direction.value if confluence.direction else None,
                    "agreeing": confluence.agreeing_strategies,
                    "total": confluence.total_strategies,
                    "top_signal": next(
                        (s.reason for s in confluence.signals if s.score > 0),
                        "No signals",
                    ),
                })
        except Exception as e:
            results.append({
                "symbol": symbol,
                "error": str(e)[:100],
            })
    return {"results": results, "timeframe": timeframe}


@app.get("/api/scan/{symbol}")
async def scan_symbol(symbol: str, timeframe: str = "5m"):
    """
    Run the full analysis pipeline on a symbol.

    1. Fetch candles
    2. Run all strategies
    3. Compute confluence score
    4. Return detailed results
    """
    symbol = symbol.upper()
    if symbol not in config.instruments:
        return {"error": f"Unknown symbol: {symbol}. Available: {config.instruments}"}

    candles = await market_data.get_candles(symbol, timeframe, limit=250)
    if not candles:
        return {"error": f"No data available for {symbol} on {timeframe}"}

    result = compute_confluence(candles, symbol, timeframe)

    formatted_signals = []
    for signal in result.signals:
        formatted_signals.append({
            "strategy": signal.strategy_name,
            "direction": signal.direction.value if signal.direction else None,
            "strength": signal.strength.value,
            "score": signal.score,
            "entry": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "reason": signal.reason,
            "metadata": signal.metadata,
        })

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "regime": result.regime.value,
        "composite_score": result.composite_score,
        "direction": result.direction.value if result.direction else None,
        "agreeing_strategies": result.agreeing_strategies,
        "total_strategies": result.total_strategies,
        "signals": formatted_signals,
        "current_price": candles[-1].close if candles else None,
        "timestamp": result.timestamp.isoformat(),
    }


@app.get("/api/evaluate/{symbol}")
async def evaluate_symbol(symbol: str, timeframe: str = "5m"):
    """
    Full pipeline: Fetch data → Run strategies → Confluence score → Claude evaluation.

    This is the BIG endpoint — it does everything and returns Claude's decision.
    Use this when you want to know: "Should I trade this right now?"
    """
    symbol = symbol.upper()
    if symbol not in config.instruments:
        return {"error": f"Unknown symbol: {symbol}"}

    candles = await market_data.get_candles(symbol, timeframe, limit=250)
    if not candles:
        return {"error": f"No data for {symbol}"}

    # Step 1: Confluence scoring
    confluence = compute_confluence(candles, symbol, timeframe)

    # Step 2: Claude evaluation
    decision = await evaluate_setup(confluence)

    # Step 3: Risk manager validation (if Claude says BUY/SELL)
    risk_check = {"passed": True, "rejections": []}
    if decision.action in ("BUY", "SELL"):
        from ..data.models import TradeSetup
        setup = TradeSetup(
            symbol=symbol,
            timeframe=timeframe,
            direction=Direction.LONG if decision.action == "BUY" else Direction.SHORT,
            entry_price=decision.entry_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            position_size=risk_manager.calculate_position_size(
                decision.entry_price, decision.stop_loss, symbol
            ),
            risk_reward_ratio=(
                abs(decision.take_profit - decision.entry_price) /
                abs(decision.entry_price - decision.stop_loss)
                if abs(decision.entry_price - decision.stop_loss) > 0 else 0
            ),
            confluence_score=confluence.composite_score,
            claude_confidence=decision.confidence,
        )
        passed, rejections = risk_manager.validate_trade(setup)
        risk_check = {"passed": passed, "rejections": rejections}

    should_trade = (
        decision.action in ("BUY", "SELL")
        and decision.confidence >= config.claude_min_confidence
        and risk_check["passed"]
    )

    # Log this evaluation to the trade journal
    try:
        signal_data = [
            {"strategy": s.strategy_name, "direction": s.direction.value if s.direction else None,
             "score": s.score, "reason": s.reason[:200]}
            for s in confluence.signals
        ]
        log_signal(
            symbol=symbol,
            timeframe=timeframe,
            regime=confluence.regime.value,
            composite_score=confluence.composite_score,
            direction=confluence.direction.value if confluence.direction else None,
            agreeing=confluence.agreeing_strategies,
            total=confluence.total_strategies,
            signals=signal_data,
            claude_action=decision.action,
            claude_confidence=decision.confidence,
            claude_reasoning=decision.reasoning,
            risk_passed=risk_check["passed"],
            risk_rejections=risk_check.get("rejections", []),
            should_trade=should_trade,
        )
    except Exception:
        pass  # Don't let journal errors block trading

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "confluence": {
            "score": confluence.composite_score,
            "direction": confluence.direction.value if confluence.direction else None,
            "regime": confluence.regime.value,
            "agreeing": confluence.agreeing_strategies,
            "total": confluence.total_strategies,
        },
        "claude_decision": {
            "action": decision.action,
            "confidence": decision.confidence,
            "entry": decision.entry_price,
            "stop_loss": decision.stop_loss,
            "take_profit": decision.take_profit,
            "reasoning": decision.reasoning,
            "risk_warnings": decision.risk_warnings,
        },
        "risk_check": risk_check,
        "current_price": candles[-1].close,
        "should_trade": should_trade,
    }


@app.get("/api/journal/signals")
async def get_signals_history(limit: int = 50):
    """Get recent signal evaluation history."""
    return {"signals": get_recent_signals(limit)}


@app.get("/api/journal/trades")
async def get_trades_history(limit: int = 50):
    """Get recent trade history."""
    return {"trades": get_recent_trades(limit)}


@app.get("/api/journal/performance")
async def get_performance():
    """Get strategy performance analysis."""
    return {"strategies": get_strategy_performance()}


@app.get("/api/risk/status")
async def get_risk_status():
    """Get current risk manager status for the dashboard."""
    return risk_manager.get_status()


@app.get("/api/candles/{symbol}")
async def get_candles(symbol: str, timeframe: str = "5m", limit: int = 100):
    """
    Get candle data for charting in the dashboard.
    Returns OHLCV data that can be rendered as candlestick charts.
    """
    symbol = symbol.upper()
    candles = await market_data.get_candles(symbol, timeframe, limit)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": [
            {
                "time": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ],
    }


# ===== PAPER TRADING ENDPOINTS =====


@app.post("/api/trade/open/{symbol}")
async def open_trade(symbol: str, timeframe: str = "5m"):
    """
    Full pipeline: Evaluate → Risk Check → Open Position.

    This is the "Take Trade" button. It:
    1. Runs all strategies
    2. Gets Claude's decision
    3. Checks risk rules
    4. Opens a simulated position if everything passes
    """
    symbol = symbol.upper()
    if symbol not in config.instruments:
        return {"error": f"Unknown symbol: {symbol}"}

    candles = await market_data.get_candles(symbol, timeframe, limit=250)
    if not candles:
        return {"error": f"No data for {symbol}"}

    # Step 1: Confluence
    confluence = compute_confluence(candles, symbol, timeframe)

    # Step 2: Claude evaluation
    decision = await evaluate_setup(confluence)

    # Log the signal
    signal_data = [
        {"strategy": s.strategy_name, "direction": s.direction.value if s.direction else None,
         "score": s.score, "reason": s.reason[:200]}
        for s in confluence.signals
    ]

    try:
        signal_id = log_signal(
            symbol=symbol, timeframe=timeframe, regime=confluence.regime.value,
            composite_score=confluence.composite_score,
            direction=confluence.direction.value if confluence.direction else None,
            agreeing=confluence.agreeing_strategies, total=confluence.total_strategies,
            signals=signal_data, claude_action=decision.action,
            claude_confidence=decision.confidence, claude_reasoning=decision.reasoning,
            risk_passed=True, risk_rejections=[],
            should_trade=decision.action in ("BUY", "SELL"),
        )
    except Exception:
        signal_id = 0

    # Step 3: Check if Claude approves
    if decision.action not in ("BUY", "SELL"):
        return {
            "status": "rejected",
            "reason": f"Claude says {decision.action}: {decision.reasoning}",
            "confluence_score": confluence.composite_score,
            "claude_confidence": decision.confidence,
        }

    if decision.confidence < config.claude_min_confidence:
        return {
            "status": "rejected",
            "reason": f"Claude confidence {decision.confidence} below minimum {config.claude_min_confidence}",
        }

    # Step 4: Calculate position size and build setup
    direction = Direction.LONG if decision.action == "BUY" else Direction.SHORT
    pos_size = risk_manager.calculate_position_size(
        decision.entry_price, decision.stop_loss, symbol
    )

    risk = abs(decision.entry_price - decision.stop_loss)
    reward = abs(decision.take_profit - decision.entry_price)
    rr = reward / risk if risk > 0 else 0

    from ..data.models import TradeSetup
    setup = TradeSetup(
        symbol=symbol, timeframe=timeframe, direction=direction,
        entry_price=decision.entry_price, stop_loss=decision.stop_loss,
        take_profit=decision.take_profit, position_size=pos_size,
        risk_reward_ratio=rr, confluence_score=confluence.composite_score,
        claude_confidence=decision.confidence,
    )

    # Step 5: Risk manager validation
    passed, rejections = risk_manager.validate_trade(setup)
    if not passed:
        return {
            "status": "rejected",
            "reason": "Risk manager blocked the trade",
            "rejections": rejections,
        }

    # Step 6: Open the position
    strategies_agreed = [
        s.strategy_name for s in confluence.signals
        if s.direction == direction
    ]

    position = paper_trader.open_position(
        signal_log_id=signal_id,
        symbol=symbol, timeframe=timeframe, direction=direction,
        regime=confluence.regime.value,
        entry_price=decision.entry_price, stop_loss=decision.stop_loss,
        take_profit=decision.take_profit, position_size=pos_size,
        confluence_score=confluence.composite_score,
        claude_confidence=decision.confidence,
        strategies_agreed=strategies_agreed,
    )

    # Send Telegram notification
    await send_telegram(format_trade_opened(
        symbol=symbol, direction=direction.value,
        entry=position.entry_price, sl=position.stop_loss, tp=position.take_profit,
        size=position.position_size, risk=position.risk_amount, confidence=decision.confidence,
    ))

    return {
        "status": "opened",
        "position": position.to_dict(),
        "risk_amount": round(position.risk_amount, 2),
        "risk_reward": round(rr, 2),
    }


@app.post("/api/trade/close/{position_id}")
async def close_trade_endpoint(position_id: str, reason: str = "manual"):
    """Manually close a position."""
    pos = paper_trader.close_position(position_id, reason=reason)
    if not pos:
        return {"error": f"Position {position_id} not found"}

    from .server import market_data as _md  # avoid circular
    from ..data.instruments import get_instrument
    spec = get_instrument(pos.symbol)
    pnl = spec.calculate_pnl(pos.entry_price, pos.exit_price, pos.position_size, pos.direction.value)

    # Send Telegram notification
    await send_telegram(format_trade_closed(
        symbol=pos.symbol, direction=pos.direction.value,
        entry=pos.entry_price, exit_price=pos.exit_price,
        pnl=pnl, exit_reason=reason, duration_mins=pos.duration_seconds / 60,
    ))

    return {
        "status": "closed",
        "position": pos.to_dict(),
        "pnl": round(pnl, 2),
        "exit_reason": reason,
    }


@app.get("/api/trade/positions")
async def get_positions():
    """Get all open positions."""
    # Trigger a price update first
    await paper_trader.update_positions()
    return {
        "positions": paper_trader.get_open_positions(),
        "count": paper_trader.open_count,
    }


@app.get("/api/trade/history")
async def get_trade_history(limit: int = 50):
    """Get closed position history."""
    return {
        "trades": paper_trader.get_closed_positions(limit),
        "summary": paper_trader.get_summary(),
    }


@app.get("/api/trade/summary")
async def get_trade_summary():
    """Get paper trading performance summary."""
    return paper_trader.get_summary()


# ===== BACKTESTING ENDPOINTS =====


@app.get("/api/backtest/{symbol}")
async def run_backtest(symbol: str, timeframe: str = "5m"):
    """
    Run a backtest on historical data for a symbol.

    Fetches max available historical data via yfinance (fallback provider),
    then walks forward testing all strategies.
    """
    symbol = symbol.upper()
    if symbol not in config.instruments:
        return {"error": f"Unknown symbol: {symbol}"}

    # Fetch historical data (yfinance for backtesting — it has more history)
    candles = await market_data._fetch_yfinance(symbol, timeframe)
    if len(candles) < 300:
        return {"error": f"Not enough historical data ({len(candles)} candles, need 300+)"}

    # Run backtest with full FundingPips risk controls (10 levers)
    bt = Backtester(
        starting_balance=100_000,
        risk_per_trade=0.003,          # 0.3% risk per trade
        max_concurrent=1,             # 1 trade at a time
        min_score=60.0,               # Higher bar for signal quality
        require_strong=True,          # STRONG signals only
        daily_loss_limit_pct=0.04,    # 4% daily circuit breaker
        total_dd_limit_pct=0.08,      # 8% total DD halt
        trade_cooldown=5,             # 5 candles between trades
        max_trades_per_day=4,         # Cap at 4 trades/day
        trailing_breakeven=True,      # Move SL to BE after 1:1
        skip_volatile_regime=True,    # Skip volatile markets
        loss_streak_threshold=3,      # Halve size after 3 losses
    )

    result = bt.run(candles, symbol, timeframe)
    return result.to_dict()


# ===== ALERT ENDPOINTS =====


@app.get("/api/alerts/status")
async def get_alert_status():
    """Get alert scanner status."""
    return alert_scanner.get_status()


@app.post("/api/alerts/test")
async def test_alert():
    """Send a test message to verify Telegram is working."""
    ok = await send_telegram("✅ *Notas Lave Test Alert*\n\nTelegram integration working!")
    return {"sent": ok, "configured": bool(config.telegram_bot_token and config.telegram_chat_id)}


@app.post("/api/alerts/scan-now")
async def trigger_scan():
    """Manually trigger one scan cycle."""
    alerts = await alert_scanner.scan_once()
    return {"alerts_sent": len(alerts), "alerts": alerts}
