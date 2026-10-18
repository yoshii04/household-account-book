"""
取引管理 動作確認チェックリストのテスト

仕様書: docs/specs/core/spec_transactions.md
"""
import pytest
from datetime import date
from unittest.mock import patch

from app.models.account import Account
from app.models.category import Category
from app.models.pattern import TransactionPattern
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
    expense: int = 500,
    income: int = 0,
    memo: str = "",
    is_transfer: bool = False,
) -> Transaction:
    tx = Transaction(
        date=tx_date or date(2024, 1, 15),
        category_id=category.id,
        account_id=account.id,
        expense_amount=expense,
        income_amount=income,
        memo=memo,
        is_transfer=is_transfer,
    )
    db_session.add(tx)
    db_session.flush()
    return tx


# ─── 取引一覧ページレンダリング ──────────────────────────────────────────────

@pytest.mark.integration
class TestTransactionListPage:
    def test_transactions_page_without_filter_returns_200(self, api_client):
        # チェックリスト: 取引一覧：初回アクセス時（`f` パラメータなし）で当月が自動選択されること
        response = api_client.get("/transactions")
        assert response.status_code == 200

    def test_transactions_new_page_without_params_returns_200(self, api_client):
        # チェックリスト: 取引入力フォーム画面が正常に表示されること
        response = api_client.get("/transactions/new")
        assert response.status_code == 200


# ─── 取引一覧 API フィルター ────────────────────────────────────────────────

@pytest.mark.integration
class TestTransactionListFilters:
    def test_filter_by_category_id_includes_children(self, api_client, db_session):
        # チェックリスト: 取引一覧：年・月・カテゴリ・アカウント・グループ・メモ検索の各フィルターが正しく機能すること
        cat1 = _create_category(db_session, "食費/外食")
        cat2 = _create_category(db_session, "交通費/電車")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat1, acc, expense=500)
        _create_transaction(db_session, cat2, acc, expense=200)

        # 親カテゴリIDでフィルターすると子カテゴリの取引も含む
        parent_id = cat1.parent_id
        res = api_client.get(f"/api/v1/transactions?category_id={parent_id}")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["items"][0]["expense_amount"] == 500

    def test_filter_by_account_id_returns_only_matching_transactions(self, api_client, db_session):
        # チェックリスト: 取引一覧：年・月・カテゴリ・アカウント・グループ・メモ検索の各フィルターが正しく機能すること
        cat = _create_category(db_session, "食費/外食")
        acc1 = _create_account(db_session, "10_財布")
        acc2 = _create_account(db_session, "30_銀行")
        _create_transaction(db_session, cat, acc1, expense=300)
        _create_transaction(db_session, cat, acc2, expense=400)

        res = api_client.get(f"/api/v1/transactions?account_id={acc1.id}")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["items"][0]["expense_amount"] == 300

    def test_filter_by_memo_search_returns_only_matching_transactions(self, api_client, db_session):
        # チェックリスト: 取引一覧：年・月・カテゴリ・アカウント・グループ・メモ検索の各フィルターが正しく機能すること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, memo="コーヒー代", expense=400)
        _create_transaction(db_session, cat, acc, memo="ランチ", expense=800)

        res = api_client.get("/api/v1/transactions?search=コーヒー")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["items"][0]["memo"] == "コーヒー代"

    def test_filter_by_category_search_returns_only_matching_transactions(self, api_client, db_session):
        # チェックリスト: 取引一覧：年・月・カテゴリ・アカウント・グループ・メモ検索の各フィルターが正しく機能すること
        cat1 = _create_category(db_session, "食費/外食")
        cat2 = _create_category(db_session, "交通費/電車")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat1, acc, expense=500)
        _create_transaction(db_session, cat2, acc, expense=200)

        res = api_client.get("/api/v1/transactions?search=交通費")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert "交通費" in body["items"][0]["category_full_path"]


# ─── 取引一覧 API：資金移動フィルター ──────────────────────────────────────

