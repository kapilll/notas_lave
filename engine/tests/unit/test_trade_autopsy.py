"""Tests for the Trade Autopsy module (Phases 1 & 2 of COPILOT-DESIGN.md)."""

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from notas_lave.core.events import TradeClosed
from notas_lave.learning import trade_autopsy
from notas_lave.learning.trade_autopsy import (
    gather_trade_context,
    should_generate_report,
    build_prompt,
    save_report,
    format_telegram_summary,
    handle_trade_closed,
    compile_weekly_summary,
    analyze_edges,
    list_reports,
    get_report_content,
    get_edge_analysis,
    _HAIKU_SYSTEM_PROMPT,
    _recent_reports,
)


@pytest.fixture(autouse=True)
def clear_duplicate_cache():
    """Reset module-level duplicate tracker between tests."""
    _recent_reports.clear()
    yield
    _recent_reports.clear()


def _make_event(
    trade_id="42",
    symbol="BTCUSD",
    direction="LONG",
    entry_price=87000.0,
    exit_price=87500.0,
    pnl=5.0,
    reason="tp_hit",
    timestamp=None,
) -> TradeClosed:
    return TradeClosed(
        trade_id=trade_id,
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=pnl,
        reason=reason,
        timestamp=timestamp or datetime.now(timezone.utc),
    )


def _make_context(
    trade_id="42",
    symbol="BTCUSD",
    direction="LONG",
    entry_price=87000.0,
    exit_price=87500.0,
    pnl=5.0,
    reason="tp_hit",
    stop_loss=86500.0,
    take_profit=87500.0,
    outcome_grade="B",
    duration_seconds=3600,
    proposing_strategy="trend_momentum",
    strategy_score=72.0,
    regime="TRENDING",
    trust_score=62.0,
    win_rate=58.0,
    current_streak=2,
    total_trades=12,
    r_multiple=1.0,
) -> dict:
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl": pnl,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_size": 0.01,
        "outcome_grade": outcome_grade,
        "duration_seconds": duration_seconds,
        "proposing_strategy": proposing_strategy,
        "strategy_score": strategy_score,
        "strategy_factors": "",
        "regime": regime,
        "timeframe": "15m",
        "lessons_learned": "Clean TP hit.",
        "trust_score": trust_score,
        "win_rate": win_rate,
        "current_streak": current_streak,
        "total_trades": total_trades,
        "r_multiple": r_multiple,
    }


