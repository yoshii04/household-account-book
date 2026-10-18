"""
カテゴリ管理 動作確認チェックリストのテスト

仕様書: docs/specs/core/spec_categories.md
"""
import io
from datetime import date

import pytest

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
    acc = Account(code=code, name=code, account_type="cash")
    db_session.add(acc)
    db_session.flush()
    return acc


def _make_tsv_bytes(rows: list[list[str]], header: list[str] | None = None) -> bytes:
    """UTF-16 BOM 付き TSV コンテンツを生成する"""
    if header is None:
        header = ["日　付", "カテゴリー", "アカウント", "入金額", "出金額", "メ　モ", "グループ"]
    lines = ["\t".join(header)] + ["\t".join(row) for row in rows]
    return "\n".join(lines).encode("utf-16")


def _upload(api_client, content: bytes, filename: str = "test.txt", mode: str = "append"):
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    data = {"mode": mode, "skip_loan": "false"}
    return api_client.post("/api/v1/import/upload", files=files, data=data)


# ─── GET /api/v1/categories ──────────────────────────────────────────────────

@pytest.mark.integration
class TestListCategories:
    def test_categories_list_returns_only_parents_with_nested_children(
        self, api_client, db_session
    ):
        # チェックリスト: GET /api/v1/categories が親カテゴリのみを返し、各親の `children` に子カテゴリが含まれること

        # Arrange
        _create_category(db_session, "A30_通信費")
        _create_category(db_session, "A30_通信費/インターネット")

        # Act
        response = api_client.get("/api/v1/categories")

        # Assert
        assert response.status_code == 200
        data = response.json()
        top_level_paths = [c["full_path"] for c in data]
        # トップレベルは親カテゴリのみ
        assert "A30_通信費" in top_level_paths
        # 子カテゴリはトップレベルに含まれない
        assert "A30_通信費/インターネット" not in top_level_paths
        # 親の children に子が含まれる
        parent_entry = next(c for c in data if c["full_path"] == "A30_通信費")
        child_paths = [ch["full_path"] for ch in parent_entry["children"]]
        assert "A30_通信費/インターネット" in child_paths


# ─── GET /api/v1/categories/parents ──────────────────────────────────────────

@pytest.mark.integration
class TestListParentCategories:
    def test_categories_parents_returns_only_root_categories_flat(
        self, api_client, db_session
    ):
        # チェックリスト: GET /api/v1/categories/parents が `parent_id=null` の親カテゴリのみをフラットで返すこと

        # Arrange
        _create_category(db_session, "A10_食費")
        _create_category(db_session, "A10_食費/外食")
        _create_category(db_session, "A20_日用品")

        # Act
        response = api_client.get("/api/v1/categories/parents")

        # Assert
        assert response.status_code == 200
        data = response.json()
        full_paths = [c["full_path"] for c in data]
        assert "A10_食費" in full_paths
        assert "A20_日用品" in full_paths
        # 子カテゴリはリストに含まれない
        assert "A10_食費/外食" not in full_paths
        # 全項目の parent_id が null
        assert all(c["parent_id"] is None for c in data)


# ─── GET /api/v1/categories/all ──────────────────────────────────────────────

@pytest.mark.integration
class TestListAllCategories:
    def test_categories_all_returns_all_categories_flat(
        self, api_client, db_session
    ):
        # チェックリスト: GET /api/v1/categories/all が親・子を含む全カテゴリをフラットで返すこと

        # Arrange
        _create_category(db_session, "A10_食費")
        _create_category(db_session, "A10_食費/外食")
        _create_category(db_session, "A20_日用品")

        # Act
        response = api_client.get("/api/v1/categories/all")

        # Assert
        assert response.status_code == 200
        data = response.json()
        full_paths = [c["full_path"] for c in data]
        assert "A10_食費" in full_paths
        assert "A10_食費/外食" in full_paths
        assert "A20_日用品" in full_paths


# ─── GET /api/v1/categories/{id}/children ────────────────────────────────────

@pytest.mark.integration
class TestListChildCategories:
    def test_categories_children_returns_only_children_of_given_parent(
        self, api_client, db_session
    ):
        # チェックリスト: GET /api/v1/categories/{id}/children が指定IDの子カテゴリのみを返すこと

        # Arrange
        parent_a = _create_category(db_session, "A10_食費")
        _create_category(db_session, "A10_食費/外食")
        _create_category(db_session, "A10_食費/食料品")
        _create_category(db_session, "A20_日用品")
        _create_category(db_session, "A20_日用品/洗剤")

        # Act
        response = api_client.get(f"/api/v1/categories/{parent_a.id}/children")

        # Assert
        assert response.status_code == 200
        data = response.json()
        full_paths = [c["full_path"] for c in data]
        assert "A10_食費/外食" in full_paths
        assert "A10_食費/食料品" in full_paths
        # 他の親の子は含まれない
        assert "A20_日用品/洗剤" not in full_paths
        # 親自身も含まれない
        assert "A10_食費" not in full_paths


# ─── GET /api/v1/categories/{id} ─────────────────────────────────────────────

@pytest.mark.integration
class TestGetCategory:
    def test_categories_get_nonexistent_id_returns_404(self, api_client):
        # チェックリスト: GET /api/v1/categories/{id} が存在しないIDで 404 を返すこと

        # Act
        response = api_client.get("/api/v1/categories/999999")

        # Assert
        assert response.status_code == 404


# ─── インポート後のカテゴリ作成 ────────────────────────────────────────────────

