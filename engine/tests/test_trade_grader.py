"""Tests for auto-grading and lesson generation."""

from engine.src.learning.trade_grader import grade_trade, generate_lesson, grade_and_learn


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
