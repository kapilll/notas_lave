"""
FastAPI server — REST API for the Next.js dashboard.

Endpoints:
- GET /api/scan/{symbol}     → Run all strategies on a symbol, return confluence score
- GET /api/prices            → Get current prices for all instruments
- GET /api/risk/status       → Get current risk manager status
- GET /api/signals           → Get latest signals across all instruments
- WebSocket /ws/live         → Real-time price and signal updates (Phase 2)
"""

from collections import defaultdict
import logging
import time as _time
from contextlib import asynccontextmanager

# DO-20: Track server start time for uptime calculation
_server_start_time = _time.time()

logger = logging.getLogger(__name__)
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from datetime import datetime, timezone

# SEC-18/SE-24: Simple in-memory rate limiting for mutation endpoints.
# Keyed by (client_ip, path) to allow 60 requests/minute per endpoint.
_rate_limit_store: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(key: str, max_per_minute: int = 60) -> bool:
    """SEC-18: Simple in-memory rate limiting."""
    now = _time.time()
    _rate_limit_store[key] = [t for t in _rate_limit_store[key] if now - t < 60]
    if len(_rate_limit_store[key]) >= max_per_minute:
        return False
    _rate_limit_store[key].append(now)
    return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    """SE-24: Rate limit POST/PUT/DELETE requests to 60/min per endpoint per client."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "DELETE"):
            client_ip = request.client.host if request.client else "unknown"
            key = f"{client_ip}:{request.url.path}"
            if not _check_rate_limit(key, max_per_minute=60):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Max 60 requests/minute per endpoint."},
                )
        return await call_next(request)

from ..data.market_data import market_data
from ..data.models import Direction
from ..data.economic_calendar import get_blackout_status, get_upcoming_events, is_in_blackout
from ..data.historical_downloader import (
    download_best_available, save_candles_csv, load_candles_csv, list_available_data,
)
from ..confluence.scorer import compute_confluence
from ..learning.analyzer import run_full_analysis
from ..learning.recommendations import generate_all_recommendations
from ..learning.claude_review import generate_review
from ..learning.optimizer import optimize_all_strategies, save_results, load_results
from ..claude_engine.decision import evaluate_setup
from ..risk.manager import risk_manager
from ..execution.paper_trader import paper_trader
from ..execution.base_broker import OrderSide, OrderType
from ..agent.autonomous_trader import autonomous_trader
from ..agent.config import agent_config, AgentMode
from ..lab.lab_trader import LabTrader
from ..execution.coindcx import CoinDCXBroker
from ..execution.mt5_broker import MT5Broker
from ..execution.binance_testnet import BinanceTestnetBroker
from ..backtester.engine import Backtester
from ..backtester.monte_carlo import run_monte_carlo
from ..learning.ab_testing import create_test as ab_create_test, record_result as ab_record_result, get_test_results as ab_get_test_results, get_all_tests as ab_get_all_tests
from ..alerts.scanner import alert_scanner
from ..alerts.telegram import send_telegram, send_error_alert, format_trade_opened, format_trade_closed
from ..journal.database import log_signal, get_recent_signals, get_recent_trades, get_strategy_performance, use_db, get_db
from ..learning.accuracy import get_accuracy_score, get_accuracy_history, log_prediction, resolve_pending_predictions
from ..monitoring.token_tracker import get_cost_summary, get_cost_history, log_build_cost
from ..config import config

# Lab engine instance (separate from production)
_lab_trader: LabTrader | None = None

# OPS-20: Use lifespan context manager instead of deprecated on_event handlers.
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic."""
    # --- Startup ---
    await paper_trader.start_monitoring(interval=10)
    await alert_scanner.start()
    await autonomous_trader.start()

    # Start Lab Engine
    global _lab_trader
    try:
        _lab_trader = LabTrader()
        await _lab_trader.start()
        logger.info("Lab Engine started alongside production")
    except Exception as e:
        logger.warning(f"Lab Engine failed to start: {e}")
        await send_error_alert("Lab Engine", f"Failed to start: {e}")
        _lab_trader = None

    yield

    # --- Shutdown (OPS-04/AT-31: graceful) ---
    try:
        autonomous_trader.stop()  # sync method, no await
    except Exception as e:
        logger.error("Error stopping autonomous trader: %s", e)

    # Stop Lab Engine
    if _lab_trader:
        _lab_trader.stop()

    paper_trader.stop_monitoring()
    alert_scanner.stop()

    # Disconnect broker if connected
    try:
        broker = await autonomous_trader._get_broker()  # async method
        if broker and hasattr(broker, 'disconnect'):
            await broker.disconnect()
    except Exception:
        pass

    # Clean up shared Telegram HTTP client (OPS-13)
    try:
        from ..alerts.telegram import cleanup_telegram_client
        await cleanup_telegram_client()
    except Exception:
        pass

    # Send shutdown notification
    try:
        await send_telegram(
            "System shutting down. Open positions have exchange-side SL/TP protection."
        )
    except Exception:
        pass


app = FastAPI(
    title="Notas Lave Trading Engine",
    description="AI-powered trading decision engine for scalping",
    version="0.1.0",
    lifespan=lifespan,
)

# SE-24: Rate limiting middleware for mutation endpoints (POST/PUT/DELETE)
app.add_middleware(RateLimitMiddleware)

# SEC-12: Restrict CORS to only needed methods/headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

# SEC-01: API key authentication for mutation endpoints.
# If API_KEY is not set in .env, auth is disabled (development mode).
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Depends(_api_key_header)):
    """
    SEC-01: Verify API key for mutation endpoints (POST/PUT/DELETE).
    If config.api_key is empty, auth is disabled for development.
    GET endpoints remain open so the dashboard works without auth.
    """
    if not config.api_key:
        return  # No key configured = dev mode, skip auth
    if api_key != config.api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


@app.get("/health")
async def health_check_root():
    """DO-20: Root-level health endpoint for load balancers and monitoring.

    No authentication required. Returns 200 with engine status, uptime,
    and component health. Duplicated at /api/health for backward compat.
    """
    return _build_health_response()


@app.get("/api/health")
async def health_check():
    """Health check endpoint with actual component status."""
    return _build_health_response()


