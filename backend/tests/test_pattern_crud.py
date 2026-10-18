"""
crud/pattern.py の当月（対象期間）記録状況判定・実績ベース次回支払日算出のテスト

対象ADR: docs/adr/0001-pattern-payment-status-tracking.md
仕様書: docs/specs/auxiliary/spec_patterns.md
"""
from datetime import date
from unittest.mock import patch

import pytest

from app.crud.pattern import (
    _target_period,
    _filter_due,
    _calc_payment_dates,
    get_pattern,
    get_patterns,
    get_due_patterns,
    get_unrecorded_patterns,
)
from app.models.account import Account
from app.models.category import Category
from app.models.group import Group
from app.models.pattern import TransactionPattern
from app.models.transaction import Transaction


# ─── テストデータ作成ヘルパー ─────────────────────────────────────────────────

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


def _create_group(db_session, code: str = "20_太郎") -> Group:
    grp = Group(code=code, name=code)
    db_session.add(grp)
    db_session.flush()
    return grp


def _create_pattern(
    db_session,
    category: Category,
    account: Account,
    to_account: Account = None,
    group: Group = None,
    name: str = "テストパターン",
    frequency: str = "monthly",
    payment_day_of_month: int = 15,
    payment_month_of_year: int = None,
    is_active: bool = True,
) -> TransactionPattern:
    p = TransactionPattern(
        name=name,
        frequency=frequency,
        category_id=category.id,
        account_id=account.id,
        to_account_id=to_account.id if to_account else None,
        group_id=group.id if group else None,
        payment_day_of_month=payment_day_of_month,
        payment_month_of_year=payment_month_of_year,
        is_active=is_active,
    )
    db_session.add(p)
    db_session.flush()
    return p


def _create_transaction(
    db_session,
    category: Category,
    account: Account,
    tx_date: date,
    pattern: TransactionPattern = None,
    group: Group = None,
    expense: int = 1000,
) -> Transaction:
    tx = Transaction(
        date=tx_date,
        category_id=category.id,
        account_id=account.id,
        expense_amount=expense,
        pattern_id=pattern.id if pattern else None,
        group_id=group.id if group else None,
    )
    db_session.add(tx)
    db_session.flush()
    return tx


# ─── _target_period ──────────────────────────────────────────────────────────

@pytest.mark.integration
class TestTargetPeriod:
    def test_monthly_returns_first_to_last_day_of_current_month(self, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, frequency="monthly", payment_day_of_month=15)

        result = _target_period(p, date(2026, 6, 10))

        assert result == (date(2026, 6, 1), date(2026, 6, 30), date(2026, 6, 15))

    def test_annual_returns_payment_month_range(self, db_session):
        cat = _create_category(db_session, "保険/自動車保険")
        acc = _create_account(db_session)
        p = _create_pattern(
            db_session, cat, acc, frequency="annual",
            payment_day_of_month=20, payment_month_of_year=3,
        )

        result = _target_period(p, date(2026, 6, 10))

        assert result == (date(2026, 3, 1), date(2026, 3, 31), date(2026, 3, 20))

    def test_annual_without_payment_month_returns_none(self, db_session):
        cat = _create_category(db_session, "保険/自動車保険")
        acc = _create_account(db_session)
        p = _create_pattern(
            db_session, cat, acc, frequency="annual",
            payment_day_of_month=20, payment_month_of_year=None,
        )

        assert _target_period(p, date(2026, 6, 10)) is None

    def test_daily_returns_none(self, db_session):
        cat = _create_category(db_session, "食費/スーパー")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, frequency="daily", payment_day_of_month=None)

        assert _target_period(p, date(2026, 6, 10)) is None

    def test_other_returns_none(self, db_session):
        cat = _create_category(db_session, "娯楽/その他")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, frequency="other", payment_day_of_month=None)

        assert _target_period(p, date(2026, 6, 10)) is None

    def test_monthly_without_payment_day_returns_none(self, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, frequency="monthly", payment_day_of_month=None)

        assert _target_period(p, date(2026, 6, 10)) is None


# ─── 記録状況判定（ハイブリッド）────────────────────────────────────────────