@pytest.mark.integration
class TestTransactionTransferFilter:
    def test_transaction_list_with_default_filter_excludes_transfer_transactions(self, api_client, db_session):
        # チェックリスト: 取引一覧：「資金移動を含む」チェックオンで資金移動取引も表示されること
        cat_normal = _create_category(db_session, "食費/外食")
        cat_transfer = _create_category(db_session, "【資金移動】", is_transfer=True)
        acc = _create_account(db_session)
        _create_transaction(db_session, cat_normal, acc, expense=500)
        tx_transfer = Transaction(
            date=date(2024, 1, 15),
            category_id=cat_transfer.id,
            account_id=acc.id,
            expense_amount=1000,
            income_amount=0,
            is_transfer=True,
        )
        db_session.add(tx_transfer)
        db_session.flush()

        # デフォルト（is_transfer=False）では資金移動を除外
        res = api_client.get("/api/v1/transactions")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["items"][0]["is_transfer"] is False

    def test_transaction_list_with_is_transfer_true_returns_only_transfer_transactions(self, api_client, db_session):
        # チェックリスト: 取引一覧：「資金移動を含む」チェックオンで資金移動取引も表示されること
        # API: is_transfer=True → 資金移動取引のみを返す
        cat_normal = _create_category(db_session, "食費/外食")
        cat_transfer = _create_category(db_session, "【資金移動】", is_transfer=True)
        acc = _create_account(db_session)
        _create_transaction(db_session, cat_normal, acc, expense=500)
        tx_transfer = Transaction(
            date=date(2024, 1, 15),
            category_id=cat_transfer.id,
            account_id=acc.id,
            expense_amount=1000,
            income_amount=0,
            is_transfer=True,
        )
        db_session.add(tx_transfer)
        db_session.flush()

        res = api_client.get("/api/v1/transactions?is_transfer=true")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] >= 1
        assert all(item["is_transfer"] for item in body["items"])

    def test_transactions_page_with_is_transfer_true_returns_200(self, api_client, db_session):
        # チェックリスト: 取引一覧：「資金移動を含む」チェックオン時にページが正常表示されること
        # ページでは is_transfer=True → effective_is_transfer=None（全件）に変換する
        cat_transfer = _create_category(db_session, "【資金移動】", is_transfer=True)
        acc = _create_account(db_session)
        tx_transfer = Transaction(
            date=date(2024, 1, 15),
            category_id=cat_transfer.id,
            account_id=acc.id,
            expense_amount=1000,
            income_amount=0,
            is_transfer=True,
        )
        db_session.add(tx_transfer)
        db_session.flush()

        res = api_client.get("/transactions?is_transfer=true")
        assert res.status_code == 200

    def test_transactions_page_first_visit_includes_transfer_by_default(self, api_client, db_session):
        # チェックリスト: 取引一覧：初回アクセス時（`f` パラメータなし）で「資金移動を含む」
        # チェックボックスがオン（資金移動を含む表示）になっていること
        cat_transfer = _create_category(db_session, "【資金移動】", is_transfer=True)
        acc = _create_account(db_session)
        _create_transaction(
            db_session, cat_transfer, acc, tx_date=date(2026, 3, 15),
            expense=1000, memo="資金移動デフォルト表示テスト", is_transfer=True,
        )

        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 3, 15)
            res = api_client.get("/transactions")

        assert res.status_code == 200
        assert "資金移動デフォルト表示テスト" in res.text

    def test_transactions_page_form_submitted_without_is_transfer_excludes_transfer(self, api_client, db_session):
        # チェックリスト: 取引一覧：フィルターフォーム送信時（`f=1`）に「資金移動を含む」
        # チェックを外して絞り込むと、資金移動が除外されること
        cat_transfer = _create_category(db_session, "【資金移動】", is_transfer=True)
        acc = _create_account(db_session)
        _create_transaction(
            db_session, cat_transfer, acc, tx_date=date(2026, 3, 15),
            expense=1000, memo="資金移動除外テスト", is_transfer=True,
        )

        # f=1（フォーム送信済み）で is_transfer 未指定 = チェックを外して送信した扱い
        res = api_client.get("/transactions?f=1")

        assert res.status_code == 200
        assert "資金移動除外テスト" not in res.text

    def test_transactions_page_first_visit_explicit_is_transfer_false_excludes_transfer(self, api_client, db_session):
        # チェックリスト: 取引一覧：初回アクセス時でも `is_transfer=false` が明示的に指定された場合は送信値を優先すること
        cat_transfer = _create_category(db_session, "【資金移動】", is_transfer=True)
        acc = _create_account(db_session)
        _create_transaction(
            db_session, cat_transfer, acc, tx_date=date(2026, 3, 15),
            expense=1000, memo="資金移動明示除外テスト", is_transfer=True,
        )

        with patch("app.routers.pages.today_jst") as mock_today:
            mock_today.return_value = date(2026, 3, 15)
            res = api_client.get("/transactions?is_transfer=false")

        assert res.status_code == 200
        assert "資金移動明示除外テスト" not in res.text