class TestGatherContext:
    """gather_trade_context reads DB + leaderboard, returns all required fields."""

    def test_gather_context_all_fields(self):
        """All expected keys are present in returned context."""
        event = _make_event()

        # Patch DB and leaderboard reads
        mock_trade = MagicMock()
        mock_trade.stop_loss = 86500.0
        mock_trade.take_profit = 87500.0
        mock_trade.position_size = 0.01
        mock_trade.outcome_grade = "B"
        mock_trade.duration_seconds = 3600
        mock_trade.proposing_strategy = "trend_momentum"
        mock_trade.strategy_score = 72.0
        mock_trade.strategy_factors = '{"rsi": 38}'
        mock_trade.regime = "TRENDING"
        mock_trade.timeframe = "15m"
        mock_trade.lessons_learned = "Clean TP hit."

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_trade

        mock_record = {
            "trust_score": 62.0,
            "win_rate": 58.0,
            "current_streak": 2,
            "total_trades": 12,
        }

        with patch("notas_lave.learning.trade_autopsy.get_db", return_value=mock_db), \
             patch("notas_lave.learning.trade_autopsy.StrategyLeaderboard") as mock_lb:
            mock_lb.return_value.get_strategy.return_value = mock_record
            ctx = gather_trade_context(event)

        required_keys = [
            "trade_id", "symbol", "direction", "entry_price", "exit_price",
            "pnl", "reason", "timestamp", "stop_loss", "take_profit",
            "position_size", "outcome_grade", "duration_seconds",
            "proposing_strategy", "strategy_score", "strategy_factors",
            "regime", "timeframe", "lessons_learned",
            "trust_score", "win_rate", "current_streak", "total_trades",
            "r_multiple",
        ]
        for key in required_keys:
            assert key in ctx, f"Missing key: {key}"

        # Verify computed r_multiple
        assert ctx["r_multiple"] != 0.0  # entry=87000, sl=86500 → risk=500, pnl=5 → r=0.01

    def test_gather_context_fallback_on_db_error(self):
        """Context still returns with defaults if DB is unavailable."""
        event = _make_event()

        with patch("notas_lave.learning.trade_autopsy.get_db", side_effect=Exception("DB down")), \
             patch("notas_lave.learning.trade_autopsy.StrategyLeaderboard"):
            ctx = gather_trade_context(event)

        assert ctx["trade_id"] == "42"
        assert ctx["symbol"] == "BTCUSD"
        assert ctx["outcome_grade"] == "?"
        assert ctx["stop_loss"] == 0.0

    def test_gather_context_r_multiple_computed(self):
        """R-multiple is correctly computed from entry, SL, and P&L."""
        event = _make_event(entry_price=100.0, pnl=10.0)

        mock_trade = MagicMock()
        mock_trade.stop_loss = 90.0  # risk = 10 pts
        mock_trade.take_profit = 120.0
        mock_trade.position_size = 1.0
        mock_trade.outcome_grade = "B"
        mock_trade.duration_seconds = 600
        mock_trade.proposing_strategy = "trend_momentum"
        mock_trade.strategy_score = 65.0
        mock_trade.strategy_factors = ""
        mock_trade.regime = "TRENDING"
        mock_trade.timeframe = "15m"
        mock_trade.lessons_learned = ""

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_trade

        with patch("notas_lave.learning.trade_autopsy.get_db", return_value=mock_db), \
             patch("notas_lave.learning.trade_autopsy.StrategyLeaderboard") as mock_lb:
            mock_lb.return_value.get_strategy.return_value = None
            ctx = gather_trade_context(event)

        # pnl=10, risk=|100-90|=10 → r_multiple = 1.0
        assert ctx["r_multiple"] == 1.0


class TestShouldGenerateReport:
    """should_generate_report enforces skip conditions."""

    def test_should_skip_grade_c(self):
        ctx = _make_context(outcome_grade="C")
        assert should_generate_report(ctx) is False

    def test_should_skip_short_duration(self):
        ctx = _make_context(duration_seconds=30)
        assert should_generate_report(ctx) is False

    def test_should_skip_duplicate_within_window(self):
        ctx = _make_context(symbol="BTCUSD", duration_seconds=300)
        # Mark as recently reported
        _recent_reports["BTCUSD"] = datetime.now(timezone.utc) - timedelta(seconds=120)
        assert should_generate_report(ctx) is False

    def test_should_allow_after_window_expires(self):
        ctx = _make_context(symbol="ETHUSD", duration_seconds=300, outcome_grade="B")
        # Mark as reported 6+ minutes ago (beyond 5-minute window)
        _recent_reports["ETHUSD"] = datetime.now(timezone.utc) - timedelta(seconds=400)
        assert should_generate_report(ctx) is True

    def test_should_allow_grade_b(self):
        ctx = _make_context(outcome_grade="B", duration_seconds=600)
        assert should_generate_report(ctx) is True

    def test_should_allow_grade_d(self):
        ctx = _make_context(outcome_grade="D", duration_seconds=300, pnl=-5.0)
        assert should_generate_report(ctx) is True

    def test_should_allow_grade_f(self):
        ctx = _make_context(outcome_grade="F", duration_seconds=120, pnl=-15.0)
        assert should_generate_report(ctx) is True