@pytest.mark.integration
class TestCategoryCreationOnImport:
    def test_import_creates_category_without_duplicates(
        self, api_client, db_session
    ):
        # チェックリスト: Actual.TXT インポート後に新規カテゴリが `full_path` UNIQUE 制約に従い重複なく作成されること

        # Arrange
        tsv_content = _make_tsv_bytes([
            ["2024/01/15", "A30_通信費/インターネット", "10_財布", "", "5000", "", ""],
        ])

        # Act
        response = _upload(api_client, tsv_content)

        # Assert
        assert response.status_code == 200
        db_session.expire_all()
        cats = db_session.query(Category).filter(
            Category.full_path == "A30_通信費/インターネット"
        ).all()
        assert len(cats) == 1

    def test_import_same_category_twice_does_not_duplicate_categories(
        self, api_client, db_session
    ):
        # チェックリスト: 同じファイルを2回インポートしてもカテゴリが重複しないこと（upsert 動作）
        # Note: Transaction の import_hash に UNIQUE 制約があるため完全同一行の2回インポートは
        # トランザクション登録エラーになるが、カテゴリの upsert 動作は別ファイル同カテゴリでも検証できる

        # Arrange: 同じカテゴリ・異なるメモ（別ハッシュ）で2回インポート
        content1 = _make_tsv_bytes([
            ["2024/01/15", "A10_食費/外食", "10_財布", "", "1000", "1回目", ""],
        ])
        content2 = _make_tsv_bytes([
            ["2024/01/16", "A10_食費/外食", "10_財布", "", "2000", "2回目", ""],
        ])

        # Act: 同カテゴリを使う2つのファイルをインポート
        _upload(api_client, content1)
        _upload(api_client, content2)

        # Assert: カテゴリは重複せず1件のみ
        db_session.expire_all()
        cats = db_session.query(Category).filter(
            Category.full_path == "A10_食費/外食"
        ).all()
        assert len(cats) == 1


# ─── 資金移動取引作成後のカテゴリ自動生成 ────────────────────────────────────

@pytest.mark.integration
class TestTransferCategoryAutoCreate:
    def test_transfer_transaction_creates_transfer_categories(
        self, api_client, db_session
    ):
        # チェックリスト: 資金移動取引作成後に `【資金移動】- {code}へ -` / `- {code}から -` カテゴリが自動生成されること

        # Arrange
        acc_from = _create_account(db_session, "10_財布")
        acc_to = _create_account(db_session, "20_銀行口座")
        payload = {
            "from_account_id": acc_from.id,
            "to_account_id": acc_to.id,
            "amount": 10000,
            "date": "2024-01-15",
            "memo": "",
        }

        # Act
        response = api_client.post("/api/v1/transactions/transfer", json=payload)

        # Assert
        assert response.status_code == 201
        db_session.expire_all()
        expense_cat = db_session.query(Category).filter(
            Category.full_path == "【資金移動】- 20_銀行口座へ -"
        ).first()
        income_cat = db_session.query(Category).filter(
            Category.full_path == "【資金移動】- 10_財布から -"
        ).first()
        assert expense_cat is not None
        assert expense_cat.is_transfer is True
        assert income_cat is not None
        assert income_cat.is_transfer is True


# ─── is_transfer=True カテゴリの集計除外 ────────────────────────────────────

@pytest.mark.integration
class TestTransferCategoryExcludedFromReport:
    def test_monthly_report_excludes_transfer_transactions(
        self, api_client, db_session
    ):
        # チェックリスト: is_transfer=True のカテゴリに紐づく取引が月次集計レポートに含まれないこと

        # Arrange
        normal_cat = _create_category(db_session, "A10_食費/外食")
        transfer_cat = _create_category(db_session, "【資金移動】/財布から銀行", is_transfer=True)
        account = _create_account(db_session, "10_財布")
        normal_tx = Transaction(
            date=date(2024, 1, 15),
            category_id=normal_cat.id,
            account_id=account.id,
            income_amount=0,
            expense_amount=1000,
            is_transfer=False,
        )
        transfer_tx = Transaction(
            date=date(2024, 1, 15),
            category_id=transfer_cat.id,
            account_id=account.id,
            income_amount=0,
            expense_amount=5000,
            is_transfer=True,
        )
        db_session.add_all([normal_tx, transfer_tx])
        db_session.flush()

        # Act
        response = api_client.get("/api/v1/reports/monthly?year=2024&month=1")

        # Assert
        assert response.status_code == 200
        data = response.json()
        all_full_paths = [item["full_path"] for item in data["categories"]]
        # 資金移動カテゴリは集計に含まれない
        assert "【資金移動】/財布から銀行" not in all_full_paths
        assert "【資金移動】" not in all_full_paths
        # 通常取引の金額のみ反映される
        assert data["total_expense"] == 1000


# ─── フロントエンドフォームの is_transfer データ属性 ─────────────────────────

@pytest.mark.integration
class TestTransactionFormIsTransferAttribute:
    def test_new_transaction_form_has_data_is_transfer_true_for_transfer_parent_category(
        self, api_client, db_session
    ):
        # チェックリスト: 取引入力フォームで is_transfer=True の親カテゴリを選択した際に資金移動フォームに切り替わること
        # フロントエンドは親カテゴリの option 要素に data-is-transfer 属性を付与し、
        # JS がその値を読み取って資金移動フォームへの切り替えを行う

        # Arrange: is_transfer=True の親カテゴリと通常の口座を作成
        _create_category(db_session, "【資金移動】", is_transfer=True)
        _create_account(db_session, "10_財布")

        # Act
        response = api_client.get("/transactions/new")

        # Assert
        assert response.status_code == 200
        html = response.text
        assert 'data-is-transfer="true"' in html