# ─── 取引一覧ページ：ソート ────────────────────────────────────────────────
# ソート機能はページエンドポイント（/transactions）で実装されており、
# API（/api/v1/transactions）ではなくページルーターが sort_by/sort_dir を処理する。

@pytest.mark.integration
class TestTransactionSort:
    def test_page_sort_by_date_asc_returns_200(self, api_client, db_session):
        # チェックリスト: 取引一覧：各列のヘッダークリックでソートが切り替わり、同列クリックで昇順・降順が反転すること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, tx_date=date(2024, 3, 1), expense=300)
        _create_transaction(db_session, cat, acc, tx_date=date(2024, 1, 1), expense=100)

        # ページエンドポイントでソートパラメータを受け付けること
        res = api_client.get("/transactions?sort_by=date&sort_dir=asc")
        assert res.status_code == 200

    def test_page_sort_by_date_desc_returns_200(self, api_client, db_session):
        # チェックリスト: 取引一覧：各列のヘッダークリックでソートが切り替わり、同列クリックで昇順・降順が反転すること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, tx_date=date(2024, 3, 1), expense=300)
        _create_transaction(db_session, cat, acc, tx_date=date(2024, 1, 1), expense=100)

        res = api_client.get("/transactions?sort_by=date&sort_dir=desc")
        assert res.status_code == 200

    def test_page_sort_by_expense_amount_returns_200(self, api_client, db_session):
        # チェックリスト: 取引一覧：各列のヘッダークリックでソートが切り替わり、同列クリックで昇順・降順が反転すること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, expense=500)
        _create_transaction(db_session, cat, acc, expense=100)

        # 出金額ソート（昇順）でページが正常表示されること
        res = api_client.get("/transactions?sort_by=expense_amount&sort_dir=asc")
        assert res.status_code == 200

    def test_api_default_sort_is_date_desc(self, api_client, db_session):
        # チェックリスト: 取引一覧：各列のヘッダークリックでソートが切り替わり、同列クリックで昇順・降順が反転すること
        # API のデフォルトソートは日付降順
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, tx_date=date(2024, 1, 1), expense=100)
        _create_transaction(db_session, cat, acc, tx_date=date(2024, 3, 1), expense=300)
        _create_transaction(db_session, cat, acc, tx_date=date(2024, 2, 1), expense=200)

        res = api_client.get("/api/v1/transactions")
        assert res.status_code == 200
        items = res.json()["items"]
        dates = [item["date"] for item in items]
        # デフォルトは日付降順（新しい順）
        assert dates == sorted(dates, reverse=True)


# ─── 取引一覧 API：ページネーション ────────────────────────────────────────

@pytest.mark.integration
class TestTransactionPagination:
    def test_transaction_list_api_default_per_page_is_50(self, api_client, db_session):
        # チェックリスト: 取引一覧：ページネーションが50件単位で機能すること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        for i in range(55):
            db_session.add(Transaction(
                date=date(2024, 1, i % 28 + 1),
                category_id=cat.id,
                account_id=acc.id,
                expense_amount=100,
                income_amount=0,
            ))
        db_session.flush()

        res = api_client.get("/api/v1/transactions")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 55
        assert len(body["items"]) == 50
        assert body["per_page"] == 50

    def test_transaction_list_api_page2_returns_remaining_items(self, api_client, db_session):
        # チェックリスト: 取引一覧：ページネーションが50件単位で機能すること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        for i in range(55):
            db_session.add(Transaction(
                date=date(2024, 1, i % 28 + 1),
                category_id=cat.id,
                account_id=acc.id,
                expense_amount=100,
                income_amount=0,
            ))
        db_session.flush()

        res = api_client.get("/api/v1/transactions?page=2")
        assert res.status_code == 200
        body = res.json()
        assert len(body["items"]) == 5


