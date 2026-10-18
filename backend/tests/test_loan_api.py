"""
ローン登録 API およびインポート skip_loan オプションの結合テスト

- conftest.py の db_session / api_client フィクスチャを使用
- SQLite in-memory DB でテスト環境を分離する
"""
import io
from datetime import date

import pytest

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction


# ─── テストデータ作成ヘルパー ─────────────────────────────────────────────────

def _make_account(db_session, code: str, account_type: str = "bank") -> Account:
    acc = Account(code=code, name=code, account_type=account_type)
    db_session.add(acc)
    db_session.flush()
    return acc


def _make_category(db_session, full_path: str, is_transfer: bool = False) -> Category:
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


def _make_actual_txt(rows: list[dict]) -> bytes:
    header = "日　付\tカテゴリー\tアカウント\t入金額\t出金額\tメ　モ\tグループ"
    lines = [header]
    for r in rows:
        lines.append(
            f"{r.get('date', '')}\t{r.get('category', '')}\t{r.get('account', '')}"
            f"\t{r.get('income', '')}\t{r.get('expense', '')}"
            f"\t{r.get('memo', '')}\t{r.get('group', '')}"
        )
    return "\n".join(lines).encode("utf-16")


def _base_loan_payload(loan_acc_id: int, repay_acc_id: int, **overrides) -> dict:
    payload = {
        "loan_account_id": loan_acc_id,
        "repayment_account_id": repay_acc_id,
        "borrow_date": "2024-01-10",
        "borrow_amount": 1_000_000,
        "annual_rate": 1.2,
        "num_payments": 3,
        "repayment_day": 25,
        "first_payment_date": "2024-02-25",
        "repayment_method": "equal_installment",
        "holiday_handling": "none",
        "create_interest_transactions": False,
    }
    payload.update(overrides)
    return payload


# ─── POST /api/v1/loans/preview ───────────────────────────────────────────────