class TestBuildPrompt:
    """build_prompt produces a compact, token-efficient string."""

    def test_build_prompt_compact(self):
        """Prompt should be under 500 tokens (estimated as words * 1.3)."""
        ctx = _make_context()
        prompt = build_prompt(ctx)
        word_count = len(prompt.split())
        estimated_tokens = word_count * 1.3
        assert estimated_tokens < 500, f"Prompt too long: {estimated_tokens:.0f} estimated tokens"

    def test_build_prompt_contains_key_fields(self):
        ctx = _make_context(symbol="BTCUSD", direction="LONG", outcome_grade="B")
        prompt = build_prompt(ctx)
        assert "BTCUSD" in prompt
        assert "LONG" in prompt
        assert "TRENDING" in prompt
        assert "trend_momentum" in prompt

    def test_build_prompt_includes_lesson_if_present(self):
        ctx = _make_context()
        ctx["lessons_learned"] = "Clean TP hit on 15m."
        prompt = build_prompt(ctx)
        assert "Clean TP hit" in prompt

    def test_build_prompt_handles_missing_lesson(self):
        ctx = _make_context()
        ctx["lessons_learned"] = ""
        prompt = build_prompt(ctx)
        # Should still produce valid output
        assert "Analyze this trade" in prompt

    def test_build_prompt_handles_factors_json(self):
        ctx = _make_context()
        ctx["strategy_factors"] = '{"rsi": 38, "ema_aligned": true}'
        prompt = build_prompt(ctx)
        assert "rsi" in prompt or "Factors" in prompt


class TestSaveReport:
    """save_report creates files with correct naming and valid markdown."""

    def test_save_report_file_created(self, tmp_path):
        ctx = _make_context(trade_id="42", symbol="BTCUSD", direction="LONG")
        analysis = {
            "verdict": "TREND_CONTINUATION",
            "what_worked": "RSI oversold aligned with EMA",
            "what_failed": "Nothing — clean trade",
            "edge_signal": "RSI<40 + EMA_aligned in TRENDING",
            "improvement": "Consider widening TP when RSI < 35",
            "confidence": 8,
        }

        filepath = save_report("42", ctx, analysis, reports_dir=tmp_path)

        assert filepath.exists()
        assert "trade_42" in filepath.name
        assert "BTCUSD" in filepath.name
        assert "LONG" in filepath.name
        assert filepath.suffix == ".md"

    def test_save_report_valid_markdown(self, tmp_path):
        ctx = _make_context(trade_id="43", symbol="ETHUSD", direction="SHORT")
        analysis = {
            "verdict": "COUNTER_TREND_FAILURE",
            "what_worked": "Entry near BB upper band",
            "what_failed": "Shorted against 1h uptrend",
            "edge_signal": "mean_reversion SHORT into bullish 1h",
            "improvement": "Add higher TF direction filter",
            "confidence": 8,
        }

        filepath = save_report("43", ctx, analysis, reports_dir=tmp_path)
        content = filepath.read_text()

        assert content.startswith("# Trade #43")
        assert "## Claude Analysis" in content
        assert "COUNTER_TREND_FAILURE" in content
        assert "## Raw Data" in content

    def test_save_report_fallback_no_analysis(self, tmp_path):
        """When analysis is empty (no Claude API), saves rule-based lesson."""
        ctx = _make_context(trade_id="44")
        ctx["lessons_learned"] = "SL hit on noise trade."

        filepath = save_report("44", ctx, {}, reports_dir=tmp_path)
        content = filepath.read_text()

        assert "## Analysis" in content
        assert "SL hit on noise trade" in content
        assert "## Claude Analysis" not in content

    def test_save_report_creates_month_subdir(self, tmp_path):
        ctx = _make_context(trade_id="45")
        filepath = save_report("45", ctx, {}, reports_dir=tmp_path)

        # File should be inside a YYYY-MM subdirectory
        assert filepath.parent != tmp_path
        assert len(filepath.parent.name) == 7  # "YYYY-MM"