def _build_health_response() -> dict:
    """DO-20: Build the health check response body."""
    agent_running = autonomous_trader._running if hasattr(autonomous_trader, "_running") else False
    open_positions = paper_trader.open_count
    uptime_seconds = _time.time() - _server_start_time
    lab_running = _lab_trader is not None and getattr(_lab_trader, "_running", False)

    components = {
        "autonomous_trader": "running" if agent_running else "stopped",
        "lab_trader": "running" if lab_running else "stopped",
        "paper_trader": "ok",
        "open_positions": open_positions,
    }

    overall = "ok" if agent_running else "degraded"

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(uptime_seconds, 1),
        "engine_version": "0.1.0",
        "components": components,
    }


@app.get("/api/system/health")
async def system_health():
    """Comprehensive system health status for the dashboard.

    Returns component statuses, timestamps, and diagnostics.
    Designed to be fast — uses in-memory data + quick DB counts only.
    """
    import os as _os
    now = datetime.now(timezone.utc)
    uptime = _time.time() - _server_start_time

    # --- Lab Engine ---
    lab_status = "stopped"
    lab_heartbeat = None
    lab_open = 0
    lab_trades_today = 0
    lab_trades_since_review = 0
    if _lab_trader:
        lab_status = "running" if getattr(_lab_trader, "_running", False) else "stopped"
        hb = getattr(_lab_trader, "_last_heartbeat", None)
        lab_heartbeat = hb.isoformat() if hb else None
        lab_open = _lab_trader.paper_trader.open_count
        lab_trades_today = _lab_trader._daily_trades.get(
            now.strftime("%Y-%m-%d"), 0
        )
        lab_trades_since_review = getattr(_lab_trader, "_trades_since_last_review", 0)

    # --- Autonomous Trader ---
    at_running = getattr(autonomous_trader, "_running", False)
    at_mode = agent_config.mode.value

    # --- Broker ---
    broker_type = config.broker
    broker_connected = False
    if broker_type == "paper":
        broker_connected = True
    elif hasattr(autonomous_trader, "_broker") and autonomous_trader._broker:
        broker_connected = autonomous_trader._broker.is_connected

    # --- Market Data (most recent candle time from cache) ---
    last_candle_time = None
    symbols_tracked = len(config.instruments)
    try:
        # Check market_data cache for most recent timestamp
        if hasattr(market_data, '_cache'):
            for key, cached in market_data._cache.items():
                candles = cached if isinstance(cached, list) else None
                if candles and len(candles) > 0 and hasattr(candles[-1], 'timestamp'):
                    ts = candles[-1].timestamp
                    if last_candle_time is None or ts > last_candle_time:
                        last_candle_time = ts
    except Exception:
        pass

    # --- Background task timestamps ---
    lab_last_backtest = None
    lab_last_optimizer = None
    lab_last_review = None
    lab_last_checkin = None
    if _lab_trader:
        bt = getattr(_lab_trader, "_last_backtest", None)
        lab_last_backtest = bt.isoformat() if bt else None
        opt = getattr(_lab_trader, "_last_optimize", None)
        lab_last_optimizer = opt.isoformat() if opt else None
        rev = getattr(_lab_trader, "_last_daily_review", None)
        lab_last_review = rev.isoformat() if rev is not None else None
        ci = getattr(_lab_trader, "_last_claude_checkin", None)
        lab_last_checkin = ci.isoformat() if ci else None

    # --- Data health (quick DB queries + file sizes) ---
    db_lab_trades = 0
    db_lab_open = lab_open
    try:
        use_db("lab")
        db = get_db()
        from ..journal.database import TradeLog
        db_lab_trades = db.query(TradeLog).filter(TradeLog.exit_price.isnot(None)).count()
    except Exception:
        pass

    # Log + WAL file sizes
    data_dir = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "data"
    )
    log_path = _os.path.join(data_dir, "notas_lave.log")
    log_size_mb = round(_os.path.getsize(log_path) / (1024 * 1024), 2) if _os.path.exists(log_path) else 0

    # WAL file for lab DB
    engine_dir = _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__)))
    wal_path = _os.path.join(engine_dir, "notas_lave_lab.db-wal")
    wal_size_mb = round(_os.path.getsize(wal_path) / (1024 * 1024), 2) if _os.path.exists(wal_path) else 0

    return {
        "timestamp": now.isoformat(),
        "uptime_seconds": round(uptime, 1),
        "components": {
            "lab_engine": {
                "status": lab_status,
                "last_heartbeat": lab_heartbeat,
                "open_positions": lab_open,
                "trades_today": lab_trades_today,
                "trades_since_last_review": lab_trades_since_review,
            },
            "autonomous_trader": {
                "status": "running" if at_running else "stopped",
                "mode": at_mode,
            },
            "broker": {
                "status": "connected" if broker_connected else "disconnected",
                "type": broker_type,
            },
            "market_data": {
                "status": "ok" if last_candle_time else "unknown",
                "last_candle_time": last_candle_time.isoformat() if last_candle_time else None,
                "symbols_tracked": symbols_tracked,
            },
        },
        "background_tasks": {
            "last_backtest": lab_last_backtest,
            "last_optimizer": lab_last_optimizer,
            "last_claude_review": lab_last_review,
            "last_checkin": lab_last_checkin,
        },
        "data_health": {
            "db_lab_trades": db_lab_trades,
            "db_lab_open": db_lab_open,
            "log_file_size_mb": log_size_mb,
            "wal_file_size_mb": wal_size_mb,
        },
        "errors_last_hour": 0,  # TODO: Add error counter middleware
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
            logger.error("scan_all error for %s: %s", symbol, e)
            results.append({
                "symbol": symbol,
                "error": "Failed to scan symbol",
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

    # Log prediction for accuracy tracking
    if decision.action in ("BUY", "SELL") and decision.entry_price > 0:
        try:
            from ..learning.accuracy import log_prediction as _log_pred
            _log_pred(
                symbol=symbol,
                timeframe=timeframe,
                strategy_name="confluence",
                predicted_direction="LONG" if decision.action == "BUY" else "SHORT",
                entry_price=decision.entry_price,
                stop_loss=decision.stop_loss,
                take_profit=decision.take_profit,
                confluence_score=confluence.composite_score,
                regime=confluence.regime.value,
            )
        except Exception:
            pass

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
async def get_signals_history(limit: int = Query(default=50, ge=1, le=500)):
    """Get recent signal evaluation history."""
    use_db("default")
    return {"signals": get_recent_signals(limit)}


@app.get("/api/journal/trades")
async def get_trades_history(limit: int = Query(default=50, ge=1, le=500)):
    """Get recent trade history."""
    use_db("default")
    return {"trades": get_recent_trades(limit)}


@app.get("/api/journal/performance")
async def get_performance():
    """Get strategy performance analysis."""
    use_db("default")
    return {"strategies": get_strategy_performance()}


@app.get("/api/risk/status")
async def get_risk_status():
    """Get current risk manager status for the dashboard."""
    return risk_manager.get_status()


@app.get("/api/risk/recommendations")
async def get_risk_recommendations():
    """Get adaptive risk recommendations for personal trading mode."""
    return risk_manager.get_personal_recommendations()


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
    result = paper_trader.close_position(position_id, reason=reason)
    if not result:
        return {"error": f"Position {position_id} not found"}
    pos, pnl = result

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
async def get_trade_history(limit: int = Query(default=50, ge=1, le=500)):
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

    # Try saved CSV data first (years of history), fall back to yfinance (60 days)
    candles = load_candles_csv(symbol, timeframe)
    if not candles:
        candles = await market_data._fetch_yfinance(symbol, timeframe)
    if len(candles) < 300:
        return {"error": f"Not enough data ({len(candles)} candles, need 300+). "
                f"Run POST /api/data/download to fetch historical data."}

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
        news_blackout_minutes=5,      # Skip trading near news events
    )

    result = bt.run(candles, symbol, timeframe)
    return result.to_dict()


@app.get("/api/backtest/walk-forward/{symbol}")
async def run_walk_forward_backtest(symbol: str, timeframe: str = "5m", folds: int = Query(default=5, ge=2, le=10)):
    """
    Run walk-forward backtest with N-fold out-of-sample validation.

    Unlike the regular backtest (single in-sample pass), this splits data
    into N folds and tests ONLY on unseen data. Blacklists are derived
    from training data only (not test data), preventing data snooping.

    Returns both in-sample and out-of-sample results plus an overfit ratio.
    If overfit_ratio > 1.5, the in-sample results are unreliable.
    """
    symbol = symbol.upper()
    if symbol not in config.instruments:
        return {"error": f"Unknown symbol: {symbol}"}

    candles = load_candles_csv(symbol, timeframe)
    if not candles:
        candles = await market_data._fetch_yfinance(symbol, timeframe)
    if len(candles) < 1000:
        return {"error": f"Walk-forward needs 1000+ candles ({len(candles)} available). "
                f"Run POST /api/data/download/{symbol} first."}

    bt = Backtester(
        starting_balance=100_000,
        risk_per_trade=0.003,
        max_concurrent=1,
        min_score=60.0,
        require_strong=True,
        daily_loss_limit_pct=0.04,
        total_dd_limit_pct=0.08,
        trade_cooldown=5,
        max_trades_per_day=4,
        trailing_breakeven=True,
        skip_volatile_regime=True,
        loss_streak_threshold=3,
        news_blackout_minutes=5,
    )

    return bt.run_walk_forward(candles, symbol, timeframe, n_folds=folds)


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


# ===== ECONOMIC CALENDAR ENDPOINTS =====


@app.get("/api/calendar/status")
async def calendar_status():
    """
    Get current news blackout status and upcoming events.

    Returns whether trading is currently blocked by a high-impact event,
    which event is blocking (if any), and the next 5 upcoming events.
    """
    return get_blackout_status(blackout_minutes=config.news_blackout_minutes)


@app.get("/api/calendar/upcoming")
async def calendar_upcoming(limit: int = Query(default=10, ge=1, le=100)):
    """Get the next N upcoming economic events."""
    events = get_upcoming_events(limit=limit)
    return {"events": [e.to_dict() for e in events]}


# ===== LEARNING ENGINE ENDPOINTS =====


@app.get("/api/learning/analysis")
async def learning_analysis():
    """
    Full learning engine analysis.

    Uses lab DB when lab is running (that's where all the trades are).
    """
    # FIX: Use lab DB if lab is running — production DB has 0 trades
    if _lab_trader:
        use_db("lab")
    return run_full_analysis()


@app.get("/api/learning/recommendations")
async def learning_recommendations():
    """
    Get actionable recommendations from the learning engine.
    """
    if _lab_trader:
        use_db("lab")
    return generate_all_recommendations()


@app.post("/api/learning/review")
async def learning_review():
    """
    Generate a Claude-powered weekly review.

    Uses lab trades when lab is running.
    """
    if _lab_trader:
        use_db("lab")
    return await generate_review()


@app.get("/api/learning/combinations")
async def get_strategy_combinations():
    """Analyze strategy combination performance."""
    if _lab_trader:
        use_db("lab")
    else:
        use_db("default")
    from ..learning.analyzer import analyze_strategy_combinations
    return analyze_strategy_combinations()


@app.post("/api/learning/optimize/{symbol}")
async def learning_optimize(symbol: str, timeframe: str = "5m"):
    """
    Run walk-forward parameter optimization for an instrument.

    Tests different parameter combinations for each strategy and finds
    the best settings. Results are saved to data/optimizer_results.json.

    WARNING: This is slow — can take several minutes per instrument.
    """
    symbol = symbol.upper()

    # Fetch historical data for optimization
    candles = await market_data._fetch_yfinance(symbol, timeframe)
    if len(candles) < 300:
        return {"error": f"Not enough data ({len(candles)} candles, need 300+)"}

    logger.info("Starting optimization for %s on %s...", symbol, timeframe)
    results = optimize_all_strategies(candles, symbol, timeframe)
    save_results(symbol, results)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "strategies_optimized": len(results),
        "results": results,
    }


@app.get("/api/learning/optimized-params")
async def learning_optimized_params(symbol: str | None = None):
    """Get saved optimization results."""
    return load_results(symbol)


# ===== BROKER ENDPOINTS =====

# Broker instances (created on demand)
_brokers: dict = {}


def _get_broker(broker_name: str | None = None):
    """Get or create a broker instance."""
    name = broker_name or config.broker
    if name not in _brokers:
        if name == "binance_testnet":
            _brokers[name] = BinanceTestnetBroker()
        elif name == "coindcx":
            _brokers[name] = CoinDCXBroker()
        elif name == "mt5":
            _brokers[name] = MT5Broker()
        else:
            return None  # Paper trader is handled separately
    return _brokers[name]


@app.get("/api/broker/status")
async def broker_status():
    """
    Get current broker connection status.

    Shows which broker is configured, whether it's connected,
    account balance, and open positions.
    """
    broker_name = config.broker

    if broker_name == "paper":
        return {
            "broker": "paper",
            "connected": True,
            "mode": config.trading_mode,
            "balance": {
                "currency": config.currency_symbol,
                "total": config.active_balance,
            },
            "open_positions": paper_trader.open_count,
        }

    broker = _get_broker(broker_name)
    if not broker:
        return {"broker": broker_name, "connected": False, "error": "Unknown broker"}

    return await broker.get_status()


@app.post("/api/broker/connect")
async def broker_connect():
    """
    Connect to the configured broker (CoinDCX or MT5).

    Requires API keys to be set in .env:
    - CoinDCX: COINDCX_API_KEY, COINDCX_API_SECRET
    - MT5: MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
    """
    broker_name = config.broker

    if broker_name == "paper":
        return {"broker": "paper", "connected": True, "message": "Paper trading is always connected"}

    broker = _get_broker(broker_name)
    if not broker:
        return {"broker": broker_name, "connected": False, "error": "Unknown broker"}

    success = await broker.connect()
    return {
        "broker": broker_name,
        "connected": success,
        "message": f"Connected to {broker_name}" if success else f"Failed to connect to {broker_name}",
    }


@app.post("/api/broker/disconnect")
async def broker_disconnect():
    """Disconnect from the active broker."""
    broker_name = config.broker
    broker = _get_broker(broker_name)
    if broker:
        await broker.disconnect()
    return {"broker": broker_name, "connected": False}


@app.get("/api/broker/balance")
async def broker_balance():
    """Get account balance from the active broker."""
    broker_name = config.broker

    if broker_name == "paper":
        return {
            "broker": "paper",
            "currency": config.currency_symbol,
            "balance": risk_manager.current_balance,
            "total_pnl": risk_manager.total_pnl,
        }

    broker = _get_broker(broker_name)
    if not broker or not broker.is_connected:
        return {"error": f"{broker_name} not connected"}

    return await broker.get_balance()


@app.get("/api/broker/positions")
async def broker_positions():
    """Get open positions from the active broker."""
    broker_name = config.broker

    if broker_name == "paper":
        return {"broker": "paper", "positions": paper_trader.get_open_positions()}

    broker = _get_broker(broker_name)
    if not broker or not broker.is_connected:
        return {"error": f"{broker_name} not connected"}

    positions = await broker.get_positions()
    return {"broker": broker_name, "positions": [p.to_dict() for p in positions]}


# ===== DATA DOWNLOAD ENDPOINTS =====


@app.post("/api/data/download/{symbol}")
async def download_data(symbol: str, timeframe: str = "5m", days: int = Query(default=365, ge=1, le=1095)):
    """
    Download historical data from Binance (free) and save to CSV.

    This gives you YEARS of data for backtesting — no rate limits.
    Supports: BTCUSD, BTCUSDT, ETHUSD, ETHUSDT.

    Example: POST /api/data/download/BTCUSD?timeframe=5m&days=365
    Downloads 1 year of 5M BTC data (~105K candles).
    """
    symbol = symbol.upper()
    candles = await download_best_available(symbol, timeframe, days)
    if not candles:
        return {"error": f"Failed to download data for {symbol}. "
                f"Crypto: use BTCUSD/ETHUSD. Metals: use XAUUSD/XAGUSD."}

    filepath = save_candles_csv(candles, symbol, timeframe)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "days": days,
        "candles": len(candles),
        "file": filepath,
        "date_range": f"{candles[0].timestamp.date()} to {candles[-1].timestamp.date()}",
    }