class TestLoanPreviewAPI:

    @pytest.fixture(autouse=True)
    def _setup(self, db_session):
        self.loan_acc = _make_account(db_session, "90_住宅ローン", "other")
        self.repay_acc = _make_account(db_session, "20_銀行口座", "bank")
        self.interest_cat = _make_category(db_session, "A10_ローン/住宅ローン利息")
        db_session.commit()

    def test_equal_installment_returns_schedule(self, api_client):
        payload = _base_loan_payload(self.loan_acc.id, self.repay_acc.id)
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert len(body["schedule"]) == 3
        assert body["total_principal"] == 1_000_000
        assert body["total_interest"] >= 0

    def test_equal_principal_returns_schedule(self, api_client):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            repayment_method="equal_principal",
        )
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert len(body["schedule"]) == 3
        assert body["total_principal"] == 1_000_000

    def test_schedule_fields_present(self, api_client):
        payload = _base_loan_payload(self.loan_acc.id, self.repay_acc.id)
        res = api_client.post("/api/v1/loans/preview", json=payload)
        item = res.json()["schedule"][0]
        assert "payment_number" in item
        assert "payment_date" in item
        assert "payment_amount" in item
        assert "principal_amount" in item
        assert "interest_amount" in item
        assert "remaining_balance" in item

    def test_invalid_repayment_method_returns_422(self, api_client):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            repayment_method="invalid_method",
        )
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 422

    def test_invalid_holiday_handling_returns_422(self, api_client):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            holiday_handling="tomorrow",
        )
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 422

    def test_nonexistent_loan_account_returns_400(self, api_client):
        payload = _base_loan_payload(99999, self.repay_acc.id)
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 400
        assert "ローン口座" in res.json()["detail"]

    def test_nonexistent_repayment_account_returns_400(self, api_client):
        payload = _base_loan_payload(self.loan_acc.id, 99999)
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 400
        assert "返済口座" in res.json()["detail"]

    def test_same_accounts_returns_400(self, api_client):
        payload = _base_loan_payload(self.loan_acc.id, self.loan_acc.id)
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 400
        assert "異なる" in res.json()["detail"]

    def test_create_interest_without_category_returns_422(self, api_client):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            create_interest_transactions=True,
            interest_category_id=None,
        )
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 422

    def test_zero_borrow_amount_returns_422(self, api_client):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            borrow_amount=0,
        )
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 422

    def test_negative_borrow_amount_returns_422(self, api_client):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            borrow_amount=-1,
        )
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 422

    def test_zero_annual_rate_allowed(self, api_client):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            annual_rate=0,
        )
        res = api_client.post("/api/v1/loans/preview", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert body["total_interest"] == 0


# ─── POST /api/v1/loans/create ────────────────────────────────────────────────

class TestLoanCreateAPI:

    @pytest.fixture(autouse=True)
    def _setup(self, db_session):
        self.loan_acc = _make_account(db_session, "90_住宅ローン", "other")
        self.repay_acc = _make_account(db_session, "20_銀行口座", "bank")
        self.interest_cat = _make_category(db_session, "A10_ローン/住宅ローン利息")
        db_session.commit()

    def test_creates_principal_transactions_only(self, api_client, db_session):
        payload = _base_loan_payload(self.loan_acc.id, self.repay_acc.id)
        res = api_client.post("/api/v1/loans/create", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert body["created_principal_count"] == 3
        assert body["created_interest_count"] == 0
        # 元本1回ごとに2トランザクション（出金・入金）
        all_tx = db_session.query(Transaction).all()
        assert len(all_tx) == 6

    def test_creates_principal_and_interest_transactions(self, api_client, db_session):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            create_interest_transactions=True,
            interest_category_id=self.interest_cat.id,
        )
        res = api_client.post("/api/v1/loans/create", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert body["created_principal_count"] == 3
        # 利息 > 0 の回数は 3（1.2%/年なので 3 回とも利息あり）
        assert body["created_interest_count"] > 0

    def test_principal_transactions_are_marked_as_transfer(self, api_client, db_session):
        payload = _base_loan_payload(self.loan_acc.id, self.repay_acc.id)
        api_client.post("/api/v1/loans/create", json=payload)
        principal_txs = db_session.query(Transaction).filter(
            Transaction.is_transfer.is_(True)
        ).all()
        assert len(principal_txs) == 6

    def test_interest_transactions_are_not_transfer(self, api_client, db_session):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            create_interest_transactions=True,
            interest_category_id=self.interest_cat.id,
        )
        api_client.post("/api/v1/loans/create", json=payload)
        non_transfer = db_session.query(Transaction).filter(
            Transaction.is_transfer.is_(False)
        ).all()
        # 利息トランザクションのみ非transfer
        assert len(non_transfer) > 0
        for tx in non_transfer:
            assert tx.expense_amount > 0

    def test_memo_format_contains_payment_number(self, api_client, db_session):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            memo_prefix="住宅ローン",
        )
        api_client.post("/api/v1/loans/create", json=payload)
        txs = db_session.query(Transaction).filter(
            Transaction.account_id == self.repay_acc.id,
            Transaction.is_transfer.is_(True),
        ).order_by(Transaction.date).all()
        assert txs[0].memo == "住宅ローン 第1回（元本）"
        assert txs[1].memo == "住宅ローン 第2回（元本）"
        assert txs[2].memo == "住宅ローン 第3回（元本）"

    def test_default_memo_prefix_is_loan_repayment(self, api_client, db_session):
        payload = _base_loan_payload(self.loan_acc.id, self.repay_acc.id)
        api_client.post("/api/v1/loans/create", json=payload)
        tx = db_session.query(Transaction).filter(
            Transaction.account_id == self.repay_acc.id,
            Transaction.is_transfer.is_(True),
        ).order_by(Transaction.date).first()
        assert tx.memo == "ローン返済 第1回（元本）"

    def test_total_principal_in_response_equals_borrow_amount(self, api_client):
        payload = _base_loan_payload(self.loan_acc.id, self.repay_acc.id)
        res = api_client.post("/api/v1/loans/create", json=payload)
        assert res.json()["total_principal"] == 1_000_000

    def test_duplicate_submission_returns_409(self, api_client):
        payload = _base_loan_payload(self.loan_acc.id, self.repay_acc.id)
        res1 = api_client.post("/api/v1/loans/create", json=payload)
        assert res1.status_code == 200
        res2 = api_client.post("/api/v1/loans/create", json=payload)
        assert res2.status_code == 409

    def test_nonexistent_loan_account_returns_400(self, api_client):
        payload = _base_loan_payload(99999, self.repay_acc.id)
        res = api_client.post("/api/v1/loans/create", json=payload)
        assert res.status_code == 400

    def test_same_accounts_returns_400(self, api_client):
        payload = _base_loan_payload(self.loan_acc.id, self.loan_acc.id)
        res = api_client.post("/api/v1/loans/create", json=payload)
        assert res.status_code == 400

    def test_create_interest_without_category_returns_422(self, api_client):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            create_interest_transactions=True,
            interest_category_id=None,
        )
        res = api_client.post("/api/v1/loans/create", json=payload)
        assert res.status_code == 422

    def test_nonexistent_interest_category_returns_400(self, api_client):
        payload = _base_loan_payload(
            self.loan_acc.id, self.repay_acc.id,
            create_interest_transactions=True,
            interest_category_id=99999,
        )
        res = api_client.post("/api/v1/loans/create", json=payload)
        assert res.status_code == 400