# ─── 取引削除 ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestTransactionDelete:
    def test_delete_existing_transaction_returns_204(self, api_client, db_session):
        # チェックリスト: 取引一覧：削除ボタンで confirm 後に取引が削除されること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        tx = _create_transaction(db_session, cat, acc)

        res = api_client.delete(f"/api/v1/transactions/{tx.id}")
        assert res.status_code == 204

    def test_get_deleted_transaction_returns_404(self, api_client, db_session):
        # チェックリスト: 取引一覧：削除後に取引が存在しないこと
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        tx = _create_transaction(db_session, cat, acc)

        api_client.delete(f"/api/v1/transactions/{tx.id}")

        res = api_client.get(f"/api/v1/transactions/{tx.id}")
        assert res.status_code == 404

    def test_delete_nonexistent_transaction_returns_404(self, api_client):
        # チェックリスト: 取引一覧：削除ボタンで confirm 後に取引が削除されること
        res = api_client.delete("/api/v1/transactions/999999")
        assert res.status_code == 404


# ─── Excel エクスポート ──────────────────────────────────────────────────────

@pytest.mark.integration
class TestTransactionExcelExport:
    def test_excel_export_with_date_filter_returns_xlsx_content_type(self, api_client, db_session):
        # チェックリスト: 取引一覧：Excel出力ボタンで現在のフィルター条件が引き継がれること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, tx_date=date(2024, 3, 10), expense=500)

        res = api_client.get("/transactions/export/excel?year=2024&month=3")
        assert res.status_code == 200
        content_type = res.headers.get("content-type", "")
        assert "spreadsheetml" in content_type or "officedocument" in content_type

    def test_excel_export_with_month_filter_returns_200(self, api_client, db_session):
        # チェックリスト: 取引一覧：Excel出力ボタンで現在のフィルター条件が引き継がれること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, tx_date=date(2024, 1, 10), expense=100)
        _create_transaction(db_session, cat, acc, tx_date=date(2024, 2, 10), expense=200)

        # 月フィルター付きエクスポートが 200 を返すこと
        res = api_client.get("/transactions/export/excel?year=2024&month=1")
        assert res.status_code == 200


# ─── カテゴリ別直近N件 ──────────────────────────────────────────────────────

@pytest.mark.integration
class TestRecentByCategory:
    def test_recent_by_category_with_over_10_items_returns_at_most_10(self, api_client, db_session):
        # チェックリスト: 取引入力：カテゴリ選択後にそのカテゴリの直近10件が表示されること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        for i in range(15):
            db_session.add(Transaction(
                date=date(2024, 1, i % 28 + 1),
                category_id=cat.id,
                account_id=acc.id,
                expense_amount=100 * (i + 1),
                income_amount=0,
            ))
        db_session.flush()

        res = api_client.get(f"/api/v1/transactions/recent/by-category/{cat.id}")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 10

    def test_recent_by_category_when_transfer_exists_excludes_transfer_transactions(self, api_client, db_session):
        # チェックリスト: 取引入力：カテゴリ選択後にそのカテゴリの直近10件が表示されること（資金移動除外）
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, expense=500)
        # 同カテゴリで is_transfer=True の取引を追加
        tx_transfer = Transaction(
            date=date(2024, 1, 15),
            category_id=cat.id,
            account_id=acc.id,
            expense_amount=1000,
            income_amount=0,
            is_transfer=True,
        )
        db_session.add(tx_transfer)
        db_session.flush()

        res = api_client.get(f"/api/v1/transactions/recent/by-category/{cat.id}")
        assert res.status_code == 200
        items = res.json()
        assert all(not item["is_transfer"] for item in items)

    def test_recent_by_category_with_custom_limit_returns_specified_count(self, api_client, db_session):
        # チェックリスト: 取引入力：カテゴリ選択後にそのカテゴリの直近10件が表示されること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        for i in range(5):
            _create_transaction(db_session, cat, acc, expense=100 * (i + 1))

        res = api_client.get(f"/api/v1/transactions/recent/by-category/{cat.id}?limit=3")
        assert res.status_code == 200
        assert len(res.json()) == 3

    def test_recent_by_category_with_fewer_than_10_items_returns_all(self, api_client, db_session):
        # チェックリスト: 取引入力：カテゴリ選択後にそのカテゴリの直近10件が表示されること（件数が少ない場合）
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        for i in range(3):
            _create_transaction(db_session, cat, acc, expense=100)

        res = api_client.get(f"/api/v1/transactions/recent/by-category/{cat.id}")
        assert res.status_code == 200
        assert len(res.json()) == 3