@pytest.mark.integration
class TestRecordedStatus:
    def test_pattern_id_match_within_period_marks_recorded_true(self, db_session):
        # チェックリスト: pattern_id を指定して取引を作成すると、対象期間内であれば true になる
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)
        tx = _create_transaction(db_session, cat, acc, date(2026, 6, 10), pattern=p)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is True
        assert result["current_period_transaction_id"] == tx.id

    def test_category_and_account_fallback_marks_recorded_true(self, db_session):
        # チェックリスト: pattern_id が NULL の取引でも category_id + account_id が一致すれば
        # 対象期間内で true になる（フォールバック）
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)
        tx = _create_transaction(db_session, cat, acc, date(2026, 6, 20), pattern=None)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is True
        assert result["current_period_transaction_id"] == tx.id

    def test_no_matching_transaction_marks_recorded_false_with_null_id(self, db_session):
        # チェックリスト: 対象期間内に該当取引がない場合、false かつ current_period_transaction_id = null
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is False
        assert result["current_period_transaction_id"] is None

    def test_transaction_outside_target_period_not_counted(self, db_session):
        # 対象期間外（先月）の取引はカウントされない
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)
        _create_transaction(db_session, cat, acc, date(2026, 5, 20), pattern=None)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is False

    def test_transfer_pattern_fallback_matches_via_category_and_account(self, db_session):
        # チェックリスト: 資金移動パターンでは to_account_id も一致条件に含まれる
        # （category_id が to_account 側の情報を含めて動的生成されるため、
        #   category_id + account_id の一致で to_account_id の一致も担保される）
        acc_from = _create_account(db_session, "10_財布")
        acc_to = _create_account(db_session, "30_銀行")
        transfer_cat = _create_category(db_session, "【資金移動】- 30_銀行へ -", is_transfer=True)
        p = _create_pattern(
            db_session, transfer_cat, acc_from, to_account=acc_to,
            name="定期送金", payment_day_of_month=10,
        )
        tx = _create_transaction(db_session, transfer_cat, acc_from, date(2026, 6, 10), pattern=None)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is True
        assert result["current_period_transaction_id"] == tx.id

    def test_transfer_pattern_to_different_account_category_does_not_match(self, db_session):
        # 別の送金先向けカテゴリの取引は、to_account が異なるため一致しない
        acc_from = _create_account(db_session, "10_財布")
        acc_to_a = _create_account(db_session, "30_銀行")
        acc_to_b = _create_account(db_session, "40_貯蓄")
        cat_to_a = _create_category(db_session, "【資金移動】- 30_銀行へ -", is_transfer=True)
        cat_to_b = _create_category(db_session, "【資金移動】- 40_貯蓄へ -", is_transfer=True)
        p = _create_pattern(
            db_session, cat_to_a, acc_from, to_account=acc_to_a,
            name="財布から銀行", payment_day_of_month=10,
        )
        # 別の送金先（貯蓄）向けの取引のみ存在
        _create_transaction(db_session, cat_to_b, acc_from, date(2026, 6, 10), pattern=None)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is False

    def test_daily_pattern_always_recorded_false(self, db_session):
        # チェックリスト: daily / other 頻度のパターンは記録状況チェックの対象外
        cat = _create_category(db_session, "食費/スーパー")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, frequency="daily", payment_day_of_month=None)
        _create_transaction(db_session, cat, acc, date(2026, 6, 10), pattern=p)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is False

    def test_other_pattern_always_recorded_false(self, db_session):
        cat = _create_category(db_session, "娯楽/その他")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, frequency="other", payment_day_of_month=None)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is False

    def test_get_patterns_returns_correct_status_for_multiple_patterns(self, db_session):
        # get_patterns（一覧）でも同じ判定ロジックがまとめて1クエリで動くこと
        cat1 = _create_category(db_session, "通信費/携帯")
        cat2 = _create_category(db_session, "水道光熱費/電気")
        acc = _create_account(db_session)
        p1 = _create_pattern(db_session, cat1, acc, name="携帯", payment_day_of_month=15)
        p2 = _create_pattern(db_session, cat2, acc, name="電気", payment_day_of_month=20)
        _create_transaction(db_session, cat1, acc, date(2026, 6, 10), pattern=p1)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            results = {r["id"]: r for r in get_patterns(db_session)}

        assert results[p1.id]["is_current_period_recorded"] is True
        assert results[p2.id]["is_current_period_recorded"] is False