class TestFormatTelegramSummary:
    """format_telegram_summary produces compact 2-line output."""

    def test_telegram_summary_length(self):
        ctx = _make_context(outcome_grade="B", pnl=5.0)
        analysis = {
            "verdict": "TREND_CONTINUATION",
            "improvement": "Consider widening TP when RSI < 35 in strong trends.",
        }
        summary = format_telegram_summary(ctx, analysis)
        lines = summary.split("\n")

        assert len(lines) == 2
        assert all(len(line) <= 200 for line in lines)

    def test_telegram_summary_loss_format(self):
        ctx = _make_context(outcome_grade="D", pnl=-4.5)
        analysis = {
            "verdict": "SL_TOO_TIGHT",
            "improvement": "Widen SL to at least 0.5 ATR.",
        }
        summary = format_telegram_summary(ctx, analysis)
        assert "❌" in summary
        assert "-$4.50" in summary or "$4.50" in summary
        assert "SL_TOO_TIGHT" in summary

    def test_telegram_summary_win_format(self):
        ctx = _make_context(outcome_grade="A", pnl=12.0)
        analysis = {
            "verdict": "CLEAN_WIN",
            "improvement": "No change needed — this is the target pattern.",
        }
        summary = format_telegram_summary(ctx, analysis)
        assert "✅" in summary
        assert "+$12.00" in summary

    def test_telegram_summary_fallback_no_analysis(self):
        ctx = _make_context(outcome_grade="D")
        ctx["lessons_learned"] = "SL hit directional call was wrong."
        summary = format_telegram_summary(ctx, {})
        lines = summary.split("\n")

        assert len(lines) == 2
        assert "SL hit" in lines[1]

    def test_telegram_summary_lines_truncated(self):
        ctx = _make_context(outcome_grade="B")
        analysis = {
            "verdict": "TREND_CONTINUATION",
            "improvement": "X" * 300,  # exceeds 200 chars
        }
        summary = format_telegram_summary(ctx, analysis)
        for line in summary.split("\n"):
            assert len(line) <= 200


class TestFallbackNoApiKey:
    """When no Claude API key, report is saved with rule-based lesson only."""

    def test_fallback_no_api_key(self, tmp_path):
        from notas_lave.learning.trade_autopsy import call_claude_haiku

        with patch.object(trade_autopsy.config, "anthropic_api_key", ""), \
             patch.object(trade_autopsy.config, "claude_provider", "direct"), \
             patch.object(trade_autopsy.config, "google_cloud_project", ""):
            result = call_claude_haiku(_HAIKU_SYSTEM_PROMPT, "test prompt")

        # Should return empty dict — no Claude call attempted
        assert result == {}

    def test_report_saved_with_rule_based_lesson_when_no_claude(self, tmp_path):
        """End-to-end: no API key → saves report with rule-based lesson section."""
        ctx = _make_context(trade_id="50", outcome_grade="D")
        ctx["lessons_learned"] = "SL hit directional call was wrong."

        # Simulate empty analysis (what call_claude_haiku returns without API key)
        filepath = save_report("50", ctx, {}, reports_dir=tmp_path)
        content = filepath.read_text()

        assert "## Analysis" in content
        assert "Lesson (rule-based)" in content
        assert "## Claude Analysis" not in content


