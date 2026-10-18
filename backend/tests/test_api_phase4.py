"""
フェーズ4: API の結合テスト

- SQLite in-memory DB でテスト環境を分離し、実データに依存しない
- TestClient で実際のエンドポイントを呼び出してレスポンスを検証する
- conftest.py の db_session / api_client フィクスチャを使用
"""
import io
from datetime import date

from app.models.account import Account
from app.models.category import Category
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
    acc = Account(code=code, name="財布", account_type="cash")
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
) -> Transaction:
    tx = Transaction(
        date=tx_date or date(2024, 1, 15),
        category_id=category.id,
        account_id=account.id,
        expense_amount=expense,
        income_amount=income,
    )
    db_session.add(tx)
    db_session.commit()
    return tx


def _make_actual_txt(rows: list[dict]) -> bytes:
    """Actual.TXT 形式（UTF-16 BOM 付き TSV）のバイト列を生成する。"""
    header = "日　付\tカテゴリー\tアカウント\t入金額\t出金額\tメ　モ\tグループ"
    lines = [header]
    for r in rows:
        lines.append(
            f"{r.get('date', '')}\t{r.get('category', '')}\t{r.get('account', '')}"
            f"\t{r.get('income', '')}\t{r.get('expense', '')}"
            f"\t{r.get('memo', '')}\t{r.get('group', '')}"
        )
    return "\n".join(lines).encode("utf-16")


# ─── GET /api/v1/transactions ─────────────────────────────────────────────────

class TestTransactionList:
    def test_empty_db_returns_200_with_empty_list(self, api_client):
        res = api_client.get("/api/v1/transactions")
        assert res.status_code == 200
        body = res.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["page"] == 1
        assert body["per_page"] == 50

    def test_returns_transaction_with_expected_fields(self, api_client, db_session):
        cat = _create_category(db_session, "A10_食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, date(2024, 3, 10), expense=1200)

        res = api_client.get("/api/v1/transactions")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["expense_amount"] == 1200
        assert item["category_full_path"] == "A10_食費/外食"
        assert item["account_code"] == "10_財布"
        assert item["parent_category_id"] is not None

    def test_filter_by_year_month(self, api_client, db_session):
        cat = _create_category(db_session, "A10_食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, date(2024, 1, 10), expense=100)
        _create_transaction(db_session, cat, acc, date(2024, 2, 10), expense=200)

        res = api_client.get("/api/v1/transactions?year=2024&month=1")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["items"][0]["expense_amount"] == 100

    def test_pagination_limits_items(self, api_client, db_session):
        cat = _create_category(db_session, "A10_食費/外食")
        acc = _create_account(db_session)
        for i in range(5):
            _create_transaction(db_session, cat, acc, date(2024, 1, i + 1), expense=(i + 1) * 100)

        res = api_client.get("/api/v1/transactions?page=1&per_page=3")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 5
        assert len(body["items"]) == 3
        assert body["page"] == 1
        assert body["per_page"] == 3

    def test_page_zero_returns_422(self, api_client):
        res = api_client.get("/api/v1/transactions?page=0")
        assert res.status_code == 422

    def test_per_page_over_limit_returns_422(self, api_client):
        res = api_client.get("/api/v1/transactions?per_page=201")
        assert res.status_code == 422


# ─── GET /api/v1/transactions/{id} ────────────────────────────────────────────

class TestTransactionGet:
    def test_existing_transaction_returns_200(self, api_client, db_session):
        cat = _create_category(db_session, "A10_食費/外食")
        acc = _create_account(db_session)
        tx = _create_transaction(db_session, cat, acc)

        res = api_client.get(f"/api/v1/transactions/{tx.id}")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == tx.id
        assert body["expense_amount"] == 500

    def test_nonexistent_id_returns_404(self, api_client):
        res = api_client.get("/api/v1/transactions/999999")
        assert res.status_code == 404


# ─── POST /api/v1/import/upload ───────────────────────────────────────────────

class TestImportUpload:
    def test_valid_file_returns_success(self, api_client):
        content = _make_actual_txt([
            {"date": "2024/01/10", "category": "A10_食費/外食", "account": "10_財布", "expense": "800"},
            {"date": "2024/01/11", "category": "A10_食費/外食", "account": "10_財布", "expense": "1200"},
        ])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "append"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["imported_rows"] == 2
        assert body["error_rows"] == 0
        assert body["total_rows"] == 2

    def test_import_data_visible_in_transactions_api(self, api_client):
        content = _make_actual_txt([
            {"date": "2024/03/05", "category": "B10_日用品/消耗品", "account": "10_財布", "expense": "350"},
        ])
        api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "append"},
        )
        res = api_client.get("/api/v1/transactions?year=2024&month=3")
        assert res.status_code == 200
        assert res.json()["total"] == 1

    def test_replace_mode_deletes_existing_data(self, api_client):
        content1 = _make_actual_txt([
            {"date": "2024/05/01", "category": "A10_食費/外食", "account": "10_財布", "expense": "500"},
            {"date": "2024/05/02", "category": "A10_食費/外食", "account": "10_財布", "expense": "600"},
        ])
        api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content1), "text/plain")},
            data={"mode": "append"},
        )

        content2 = _make_actual_txt([
            {"date": "2024/05/10", "category": "A10_食費/外食", "account": "10_財布", "expense": "999"},
        ])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content2), "text/plain")},
            data={"mode": "replace"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["deleted_rows"] == 2

        res2 = api_client.get("/api/v1/transactions")
        assert res2.json()["total"] == 1

    def test_empty_file_returns_error_status(self, api_client):
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(b""), "text/plain")},
            data={"mode": "append"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "error"

    def test_invalid_mode_returns_400(self, api_client):
        content = _make_actual_txt([])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "invalid_mode"},
        )
        assert res.status_code == 400

    def test_missing_file_returns_422(self, api_client):
        res = api_client.post("/api/v1/import/upload", data={"mode": "append"})
        assert res.status_code == 422

    def test_new_categories_and_accounts_reported(self, api_client):
        content = _make_actual_txt([
            {"date": "2024/06/01", "category": "C10_交通費/電車", "account": "30_銀行", "expense": "200"},
        ])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "append"},
        )
        body = res.json()
        assert "C10_交通費/電車" in body["new_categories"]
        assert "30_銀行" in body["new_accounts"]