# ─── 記録状況判定（group_id 非対称マッチング）──────────────────────────────
# 対象ADR: docs/adr/0002-pattern-recorded-check-group-match.md

@pytest.mark.integration
class TestRecordedStatusGroupMatch:
    def test_pattern_with_group_id_matches_transaction_with_same_group_id(self, db_session):
        # チェックリスト: パターンに group_id が設定されている場合、取引側の group_id が
        # 一致すれば true になる
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        grp = _create_group(db_session, "20_太郎")
        p = _create_pattern(db_session, cat, acc, group=grp, payment_day_of_month=15)
        tx = _create_transaction(db_session, cat, acc, date(2026, 6, 20), pattern=None, group=grp)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is True
        assert result["current_period_transaction_id"] == tx.id

    def test_pattern_with_group_id_does_not_match_transaction_with_different_group_id(self, db_session):
        # チェックリスト: パターンに group_id が設定されている場合、category_id + account_id が
        # 一致していても取引側の group_id が異なれば false のままになる（グループ違いパターン間の誤判定防止）
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        grp_a = _create_group(db_session, "20_太郎")
        grp_b = _create_group(db_session, "10_必須(通常)")
        p = _create_pattern(db_session, cat, acc, group=grp_a, payment_day_of_month=15)
        _create_transaction(db_session, cat, acc, date(2026, 6, 20), pattern=None, group=grp_b)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is False
        assert result["current_period_transaction_id"] is None

    def test_pattern_with_group_id_does_not_match_transaction_with_null_group_id(self, db_session):
        # パターンに group_id が設定されている場合、取引側の group_id が NULL（未指定）でも
        # 一致とはみなさない
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        grp = _create_group(db_session, "20_太郎")
        p = _create_pattern(db_session, cat, acc, group=grp, payment_day_of_month=15)
        _create_transaction(db_session, cat, acc, date(2026, 6, 20), pattern=None, group=None)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is False

    def test_pattern_without_group_id_matches_transaction_regardless_of_group_id(self, db_session):
        # チェックリスト: パターンの group_id が NULL（グループ未指定）の場合、取引側の group_id の
        # 値に関わらず category_id + account_id の一致のみで true になる（回帰防止の確認）
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        grp = _create_group(db_session, "20_太郎")
        p = _create_pattern(db_session, cat, acc, group=None, payment_day_of_month=15)
        tx = _create_transaction(db_session, cat, acc, date(2026, 6, 20), pattern=None, group=grp)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            result = get_pattern(db_session, p.id)

        assert result["is_current_period_recorded"] is True
        assert result["current_period_transaction_id"] == tx.id

    def test_two_patterns_share_category_and_account_but_differ_by_group_do_not_cross_match(self, db_session):
        # ADR-0002 の核心シナリオ: 同一 category_id + account_id を共有するが group_id が
        # 異なる2つのパターンが存在する場合、一方の記録がもう一方に誤って波及しない
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        grp_a = _create_group(db_session, "20_太郎")
        grp_b = _create_group(db_session, "10_必須(通常)")
        p_a = _create_pattern(db_session, cat, acc, group=grp_a, name="携帯代（太郎）", payment_day_of_month=15)
        p_b = _create_pattern(db_session, cat, acc, group=grp_b, name="携帯代（必須）", payment_day_of_month=15)
        _create_transaction(db_session, cat, acc, date(2026, 6, 20), pattern=None, group=grp_a)

        with patch("app.crud.pattern.today_jst", return_value=date(2026, 6, 20)):
            results = {r["id"]: r for r in get_patterns(db_session)}

        assert results[p_a.id]["is_current_period_recorded"] is True
        assert results[p_b.id]["is_current_period_recorded"] is False


# ─── 実績ベースの次回・前回支払日算出 ────────────────────────────────────────

