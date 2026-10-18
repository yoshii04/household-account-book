"""
ダッシュボード 動作確認チェックリストのテスト

仕様書: docs/specs/reports/spec_dashboard.md
"""
from datetime import date
from unittest.mock import patch

import pytest

from app.models.account import Account
from app.models.category import Category
from app.models.pattern import TransactionPattern  # noqa: F401 — transaction_patterns テーブル作成のため
from app.models.pattern_group import PatternGroup  # noqa: F401 — pattern_groups テーブル作成のため
from app.models.transaction import Transaction


# ─── テストデータ作成ヘルパー ─────────────────────────────────────────────────

def _create_category(db_session, full_path: str, is_transfer: bool = False) -> Category:
    """カテゴリを作成する。スラッシュがある場合は親も作成する。"""
    parts = full_path.split("/", 1)
    parent = None
    if len(parts) == 2:
        parent = db_session.query(Category).filter(Category.full_path == parts[0]).first()
        if not parent:
            parent = Category(
                code=parts[0], name=parts[0],
                full_path=parts[0], is_transfer=is_transfer,
            )
            db_session.add(parent)
            db_session.flush()
    cat = Category(
        code=parts[-1], name=parts[-1],
        parent_id=parent.id if parent else None,
        full_path=full_path,
        is_transfer=is_transfer,
    )
    db_session.add(cat)
    db_session.flush()
    return cat


def _create_account(db_session, code: str = "10_財布") -> Account:
    acc = Account(code=code, name=code, account_type="cash")
    db_session.add(acc)
    db_session.flush()
    return acc


def _create_transaction(
    db_session,
    category: Category,
    account: Account,
    tx_date: date = None,
    expense: int = 0,
    income: int = 0,
    is_transfer: bool = False,
    memo: str = None,
) -> Transaction:
    tx = Transaction(
        date=tx_date or date(2026, 6, 15),
        category_id=category.id,
        account_id=account.id,
        expense_amount=expense,
        income_amount=income,
        is_transfer=is_transfer,
        memo=memo,
    )
    db_session.add(tx)
    db_session.flush()
    return tx


def _create_pattern(
    db_session,
    category: Category,
    account: Account,
    name: str = "テストパターン",
    frequency: str = "monthly",
    payment_day_of_month: int = 15,
    payment_month_of_year: int = None,
    is_active: bool = True,
    is_income: bool = False,
    typical_amount: int = 1000,
) -> TransactionPattern:
    p = TransactionPattern(
        name=name,
        frequency=frequency,
        category_id=category.id,
        account_id=account.id,
        payment_day_of_month=payment_day_of_month,
        payment_month_of_year=payment_month_of_year,
        is_active=is_active,
        is_income=is_income,
        typical_amount=typical_amount,
    )
    db_session.add(p)
    db_session.flush()
    return p


# ─── ダッシュボード画面: 年月表示 ─────────────────────────────────────────────

@pytest.mark.integration
class TestDashboardCurrentMonth:
    def test_dashboard_shows_current_jst_year_month_in_title(self, api_client):
        # チェックリスト: / にアクセスして当月の年月（JST 基準）がタイトルに表示されること

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 3, 15)
            response = api_client.get("/")

        # Assert
        assert response.status_code == 200
        assert "2026年3月" in response.text

    def test_dashboard_jst_midnight_uses_jst_date_not_utc(self, api_client):
        # チェックリスト: JST と UTC で日付が異なる深夜時間帯（UTC 15:00 = JST 翌 0:00）に
        # JST 基準の当月が正しく反映されること
        # UTC では 3 月末だが JST では翌月 4 月 1 日 0:30 相当のシナリオをシミュレート

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 4, 1)  # JST では 4 月
            response = api_client.get("/")

        # Assert
        assert response.status_code == 200
        assert "2026年4月" in response.text
        assert "2026年3月" not in response.text


# ─── 収支サマリーカード ─────────────────────────────────────────────────────────

