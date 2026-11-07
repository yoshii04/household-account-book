"""notify/scheduler.py の時刻判定・ループのテスト（実際には待たない）

対象ADR: docs/adr/0007-pattern-payment-notification-via-slack.md
仕様書: docs/specs/auxiliary/spec_notifications.md
"""
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from app.jst import JST
from app.notify import scheduler
from app.notify.scheduler import LATE_TOLERANCE, decide, initial_handled_date, parse_notify_time

NOTIFY = time(22, 30)


def _at(day, hour, minute, second=0):
    return datetime(2026, 11, day, hour, minute, second, tzinfo=JST)


class TestParseNotifyTime:
    @pytest.mark.parametrize(
        "value, expected",
        [("22:30", time(22, 30)), ("00:00", time(0, 0)), ("23:59", time(23, 59)), (" 07:05 ", time(7, 5))],
    )
    def test_valid(self, value, expected):
        assert parse_notify_time(value) == expected

    @pytest.mark.parametrize(
        "value", ["25:00", "24:00", "2230", "", "22:60", "7:05", "22:30:00", "ab:cd", "２２:３０"]
    )
    def test_invalid(self, value):
        assert parse_notify_time(value) is None


class TestDecide:
    def test_waits_before_notify_time(self):
        assert decide(_at(3, 22, 29, 59), NOTIFY, None, LATE_TOLERANCE) == "wait"

    def test_runs_at_notify_time(self):
        assert decide(_at(3, 22, 30), NOTIFY, None, LATE_TOLERANCE) == "run"

    def test_runs_within_tolerance(self):
        assert decide(_at(3, 22, 40), NOTIFY, None, LATE_TOLERANCE) == "run"

    def test_skips_beyond_tolerance(self):
        assert decide(_at(3, 22, 40, 1), NOTIFY, None, LATE_TOLERANCE) == "skip"

    def test_does_not_run_twice_in_a_day(self):
        assert decide(_at(3, 22, 31), NOTIFY, date(2026, 11, 3), LATE_TOLERANCE) == "wait"

    def test_runs_again_on_the_next_day(self):
        assert decide(_at(4, 22, 30), NOTIFY, date(2026, 11, 3), LATE_TOLERANCE) == "run"

    def test_midnight_notify_time(self):
        assert decide(_at(4, 0, 0), time(0, 0), date(2026, 11, 3), LATE_TOLERANCE) == "run"


class TestInitialHandledDate:
    def test_started_after_notify_time_counts_today_as_handled(self):
        assert initial_handled_date(_at(3, 22, 31), NOTIFY) == date(2026, 11, 3)

    def test_started_before_notify_time_is_not_handled(self):
        assert initial_handled_date(_at(3, 22, 29), NOTIFY) is None


class _Clock:
    """now_fn を一定間隔で進める。sleep はその間隔ぶん時計を進めるだけ。"""

    def __init__(self, start):
        self.now = start

    def now_fn(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


def _cfg(notify_time="22:30"):
    return SimpleNamespace(notify_time=notify_time)


class TestMainLoop:
    def test_invalid_notify_time_exits_with_2(self, caplog):
        assert scheduler.main(_cfg("25:00"), runner=lambda: 0, max_loops=1) == 2
        assert "NOTIFY_TIME が不正" in caplog.text

    def test_runs_once_at_notify_time(self):
        clock = _Clock(_at(3, 22, 28))
        calls = []

        scheduler.main(
            _cfg(), now_fn=clock.now_fn, sleep=clock.sleep, runner=lambda: calls.append(1) or 0, max_loops=20
        )

        assert len(calls) == 1

    def test_does_not_run_when_started_after_notify_time(self):
        clock = _Clock(_at(3, 22, 31))
        calls = []

        scheduler.main(
            _cfg(), now_fn=clock.now_fn, sleep=clock.sleep, runner=lambda: calls.append(1) or 0, max_loops=20
        )

        assert calls == []

    def test_runs_again_on_the_next_day(self):
        clock = _Clock(_at(3, 22, 31))
        calls = []

        # 11/3 22:31 起動 → 翌日 22:30 の実行までを回す（30 秒 × 2900 ≒ 24 時間）
        scheduler.main(
            _cfg(), now_fn=clock.now_fn, sleep=clock.sleep, runner=lambda: calls.append(1) or 0, max_loops=2900
        )

        assert len(calls) == 1
        assert clock.now.date() == date(2026, 11, 4)

    def test_skips_when_woken_far_after_notify_time(self, caplog):
        clock = _Clock(_at(3, 22, 0))
        calls = []

        def sleep(seconds):
            # スリープ復帰を模して、実行時刻の 1 時間後まで一気に進める
            clock.now = _at(3, 23, 30) if clock.now < _at(3, 22, 30) else clock.now + timedelta(seconds=seconds)

        scheduler.main(
            _cfg(), now_fn=clock.now_fn, sleep=sleep, runner=lambda: calls.append(1) or 0, max_loops=5
        )

        assert calls == []
        assert "今日は送信しません" in caplog.text

    def test_loop_survives_unexpected_exception_from_runner(self, caplog):
        clock = _Clock(_at(3, 22, 29))
        calls = []

        def runner():
            calls.append(1)
            raise ValueError("boom with SECRET")

        code = scheduler.main(_cfg(), now_fn=clock.now_fn, sleep=clock.sleep, runner=runner, max_loops=10)

        assert code == 0
        assert len(calls) == 1  # 例外でも「今日は処理済み」になり、同じ日に繰り返さない
        assert "type=ValueError" in caplog.text
        assert "SECRET" not in caplog.text

    @pytest.mark.parametrize("result", [1, None])
    def test_loop_continues_after_daily_failure(self, result):
        clock = _Clock(_at(3, 22, 29))
        calls = []

        def runner():
            calls.append(1)
            return result

        code = scheduler.main(_cfg(), now_fn=clock.now_fn, sleep=clock.sleep, runner=runner, max_loops=10)

        assert code == 0
        assert len(calls) == 1