@pytest.mark.integration
class TestRealizedPaymentDates:
    def test_monthly_recorded_and_past_due_advances_to_next_month(self, db_session):
        # チェックリスト: monthly は今日が支払日より後なら last=当月, next=翌月（記録済みの場合）
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)
        _create_transaction(db_session, cat, acc, date(2026, 6, 15), pattern=p)

        last_pd, next_pd = _calc_payment_dates(p, date(2026, 6, 20), recorded=True)

        assert last_pd == date(2026, 6, 15)
        assert next_pd == date(2026, 7, 15)

    def test_monthly_unrecorded_and_past_due_keeps_next_at_current_month(self, db_session):
        # チェックリスト: 支払日を過ぎても未記録の場合、next_payment_date が
        # 対象期間内の支払日のまま据え置かれる（先送りされない）
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        last_pd, next_pd = _calc_payment_dates(p, date(2026, 6, 20), recorded=False)

        assert next_pd == date(2026, 6, 15)

    def test_monthly_unrecorded_before_due_date_next_is_still_current_month(self, db_session):
        # 支払日前でも未記録なら next は当月の支払日のまま（先送りしない設計に統一）
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        last_pd, next_pd = _calc_payment_dates(p, date(2026, 6, 5), recorded=False)

        assert next_pd == date(2026, 6, 15)

    def test_annual_recorded_and_past_due_advances_to_next_year(self, db_session):
        # チェックリスト: annual は当年支払日が今日より後なら last=前年, next=当年（記録済みの場合）
        # ここでは当年支払日が今日以前のケースを検証: last=当年, next=翌年
        cat = _create_category(db_session, "保険/自動車保険")
        acc = _create_account(db_session)
        p = _create_pattern(
            db_session, cat, acc, frequency="annual",
            payment_day_of_month=20, payment_month_of_year=3,
        )

        last_pd, next_pd = _calc_payment_dates(p, date(2026, 6, 1), recorded=True)

        assert last_pd == date(2026, 3, 20)
        assert next_pd == date(2027, 3, 20)

    def test_annual_unrecorded_keeps_next_at_current_year_period(self, db_session):
        # annual で未記録の場合、next は当年の対象期間の支払日のまま据え置かれる
        cat = _create_category(db_session, "保険/自動車保険")
        acc = _create_account(db_session)
        p = _create_pattern(
            db_session, cat, acc, frequency="annual",
            payment_day_of_month=20, payment_month_of_year=3,
        )

        last_pd, next_pd = _calc_payment_dates(p, date(2026, 6, 1), recorded=False)

        assert next_pd == date(2026, 3, 20)

    def test_no_payment_day_returns_none_none(self, db_session):
        # チェックリスト: payment_day_of_month 未設定の場合は None を返す
        cat = _create_category(db_session, "食費/スーパー")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=None)

        last_pd, next_pd = _calc_payment_dates(p, date(2026, 6, 1), recorded=False)

        assert last_pd is None
        assert next_pd is None

    def test_month_end_clamped_for_short_month(self, db_session):
        # チェックリスト: 月末（31日等）指定で短い月でも正しく月末に丸められる
        cat = _create_category(db_session, "その他/積立")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=31)

        _, next_pd = _calc_payment_dates(p, date(2026, 2, 10), recorded=False)

        assert next_pd == date(2026, 2, 28)  # 2026年は平年


# ─── _filter_due / get_due_patterns（記録済み除外） ─────────────────────────
# 対象ADR: docs/adr/0004-dashboard-due-patterns-exclude-recorded.md