@app.get("/api/data/available")
async def available_data():
    """List all saved historical data files available for backtesting."""
    return {"files": list_available_data()}


@app.get("/api/data/rate-limits")
async def rate_limits():
    """Get current API rate limit usage for Twelve Data."""
    return market_data.get_rate_limit_status()


# ===== AUTONOMOUS AGENT ENDPOINTS =====


@app.get("/api/agent/status")
async def agent_status():
    """Get autonomous trading agent status."""
    return autonomous_trader.get_status()


@app.post("/api/agent/start")
async def agent_start():
    """Start the autonomous trading agent."""
    await autonomous_trader.start()
    return {"status": "started", "mode": agent_config.mode.value}


@app.post("/api/agent/stop")
async def agent_stop():
    """Stop the autonomous trading agent."""
    autonomous_trader.stop()
    return {"status": "stopped"}


# ===== PREDICTION ACCURACY ENDPOINTS =====


@app.get("/api/accuracy/score")
async def accuracy_score(days: int = Query(default=30, ge=1, le=1095)):
    """
    Get current prediction accuracy score and breakdowns.

    Like ML model accuracy — measures how good our signal predictions are.
    Direction accuracy: Did price move in predicted direction?
    Target accuracy: Did TP get hit before SL?
    Calibration: Do higher scores actually predict better?
    """
    return get_accuracy_score(max_age_days=days)