# ─── POST /api/v1/import/upload（skip_loan オプション）──────────────────────

class TestImportSkipLoan:

    def test_skip_loan_false_imports_loan_rows(self, api_client):
        content = _make_actual_txt([
            {"date": "2024/01/10", "category": "A10_食費/外食", "account": "10_財布", "expense": "800"},
            {"date": "2024/01/15", "category": "【ﾛｰﾝ】住宅", "account": "10_財布", "expense": "50000"},
        ])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "append", "skip_loan": "false"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["imported_rows"] == 2
        assert body.get("skipped_loan_rows", 0) == 0

    def test_skip_loan_true_skips_loan_rows(self, api_client):
        content = _make_actual_txt([
            {"date": "2024/01/10", "category": "A10_食費/外食", "account": "10_財布", "expense": "800"},
            {"date": "2024/01/15", "category": "【ﾛｰﾝ】住宅", "account": "10_財布", "expense": "50000"},
            {"date": "2024/01/16", "category": "【ﾛｰﾝ】車", "account": "10_財布", "expense": "30000"},
        ])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "append", "skip_loan": "true"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["imported_rows"] == 1
        assert body["skipped_loan_rows"] == 2

    def test_skip_loan_count_appears_in_skipped_rows(self, api_client):
        content = _make_actual_txt([
            {"date": "2024/02/01", "category": "【ﾛｰﾝ】カーローン", "account": "10_財布", "expense": "20000"},
        ])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "append", "skip_loan": "true"},
        )
        body = res.json()
        assert body["skipped_rows"] >= 1
        assert body["skipped_loan_rows"] == 1

    def test_skip_loan_detail_contains_reason(self, api_client):
        content = _make_actual_txt([
            {"date": "2024/03/01", "category": "【ﾛｰﾝ】住宅", "account": "10_財布", "expense": "100000"},
        ])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "append", "skip_loan": "true"},
        )
        body = res.json()
        detail = body.get("skipped_detail", [])
        assert len(detail) >= 1
        loan_detail = next((d for d in detail if "【ﾛｰﾝ】" in d.get("category", "")), None)
        assert loan_detail is not None
        assert "ローン" in loan_detail["reason"]

    def test_normal_rows_not_affected_by_skip_loan(self, api_client):
        content = _make_actual_txt([
            {"date": "2024/04/01", "category": "B10_日用品/消耗品", "account": "10_財布", "expense": "300"},
            {"date": "2024/04/02", "category": "A10_食費/外食", "account": "10_財布", "expense": "1000"},
        ])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "append", "skip_loan": "true"},
        )
        body = res.json()
        assert body["imported_rows"] == 2
        assert body.get("skipped_loan_rows", 0) == 0

    def test_skip_loan_default_is_false(self, api_client):
        content = _make_actual_txt([
            {"date": "2024/05/01", "category": "【ﾛｰﾝ】住宅", "account": "10_財布", "expense": "50000"},
        ])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "append"},
        )
        body = res.json()
        # skip_loan未指定時はインポートされる（スキップされない）
        assert body["imported_rows"] == 1
        assert body.get("skipped_loan_rows", 0) == 0

    def test_all_loan_rows_skipped_returns_partial_or_success(self, api_client):
        content = _make_actual_txt([
            {"date": "2024/06/01", "category": "【ﾛｰﾝ】A", "account": "10_財布", "expense": "10000"},
            {"date": "2024/06/02", "category": "【ﾛｰﾝ】B", "account": "10_財布", "expense": "20000"},
        ])
        res = api_client.post(
            "/api/v1/import/upload",
            files={"file": ("Actual.TXT", io.BytesIO(content), "text/plain")},
            data={"mode": "append", "skip_loan": "true"},
        )
        body = res.json()
        assert body["imported_rows"] == 0
        assert body["skipped_loan_rows"] == 2
