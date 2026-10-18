"""
パターン管理 動作確認チェックリストのテスト（記録状況フィールドの API 反映）

対象ADR: docs/adr/0001-pattern-payment-status-tracking.md
仕様書: docs/specs/auxiliary/spec_patterns.md
"""
from datetime import date
from unittest.mock import patch

import pytest

from app.models.account import Account
from app.models.category import Category
from app.models.pattern import TransactionPattern
from app.models.transaction import Transaction


def _create_category(db_session, full_path: str, is_transfer: bool = False) -> Category:
    parts = full_path.split("/", 1)
    parent = None
    if len(parts) == 2:
        parent = db_session.query(Category).filter(Category.full_path == parts[0]).first()
        if not parent:
            parent = Category(code=parts[0], name=parts[0], full_path=parts[0], is_transfer=is_transfer)
            db_session.add(parent)
            db_session.flush()
    cat = Category(
        code=parts[-1], name=parts[-1],
        parent_id=parent.id if parent else None,
        full_path=full_path, is_transfer=is_transfer,
    )
    db_session.add(cat)
    db_session.flush()
    return cat


def _create_account(db_session, code: str = "10_財布") -> Account:
    acc = Account(code=code, name=code, account_type="cash")
    db_session.add(acc)
    db_session.flush()
    return acc


def _create_pattern(
    db_session, category: Category, account: Account,
    name: str = "テストパターン", frequency: str = "monthly", payment_day_of_month: int = 15,
) -> TransactionPattern:
    p = TransactionPattern(
        name=name, frequency=frequency, category_id=category.id, account_id=account.id,
        payment_day_of_month=payment_day_of_month,
    )
    db_session.add(p)
    db_session.flush()
    return p


def _create_transaction(db_session, category: Category, account: Account, tx_date: date) -> Transaction:
    tx = Transaction(date=tx_date, category_id=category.id, account_id=account.id, expense_amount=1000)
    db_session.add(tx)
    db_session.flush()
    return tx


@pytest.mark.integration
class TestPatternsListRecordedFields:
    def test_list_patterns_includes_recorded_status_fields(self, api_client, db_session):
        # チェックリスト: GET /api/v1/patterns のレスポンスに
        # is_current_period_recorded / current_period_transaction_id が含まれる
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            res = api_client.get("/api/v1/patterns")

        assert res.status_code == 200
        body = res.json()
        assert len(body) == 1
        assert body[0]["is_current_period_recorded"] is False
        assert body[0]["current_period_transaction_id"] is None

    def test_due_patterns_includes_recorded_status_fields(self, api_client, db_session):
        # チェックリスト: GET /api/v1/patterns/due のレスポンスにも同フィールドが含まれる
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 15)), \
             patch("app.routers.patterns.today_jst", return_value=date(2026, 6, 15)):
            res = api_client.get("/api/v1/patterns/due")

        assert res.status_code == 200
        body = res.json()
        assert len(body) == 1
        assert "is_current_period_recorded" in body[0]
        assert "current_period_transaction_id" in body[0]

    def test_due_patterns_excludes_recorded_pattern(self, api_client, db_session):
        # 対象ADR: docs/adr/0004-dashboard-due-patterns-exclude-recorded.md
        # チェックリスト: 対象期間について記録済み（is_current_period_recorded = true）の
        # パターンはレスポンスに含まれないこと
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, payment_day_of_month=15)
        _create_transaction(db_session, cat, acc, date(2026, 6, 15))

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 15)), \
             patch("app.routers.patterns.today_jst", return_value=date(2026, 6, 15)):
            res = api_client.get("/api/v1/patterns/due")

        assert res.status_code == 200
        assert res.json() == []