@pytest.mark.integration
class TestDashboardSummaryCards:
    def test_summary_cards_show_correct_monthly_income_and_expense(self, api_client, db_session):
        # チェックリスト: 収入・支出・差引の各サマリーカードに当月の正しい集計値が表示されること

        # Arrange
        income_cat = _create_category(db_session, "給与")
        expense_cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, income_cat, acc, tx_date=date(2026, 6, 1), income=300000)
        _create_transaction(db_session, expense_cat, acc, tx_date=date(2026, 6, 10), expense=30000)

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert
        assert response.status_code == 200
        assert "300,000" in response.text  # 収入合計
        assert "30,000" in response.text   # 支出合計

    def test_positive_balance_shows_positive_style(self, api_client, db_session):
        # チェックリスト: 差引が正の場合にサマリーカードが .positive スタイルで表示されること

        # Arrange: 収入 > 支出 → 差引 > 0
        income_cat = _create_category(db_session, "給与")
        expense_cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, income_cat, acc, tx_date=date(2026, 6, 1), income=200000)
        _create_transaction(db_session, expense_cat, acc, tx_date=date(2026, 6, 2), expense=50000)

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert: 差引カードに positive クラスが付与されること
        assert response.status_code == 200
        assert "positive" in response.text
        assert "negative" not in response.text

    def test_negative_balance_shows_negative_style(self, api_client, db_session):
        # チェックリスト: 差引が負の場合にサマリーカードが .negative スタイルで表示されること

        # Arrange: 支出 > 収入 → 差引 < 0
        income_cat = _create_category(db_session, "給与")
        expense_cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, income_cat, acc, tx_date=date(2026, 6, 1), income=30000)
        _create_transaction(db_session, expense_cat, acc, tx_date=date(2026, 6, 2), expense=50000)

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert: 差引カードに negative クラスが付与されること
        assert response.status_code == 200
        assert "negative" in response.text

    def test_transfer_transactions_excluded_from_summary(self, api_client, db_session):
        # チェックリスト: 費目別支出の円グラフに当月の支出カテゴリが描画されること（資金移動カテゴリが含まれないこと）
        # is_transfer=True の取引は集計から除外され、支出合計に加算されないことを確認する

        # Arrange: 通常支出 3,000 + 資金移動 10,000（除外対象）
        transfer_cat = _create_category(db_session, "【資金移動】/財布→銀行", is_transfer=True)
        expense_cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(
            db_session, transfer_cat, acc,
            tx_date=date(2026, 6, 1), expense=10000, is_transfer=True,
        )
        _create_transaction(db_session, expense_cat, acc, tx_date=date(2026, 6, 2), expense=3000)

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert: 通常支出 3,000 は表示、資金移動 10,000 が加算された 13,000 は表示されない
        assert response.status_code == 200
        assert "3,000" in response.text
        assert "13,000" not in response.text


# ─── 直近の取引テーブル ─────────────────────────────────────────────────────────

@pytest.mark.integration
class TestDashboardRecentTransactions:
    def test_recent_transactions_shows_max_5_items(self, api_client, db_session):
        # チェックリスト: 直近の取引テーブルに当月の非資金移動取引が最大 5 件表示されること

        # Arrange: 6 件登録（うち最大 5 件のみ表示されるはず）
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        for i in range(6):
            _create_transaction(
                db_session, cat, acc,
                tx_date=date(2026, 6, i + 1), expense=1000,
            )

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert: 5 件分の ¥1,000 が表示され、6 件目は含まれない
        assert response.status_code == 200
        assert response.text.count("¥1,000") == 5

    def test_show_all_link_contains_year_and_month(self, api_client):
        # チェックリスト: 「すべて表示 →」リンクが /transactions?year={year}&month={month} に正しく遷移すること

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert: year と month を含むリンクが出力されること（& の HTML エスケープ両形式に対応）
        assert response.status_code == 200
        assert "year=2026" in response.text
        assert "month=6" in response.text
        assert "/transactions" in response.text

    def test_show_all_link_contains_f_flag_to_keep_transfer_excluded(self, api_client):
        # チェックリスト: 「すべて表示 →」リンクが、直近の取引（資金移動除外）と同じ絞り込み
        # 条件を維持するため `f=1` を付与すること（付与しないと取引一覧側の「初回アクセス」
        # 扱いになり、資金移動を含む表示にデフォルトが変わってしまうため）
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        assert response.status_code == 200
        assert 'href="/transactions?year=2026&month=6&f=1"' in response.text

    def test_empty_transactions_shows_no_data_message(self, api_client):
        # チェックリスト: 当月に取引が 0 件の場合、直近取引テーブルに「データなし」が表示されること

        # Act: データなしの状態でダッシュボードにアクセス
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert
        assert response.status_code == 200
        assert "データなし" in response.text

    def test_transfer_transactions_excluded_from_recent_items(self, api_client, db_session):
        # 仕様: 直近取引テーブルには is_transfer=True の取引が表示されないこと（0 件として扱われる）

        # Arrange: 資金移動取引のみ登録
        transfer_cat = _create_category(db_session, "【資金移動】/財布→銀行", is_transfer=True)
        acc = _create_account(db_session)
        _create_transaction(
            db_session, transfer_cat, acc,
            tx_date=date(2026, 6, 1), expense=10000, is_transfer=True,
        )

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert: 資金移動のみなので「データなし」が表示される
        assert response.status_code == 200
        assert "データなし" in response.text