# ─── フリーワード検索 ────────────────────────────────────────────────────────

@pytest.mark.integration
class TestTransactionSearch:
    def test_search_by_memo_returns_matching_transaction(self, api_client, db_session):
        # チェックリスト: 取引入力：フリーワード検索でメモ・カテゴリを横断検索できること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, memo="スターバックス", expense=500)
        _create_transaction(db_session, cat, acc, memo="ランチ", expense=800)

        res = api_client.get("/api/v1/transactions/search?q=スターバックス")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 1
        assert items[0]["memo"] == "スターバックス"

    def test_search_by_category_full_path_returns_matching_transaction(self, api_client, db_session):
        # チェックリスト: 取引入力：フリーワード検索でメモ・カテゴリを横断検索できること
        cat1 = _create_category(db_session, "食費/外食")
        cat2 = _create_category(db_session, "交通費/電車")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat1, acc, expense=500)
        _create_transaction(db_session, cat2, acc, expense=200)

        res = api_client.get("/api/v1/transactions/search?q=交通費")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 1
        assert "交通費" in items[0]["category_full_path"]

    def test_search_when_transfer_exists_excludes_transfer_transactions(self, api_client, db_session):
        # チェックリスト: フリーワード検索は is_transfer=False の取引のみ対象
        cat = _create_category(db_session, "食費/外食")
        cat_transfer = _create_category(db_session, "【資金移動】", is_transfer=True)
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, memo="テスト購入", expense=500)
        db_session.add(Transaction(
            date=date(2024, 1, 15),
            category_id=cat_transfer.id,
            account_id=acc.id,
            expense_amount=1000,
            income_amount=0,
            is_transfer=True,
            memo="テスト移動",
        ))
        db_session.flush()

        res = api_client.get("/api/v1/transactions/search?q=テスト")
        assert res.status_code == 200
        items = res.json()
        assert all(not item["is_transfer"] for item in items)

    def test_search_missing_q_returns_422(self, api_client):
        # チェックリスト: フリーワード検索は q パラメータ必須
        res = api_client.get("/api/v1/transactions/search")
        assert res.status_code == 422


# ─── 取引作成（一括登録） ────────────────────────────────────────────────────

@pytest.mark.integration
class TestTransactionCreate:
    def test_create_single_expense_transaction_returns_201_with_correct_fields(self, api_client, db_session):
        # チェックリスト: 取引入力：一括登録で複数取引を選択して日付・金額を変更してまとめて登録できること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)

        res = api_client.post("/api/v1/transactions", json={
            "date": "2024-03-15",
            "category_id": cat.id,
            "account_id": acc.id,
            "income_amount": 0,
            "expense_amount": 1500,
            "memo": "ランチ",
        })
        assert res.status_code == 201
        body = res.json()
        assert body["expense_amount"] == 1500
        assert body["memo"] == "ランチ"
        assert body["category_full_path"] == "食費/外食"

    def test_bulk_create_multiple_transactions_all_return_201(self, api_client, db_session):
        # チェックリスト: 取引入力：一括登録で複数取引を選択して日付・金額を変更してまとめて登録できること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)

        # 複数件を逐次登録（フロントエンドは逐次 POST 呼び出し）
        amounts = [500, 800, 1200]
        for amount in amounts:
            res = api_client.post("/api/v1/transactions", json={
                "date": "2024-03-15",
                "category_id": cat.id,
                "account_id": acc.id,
                "income_amount": 0,
                "expense_amount": amount,
            })
            assert res.status_code == 201

        res_list = api_client.get("/api/v1/transactions?year=2024&month=3")
        assert res_list.json()["total"] == 3

    def test_create_income_transaction_returns_201_with_income_amount(self, api_client, db_session):
        # チェックリスト: 取引入力：入金取引の作成が正しく機能すること
        cat = _create_category(db_session, "給与/月給")
        acc = _create_account(db_session)

        res = api_client.post("/api/v1/transactions", json={
            "date": "2024-03-25",
            "category_id": cat.id,
            "account_id": acc.id,
            "income_amount": 250000,
            "expense_amount": 0,
        })
        assert res.status_code == 201
        body = res.json()
        assert body["income_amount"] == 250000
        assert body["expense_amount"] == 0