@pytest.mark.integration
class TestFilterDue:
    def test_filter_due_excludes_recorded_pattern(self, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        recorded_lookup = {p.id: {"recorded": True, "transaction_id": 999}}
        result = _filter_due([p], date(2026, 6, 15), recorded_lookup)

        assert result == []

    def test_filter_due_includes_unrecorded_pattern(self, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        recorded_lookup = {p.id: {"recorded": False, "transaction_id": None}}
        result = _filter_due([p], date(2026, 6, 15), recorded_lookup)

        assert result == [p]

    def test_filter_due_defaults_to_unrecorded_when_missing_from_lookup(self, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        result = _filter_due([p], date(2026, 6, 15), {})

        assert result == [p]


@pytest.mark.integration
class TestGetDuePatterns:
    def test_returns_pattern_when_due_today_and_unrecorded(self, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        result = get_due_patterns(db_session, date(2026, 6, 15))

        assert [r["id"] for r in result] == [p.id]

    def test_excludes_pattern_when_due_today_but_already_recorded(self, db_session):
        # チェックリスト: 支払日当日かつ記録済みの場合は除外されること
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)
        _create_transaction(db_session, cat, acc, date(2026, 6, 15), pattern=p)

        result = get_due_patterns(db_session, date(2026, 6, 15))

        assert result == []

    def test_excludes_pattern_when_due_today_and_recorded_via_fallback(self, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)
        _create_transaction(db_session, cat, acc, date(2026, 6, 15), pattern=None)

        result = get_due_patterns(db_session, date(2026, 6, 15))

        assert result == []

    def test_excludes_only_recorded_pattern_keeps_others_due_today(self, db_session):
        cat1 = _create_category(db_session, "通信費/携帯")
        cat2 = _create_category(db_session, "水道光熱費/電気")
        acc = _create_account(db_session)
        p1 = _create_pattern(db_session, cat1, acc, name="携帯", payment_day_of_month=15)
        p2 = _create_pattern(db_session, cat2, acc, name="電気", payment_day_of_month=15)
        _create_transaction(db_session, cat1, acc, date(2026, 6, 15), pattern=p1)

        result = get_due_patterns(db_session, date(2026, 6, 15))

        assert [r["id"] for r in result] == [p2.id]


# ─── get_unrecorded_patterns ─────────────────────────────────────────────────

@pytest.mark.integration
class TestGetUnrecordedPatterns:
    def test_returns_pattern_when_due_date_passed_and_unrecorded(self, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        result = get_unrecorded_patterns(db_session, date(2026, 6, 16))

        assert [r["id"] for r in result] == [p.id]

    def test_excludes_pattern_when_recorded(self, db_session):
        # チェックリスト: 対象期間内に記録済みのパターンが含まれないこと
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, payment_day_of_month=15)
        _create_transaction(db_session, cat, acc, date(2026, 6, 15), pattern=p)

        result = get_unrecorded_patterns(db_session, date(2026, 6, 16))

        assert result == []

    def test_excludes_pattern_when_due_date_not_yet_passed(self, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        result = get_unrecorded_patterns(db_session, date(2026, 6, 10))

        assert result == []

    def test_excludes_pattern_on_exact_due_date(self, db_session):
        # 支払日当日はまだ「過ぎて」いないため対象外（今日の支払いパターンバナー側の役割）
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, payment_day_of_month=15)

        result = get_unrecorded_patterns(db_session, date(2026, 6, 15))

        assert result == []

    def test_excludes_inactive_pattern(self, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, payment_day_of_month=15, is_active=False)

        result = get_unrecorded_patterns(db_session, date(2026, 6, 20))

        assert result == []

    def test_excludes_daily_and_other_patterns(self, db_session):
        # チェックリスト: daily / other 頻度のパターンが含まれないこと
        cat = _create_category(db_session, "食費/スーパー")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, frequency="daily", payment_day_of_month=None)
        _create_pattern(db_session, cat, acc, frequency="other", payment_day_of_month=None, name="その他パターン")

        result = get_unrecorded_patterns(db_session, date(2026, 6, 20))

        assert result == []

    def test_annual_pattern_included_when_past_due_and_unrecorded(self, db_session):
        # チェックリスト: annual パターンで当年の対象期間の支払日を過ぎても未記録の場合に表示されること
        cat = _create_category(db_session, "保険/自動車保険")
        acc = _create_account(db_session)
        p = _create_pattern(
            db_session, cat, acc, frequency="annual",
            payment_day_of_month=20, payment_month_of_year=3,
        )

        result = get_unrecorded_patterns(db_session, date(2026, 6, 1))

        assert [r["id"] for r in result] == [p.id]