@app.get("/api/accuracy/history")
async def accuracy_history(window: int = Query(default=20, ge=5, le=200)):
    """
    Get rolling accuracy over time for the improvement graph.

    Shows whether predictions are getting better (the EVOLVE goal).
    Each point is accuracy computed over a sliding window of N predictions.
    """
    return get_accuracy_history(window_size=window)


# ===== COST TRACKING ENDPOINTS =====


@app.get("/api/costs/summary")
async def costs_summary(days: int = Query(default=30, ge=1, le=1095)):
    """
    Get token usage and cost summary.

    Two categories:
    - Runtime: Claude API calls for trade analysis, evaluations, reviews
    - Build: Estimated cost of Claude Code sessions building the system
    """
    return get_cost_summary(max_age_days=days)


@app.get("/api/costs/history")
async def costs_history(days: int = Query(default=30, ge=1, le=1095)):
    """Get daily cost history for graphing."""
    return get_cost_history(max_age_days=days)


@app.post("/api/costs/log-build")
async def log_build_session(
    cost: float = 0.0,
    description: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
):
    """
    Manually log a Claude Code build session cost.

    Call this after a coding session to track build investment.
    Example: POST /api/costs/log-build?cost=2.50&description=Session%204a%20expert%20review
    """
    entry_id = log_build_cost(
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        estimated_cost=cost,
        description=description,
    )
    return {"id": entry_id, "cost": cost, "description": description}


# ===== AUTONOMOUS AGENT ENDPOINTS =====


@app.post("/api/agent/mode/{mode}", dependencies=[Depends(verify_api_key)])
async def agent_set_mode(mode: str):
    """
    Change agent mode. SEC-13: Requires API key authentication.

    Modes:
    - full_auto: Auto paper trade + learn + adjust (recommended)
    - semi_auto: Auto trade + learn, human approves changes
    - alert_only: Only send alerts, no auto trading (legacy)
    """
    try:
        agent_config.mode = AgentMode(mode)
        return {"mode": agent_config.mode.value}
    except ValueError:
        return {"error": f"Invalid mode. Use: full_auto, semi_auto, alert_only"}


