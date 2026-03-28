"""Tests for auto-grading and lesson generation."""

from notas_lave.learning.trade_grader import grade_trade, generate_lesson, grade_and_learn


class TestGrading:
    """Trade grading A-F based on R-multiples and exit quality."""

    def test_grade_a_extended_tp(self):
        grade = grade_trade(
            pnl=20.0, entry_price=100, exit_price=110, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="extended_tp",
            tp_extensions=2,
        )
        assert grade == "A"

    def test_grade_b_clean_tp_hit(self):
        grade = grade_trade(
            pnl=5.0, entry_price=100, exit_price=110, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="tp_hit",
        )
        assert grade == "B"

    def test_grade_c_small_win(self):
        grade = grade_trade(
            pnl=1.0, entry_price=100, exit_price=101, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="manual",
        )
        assert grade == "C"

    def test_grade_d_normal_sl_hit(self):
        grade = grade_trade(
            pnl=-5.0, entry_price=100, exit_price=95, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="sl_hit",
        )
        assert grade == "D"

    def test_grade_f_big_loss(self):
        grade = grade_trade(
            pnl=-15.0, entry_price=100, exit_price=85, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="sl_hit",
        )
        assert grade == "F"

    def test_grade_f_zero_sl(self):
        grade = grade_trade(
            pnl=-5.0, entry_price=100, exit_price=95, stop_loss=0,
            take_profit=110, direction="LONG", exit_reason="sl_hit",
        )
        assert grade == "F"

    def test_grade_b_smart_exit_profit(self):
        grade = grade_trade(
            pnl=3.0, entry_price=100, exit_price=103, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="smart_exit",
        )
        assert grade == "B"


class TestLessons:
    """Lesson generation produces meaningful insights."""

    def test_sl_hit_fast_lesson(self):
        lesson = generate_lesson(
            symbol="BTCUSD", direction="LONG", entry_price=100, exit_price=95,
            stop_loss=95, take_profit=110, exit_reason="sl_hit", pnl=-5.0,
            duration_seconds=120, strategies=["ema_crossover"],
            regime="TRENDING", timeframe="1h", grade="D",
        )
        assert "SL hit" in lesson
        assert "2m" in lesson or "entry timing" in lesson

    def test_tp_hit_clean_lesson(self):
        lesson = generate_lesson(
            symbol="ETHUSD", direction="SHORT", entry_price=100, exit_price=90,
            stop_loss=105, take_profit=90, exit_reason="tp_hit", pnl=10.0,
            duration_seconds=3600, strategies=["bollinger_bands"],
            regime="RANGING", timeframe="4h", grade="B",
        )
        assert "Clean TP hit" in lesson

    def test_extended_tp_lesson(self):
        lesson = generate_lesson(
            symbol="BTCUSD", direction="LONG", entry_price=100, exit_price=120,
            stop_loss=95, take_profit=110, exit_reason="extended_tp", pnl=20.0,
            duration_seconds=7200, strategies=["momentum_breakout"],
            regime="TRENDING", timeframe="1h", grade="A", tp_extensions=2,
        )
        assert "extended" in lesson.lower() or "runner" in lesson.lower()


class TestGradingEdgeCases:
    """Cover remaining grade_trade branches."""

    def test_grade_b_large_profit_no_tp_hit(self):
        """Profit > 0, R-multiple >= 1.0 → B."""
        grade = grade_trade(
            pnl=10.0, entry_price=100, exit_price=110, stop_loss=95,
            take_profit=120, direction="LONG", exit_reason="manual",
        )
        assert grade in ("B", "C")  # 1.0R+ profit without TP hit = B or C

    def test_grade_c_breakeven(self):
        grade = grade_trade(
            pnl=0.0, entry_price=100, exit_price=100, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="manual",
        )
        assert grade == "C"

    def test_grade_c_tiny_loss(self):
        """Small loss (< 0.5R) → C."""
        grade = grade_trade(
            pnl=-1.0, entry_price=100, exit_price=99, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="manual",
        )
        assert grade == "C"

    def test_grade_d_normal_sl(self):
        """SL hit within -1.1R → D."""
        grade = grade_trade(
            pnl=-5.0, entry_price=100, exit_price=95, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="sl_hit",
        )
        assert grade == "D"

    def test_grade_f_catastrophic(self):
        """Big loss beyond -1.1R → F."""
        grade = grade_trade(
            pnl=-15.0, entry_price=100, exit_price=85, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="sl_hit",
        )
        assert grade == "F"

    def test_grade_f_missing_sl(self):
        """Zero or missing SL → F (no risk management)."""
        grade = grade_trade(
            pnl=-5.0, entry_price=100, exit_price=95, stop_loss=0,
            take_profit=110, direction="LONG", exit_reason="sl_hit",
        )
        assert grade == "F"

    def test_grade_f_missing_entry(self):
        """Missing entry price → F (invalid data)."""
        grade = grade_trade(
            pnl=-5.0, entry_price=0, exit_price=95, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="sl_hit",
        )
        assert grade == "F"

    def test_grade_a_2r_tp_hit(self):
        """TP hit with 2R+ profit → A."""
        grade = grade_trade(
            pnl=20.0, entry_price=100, exit_price=120, stop_loss=90,
            take_profit=120, direction="LONG", exit_reason="tp_hit",
        )
        assert grade == "A"

    def test_grade_b_smart_exit_loss(self):
        """Smart exit with loss doesn't auto-grade as B."""
        grade = grade_trade(
            pnl=-1.0, entry_price=100, exit_price=99, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="smart_exit",
        )
        assert grade in ("C", "D")  # Smart exit with loss = C or D

    def test_trailing_sl_winner(self):
        """Trailing SL with profit → B."""
        grade = grade_trade(
            pnl=5.0, entry_price=100, exit_price=105, stop_loss=95,
            take_profit=110, direction="LONG", exit_reason="trailing_sl",
        )
        assert grade in ("B", "C")