class TestHandleTradeClosedE2E:
    """handle_trade_closed orchestrates the full flow."""

    @pytest.mark.asyncio
    async def test_handle_trade_closed_e2e(self, tmp_path):
        """Full flow: gather → should_generate → build → call_haiku → save → telegram."""
        event = _make_event(trade_id="55", symbol="SOLUSD", direction="LONG", pnl=8.0)

        mock_trade = MagicMock()
        mock_trade.stop_loss = 90.0
        mock_trade.take_profit = 120.0
        mock_trade.position_size = 1.0
        mock_trade.outcome_grade = "B"
        mock_trade.duration_seconds = 600
        mock_trade.proposing_strategy = "breakout"
        mock_trade.strategy_score = 68.0
        mock_trade.strategy_factors = ""
        mock_trade.regime = "TRENDING"
        mock_trade.timeframe = "15m"
        mock_trade.lessons_learned = "Clean TP hit."

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_trade

        mock_analysis = {
            "verdict": "CLEAN_WIN",
            "what_worked": "RSI aligned",
            "what_failed": "Nothing",
            "edge_signal": "breakout in TRENDING",
            "improvement": "No change needed.",
            "confidence": 9,
        }

        saved_paths = []

        def mock_save_report(trade_id, context, analysis, reports_dir=None):
            path = tmp_path / f"trade_{trade_id}.md"
            path.write_text("# Test report", encoding="utf-8")
            saved_paths.append(path)
            return path

        with patch.object(trade_autopsy.config, "autopsy_enabled", True), \
             patch("notas_lave.learning.trade_autopsy.get_db", return_value=mock_db), \
             patch("notas_lave.learning.trade_autopsy.StrategyLeaderboard") as mock_lb, \
             patch("notas_lave.learning.trade_autopsy.call_claude_haiku", return_value=mock_analysis), \
             patch("notas_lave.learning.trade_autopsy.save_report", side_effect=mock_save_report), \
             patch("notas_lave.learning.trade_autopsy.send_telegram") as mock_telegram:

            mock_lb.return_value.get_strategy.return_value = {
                "trust_score": 55.0, "win_rate": 55.0, "current_streak": 1, "total_trades": 10
            }
            mock_telegram.return_value = True

            await handle_trade_closed(event)

        # Report was saved
        assert len(saved_paths) == 1
        # Telegram was called
        mock_telegram.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_skips_when_disabled(self):
        """handle_trade_closed does nothing when autopsy_enabled=False."""
        event = _make_event()

        with patch.object(trade_autopsy.config, "autopsy_enabled", False), \
             patch("notas_lave.learning.trade_autopsy.gather_trade_context") as mock_gather:
            await handle_trade_closed(event)
            mock_gather.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_skips_grade_c(self):
        """handle_trade_closed skips grade C trades without saving a report."""
        event = _make_event(trade_id="60", pnl=0.1)

        mock_trade = MagicMock()
        mock_trade.stop_loss = 86500.0
        mock_trade.take_profit = 87500.0
        mock_trade.position_size = 0.01
        mock_trade.outcome_grade = "C"
        mock_trade.duration_seconds = 300
        mock_trade.proposing_strategy = "trend_momentum"
        mock_trade.strategy_score = 60.0
        mock_trade.strategy_factors = ""
        mock_trade.regime = "RANGING"
        mock_trade.timeframe = "15m"
        mock_trade.lessons_learned = ""

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_trade

        with patch.object(trade_autopsy.config, "autopsy_enabled", True), \
             patch("notas_lave.learning.trade_autopsy.get_db", return_value=mock_db), \
             patch("notas_lave.learning.trade_autopsy.StrategyLeaderboard") as mock_lb, \
             patch("notas_lave.learning.trade_autopsy.save_report") as mock_save:

            mock_lb.return_value.get_strategy.return_value = None
            await handle_trade_closed(event)
            mock_save.assert_not_called()


# ─── Phase 2 Tests ────────────────────────────────────────────────────────────

def _write_fake_report(
    path: Path,
    trade_id: str = "10",
    symbol: str = "BTCUSD",
    direction: str = "LONG",
    grade: str = "B",
    pnl: float = 5.0,
    strategy: str = "trend_momentum",
    regime: str = "TRENDING",
    verdict: str = "CLEAN_WIN",
    what_failed: str = "Nothing — clean trade",
    edge_signal: str = "RSI<40 + EMA aligned in TRENDING",
    improvement: str = "No change needed.",
    timestamp: str = "2026-03-31T10:00:00+00:00",
    date_str: str = "20260331",
):
    """Write a fake trade report markdown file for testing."""
    duration_min = 60
    content = (
        f"# Trade #{trade_id} — {symbol} {direction}\n\n"
        f"**Date:** {timestamp}\n"
        f"**Strategy:** {strategy} | **Trust:** 62 | **Signal Score:** 72.0\n"
        f"**Grade:** {grade} | **P&L:** ${pnl:.2f} | **R-Multiple:** 1.00R\n"
        f"**Duration:** {duration_min} min | **Exit:** tp_hit\n\n"
        f"## Context at Entry\n"
        f"- Regime: {regime}\n"
        f"- Entry: 87000.0000 | SL: 86500.0000 | TP: 87500.0000 | Exit: 87500.0000\n"
        f"- Strategy Win Rate: 58.0% | Streak: +2\n\n"
        f"## Claude Analysis\n"
        f"- **Verdict:** {verdict}\n"
        f"- **What worked:** RSI aligned with EMA\n"
        f"- **What failed:** {what_failed}\n"
        f"- **Edge signal:** {edge_signal}\n"
        f"- **Improvement:** {improvement}\n"
        f"- **Confidence:** 8/10\n\n"
        f"## Raw Data\n"
        f"- Entry: 87000.0000 | Exit: 87500.0000 | SL: 86500.0000 | TP: 87500.0000\n"
    )
    # Write into a YYYY-MM subdirectory based on date_str
    month = date_str[:7].replace("", "-")  # fallback
    try:
        month = f"{date_str[:4]}-{date_str[4:6]}"
    except Exception:
        month = "2026-03"
    month_dir = path / month
    month_dir.mkdir(parents=True, exist_ok=True)
    filepath = month_dir / f"trade_{trade_id}_{symbol}_{direction}_{date_str}.md"
    filepath.write_text(content, encoding="utf-8")
    return filepath