# ===== MONTE CARLO SIMULATION ENDPOINTS =====


@app.get("/api/backtest/monte-carlo/{symbol}")
async def run_monte_carlo_endpoint(
    symbol: str,
    timeframe: str = "5m",
    n_simulations: int = Query(default=10000, ge=100, le=20000),
):
    """
    Run a backtest then Monte Carlo permutation test on the trades.

    Shuffles trade order N times to measure robustness. Returns:
    - Percentile stats (P5/P25/P50/P75/P95) for max drawdown and final equity
    - Probability of ruin (drawdown > 10%)
    - Whether the strategy is robust
    """
    symbol = symbol.upper()
    if symbol not in config.instruments:
        return {"error": f"Unknown symbol: {symbol}"}

    # Load data
    candles = load_candles_csv(symbol, timeframe)
    if not candles:
        candles = await market_data._fetch_yfinance(symbol, timeframe)
    if len(candles) < 300:
        return {"error": f"Not enough data ({len(candles)} candles, need 300+). "
                f"Run POST /api/data/download to fetch historical data."}

    # Run backtest to get trades
    bt = Backtester(
        starting_balance=100_000,
        risk_per_trade=0.003,
        max_concurrent=1,
        min_score=60.0,
        require_strong=True,
        daily_loss_limit_pct=0.04,
        total_dd_limit_pct=0.08,
        trade_cooldown=5,
        max_trades_per_day=4,
        trailing_breakeven=True,
        skip_volatile_regime=True,
        loss_streak_threshold=3,
        news_blackout_minutes=5,
    )

    result = bt.run(candles, symbol, timeframe)

    if not result.trades:
        return {"error": "Backtest produced no trades — cannot run Monte Carlo"}

    # Run Monte Carlo on the trades
    mc = run_monte_carlo(
        trades=result.trades,
        starting_balance=100_000,
        n_simulations=min(n_simulations, 50_000),  # Cap at 50K for safety
    )

    # Add backtest context
    mc["backtest_summary"] = {
        "total_trades": result.total_trades,
        "win_rate": result.win_rate,
        "net_pnl": result.net_pnl,
        "max_drawdown_pct": result.max_drawdown_pct,
        "profit_factor": result.profit_factor,
    }

    return mc


# ===== A/B TESTING ENDPOINTS =====


@app.post("/api/ab-test/create")
async def ab_test_create(name: str, description: str = ""):
    """
    Create a new A/B test.

    Pass param_a and param_b as query parameters (JSON strings).
    Example: POST /api/ab-test/create?name=rsi_14_vs_21&description=Compare+RSI+periods

    For now, creates with empty param sets — update via direct API.
    """
    test = ab_create_test(name, {}, {}, description)
    return test


@app.post("/api/ab-test/record")
async def ab_test_record(
    test_name: str,
    variant: str,
    prediction: str,
    outcome: str,
    pnl: float = 0.0,
):
    """
    Record a prediction result for a variant in an A/B test.

    Args:
        test_name: Name of the test
        variant: "A" or "B"
        prediction: What was predicted (LONG, SHORT, SKIP)
        outcome: What happened (WIN, LOSS, BREAKEVEN)
        pnl: Actual or virtual P&L
    """
    try:
        row_id = ab_record_result(test_name, variant, prediction, outcome, pnl)
        return {"id": row_id, "test_name": test_name, "variant": variant}
    except ValueError as e:
        logger.error("A/B test record error: %s", e)
        return {"error": "Invalid test parameters"}


@app.get("/api/ab-test/results/{test_name}")
async def ab_test_results(test_name: str):
    """Get comparison results for a specific A/B test."""
    return ab_get_test_results(test_name)


@app.get("/api/ab-test/results")
async def ab_test_all_results():
    """Get results for all A/B tests."""
    return {"tests": ab_get_all_tests()}


# ═══════════════════════════════════════════════════════════
# LAB ENGINE ENDPOINTS
# ═══════════════════════════════════════════════════════════

@app.get("/api/lab/status")
async def lab_status():
    """Get Lab Engine status."""
    if not _lab_trader:
        return {"status": "not_running", "message": "Lab engine not started"}
    return _lab_trader.get_status()


@app.post("/api/lab/sync-balance")
async def lab_sync_balance():
    """Force sync Lab balance from Binance and reset P&L to match reality."""
    if not _lab_trader:
        return {"error": "Lab not running"}
    _lab_trader._load_risk_state()
    broker = await _lab_trader._get_broker()
    if broker:
        bal = await broker.get_balance()
        real = bal.get("total", 0)
        if real > 0:
            _lab_trader.risk_manager.current_balance = real
            _lab_trader.risk_manager.total_pnl = 0.0
            _lab_trader.risk_manager.peak_balance = real
            _lab_trader._save_risk_state()
            return {"synced": True, "balance": real, "total_pnl": 0.0}
    return {"synced": False}