# ─── 今日のパターン通知バナー ─────────────────────────────────────────────────

@pytest.mark.integration
class TestDashboardDuePatternsBanner:
    def test_monthly_pattern_due_today_shows_banner(self, api_client, db_session):
        # チェックリスト: 今日が payment_day_of_month に一致するアクティブな monthly パターンがある場合、バナーが表示されること

        # Arrange: 支払日が 15 日の monthly パターンを登録
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, name="携帯料金", frequency="monthly",
                        payment_day_of_month=15)

        # Act: 今日が 6 月 15 日
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert: バナーにパターン名が表示されること
        assert response.status_code == 200
        assert "携帯料金" in response.text
        assert "due-patterns-banner" in response.text

    def test_annual_pattern_due_today_shows_banner(self, api_client, db_session):
        # チェックリスト: 今日が payment_day_of_month かつ payment_month_of_year に一致するアクティブな
        # annual パターンがある場合、バナーが表示されること

        # Arrange: 6 月 20 日 の annual パターンを登録
        cat = _create_category(db_session, "保険/自動車保険")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, name="自動車保険", frequency="annual",
                        payment_day_of_month=20, payment_month_of_year=6)

        # Act: 今日が 6 月 20 日（月・日ともに一致）
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 20)
            response = api_client.get("/")

        # Assert: バナーにパターン名が表示されること
        assert response.status_code == 200
        assert "自動車保険" in response.text
        assert "due-patterns-banner" in response.text

    def test_annual_pattern_wrong_month_does_not_show_banner(self, api_client, db_session):
        # 仕様: annual パターンは payment_month_of_year が一致しない月では表示されないこと

        # Arrange: 6 月 20 日の annual パターンを登録
        cat = _create_category(db_session, "保険/自動車保険")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, name="自動車保険", frequency="annual",
                        payment_day_of_month=20, payment_month_of_year=6)

        # Act: 今日は 7 月 20 日（日は一致するが月が違う）
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 7, 20)
            response = api_client.get("/")

        # Assert: 今日の支払いバナーには表示されない
        # (ADR-0001 により、6月分が未記録のままなら「今月未記録のパターン」セクションには
        #  7月時点でも表示されうるため、ページ全体からの不在は検証しない)
        assert response.status_code == 200
        assert "due-patterns-banner" not in response.text

    def test_no_due_patterns_hides_banner(self, api_client):
        # チェックリスト: 今日が支払日のパターンがない場合、バナーが表示されないこと

        # Act: パターンが 0 件の状態でアクセス
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert
        assert response.status_code == 200
        assert "due-patterns-banner" not in response.text

    def test_inactive_pattern_not_shown_in_banner(self, api_client, db_session):
        # 仕様: is_active=False のパターンはバナーに表示されないこと

        # Arrange: is_active=False の monthly パターン（支払日は一致）
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, name="無効パターン", frequency="monthly",
                        payment_day_of_month=15, is_active=False)

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert: 無効パターンはバナーに表示されない
        assert response.status_code == 200
        assert "無効パターン" not in response.text
        assert "due-patterns-banner" not in response.text

    def test_due_pattern_banner_links_to_transaction_new_with_pattern_id(self, api_client, db_session):
        # チェックリスト: バナーの「入力する →」ボタンが /transactions/new?pattern_id={id} に遷移すること

        # Arrange
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, name="携帯料金", frequency="monthly",
                            payment_day_of_month=15)

        # Act
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        # Assert: バナーの「入力する」リンクに pattern_id が含まれること
        assert response.status_code == 200
        assert f"/transactions/new?pattern_id={p.id}" in response.text

    def test_recorded_pattern_not_shown_in_due_banner(self, api_client, db_session):
        # チェックリスト: 今日が支払日のパターンでも、対象期間について記録済み
        # （is_current_period_recorded = true）の場合はバナーに表示されないこと。
        # 記録済みパターンが今日の支払いパターンとして唯一の対象のため、
        # バナー自体が表示されないこと（対象ADR: 0004）も同時に検証する
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, name="携帯料金", frequency="monthly",
                        payment_day_of_month=15)
        _create_transaction(db_session, cat, acc, date(2026, 6, 15))

        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        assert response.status_code == 200
        assert "携帯料金" not in response.text
        assert "due-patterns-banner" not in response.text

    def test_recorded_pattern_excluded_but_others_due_today_still_shown(self, api_client, db_session):
        # 対象ADR: docs/adr/0004-dashboard-due-patterns-exclude-recorded.md
        # 記録済みパターンのみがバナーから除外され、未記録の他パターンは表示され続けること
        cat1 = _create_category(db_session, "通信費/携帯")
        cat2 = _create_category(db_session, "水道光熱費/電気")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat1, acc, name="携帯料金", frequency="monthly",
                        payment_day_of_month=15)
        _create_pattern(db_session, cat2, acc, name="電気料金", frequency="monthly",
                        payment_day_of_month=15)
        _create_transaction(db_session, cat1, acc, date(2026, 6, 15))

        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        assert response.status_code == 200
        assert "due-patterns-banner" in response.text
        assert "携帯料金" not in response.text
        assert "電気料金" in response.text