# ─── 資金移動取引 ────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestTransactionTransfer:
    def test_transfer_with_valid_accounts_creates_two_transactions(self, api_client, db_session):
        # チェックリスト: 資金移動：送信後に出金・入金の2件が作成されること
        acc1 = _create_account(db_session, "10_財布")
        acc2 = _create_account(db_session, "30_銀行")

        res = api_client.post("/api/v1/transactions/transfer", json={
            "date": "2024-03-15",
            "from_account_id": acc1.id,
            "to_account_id": acc2.id,
            "amount": 5000,
        })
        assert res.status_code == 201
        body = res.json()
        assert "expense_tx" in body
        assert "income_tx" in body
        assert body["expense_tx"]["expense_amount"] == 5000
        assert body["income_tx"]["income_amount"] == 5000

    def test_transfer_with_valid_accounts_category_names_follow_format(self, api_client, db_session):
        # チェックリスト: 資金移動：送金元・送金先カテゴリが `【資金移動】- {code}へ -` / `- {code}から -` 形式で自動生成されること
        acc1 = _create_account(db_session, "10_財布")
        acc2 = _create_account(db_session, "30_銀行")

        res = api_client.post("/api/v1/transactions/transfer", json={
            "date": "2024-03-15",
            "from_account_id": acc1.id,
            "to_account_id": acc2.id,
            "amount": 3000,
        })
        assert res.status_code == 201
        body = res.json()
        # 出金側: 【資金移動】- {to_account.code}へ -
        expense_detail = body["expense_tx"]["transfer_detail"]
        assert expense_detail == "【資金移動】- 30_銀行へ -"
        # 入金側: 【資金移動】- {from_account.code}から -
        income_detail = body["income_tx"]["transfer_detail"]
        assert income_detail == "【資金移動】- 10_財布から -"

    def test_transfer_with_valid_accounts_both_flagged_as_is_transfer(self, api_client, db_session):
        # チェックリスト: 資金移動：送信後に出金・入金の2件が作成されること（is_transfer=True）
        acc1 = _create_account(db_session, "10_財布")
        acc2 = _create_account(db_session, "30_銀行")

        res = api_client.post("/api/v1/transactions/transfer", json={
            "date": "2024-03-15",
            "from_account_id": acc1.id,
            "to_account_id": acc2.id,
            "amount": 2000,
        })
        assert res.status_code == 201
        body = res.json()
        assert body["expense_tx"]["is_transfer"] is True
        assert body["income_tx"]["is_transfer"] is True

    def test_transfer_with_valid_accounts_categories_auto_created_under_parent(self, api_client, db_session):
        # チェックリスト: 資金移動：送金元・送金先カテゴリが `【資金移動】- {code}へ -` / `- {code}から -` 形式で自動生成されること
        acc1 = _create_account(db_session, "10_財布")
        acc2 = _create_account(db_session, "30_銀行")

        res = api_client.post("/api/v1/transactions/transfer", json={
            "date": "2024-03-15",
            "from_account_id": acc1.id,
            "to_account_id": acc2.id,
            "amount": 1000,
        })
        assert res.status_code == 201
        body = res.json()
        # カテゴリが 【資金移動】 親カテゴリの配下に作成されている
        expense_path = body["expense_tx"]["category_full_path"]
        income_path = body["income_tx"]["category_full_path"]
        assert expense_path.startswith("【資金移動】")
        assert income_path.startswith("【資金移動】")