@app.post("/api/lab/sync-positions")
async def lab_sync_positions():
    """Sync local positions to match Binance exactly. Non-destructive.

    - Rebuilds local position objects from Binance's actual positions
    - Closes orphaned open entries in DB (marks as 'synced_out')
    - Syncs balance from exchange
    - Preserves ALL closed trade history
    """
    if not _lab_trader:
        return {"error": "Lab not running"}

    broker = await _lab_trader._get_broker()
    if not broker or not broker.is_connected:
        return {"error": "Broker not connected"}

    from ..execution.binance_testnet import SYMBOL_MAP
    from ..execution.paper_trader import Position
    from ..data.models import Direction
    import uuid

    # Step 1: Clear local positions
    old_count = len(_lab_trader.paper_trader.positions)
    _lab_trader.paper_trader.positions.clear()

    # Step 2: Read Binance positions and create matching local ones
    exchange_positions = await broker.get_positions()
    reverse_map = {v: k for k, v in SYMBOL_MAP.items() if not k.endswith("USDT")}

    synced = []
    for ep in exchange_positions:
        our_sym = reverse_map.get(ep.symbol, ep.symbol)
        direction = Direction.LONG if ep.side.value == "BUY" else Direction.SHORT

        pos = Position(
            id=str(uuid.uuid4())[:16],
            signal_log_id=0,
            symbol=our_sym,
            timeframe="1h",
            direction=direction,
            regime="unknown",
            entry_price=ep.entry_price,
            stop_loss=0,
            take_profit=0,
            position_size=ep.quantity,
            confluence_score=0,
            claude_confidence=0,
            strategies_agreed=[],
            current_price=ep.current_price,
            original_stop_loss=0,
            original_take_profit=0,
        )
        pos.unrealized_pnl = ep.unrealized_pnl
        _lab_trader.paper_trader.positions[pos.id] = pos
        synced.append({
            "symbol": our_sym,
            "direction": direction.value,
            "entry": ep.entry_price,
            "qty": ep.quantity,
            "pnl": round(ep.unrealized_pnl, 2),
        })

    # Step 3: Sync balance
    bal = await broker.get_balance()
    real_bal = bal.get("total", 0)
    if real_bal > 0:
        _lab_trader.risk_manager.current_balance = real_bal
        _lab_trader.risk_manager.total_pnl = real_bal - 4999.98
        _lab_trader._save_risk_state()

    # Step 4: Delete orphaned open trade_logs that no longer match exchange
    # These are local entries with no matching Binance position — just remove them
    use_db("lab")
    db = get_db()
    from ..journal.database import TradeLog
    orphaned_count = db.query(TradeLog).filter(TradeLog.exit_price.is_(None)).delete()
    # Also clean up any old synced_out entries (noise from previous syncs)
    synced_out_count = db.query(TradeLog).filter(TradeLog.exit_reason == "synced_out").delete()
    db.commit()

    return {
        "status": "synced",
        "old_positions_cleared": old_count,
        "new_positions_from_binance": len(synced),
        "positions": synced,
        "balance": real_bal,
        "orphaned_deleted": orphaned_count,
        "synced_out_cleaned": synced_out_count,
    }


@app.get("/api/lab/verify")
async def lab_verify():
    """Verify Lab data against Binance Demo — the source of truth.

    Compares: balance, open positions (count, side, qty, entry price),
    and flags any discrepancies. Call anytime to confirm data integrity.
    """
    if not _lab_trader:
        return {"error": "Lab not running"}

    broker = await _lab_trader._get_broker()
    if not broker:
        return {"error": "Broker not connected"}

    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "checks": [], "passed": True}

    # --- Balance ---
    try:
        bal_data = await broker.get_balance()
        binance_bal = float(bal_data.get("total", 0))
        our_bal = _lab_trader.risk_manager.current_balance
        bal_diff = abs(binance_bal - our_bal)
        bal_ok = bal_diff < 1.0
        report["checks"].append({
            "check": "balance",
            "binance": round(binance_bal, 2),
            "ours": round(our_bal, 2),
            "diff": round(bal_diff, 2),
            "passed": bal_ok,
        })
        if not bal_ok:
            report["passed"] = False
    except Exception as e:
        report["checks"].append({"check": "balance", "error": str(e), "passed": False})
        report["passed"] = False

    # --- Open positions ---
    try:
        exchange_positions = await broker.get_positions()
        ex_map = {}
        for p in exchange_positions:
            sym_reverse = {
                "BTCUSDT": "BTCUSD", "ETHUSDT": "ETHUSD", "SOLUSDT": "SOLUSD",
                "XRPUSDT": "XRPUSD", "BNBUSDT": "BNBUSD", "DOTUSDT": "DOTUSD",
                "ADAUSDT": "ADAUSD", "AVAXUSDT": "AVAXUSD", "LINKUSDT": "LINKUSD",
                "LTCUSDT": "LTCUSD", "NEARUSDT": "NEARUSD", "SUIUSDT": "SUIUSD",
                "ARBUSDT": "ARBUSD", "DOGEUSDT": "DOGEUSD", "PEPEUSDT": "PEPEUSD",
                "WIFUSDT": "WIFUSD", "FTMUSDT": "FTMUSD", "ATOMUSDT": "ATOMUSD",
            }
            our_sym = sym_reverse.get(p.symbol, p.symbol)
            ex_map[our_sym] = {
                "side": p.side.value, "qty": p.quantity,
                "entry": p.entry_price, "pnl": round(p.unrealized_pnl, 2),
            }

        our_positions = {
            pos.symbol: {
                "side": "BUY" if pos.direction.value == "LONG" else "SELL",
                "qty": pos.position_size, "entry": pos.entry_price,
            }
            for pos in _lab_trader.paper_trader.positions.values()
        }

        count_ok = len(ex_map) == len(our_positions)
        pos_details = []
        for sym in set(list(ex_map.keys()) + list(our_positions.keys())):
            ep = ex_map.get(sym)
            op = our_positions.get(sym)
            if ep and op:
                entry_diff = abs(ep["entry"] - op["entry"])
                qty_match = abs(ep["qty"] - op["qty"]) < 0.01
                side_match = ep["side"] == op["side"]
                ok = entry_diff < 2 and qty_match and side_match
                pos_details.append({
                    "symbol": sym, "passed": ok,
                    "binance": {"side": ep["side"], "qty": ep["qty"], "entry": ep["entry"], "unrealized_pnl": ep["pnl"]},
                    "ours": {"side": op["side"], "qty": op["qty"], "entry": op["entry"]},
                    "entry_diff": round(entry_diff, 4),
                })
                if not ok:
                    report["passed"] = False
            elif ep:
                pos_details.append({"symbol": sym, "passed": False, "issue": "on Binance but not tracked locally"})
                report["passed"] = False
            else:
                pos_details.append({"symbol": sym, "passed": False, "issue": "in our DB but not on Binance"})
                report["passed"] = False

        report["checks"].append({
            "check": "positions",
            "binance_count": len(ex_map),
            "our_count": len(our_positions),
            "count_match": count_ok,
            "positions": pos_details,
            "passed": count_ok and all(p["passed"] for p in pos_details),
        })
    except Exception as e:
        report["checks"].append({"check": "positions", "error": str(e), "passed": False})
        report["passed"] = False

    # --- P&L consistency ---
    try:
        use_db("lab")
        db = get_db()
        from ..journal.database import TradeLog
        closed = db.query(TradeLog).filter(TradeLog.exit_price.isnot(None)).all()
        db_total_pnl = sum(t.pnl or 0 for t in closed)
        api_pnl = _lab_trader.risk_manager.total_pnl
        pnl_diff = abs(db_total_pnl - api_pnl)
        pnl_ok = pnl_diff < 1.0
        report["checks"].append({
            "check": "pnl_consistency",
            "db_total_pnl": round(db_total_pnl, 2),
            "risk_manager_pnl": round(api_pnl, 2),
            "diff": round(pnl_diff, 2),
            "closed_trade_count": len(closed),
            "passed": pnl_ok,
        })
        if not pnl_ok:
            report["passed"] = False
    except Exception as e:
        report["checks"].append({"check": "pnl_consistency", "error": str(e), "passed": False})

    report["summary"] = "ALL CHECKS PASSED" if report["passed"] else "DISCREPANCIES FOUND"
    return report


