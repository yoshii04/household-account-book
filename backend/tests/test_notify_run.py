"""notify/run.py（daily / test）の結合テスト。SQLite in-memory（conftest の db_session）を使う。

対象ADR: docs/adr/0007-pattern-payment-notification-via-slack.md
仕様書: docs/specs/auxiliary/spec_notifications.md
"""
import io
import logging
from datetime import date
from types import SimpleNamespace

import pytest

from app.crud.pattern import get_due_and_unrecorded_patterns
from app.models.account import Account
from app.models.category import Category
from app.models.pattern import TransactionPattern
from app.models.transaction import Transaction
from app.notify import run
from app.notify.base import NotificationError, NotificationMessage, Notifier
from app.notify.messages import build_daily_message

TODAY = date(2026, 11, 3)
VALID_URL = "https://hooks.slack.com/services/T0/B0/xxxx"


class FakeNotifier(Notifier):
    def __init__(self, error=None):
        self.sent: list[NotificationMessage] = []
        self.error = error

    def send(self, message):
        if self.error:
            raise self.error
        self.sent.append(message)


def _setup(db_session):
    cat = Category(code="住居", name="住居", full_path="住居")
    acc = Account(code="10_財布", name="10_財布", account_type="cash")
    db_session.add_all([cat, acc])
    db_session.flush()
    return cat, acc


def _pattern(db_session, cat, acc, name, day, amount=1000, **extra):
    p = TransactionPattern(
        name=name, frequency="monthly", category_id=cat.id, account_id=acc.id,
        payment_day_of_month=day, typical_amount=amount, **extra,
    )
    db_session.add(p)
    db_session.flush()
    return p


def _record(db_session, cat, acc, pattern, tx_date):
    db_session.add(Transaction(
        date=tx_date, category_id=cat.id, account_id=acc.id, expense_amount=1, pattern_id=pattern.id,
    ))
    db_session.flush()


def _run(db_session, notifier=None, show_amount=True, dry_run=False):
    out = io.StringIO()
    code = run.run_daily(
        db_session, notifier, today=TODAY, show_amount=show_amount, dry_run=dry_run, out=out
    )
    return code, out.getvalue()


@pytest.mark.integration
class TestRunDaily:
    def test_due_pattern_is_sent(self, db_session):
        cat, acc = _setup(db_session)
        _pattern(db_session, cat, acc, "家賃", 3, 80000)
        notifier = FakeNotifier()

        code, _ = _run(db_session, notifier)

        assert code == 0
        assert len(notifier.sent) == 1
        assert "■ 今日が支払日（まだ未記録 1件）\n• 家賃 — 80,000円" in notifier.sent[0].text

    def test_overdue_unrecorded_pattern_is_sent(self, db_session):
        cat, acc = _setup(db_session)
        _pattern(db_session, cat, acc, "通信費", 1, 5500)
        notifier = FakeNotifier()

        _run(db_session, notifier)

        assert "■ 支払日を過ぎて未記録（1件）\n• 通信費 — 5,500円（支払日: 11/01）" in notifier.sent[0].text

    def test_recorded_pattern_is_excluded(self, db_session):
        cat, acc = _setup(db_session)
        rent = _pattern(db_session, cat, acc, "家賃", 3)
        phone = _pattern(db_session, cat, acc, "通信費", 1)
        _record(db_session, cat, acc, rent, date(2026, 11, 3))
        _record(db_session, cat, acc, phone, date(2026, 11, 2))
        notifier = FakeNotifier()

        code, _ = _run(db_session, notifier)

        assert code == 0
        assert notifier.sent == []

    def test_inactive_pattern_is_excluded(self, db_session):
        cat, acc = _setup(db_session)
        _pattern(db_session, cat, acc, "家賃", 3, is_active=False)
        notifier = FakeNotifier()

        _run(db_session, notifier)

        assert notifier.sent == []

    def test_no_targets_sends_nothing_and_exits_0(self, db_session):
        cat, acc = _setup(db_session)
        _pattern(db_session, cat, acc, "来週の支払い", 20)
        notifier = FakeNotifier()

        code, _ = _run(db_session, notifier)

        assert code == 0
        assert notifier.sent == []

    def test_send_failure_exits_1_and_logs_without_url(self, db_session, caplog):
        cat, acc = _setup(db_session)
        _pattern(db_session, cat, acc, "家賃", 3)
        notifier = FakeNotifier(error=NotificationError(500, "HTTPStatusError", attempts=3))

        code, _ = _run(db_session, notifier)

        assert code == 1
        assert "status=500 type=HTTPStatusError attempts=3" in caplog.text

    def test_dry_run_prints_body_and_does_not_send(self, db_session):
        cat, acc = _setup(db_session)
        _pattern(db_session, cat, acc, "家賃", 3, 80000)
        notifier = FakeNotifier()

        code, output = _run(db_session, notifier, dry_run=True)

        assert code == 0
        assert notifier.sent == []
        assert "• 家賃 — 80,000円" in output

    def test_dry_run_without_notifier_and_no_targets(self, db_session):
        _setup(db_session)

        code, output = _run(db_session, None, dry_run=True)

        assert code == 0
        assert "送信対象はありません" in output

    def test_show_amount_false_hides_amount(self, db_session):
        cat, acc = _setup(db_session)
        _pattern(db_session, cat, acc, "家賃", 3, 80000)
        notifier = FakeNotifier()

        _run(db_session, notifier, show_amount=False)

        assert "円" not in notifier.sent[0].text

    def test_body_matches_dashboard_counts_and_order(self, db_session):
        cat, acc = _setup(db_session)
        _pattern(db_session, cat, acc, "B", 3, sort_order=2)
        _pattern(db_session, cat, acc, "A", 3, sort_order=1)
        _pattern(db_session, cat, acc, "D", 1, sort_order=4)
        _pattern(db_session, cat, acc, "C", 2, sort_order=3)
        due, unrecorded = get_due_and_unrecorded_patterns(db_session, TODAY)
        notifier = FakeNotifier()

        _run(db_session, notifier)

        assert [p["name"] for p in due] == ["A", "B"]
        assert [p["name"] for p in unrecorded] == ["C", "D"]
        assert notifier.sent[0].text == build_daily_message(due, unrecorded, True, TODAY).text