# ─── 今月未記録のパターン（ADR-0001） ────────────────────────────────────────
# 対象ADR: docs/adr/0001-pattern-payment-status-tracking.md

@pytest.mark.integration
class TestDashboardUnrecordedPatterns:
    def test_unrecorded_pattern_past_due_shows_in_section(self, api_client, db_session):
        # チェックリスト: 支払日を過ぎても未記録のアクティブパターンがある場合、
        # 「今月未記録のパターン」セクションに表示されること
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, name="携帯料金", frequency="monthly",
                        payment_day_of_month=10)

        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        assert response.status_code == 200
        assert "unrecorded-patterns-section" in response.text
        assert "携帯料金" in response.text

    def test_recorded_pattern_not_shown_in_unrecorded_section(self, api_client, db_session):
        # チェックリスト: 対象期間内に記録済みのパターンが含まれないこと
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, name="携帯料金", frequency="monthly",
                            payment_day_of_month=10)
        _create_transaction(db_session, cat, acc, tx_date=date(2026, 6, 10), expense=3000)

        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        assert response.status_code == 200
        assert "unrecorded-patterns-section" not in response.text

    def test_no_unrecorded_patterns_hides_section(self, api_client):
        # チェックリスト: 該当パターンが0件の場合、セクションが表示されないこと
        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        assert response.status_code == 200
        assert "unrecorded-patterns-section" not in response.text

    def test_daily_pattern_not_shown_in_unrecorded_section(self, api_client, db_session):
        # チェックリスト: daily / other 頻度のパターンが含まれないこと
        cat = _create_category(db_session, "食費/スーパー")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, name="日次パターン", frequency="daily",
                        payment_day_of_month=None)

        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        assert response.status_code == 200
        assert "unrecorded-patterns-section" not in response.text

    def test_annual_pattern_past_due_and_unrecorded_shows_in_section(self, api_client, db_session):
        # チェックリスト: annual パターンで当年の対象期間の支払日を過ぎても未記録の場合に表示されること
        cat = _create_category(db_session, "保険/自動車保険")
        acc = _create_account(db_session)
        _create_pattern(db_session, cat, acc, name="自動車保険", frequency="annual",
                        payment_day_of_month=20, payment_month_of_year=3)

        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 1)
            response = api_client.get("/")

        assert response.status_code == 200
        assert "unrecorded-patterns-section" in response.text
        assert "自動車保険" in response.text

    def test_unrecorded_pattern_links_to_transaction_new_with_pattern_id(self, api_client, db_session):
        # チェックリスト: 「入力する →」ボタンが /transactions/new?pattern_id={id} に遷移すること
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, name="携帯料金", frequency="monthly",
                            payment_day_of_month=10)

        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        assert response.status_code == 200
        assert f"/transactions/new?pattern_id={p.id}" in response.text

    def test_unrecorded_pattern_link_includes_missed_due_date(self, api_client, db_session):
        # 未記録の支払日（次回支払日が据え置かれた対象期間内の支払日）をURLに含めることで、
        # 「入力する」リンクから今日の日付でなく本来の支払日でフォームを開始できること
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc, name="携帯料金", frequency="monthly",
                            payment_day_of_month=10)

        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 6, 15)
            response = api_client.get("/")

        assert response.status_code == 200
        assert f"/transactions/new?pattern_id={p.id}&date=2026-06-10" in response.text