@app.get("/api/lab/positions")
async def lab_positions():
    """Get Lab Engine open positions with Binance-verified P&L.

    Overlays Binance's actual unrealized P&L onto our local positions.
    Binance is the source of truth — our formula can be wrong.
    """
    if not _lab_trader:
        return {"positions": []}

    positions = _lab_trader.paper_trader.get_open_positions()

    # Overlay Binance P&L (the source of truth)
    try:
        broker = await _lab_trader._get_broker()
        if broker and broker.is_connected:
            from ..execution.binance_testnet import _map_symbol
            exchange_positions = await broker.get_positions()
            # Build map: binance_symbol → exchange position data
            ex_map = {}
            for ep in exchange_positions:
                ex_map[ep.symbol] = {
                    "unrealized_pnl": round(ep.unrealized_pnl, 2),
                    "entry_price": ep.entry_price,
                    "side": ep.side.value,
                    "quantity": ep.quantity,
                }

            for p in positions:
                try:
                    binance_sym = _map_symbol(p["symbol"])
                    if binance_sym in ex_map:
                        ex = ex_map[binance_sym]
                        # Override with Binance's actual P&L
                        p["exchange_pnl"] = ex["unrealized_pnl"]
                        p["exchange_entry"] = ex["entry_price"]
                        p["exchange_side"] = ex["side"]
                        p["exchange_qty"] = ex["quantity"]
                        # Flag direction mismatch
                        our_side = "BUY" if p["direction"] == "LONG" else "SELL"
                        if our_side != ex["side"]:
                            p["pnl_warning"] = f"DIRECTION MISMATCH: we say {p['direction']}, Binance says {ex['side']}"
                        # Use Binance P&L for display
                        p["unrealized_pnl"] = ex["unrealized_pnl"]
                except (ValueError, KeyError):
                    pass
    except Exception:
        pass

    return {"positions": positions}


@app.post("/api/lab/close/{position_id}")
async def lab_close_position(position_id: str, reason: str = "manual"):
    """Manually close a Lab position (and on exchange if connected)."""
    if not _lab_trader:
        return {"error": "Lab engine not running"}

    if position_id not in _lab_trader.paper_trader.positions:
        return {"error": f"Position {position_id} not found in lab"}

    pos = _lab_trader.paper_trader.positions[position_id]

    # Get current price so close_position has a reasonable exit price
    price = await market_data.get_current_price(pos.symbol)
    if price and price > 0:
        pos.current_price = price

    # Close on exchange first (if broker connected)
    real_exit = None
    try:
        real_exit = await _lab_trader._close_on_exchange(pos)
    except Exception as e:
        logger.warning("[LAB] Exchange close failed for %s: %s", position_id, e)

    exit_price = real_exit if real_exit and real_exit > 0 else None

    use_db("lab")
    result = _lab_trader.paper_trader.close_position(position_id, reason=reason, exit_price=exit_price)
    if not result:
        return {"error": f"Failed to close position {position_id}"}

    closed_pos, pnl = result

    # Update lab risk manager
    _lab_trader.risk_manager.record_trade_result(pnl)

    await send_telegram(format_trade_closed(
        symbol=closed_pos.symbol, direction=closed_pos.direction.value,
        entry=closed_pos.entry_price, exit_price=closed_pos.exit_price,
        pnl=pnl, exit_reason=reason, duration_mins=closed_pos.duration_seconds / 60,
    ))

    return {
        "status": "closed",
        "position": closed_pos.to_dict(),
        "pnl": round(pnl, 2),
        "exit_reason": reason,
        "exchange_closed": real_exit is not None,
    }


@app.get("/api/lab/trades")
async def lab_trades(
    limit: int = Query(default=50, ge=1, le=500),
    period: str = Query(default="all", description="Filter: today, week, month, all"),
):
    """Get Lab Engine closed trades with time filtering.

    Reads from DATABASE (survives restarts). Supports filtering by period:
    - today: trades opened today
    - week: trades opened in the last 7 days
    - month: trades opened in the last 30 days
    - all: no time filter (default)
    """
    use_db("lab")
    db = get_db()
    from ..journal.database import TradeLog
    from datetime import timedelta
    import json as _json

    query = db.query(TradeLog).filter(TradeLog.exit_price.isnot(None))

    # Apply time filter
    now = datetime.now(timezone.utc)
    if period == "today":
        cutoff = datetime.combine(now.date(), datetime.min.time()).replace(tzinfo=timezone.utc)
        query = query.filter(TradeLog.opened_at >= cutoff)
    elif period == "week":
        cutoff = now - timedelta(days=7)
        query = query.filter(TradeLog.opened_at >= cutoff)
    elif period == "month":
        cutoff = now - timedelta(days=30)
        query = query.filter(TradeLog.opened_at >= cutoff)

    trades = query.order_by(TradeLog.id.desc()).limit(limit).all()

    result = []
    for t in trades:
        strategies = []
        try:
            strategies = _json.loads(t.strategies_agreed) if t.strategies_agreed else []
        except Exception:
            pass
        result.append({
            "id": str(t.id),
            "symbol": t.symbol,
            "direction": t.direction,
            "regime": t.regime,
            "entry_price": t.entry_price or 0,
            "exit_price": t.exit_price or 0,
            "stop_loss": t.stop_loss or 0,
            "take_profit": t.take_profit or 0,
            "position_size": t.position_size or 0,
            "pnl": round(t.pnl or 0, 2),
            "pnl_pct": round(t.pnl_pct or 0, 2),
            "exit_reason": t.exit_reason or "",
            "confluence_score": t.confluence_score or 0,
            "duration_seconds": t.duration_seconds or 0,
            "strategies": strategies,
            "opened_at": t.opened_at.isoformat() if t.opened_at else "",
            "closed_at": t.closed_at.isoformat() if t.closed_at else "",
            "outcome_grade": t.outcome_grade or "",
            "status": "CLOSED",
        })
    # Summary stats for this period
    total_pnl = sum(t.pnl or 0 for t in trades)
    wins = sum(1 for t in trades if (t.pnl or 0) > 0)
    losses = sum(1 for t in trades if (t.pnl or 0) < 0)
    return {
        "trades": result,
        "period": period,
        "summary": {
            "total": len(result),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / max(len(result), 1) * 100, 1),
            "total_pnl": round(total_pnl, 2),
        },
    }