# ─── 取引更新 ────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestTransactionUpdate:
    def test_update_transaction_memo_and_amount_returns_updated_values(self, api_client, db_session):
        # チェックリスト: 取引編集：保存後に元の一覧（return_url）へリダイレクトされること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        tx = _create_transaction(db_session, cat, acc, expense=500, memo="更新前")

        res = api_client.put(f"/api/v1/transactions/{tx.id}", json={
            "memo": "更新後",
            "expense_amount": 750,
        })
        assert res.status_code == 200
        body = res.json()
        assert body["memo"] == "更新後"
        assert body["expense_amount"] == 750

    def test_update_nonexistent_transaction_returns_404(self, api_client):
        # チェックリスト: 取引編集：保存後に元の一覧（return_url）へリダイレクトされること
        res = api_client.put("/api/v1/transactions/999999", json={"memo": "テスト"})
        assert res.status_code == 404

    def test_update_transaction_with_transfer_fields_keeps_original_values(self, api_client, db_session):
        # チェックリスト: 取引編集：is_transfer / transfer_detail は更新不可
        # TransactionUpdate スキーマにはこれらのフィールドが含まれていないため
        # 送信してもエラーにならず、値は変更されないことを確認する
        cat_transfer = _create_category(db_session, "【資金移動】", is_transfer=True)
        acc = _create_account(db_session)
        tx = Transaction(
            date=date(2024, 1, 15),
            category_id=cat_transfer.id,
            account_id=acc.id,
            expense_amount=1000,
            income_amount=0,
            is_transfer=True,
            transfer_detail="【資金移動】- 30_銀行へ -",
        )
        db_session.add(tx)
        db_session.flush()

        # memo のみ更新可能フィールドを更新
        res = api_client.put(f"/api/v1/transactions/{tx.id}", json={"memo": "更新テスト"})
        assert res.status_code == 200
        body = res.json()
        assert body["is_transfer"] is True  # 変更されていない
        assert body["transfer_detail"] == "【資金移動】- 30_銀行へ -"  # 変更されていない


# ─── 取引編集ページ ──────────────────────────────────────────────────────────

@pytest.mark.integration
class TestTransactionEditPage:
    def test_edit_page_for_existing_transaction_returns_200_with_content(self, api_client, db_session):
        # チェックリスト: 取引編集：既存取引の内容が初期値として表示されること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        tx = _create_transaction(db_session, cat, acc, expense=500, memo="編集対象")

        res = api_client.get(f"/transactions/{tx.id}/edit")
        assert res.status_code == 200
        # 取引データが HTML 内に含まれていること
        assert "編集対象" in res.text or str(tx.id) in res.text

    def test_edit_page_for_nonexistent_transaction_returns_404(self, api_client):
        # チェックリスト: 取引編集：既存取引の内容が初期値として表示されること（存在しない場合は404）
        res = api_client.get("/transactions/999999/edit")
        assert res.status_code == 404


# ─── コピー機能 ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestTransactionCopyFeature:
    def test_new_page_with_copy_from_id_returns_200(self, api_client, db_session):
        # チェックリスト: コピー機能：`copy_from_id` パラメータでコピー元のデータがフォームに反映されること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        tx = _create_transaction(db_session, cat, acc, expense=500, memo="コピー元メモ")

        res = api_client.get(f"/transactions/new?copy_from_id={tx.id}")
        assert res.status_code == 200

    def test_new_page_with_copy_from_id_includes_source_data(self, api_client, db_session):
        # チェックリスト: コピー機能：`copy_from_id` パラメータでコピー元のデータがフォームに反映されること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        tx = _create_transaction(db_session, cat, acc, expense=500, memo="コピー元メモ")

        res = api_client.get(f"/transactions/new?copy_from_id={tx.id}")
        assert res.status_code == 200
        # コピー元のメモが HTML 内に含まれていること
        assert "コピー元メモ" in res.text


# ─── pattern_id 紐付け（ADR-0001） ──────────────────────────────────────────
# 対象ADR: docs/adr/0001-pattern-payment-status-tracking.md

def _create_pattern(
    db_session,
    category: Category,
    account: Account,
    to_account: Account = None,
    name: str = "テストパターン",
    frequency: str = "monthly",
    payment_day_of_month: int = 15,
) -> TransactionPattern:
    p = TransactionPattern(
        name=name,
        frequency=frequency,
        category_id=category.id,
        account_id=account.id,
        to_account_id=to_account.id if to_account else None,
        payment_day_of_month=payment_day_of_month,
    )
    db_session.add(p)
    db_session.flush()
    return p