# ─── GET /api/v1/reports/monthly ──────────────────────────────────────────────

class TestMonthlyReport:
    def test_empty_month_returns_valid_structure(self, api_client):
        res = api_client.get("/api/v1/reports/monthly?year=2024&month=1")
        assert res.status_code == 200
        body = res.json()
        assert "year" in body
        assert "month" in body
        assert "total_income" in body
        assert "total_expense" in body
        assert "categories" in body
        assert isinstance(body["categories"], list)

    def test_missing_month_param_returns_422(self, api_client):
        res = api_client.get("/api/v1/reports/monthly?year=2024")
        assert res.status_code == 422

    def test_missing_year_param_returns_422(self, api_client):
        res = api_client.get("/api/v1/reports/monthly?month=1")
        assert res.status_code == 422

    def test_invalid_month_returns_422(self, api_client):
        res = api_client.get("/api/v1/reports/monthly?year=2024&month=13")
        assert res.status_code == 422

    def test_expense_total_matches_transactions(self, api_client, db_session):
        cat = _create_category(db_session, "A10_食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, date(2024, 6, 1), expense=2000)
        _create_transaction(db_session, cat, acc, date(2024, 6, 15), expense=3000)

        res = api_client.get("/api/v1/reports/monthly?year=2024&month=6")
        assert res.status_code == 200
        body = res.json()
        assert body["total_expense"] == 5000
        assert body["year"] == 2024
        assert body["month"] == 6

    def test_transfer_transactions_excluded_from_total(self, api_client, db_session):
        cat_normal = _create_category(db_session, "A10_食費/外食")
        cat_transfer = _create_category(db_session, "【資金移動】", is_transfer=True)
        acc = _create_account(db_session)
        _create_transaction(db_session, cat_normal, acc, date(2024, 7, 1), expense=1000)
        tx_transfer = Transaction(
            date=date(2024, 7, 1),
            category_id=cat_transfer.id,
            account_id=acc.id,
            expense_amount=5000,
            income_amount=0,
            is_transfer=True,
        )
        db_session.add(tx_transfer)
        db_session.commit()

        res = api_client.get("/api/v1/reports/monthly?year=2024&month=7")
        body = res.json()
        assert body["total_expense"] == 1000

    def test_category_structure_has_parent_and_children(self, api_client, db_session):
        cat = _create_category(db_session, "A10_食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, date(2024, 8, 1), expense=1500)

        res = api_client.get("/api/v1/reports/monthly?year=2024&month=8")
        body = res.json()
        assert len(body["categories"]) >= 1
        parent = body["categories"][0]
        assert "children" in parent
        assert len(parent["children"]) >= 1
        child = parent["children"][0]
        assert child["full_path"] == "A10_食費/外食"
        assert child["total_expense"] == 1500


# ─── GET /api/v1/reports/comparison ──────────────────────────────────────────

class TestComparisonReport:
    def test_empty_db_returns_valid_structure(self, api_client):
        res = api_client.get("/api/v1/reports/comparison?year=2024&month=1")
        assert res.status_code == 200
        body = res.json()
        assert "year" in body
        assert "last_year" in body
        assert "month" in body
        assert "income_categories" in body
        assert "expense_categories" in body
        assert "total_this_expense" in body
        assert "total_last_expense" in body

    def test_missing_year_returns_422(self, api_client):
        res = api_client.get("/api/v1/reports/comparison?month=4")
        assert res.status_code == 422

    def test_missing_month_returns_422(self, api_client):
        res = api_client.get("/api/v1/reports/comparison?year=2024")
        assert res.status_code == 422

    def test_this_year_and_last_year_totals(self, api_client, db_session):
        cat = _create_category(db_session, "A10_食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, date(2024, 4, 10), expense=3000)
        _create_transaction(db_session, cat, acc, date(2023, 4, 10), expense=1500)

        res = api_client.get("/api/v1/reports/comparison?year=2024&month=4")
        assert res.status_code == 200
        body = res.json()
        assert body["total_this_expense"] == 3000
        assert body["total_last_expense"] == 1500
        assert body["diff_expense_total"] == 1500
        assert body["year"] == 2024
        assert body["last_year"] == 2023

    def test_category_has_this_and_last_year_fields(self, api_client, db_session):
        cat = _create_category(db_session, "A10_食費/外食")
        acc = _create_account(db_session)
        _create_transaction(db_session, cat, acc, date(2024, 5, 1), expense=2000)

        res = api_client.get("/api/v1/reports/comparison?year=2024&month=5")
        body = res.json()
        assert len(body["expense_categories"]) >= 1
        cat_entry = body["expense_categories"][0]
        assert "this_year_expense" in cat_entry
        assert "last_year_expense" in cat_entry
        assert "diff_expense" in cat_entry
        assert cat_entry["this_year_expense"] == 2000
        assert cat_entry["last_year_expense"] == 0