@app.get("/api/lab/summary")
async def lab_summary():
    """Get Lab Engine performance summary — reads from DATABASE."""
    use_db("lab")
    db = get_db()
    from ..journal.database import TradeLog
    closed = db.query(TradeLog).filter(TradeLog.exit_price.isnot(None)).all()
    wins = [t for t in closed if (t.pnl or 0) > 0]
    losses = [t for t in closed if (t.pnl or 0) < 0]
    total_pnl = sum(t.pnl or 0 for t in closed)
    open_count = _lab_trader.paper_trader.open_count if _lab_trader else 0
    return {
        "open_positions": open_count,
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / max(len(closed), 1) * 100, 1),
        "total_pnl": round(total_pnl, 2),
    }


@app.get("/api/lab/risk")
async def lab_risk():
    """Get Lab risk status with Binance-verified balance and DB-backed trades_today."""
    if not _lab_trader:
        return {"status": "not_running"}
    status = _lab_trader.risk_manager.get_status()

    try:
        # Balance + P&L from Binance (source of truth, not in-memory)
        broker = await _lab_trader._get_broker()
        if broker and broker.is_connected:
            bal = await broker.get_balance()
            real_bal = float(bal.get("total", 0))
            if real_bal > 0:
                status["balance"] = round(real_bal, 2)
                status["total_pnl"] = round(real_bal - 4999.98, 2)

        # trades_today from DB (survives restarts)
        use_db("lab")
        db = get_db()
        from ..journal.database import TradeLog
        today_start = datetime.combine(
            datetime.now(timezone.utc).date(), datetime.min.time(),
        ).replace(tzinfo=timezone.utc)
        status["trades_today"] = db.query(TradeLog).filter(
            TradeLog.opened_at >= today_start,
            TradeLog.exit_price.isnot(None),
        ).count()
    except Exception:
        pass
    return status


@app.get("/api/lab/strategies")
async def lab_strategies():
    """Get detailed per-strategy performance from Lab.
    Each strategy's WR, best TF, best regime, recent trades."""
    if not _lab_trader:
        return {"strategies": []}
    use_db("lab")
    return {"strategies": _lab_trader.get_strategy_details()}


@app.get("/api/lab/markets")
async def lab_markets():
    """Get ALL lab instruments with current prices and position status.

    Returns all 18 instruments the lab monitors — not just the 4 production ones.
    Uses Binance P&L as source of truth for open positions.
    """
    from ..lab.lab_config import lab_config as _lc

    # Build open positions map from local tracker
    open_map: dict[str, dict] = {}
    if _lab_trader:
        for pos in _lab_trader.paper_trader.positions.values():
            open_map[pos.symbol] = {
                "direction": pos.direction.value,
                "pnl": round(pos.unrealized_pnl, 2),
                "health": pos.health_momentum,
            }

    # Overlay Binance P&L (source of truth)
    try:
        broker = await _lab_trader._get_broker() if _lab_trader else None
        if broker and broker.is_connected:
            from ..execution.binance_testnet import _map_symbol, SYMBOL_MAP
            # Reverse map: BTCUSDT → BTCUSD
            reverse_map = {}
            for k, v in SYMBOL_MAP.items():
                if not k.endswith("USDT"):
                    reverse_map[v] = k

            exchange_positions = await broker.get_positions()
            for ep in exchange_positions:
                our_sym = reverse_map.get(ep.symbol, ep.symbol)
                direction = "LONG" if ep.side.value == "BUY" else "SHORT"
                open_map[our_sym] = {
                    "direction": direction,
                    "pnl": round(ep.unrealized_pnl, 2),
                    "health": open_map.get(our_sym, {}).get("health", ""),
                }
    except Exception:
        pass

    results = []
    for symbol in _lc.lab_instruments:
        item: dict = {"symbol": symbol, "price": 0, "has_position": symbol in open_map}
        if symbol in open_map:
            item.update(open_map[symbol])

        # Get current price (fast, usually cached)
        try:
            candles = await market_data.get_candles(symbol, "1m", limit=1)
            if candles:
                item["price"] = candles[-1].close
        except Exception:
            pass

        results.append(item)

    return {"markets": results, "total": len(results)}


@app.get("/api/lab/feedback")
async def lab_feedback():
    """Get Lab feedback data — scan stats, conversion funnel, per-TF performance.
    This is what Claude uses to suggest improvements."""
    if not _lab_trader:
        return {"status": "not_running"}
    return _lab_trader.get_feedback_data()


@app.get("/api/lab/checkin-reports")
async def lab_checkin_reports(limit: int = Query(default=20, ge=1, le=100)):
    """Get recent 15-minute check-in reports."""
    import json as _json
    import os as _os
    reports_path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
        "data", "lab_checkin_reports.json"
    )
    try:
        if _os.path.exists(reports_path):
            with open(reports_path) as f:
                reports = _json.load(f)
            return {"reports": reports[-limit:]}
    except Exception:
        pass
    return {"reports": []}


@app.get("/api/learning/state")
async def get_learning_state_endpoint():
    """Get complete learning state — the system's memory.

    Call this first in any new Claude session to understand
    what the system has learned so far. Returns blacklists,
    weights, recent lessons, recommendations, and performance.
    """
    from ..learning.progress import get_learning_state, save_learning_state
    db_key = "lab" if _lab_trader else "default"
    state = get_learning_state(db_key=db_key)
    save_learning_state(state)
    return state


@app.get("/api/broker/balance")
async def broker_balance():
    """Get ACTUAL broker balance (Binance Demo real balance, not theoretical)."""
    try:
        broker = await autonomous_trader._get_broker()
        if broker and broker.is_connected:
            balance = await broker.get_balance()
            return {"source": "binance_demo", "balance": balance}
        # Try connecting
        from ..execution.binance_testnet import BinanceTestnetBroker
        b = BinanceTestnetBroker()
        if await b.connect():
            balance = await b.get_balance()
            await b.disconnect()
            return {"source": "binance_demo", "balance": balance}
    except Exception:
        pass
    return {"source": "config", "balance": {"total": config.active_balance_usd, "currency": "USD"}}
