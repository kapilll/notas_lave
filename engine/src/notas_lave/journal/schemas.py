"""
Pydantic schemas for all JSON data files in the Notas Lave trading system.

WHY THIS EXISTS:
JSON files have no built-in schema validation. Fields can drift, go missing,
or have wrong types — especially when multiple modules read/write the same file.
These Pydantic models enforce a contract on every read and write.

COVERED FILES:
1. engine/data/lab_risk_state.json — lab risk manager state (balance, P&L, peak)
2. engine/data/lab_checkin_reports.json — 15-min check-in reports (rolling list)
3. engine/data/optimizer_results.json — walk-forward optimizer findings
4. engine/data/learned_blacklists.json — dynamic strategy blacklists per instrument
5. engine/data/learned_state.json — confluence regime weights (persisted)
6. engine/data/system_state.json — learning state snapshot (from progress.py)
7. engine/data/adjustment_state.json — recommendation adjustment cooldown tracker
8. engine/data/rate_limit_state.json — Twelve Data API rate limit counter

USAGE:
    from engine.src.journal.schemas import safe_load_json, safe_save_json, LabRiskState

    # Load with validation (returns default on error, never crashes)
    state = safe_load_json("engine/data/lab_risk_state.json", LabRiskState)

    # Save with validation
    state.current_balance = 5100.0
    safe_save_json("engine/data/lab_risk_state.json", state)
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 1. LAB RISK STATE — engine/data/lab_risk_state.json
#    Written by: lab_trader.py _save_risk_state()
#    Read by:    lab_trader.py _load_risk_state()
# ═══════════════════════════════════════════════════════════════════

class LabRiskState(BaseModel):
    """Schema for lab_risk_state.json.

    Tracks the lab engine's balance and P&L across restarts.
    This is the MOST critical JSON file — it directly affects
    position sizing and drawdown calculations.

    Fields match what _save_risk_state() writes:
        current_balance: float  — current lab account balance
        total_pnl: float        — cumulative profit/loss
        peak_balance: float     — highest balance seen (for drawdown calc)
        updated_at: str         — ISO timestamp of last save
    """
    current_balance: float = 5000.0
    total_pnl: float = 0.0
    peak_balance: float = 5000.0
    updated_at: str = ""


# ═══════════════════════════════════════════════════════════════════
# 2. LAB CHECK-IN REPORTS — engine/data/lab_checkin_reports.json
#    Written by: lab_trader.py _claude_checkin()
#    Read by:    learning/progress.py get_learning_state()
# ═══════════════════════════════════════════════════════════════════

class CheckinScanStats(BaseModel):
    """Scan statistics within a single check-in report."""
    total_scans: int = 0
    signal_rate: float = 0.0
    trade_rate: float = 0.0
    top_rejection_reason: str = "none"


class CheckinTimeframeStats(BaseModel):
    """Per-timeframe breakdown within a check-in report."""
    scans: int = 0
    signals: int = 0
    trades: int = 0
    wins: int = 0
    losses: int = 0


class CheckinRecentTrades(BaseModel):
    """Recent trade summary within a check-in report."""
    wins: int = 0
    losses: int = 0
    wr: float = 0.0


class CheckinReport(BaseModel):
    """Schema for a single 15-min check-in report entry.

    Fields match what _claude_checkin() writes in lab_trader.py:
        timestamp: str                        — ISO timestamp
        scan_stats: CheckinScanStats          — aggregate scan metrics
        per_timeframe: dict[str, ...]         — breakdown by timeframe (15m, 1h, 4h)
        top_strategies_firing: dict[str, int] — strategy name -> signal count
        recent_10_trades: CheckinRecentTrades — last 10 trade W/L/WR
        balance: float                        — current balance
        open_positions: int                   — number of open positions
        daily_trades: int                     — trades taken today
    """
    timestamp: str
    scan_stats: CheckinScanStats = Field(default_factory=CheckinScanStats)
    per_timeframe: dict[str, CheckinTimeframeStats] = Field(default_factory=dict)
    top_strategies_firing: dict[str, int] = Field(default_factory=dict)
    recent_10_trades: CheckinRecentTrades = Field(default_factory=CheckinRecentTrades)
    balance: float = 0.0
    open_positions: int = 0
    daily_trades: int = 0


class CheckinReportList(BaseModel):
    """Wrapper for the full lab_checkin_reports.json file (a JSON array)."""
    reports: list[CheckinReport] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# 3. OPTIMIZER RESULTS — engine/data/optimizer_results.json
#    Written by: learning/optimizer.py save_results()
#    Read by:    learning/optimizer.py load_results(), get_optimal_params()
#               learning/progress.py get_learning_state()
# ═══════════════════════════════════════════════════════════════════

class OptimizerStrategyResult(BaseModel):
    """A single strategy's optimization result within one symbol.

    Fields match OptimizationResult.to_dict() in optimizer.py.
    """
    strategy: str = ""
    symbol: str = ""
    best_params: dict[str, Any] = Field(default_factory=dict)
    best_profit_factor: float = 0.0
    best_win_rate: float = 0.0
    best_net_pnl: float = 0.0
    total_combos_tested: int = 0
    default_profit_factor: float = 0.0
    improvement_pct: float = 0.0


class OptimizerSymbolResults(BaseModel):
    """Results for one symbol in optimizer_results.json."""
    results: list[OptimizerStrategyResult] = Field(default_factory=list)
    optimized_at: str = ""


class OptimizerResults(BaseModel):
    """Schema for optimizer_results.json — keyed by symbol.

    Structure: {symbol: {results: [...], optimized_at: str}}
    """
    data: dict[str, OptimizerSymbolResults] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
# 4. LEARNED BLACKLISTS — engine/data/learned_blacklists.json
#    Written by: backtester/engine.py _save_blacklist_state()
#    Read by:    learning/progress.py get_learning_state()
# ═══════════════════════════════════════════════════════════════════

class LearnedBlacklists(BaseModel):
    """Schema for learned_blacklists.json.

    Structure: {symbol: [strategy_names]}
    Maps each instrument to the strategies that have been blacklisted
    on it due to poor performance.
    """
    data: dict[str, list[str]] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
# 5. LEARNED STATE (REGIME WEIGHTS) — engine/data/learned_state.json
#    Written by: confluence/scorer.py _save_learned_state()
#    Read by:    confluence/scorer.py _load_learned_state()
# ═══════════════════════════════════════════════════════════════════

class LearnedState(BaseModel):
    """Schema for learned_state.json.

    Persists dynamically adjusted confluence regime weights so they
    survive server restarts. Without this, every restart resets the
    system to default weights — losing everything it learned.

    Structure:
        regime_weights: {regime_name: {category: weight}}
        updated_at: str — ISO timestamp
    """
    regime_weights: dict[str, dict[str, float]] = Field(default_factory=dict)
    updated_at: str = ""


# ═══════════════════════════════════════════════════════════════════
# 6. SYSTEM STATE — engine/data/system_state.json
#    Written by: learning/progress.py save_learning_state()
#    Read by:    learning/progress.py (cross-session persistence)
# ═══════════════════════════════════════════════════════════════════

class SystemState(BaseModel):
    """Schema for system_state.json.

    A flexible learning state snapshot saved after trade-count reviews.
    Fields vary depending on what triggered the save, so this uses
    a loose schema that captures the known fields with defaults.
    """
    trigger: str = ""
    trades_since_last_review: int = 0
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    balance: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# 7. ADJUSTMENT STATE — engine/data/adjustment_state.json
#    Written by: learning/recommendations.py _save_adjustment_state()
#    Read by:    learning/recommendations.py _load_adjustment_state()
# ═══════════════════════════════════════════════════════════════════

class AdjustmentState(BaseModel):
    """Schema for adjustment_state.json.

    Tracks when the last weight/blacklist adjustment was applied
    to prevent daily churn (ML-20/TP-07 cooldown mechanism).
    """
    last_adjustment_date: str | None = None
    trades_at_last_adjustment: int = 0
    win_rate_at_adjustment: float = 0.0
    profit_factor_at_adjustment: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# 8. RATE LIMIT STATE — engine/data/rate_limit_state.json
#    Written by: data/market_data.py _persist_rate_limit()
#    Read by:    data/market_data.py _load_rate_limit()
# ═══════════════════════════════════════════════════════════════════

class RateLimitState(BaseModel):
    """Schema for rate_limit_state.json.

    Persists the Twelve Data API daily call counter so restarts
    don't reset it and accidentally exceed the API quota.
    """
    daily_calls: int = 0
    date: str = ""


# ═══════════════════════════════════════════════════════════════════
# VALIDATION HELPERS — safe load/save that never crash
# ═══════════════════════════════════════════════════════════════════

def validate_json_file(
    path: str,
    schema_class: type[BaseModel],
) -> tuple[bool, str]:
    """Validate a JSON file against a Pydantic schema.

    Returns (is_valid, error_message).
    Does NOT modify the file — read-only check.

    Args:
        path: Absolute path to the JSON file.
        schema_class: The Pydantic model class to validate against.

    Returns:
        (True, "") if valid, (False, "error description") if not.
    """
    try:
        if not os.path.exists(path):
            return False, f"File not found: {path}"

        with open(path) as f:
            raw = json.load(f)

        # Some schemas wrap flat dicts (LearnedBlacklists, OptimizerResults)
        # where the JSON is the dict itself, not nested under a key.
        # For list-based files (checkin reports), we need special handling.
        if schema_class is CheckinReportList:
            if not isinstance(raw, list):
                return False, f"Expected JSON array, got {type(raw).__name__}"
            CheckinReportList(reports=raw)
        elif schema_class in (LearnedBlacklists, OptimizerResults):
            # These schemas wrap a top-level dict under a 'data' key
            if schema_class is LearnedBlacklists:
                LearnedBlacklists(data=raw)
            else:
                OptimizerResults(data=raw)
        else:
            schema_class.model_validate(raw)

        return True, ""

    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except Exception as e:
        return False, f"Validation error: {e}"


def safe_load_json(
    path: str,
    schema_class: type[BaseModel],
    default: BaseModel | None = None,
) -> BaseModel:
    """Load and validate a JSON file. Returns validated model or default on failure.

    NEVER crashes — returns the default (or a fresh instance) on any error.
    Logs validation errors as warnings for debugging.

    Args:
        path: Absolute path to the JSON file.
        schema_class: The Pydantic model class to validate against.
        default: Fallback value if loading fails. If None, creates a new instance.

    Returns:
        A validated Pydantic model instance.
    """
    fallback = default if default is not None else schema_class()

    try:
        if not os.path.exists(path):
            logger.debug("JSON file not found (using defaults): %s", path)
            return fallback

        with open(path) as f:
            raw = json.load(f)

        # Handle list-based files (checkin reports)
        if schema_class is CheckinReportList:
            if isinstance(raw, list):
                return CheckinReportList(reports=raw)
            logger.warning("Expected JSON array in %s, got %s", path, type(raw).__name__)
            return fallback

        # Handle wrapper schemas where JSON is a flat dict
        if schema_class is LearnedBlacklists:
            if isinstance(raw, dict):
                return LearnedBlacklists(data=raw)
            return fallback

        if schema_class is OptimizerResults:
            if isinstance(raw, dict):
                return OptimizerResults(data=raw)
            return fallback

        # Standard case: JSON maps directly to the model
        return schema_class.model_validate(raw)

    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in %s: %s", path, e)
        return fallback
    except Exception as e:
        logger.warning("Failed to load/validate %s: %s", path, e)
        return fallback


def safe_save_json(path: str, data: BaseModel) -> bool:
    """Save a Pydantic model to JSON with validation.

    Serializes the model and writes to disk atomically-ish
    (creates parent dirs if needed). Returns True on success.

    Args:
        path: Absolute path to write the JSON file.
        data: A Pydantic model instance to serialize.

    Returns:
        True if saved successfully, False on error.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)

        # Handle wrapper schemas — unwrap the 'data'/'reports' key
        if isinstance(data, CheckinReportList):
            serialized = [r.model_dump() for r in data.reports]
        elif isinstance(data, (LearnedBlacklists, OptimizerResults)):
            serialized = data.data if hasattr(data, "data") else data.model_dump()
            # For OptimizerResults, convert nested models to dicts
            if isinstance(data, OptimizerResults):
                serialized = {
                    k: v.model_dump() if isinstance(v, BaseModel) else v
                    for k, v in data.data.items()
                }
        else:
            serialized = data.model_dump()

        with open(path, "w") as f:
            json.dump(serialized, f, indent=2, default=str)

        return True

    except Exception as e:
        logger.error("Failed to save JSON to %s: %s", path, e)
        return False