class TestCompileWeeklySummary:
    """compile_weekly_summary aggregates reports into a compact string."""

    def test_compile_weekly_summary_basic(self, tmp_path):
        """10 fake reports → summary < 2500 tokens, correct counts."""
        for i in range(10):
            pnl = 5.0 if i < 6 else -3.0
            grade = "B" if pnl > 0 else "D"
            _write_fake_report(
                tmp_path,
                trade_id=str(100 + i),
                pnl=pnl,
                grade=grade,
                date_str="20260331",
            )

        summary = compile_weekly_summary(reports_dir=tmp_path, week="2026-W14")
        # 2026-03-31 is in W14
        assert "10 trades" in summary
        assert "6W/4L" in summary
        word_count = len(summary.split())
        assert word_count * 1.3 < 2500, f"Summary too long: ~{int(word_count * 1.3)} tokens"

    def test_compile_weekly_summary_empty(self, tmp_path):
        """No reports → informative message, no crash."""
        summary = compile_weekly_summary(reports_dir=tmp_path, week="2026-W01")
        assert "No reports found" in summary

    def test_compile_weekly_summary_aggregates_by_strategy(self, tmp_path):
        """Reports from multiple strategies are aggregated separately."""
        _write_fake_report(tmp_path, trade_id="200", strategy="trend_momentum",
                           pnl=5.0, grade="B", date_str="20260331")
        _write_fake_report(tmp_path, trade_id="201", strategy="breakout",
                           pnl=-3.0, grade="D", date_str="20260331")

        summary = compile_weekly_summary(reports_dir=tmp_path, week="2026-W14")
        assert "trend_momentum" in summary
        assert "breakout" in summary

    def test_compile_weekly_summary_aggregates_by_regime(self, tmp_path):
        _write_fake_report(tmp_path, trade_id="300", regime="TRENDING",
                           pnl=5.0, grade="B", date_str="20260331")
        _write_fake_report(tmp_path, trade_id="301", regime="RANGING",
                           pnl=-2.0, grade="D", date_str="20260331")

        summary = compile_weekly_summary(reports_dir=tmp_path, week="2026-W14")
        assert "TRENDING" in summary
        assert "RANGING" in summary

    def test_compile_weekly_summary_includes_verdicts(self, tmp_path):
        _write_fake_report(tmp_path, trade_id="400", verdict="CLEAN_WIN",
                           date_str="20260331")
        _write_fake_report(tmp_path, trade_id="401", verdict="COUNTER_TREND_FAILURE",
                           pnl=-3.0, grade="D", date_str="20260331")

        summary = compile_weekly_summary(reports_dir=tmp_path, week="2026-W14")
        assert "CLEAN_WIN" in summary
        assert "COUNTER_TREND_FAILURE" in summary