class TestParseShowAmount:
    @pytest.mark.parametrize("value, expected", [("true", True), ("TRUE", True), ("False", False), (" false ", False)])
    def test_valid(self, value, expected):
        assert run.parse_show_amount(value) is expected

    @pytest.mark.parametrize("value", ["", "flase", "1", "yes", "0"])
    def test_invalid_is_none(self, value):
        assert run.parse_show_amount(value) is None


def _cfg(url=VALID_URL, show_amount="true"):
    return SimpleNamespace(slack_webhook_url=url, notify_show_amount=show_amount)


class _NoDb:
    """DB に触れたら失敗させる（SessionLocal を差し替えて使う）。"""

    def __call__(self):
        raise AssertionError("DB に接続してはいけない")


class TestMainDaily:
    @pytest.fixture(autouse=True)
    def _no_real_db(self, monkeypatch):
        monkeypatch.setattr("app.database.SessionLocal", _NoDb())

    def test_empty_url_is_disabled_and_exits_0_without_db(self, caplog):
        assert run.main(["daily"], _cfg(url="")) == 0
        assert "通知は無効です" in caplog.text

    @pytest.mark.parametrize(
        "url", ["http://hooks.slack.com/services/a/b/c", "https://example.com/services/SECRETVALUE/b/c"]
    )
    def test_invalid_url_exits_1_without_db_and_without_echoing_url(self, url, caplog):
        assert run.main(["daily"], _cfg(url=url)) == 1
        assert "形式が不正" in caplog.text
        assert "SECRETVALUE" not in caplog.text

    @pytest.mark.parametrize("value", ["", "flase", "1"])
    @pytest.mark.parametrize("argv", [["daily"], ["daily", "--dry-run"]])
    def test_invalid_show_amount_exits_1_without_db(self, value, argv, caplog):
        assert run.main(argv, _cfg(show_amount=value)) == 1
        assert "NOTIFY_SHOW_AMOUNT が不正" in caplog.text

    def test_unexpected_db_error_exits_1_without_leaking_url(self, caplog):
        assert run.main(["daily"], _cfg()) == 1
        assert "想定外のエラー" in caplog.text
        assert "hooks.slack.com" not in caplog.text

    def test_unexpected_db_error_does_not_log_sql_or_parameters(self, monkeypatch, caplog):
        from sqlalchemy.exc import OperationalError

        def boom():
            raise OperationalError(
                "SELECT secret FROM t WHERE x = %(p)s", {"p": "PARAMVALUE"},
                Exception("connection refused\nsecond line"),
            )

        monkeypatch.setattr("app.database.SessionLocal", boom)

        assert run.main(["daily"], _cfg()) == 1
        assert "connection refused" in caplog.text
        for leaked in ("SELECT", "PARAMVALUE", "second line"):
            assert leaked not in caplog.text

    def test_dry_run_works_without_url(self, db_session, monkeypatch, capsys):
        cat, acc = _setup(db_session)
        _pattern(db_session, cat, acc, "家賃", 3, 80000)
        monkeypatch.setattr("app.database.SessionLocal", lambda: db_session)
        monkeypatch.setattr(run, "today_jst", lambda: TODAY)

        code = run.main(["daily", "--dry-run"], _cfg(url=""))

        assert code == 0
        assert "• 家賃 — 80,000円" in capsys.readouterr().out

    def test_sends_through_slack_notifier(self, db_session, monkeypatch):
        cat, acc = _setup(db_session)
        _pattern(db_session, cat, acc, "家賃", 3, 80000)
        sent = []
        monkeypatch.setattr("app.database.SessionLocal", lambda: db_session)
        monkeypatch.setattr(run, "today_jst", lambda: TODAY)
        monkeypatch.setattr(run.SlackNotifier, "send", lambda self, message: sent.append(message))

        code = run.main(["daily"], _cfg())

        assert code == 0
        assert len(sent) == 1


class TestMainTest:
    @pytest.fixture(autouse=True)
    def _no_real_db(self, monkeypatch):
        monkeypatch.setattr("app.database.SessionLocal", _NoDb())

    def test_sends_test_message_without_db(self, monkeypatch):
        sent = []
        monkeypatch.setattr(run.SlackNotifier, "send", lambda self, message: sent.append(message))

        assert run.main(["test"], _cfg()) == 0
        assert len(sent) == 1
        assert "テスト通知です" in sent[0].text

    def test_empty_url_exits_1(self, caplog):
        assert run.main(["test"], _cfg(url="")) == 1
        assert "未設定" in caplog.text

    def test_invalid_url_exits_1(self, caplog):
        assert run.main(["test"], _cfg(url="https://example.com/services/SECRETVALUE")) == 1
        assert "SECRETVALUE" not in caplog.text

    def test_send_failure_exits_1(self, monkeypatch):
        def fail(self, message):
            raise NotificationError(None, "ConnectError", attempts=3)

        monkeypatch.setattr(run.SlackNotifier, "send", fail)

        assert run.main(["test"], _cfg()) == 1


class TestArguments:
    def test_unknown_command_exits_2(self):
        with pytest.raises(SystemExit) as exc_info:
            run.main(["unknown"], _cfg())

        assert exc_info.value.code == 2