@pytest.mark.integration
class TestTransactionPatternIdLinking:
    def test_create_with_pattern_id_saves_pattern_id(self, api_client, db_session):
        # チェックリスト: 取引入力：`pattern_id` クエリパラメータ経由で入力したフォームを送信すると
        # `transactions.pattern_id` に値が保存されること
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc)

        res = api_client.post("/api/v1/transactions", json={
            "date": "2024-03-15",
            "category_id": cat.id,
            "account_id": acc.id,
            "expense_amount": 3000,
            "pattern_id": p.id,
        })
        assert res.status_code == 201
        assert res.json()["pattern_id"] == p.id

    def test_create_without_pattern_id_keeps_it_null(self, api_client, db_session):
        # チェックリスト: 取引入力：パターンを使わない自由入力で送信すると
        # `transactions.pattern_id` が `NULL` のままであること
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)

        res = api_client.post("/api/v1/transactions", json={
            "date": "2024-03-15",
            "category_id": cat.id,
            "account_id": acc.id,
            "expense_amount": 1000,
        })
        assert res.status_code == 201
        assert res.json()["pattern_id"] is None

    def test_transfer_with_pattern_id_sets_it_on_both_transactions(self, api_client, db_session):
        # チェックリスト: 資金移動：`pattern_id` を指定して送信すると、
        # 出金・入金の両方の取引に同じ `pattern_id` が設定されること
        acc1 = _create_account(db_session, "10_財布")
        acc2 = _create_account(db_session, "30_銀行")
        transfer_cat = _create_category(db_session, "【資金移動】", is_transfer=True)
        p = _create_pattern(db_session, transfer_cat, acc1, to_account=acc2, name="定期送金")

        res = api_client.post("/api/v1/transactions/transfer", json={
            "date": "2024-03-15",
            "from_account_id": acc1.id,
            "to_account_id": acc2.id,
            "amount": 5000,
            "pattern_id": p.id,
        })
        assert res.status_code == 201
        body = res.json()
        assert body["expense_tx"]["pattern_id"] == p.id
        assert body["income_tx"]["pattern_id"] == p.id

    def test_deleting_pattern_sets_linked_transaction_pattern_id_to_null(self, api_client, db_session):
        # チェックリスト: パターン削除後も、紐付いていた取引の `pattern_id` が `NULL` になるだけで
        # 取引自体は削除されないこと（SET NULL）
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc)
        tx = _create_transaction(db_session, cat, acc, expense=3000)
        tx.pattern_id = p.id
        db_session.flush()
        db_session.commit()

        res = api_client.delete(f"/api/v1/patterns/{p.id}")
        assert res.status_code == 204

        res_tx = api_client.get(f"/api/v1/transactions/{tx.id}")
        assert res_tx.status_code == 200
        assert res_tx.json()["pattern_id"] is None

    def test_create_with_mismatched_pattern_id_returns_400(self, api_client, db_session):
        # pattern_id が指定されたカテゴリ/アカウントと一致しない場合はサーバー側で拒否する
        # （手動でカテゴリ/アカウントを変更した後に古い pattern_id が送信されるケースの防止）
        cat = _create_category(db_session, "通信費/携帯")
        other_cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session)
        p = _create_pattern(db_session, cat, acc)

        res = api_client.post("/api/v1/transactions", json={
            "date": "2024-03-15",
            "category_id": other_cat.id,
            "account_id": acc.id,
            "expense_amount": 1000,
            "pattern_id": p.id,
        })
        assert res.status_code == 400

    def test_create_with_nonexistent_pattern_id_returns_400(self, api_client, db_session):
        cat = _create_category(db_session, "通信費/携帯")
        acc = _create_account(db_session)

        res = api_client.post("/api/v1/transactions", json={
            "date": "2024-03-15",
            "category_id": cat.id,
            "account_id": acc.id,
            "expense_amount": 1000,
            "pattern_id": 999999,
        })
        assert res.status_code == 400

    def test_transfer_with_mismatched_pattern_id_returns_400(self, api_client, db_session):
        acc1 = _create_account(db_session, "10_財布")
        acc2 = _create_account(db_session, "30_銀行")
        acc3 = _create_account(db_session, "40_貯蓄")
        transfer_cat = _create_category(db_session, "【資金移動】", is_transfer=True)
        p = _create_pattern(db_session, transfer_cat, acc1, to_account=acc2, name="定期送金")

        res = api_client.post("/api/v1/transactions/transfer", json={
            "date": "2024-03-15",
            "from_account_id": acc1.id,
            "to_account_id": acc3.id,
            "amount": 5000,
            "pattern_id": p.id,
        })
        assert res.status_code == 400