class TestAnalyzeEdges:
    """analyze_edges calls Sonnet and saves result."""

    def test_analyze_edges_saves_output(self, tmp_path):
        """Mock Sonnet response → verify markdown saved to summaries/."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="## Edges Found\n\n### Edge 1: RSI<40 + EMA")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=200)

        with patch.object(trade_autopsy.config, "anthropic_api_key", "sk-test"), \
             patch.object(trade_autopsy.config, "claude_provider", "direct"), \
             patch("anthropic.Anthropic") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = analyze_edges("WEEK SUMMARY: 5 trades", week="2026-W14", reports_dir=tmp_path)

        assert "Edge 1" in result
        saved = tmp_path / "summaries" / "week_2026-W14.md"
        assert saved.exists()
        content = saved.read_text()
        assert "Edge Analysis" in content
        assert "Edge 1" in content

    def test_analyze_edges_returns_empty_without_api_key(self, tmp_path):
        """No API key → returns empty string, no file created."""
        with patch.object(trade_autopsy.config, "anthropic_api_key", ""), \
             patch.object(trade_autopsy.config, "claude_provider", "direct"), \
             patch.object(trade_autopsy.config, "google_cloud_project", ""):
            result = analyze_edges("WEEK SUMMARY: 5 trades", week="2026-W01", reports_dir=tmp_path)

        assert result == ""
        assert not (tmp_path / "summaries" / "week_2026-W01.md").exists()

    def test_analyze_edges_handles_api_error(self, tmp_path):
        """API error → returns empty string, no crash."""
        with patch.object(trade_autopsy.config, "anthropic_api_key", "sk-test"), \
             patch.object(trade_autopsy.config, "claude_provider", "direct"), \
             patch("anthropic.Anthropic", side_effect=Exception("API down")):
            result = analyze_edges("WEEK SUMMARY", week="2026-W02", reports_dir=tmp_path)

        assert result == ""


class TestListReports:
    """list_reports returns metadata for recent report files."""

    def test_reports_list_returns_entries(self, tmp_path):
        """3 report files → GET returns 3 entries with metadata."""
        _write_fake_report(tmp_path, trade_id="10", symbol="BTCUSD", date_str="20260331")
        _write_fake_report(tmp_path, trade_id="11", symbol="ETHUSD", date_str="20260331")
        _write_fake_report(tmp_path, trade_id="12", symbol="SOLUSD", date_str="20260331")

        results = list_reports(limit=20, reports_dir=tmp_path)
        assert len(results) == 3
        symbols = {r["symbol"] for r in results}
        assert "BTCUSD" in symbols
        assert "ETHUSD" in symbols
        assert "SOLUSD" in symbols

    def test_reports_list_respects_limit(self, tmp_path):
        for i in range(5):
            _write_fake_report(tmp_path, trade_id=str(20 + i), date_str="20260331")

        results = list_reports(limit=3, reports_dir=tmp_path)
        assert len(results) == 3

    def test_reports_list_empty_dir(self, tmp_path):
        results = list_reports(reports_dir=tmp_path)
        assert results == []

    def test_reports_list_metadata_fields(self, tmp_path):
        _write_fake_report(tmp_path, trade_id="50", symbol="BTCUSD",
                           grade="B", pnl=5.0, strategy="trend_momentum",
                           verdict="CLEAN_WIN", date_str="20260331")

        results = list_reports(reports_dir=tmp_path)
        assert len(results) == 1
        r = results[0]
        assert r["trade_id"] == "50"
        assert r["symbol"] == "BTCUSD"
        assert r["grade"] == "B"
        assert r["pnl"] == 5.0
        assert r["strategy"] == "trend_momentum"
        assert r["verdict"] == "CLEAN_WIN"
        assert "filename" in r
        assert "week" in r


class TestGetReportContent:
    """get_report_content returns full markdown for a trade."""

    def test_report_detail_returns_content(self, tmp_path):
        _write_fake_report(tmp_path, trade_id="99", symbol="BTCUSD", date_str="20260331")
        content = get_report_content("99", reports_dir=tmp_path)
        assert content is not None
        assert "# Trade #99" in content

    def test_report_detail_not_found(self, tmp_path):
        content = get_report_content("9999", reports_dir=tmp_path)
        assert content is None


class TestGetEdgeAnalysis:
    """get_edge_analysis reads weekly analysis from disk."""

    def test_get_edge_analysis_returns_content(self, tmp_path):
        summaries_dir = tmp_path / "summaries"
        summaries_dir.mkdir()
        (summaries_dir / "week_2026-W14.md").write_text("# Edge Analysis\nTest", encoding="utf-8")

        content = get_edge_analysis(week="2026-W14", reports_dir=tmp_path)
        assert content is not None
        assert "Edge Analysis" in content

    def test_get_edge_analysis_not_found(self, tmp_path):
        content = get_edge_analysis(week="2026-W01", reports_dir=tmp_path)
        assert content is None