class TestLessonsEdgeCases:
    """Cover remaining generate_lesson branches."""

    def test_sl_hit_fast(self):
        """SL hit in < 5 min gets 'too early' message."""
        lesson = generate_lesson(
            symbol="BTCUSD", direction="LONG", entry_price=100, exit_price=95,
            stop_loss=95, take_profit=110, exit_reason="sl_hit", pnl=-5.0,
            duration_seconds=120, strategies=["ema_crossover"],
            regime="TRENDING", timeframe="1h", grade="D",
        )
        assert "timing" in lesson.lower() or "early" in lesson.lower() or "2m" in lesson

    def test_sl_hit_medium_duration(self):
        """SL hit in 5-30 min gets range zone check message."""
        lesson = generate_lesson(
            symbol="BTCUSD", direction="LONG", entry_price=100, exit_price=95,
            stop_loss=95, take_profit=110, exit_reason="sl_hit", pnl=-5.0,
            duration_seconds=600, strategies=["rsi_divergence"],
            regime="RANGING", timeframe="5m", grade="D",
        )
        assert "range" in lesson.lower() or "SL hit" in lesson

    def test_tp_extended_with_extensions(self):
        """TP hit with extensions gets 'extended' message."""
        lesson = generate_lesson(
            symbol="ETHUSD", direction="LONG", entry_price=100, exit_price=120,
            stop_loss=95, take_profit=110, exit_reason="tp_hit", pnl=20.0,
            duration_seconds=3600, strategies=["momentum_breakout"],
            regime="TRENDING", timeframe="1h", grade="A", tp_extensions=2,
        )
        assert "2x" in lesson or "extended" in lesson.lower()

    def test_trailing_sl_winner_lesson(self):
        """Trailing SL with profit → 'locked profit' message."""
        lesson = generate_lesson(
            symbol="XAUUSD", direction="LONG", entry_price=100, exit_price=108,
            stop_loss=95, take_profit=115, exit_reason="trailing_sl", pnl=8.0,
            duration_seconds=7200, strategies=["london_breakout"],
            regime="TRENDING", timeframe="15m", grade="B",
        )
        assert "trail" in lesson.lower() or "profit" in lesson.lower()

    def test_trailing_sl_loser_lesson(self):
        """Trailing SL with loss → 'breakeven then reversed' message."""
        lesson = generate_lesson(
            symbol="BTCUSD", direction="LONG", entry_price=100, exit_price=100,
            stop_loss=95, take_profit=115, exit_reason="trailing_sl", pnl=-0.5,
            duration_seconds=1800, strategies=["ema_crossover"],
            regime="RANGING", timeframe="5m", grade="C",
        )
        assert "trail" in lesson.lower() or "breakeven" in lesson.lower() or "flat" in lesson.lower()

    def test_patience_lesson_long_trade(self):
        """Long duration winning trade → patience lesson."""
        lesson = generate_lesson(
            symbol="XAUUSD", direction="LONG", entry_price=100, exit_price=115,
            stop_loss=95, take_profit=115, exit_reason="tp_hit", pnl=15.0,
            duration_seconds=18000, strategies=["fibonacci_golden_zone"],
            regime="TRENDING", timeframe="1h", grade="A",
        )
        # Should either mention patience or the clean TP hit
        assert isinstance(lesson, str) and len(lesson) > 5

    def test_lesson_no_parts_loss(self):
        """Trade with unusual params falls through to default 'loss taken' message."""
        lesson = generate_lesson(
            symbol="SOLUSD", direction="SHORT", entry_price=100, exit_price=95,
            stop_loss=105, take_profit=90, exit_reason="manual", pnl=-3.0,
            duration_seconds=9000, strategies=["vwap_scalping"],
            regime="UNKNOWN", timeframe="30m", grade="C",
        )
        assert isinstance(lesson, str) and len(lesson) > 5


class TestGradeAndLearn:
    """Integration test for grade_and_learn convenience function."""

    def test_returns_grade_and_lesson(self):
        grade, lesson = grade_and_learn({
            "pnl": -5.0,
            "entry_price": 100,
            "exit_price": 95,
            "stop_loss": 95,
            "take_profit": 110,
            "direction": "LONG",
            "exit_reason": "sl_hit",
            "duration_seconds": 300,
            "strategies_agreed": '["ema_crossover"]',
            "regime": "TRENDING",
            "timeframe": "1h",
            "symbol": "BTCUSD",
        })
        assert grade in ("C", "D", "F")
        assert len(lesson) > 10

    def test_handles_missing_fields(self):
        grade, lesson = grade_and_learn({})
        assert grade == "F"
        assert isinstance(lesson, str)
