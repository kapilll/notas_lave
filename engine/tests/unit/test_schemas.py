"""Tests for journal schemas — Pydantic validation for JSON state files."""

import json
import os
import tempfile

import pytest
from notas_lave.journal.schemas import (
    LabRiskState,
    LearnedState,
    RateLimitState,
    safe_load_json,
    safe_save_json,
    validate_json_file,
)


class TestLabRiskState:
    def test_default_values(self):
        """Fresh LabRiskState defaults to $5000 — Delta Exchange testnet balance."""
        state = LabRiskState()
        assert state.current_balance == 5000.0
        assert state.total_pnl == 0.0
        assert state.peak_balance == 5000.0

    def test_custom_values(self):
        state = LabRiskState(current_balance=10500.0, total_pnl=500.0)
        assert state.current_balance == 10500.0
        assert state.total_pnl == 500.0


class TestLearnedState:
    def test_default_empty_weights(self):
        """LearnedState starts with empty regime_weights."""
        state = LearnedState()
        assert state.regime_weights == {}

    def test_with_weights(self):
        state = LearnedState(
            regime_weights={"TRENDING": {"scalping": 0.2, "ict": 0.3}},
            updated_at="2026-03-29T00:00:00Z",
        )
        assert "TRENDING" in state.regime_weights


class TestRateLimitState:
    def test_default_values(self):
        state = RateLimitState()
        assert state.daily_calls == 0
        assert state.date == ""


class TestSafeLoadJson:
    def test_missing_file_returns_default(self):
        """Missing file returns default instance, never crashes."""
        result = safe_load_json("/nonexistent/path.json", LabRiskState)
        assert isinstance(result, LabRiskState)
        assert result.total_pnl == 0.0

    def test_valid_json_loads_correctly(self):
        """Valid JSON with matching schema loads successfully."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"current_balance": 9500.0, "total_pnl": 500.0, "peak_balance": 9500.0}, f)
            path = f.name
        try:
            result = safe_load_json(path, LabRiskState)
            assert result.current_balance == 9500.0
            assert result.total_pnl == 500.0
        finally:
            os.unlink(path)

    def test_invalid_json_returns_default(self):
        """Corrupted JSON returns default, never crashes."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{invalid json content!!!")
            path = f.name
        try:
            result = safe_load_json(path, LabRiskState)
            assert isinstance(result, LabRiskState)
        finally:
            os.unlink(path)

    def test_custom_default_returned_on_error(self):
        """Custom default is returned when loading fails."""
        custom = LabRiskState(current_balance=42.0)
        result = safe_load_json("/nonexistent.json", LabRiskState, default=custom)
        assert result.current_balance == 42.0


class TestSafeSaveJson:
    def test_save_and_load_roundtrip(self):
        """Save then load preserves data."""
        state = LabRiskState(current_balance=7777.0, total_pnl=123.45)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_state.json")
            ok = safe_save_json(path, state)
            assert ok is True

            loaded = safe_load_json(path, LabRiskState)
            assert loaded.current_balance == 7777.0
            assert loaded.total_pnl == 123.45

    def test_save_creates_parent_dirs(self):
        """safe_save_json creates parent directories if needed."""
        state = LabRiskState()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nested", "deep", "state.json")
            ok = safe_save_json(path, state)
            assert ok is True
            assert os.path.exists(path)


class TestValidateJsonFile:
    def test_valid_file_passes(self):
        """Valid JSON file passes validation."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"current_balance": 5000.0}, f)
            path = f.name
        try:
            valid, error = validate_json_file(path, LabRiskState)
            assert valid is True
            assert error == ""
        finally:
            os.unlink(path)

    def test_invalid_json_fails(self):
        """Invalid JSON fails validation with error message."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            valid, error = validate_json_file(path, LabRiskState)
            assert valid is False
            assert len(error) > 0
        finally:
            os.unlink(path)

    def test_missing_file_fails(self):
        """Missing file fails validation."""
        valid, error = validate_json_file("/nonexistent.json", LabRiskState)
        assert valid is False
