"""
口座管理 動作確認チェックリストのテスト

仕様書: docs/specs/core/spec_accounts.md
"""
import pytest

from app.models.account import Account
from app.models.account_type import AccountType


# ─── テストデータ作成ヘルパー ─────────────────────────────────────────────────

def _create_account_type(
    db_session,
    code: str,
    label: str = "テスト種別",
    sort_order: int = 0,
) -> AccountType:
    at = AccountType(code=code, label=label, sort_order=sort_order)
    db_session.add(at)
    db_session.flush()
    return at


def _create_account(
    db_session,
    code: str,
    name: str = None,
    account_type: str = "other",
    sort_order: int = 0,
    is_active: bool = True,
    classification: str = None,
) -> Account:
    acc = Account(
        code=code,
        name=name or code,
        account_type=account_type,
        sort_order=sort_order,
        is_active=is_active,
        classification=classification,
    )
    db_session.add(acc)
    db_session.flush()
    return acc


# ─── /accounts 画面 ──────────────────────────────────────────────────────────

@pytest.mark.integration
class TestAccountsPage:
    def test_accounts_page_renders(self, api_client):
        # チェックリスト: /accounts にアクセスして口座一覧が sort_order, code 順で表示されること

        # Act
        response = api_client.get("/accounts")

        # Assert
        assert response.status_code == 200

    def test_accounts_page_contains_oldest_transaction_date_hint(self, api_client, db_session):
        # チェックリスト: start_date 未設定時の編集モードで「最古取引日を使用」のヒントが表示されること

        # Arrange
        _create_account(db_session, "10_財布", sort_order=10)

        # Act
        response = api_client.get("/accounts")

        # Assert
        assert response.status_code == 200
        assert "最古取引日" in response.text


# ─── GET /api/v1/accounts ────────────────────────────────────────────────────

@pytest.mark.integration
class TestListAccounts:
    def test_accounts_list_sorted_by_sort_order_then_code(self, api_client, db_session):
        # チェックリスト: /accounts にアクセスして口座一覧が sort_order, code 順で表示されること

        # Arrange: sort_order が異なる口座を逆順に登録
        _create_account(db_session, "Z_後順", sort_order=20)
        _create_account(db_session, "A_先頭", sort_order=10)
        # sort_order が同じ場合は code 昇順
        _create_account(db_session, "B_同順2", sort_order=5)
        _create_account(db_session, "A_同順1", sort_order=5)

        # Act
        response = api_client.get("/api/v1/accounts")

        # Assert
        assert response.status_code == 200
        data = response.json()
        codes = [a["code"] for a in data]
        a_idx = codes.index("A_同順1")
        b_idx = codes.index("B_同順2")
        first_idx = codes.index("A_先頭")
        z_idx = codes.index("Z_後順")
        # sort_order=5 の口座が先、sort_order=10、20 の順
        assert a_idx < first_idx < z_idx
        # sort_order 同値の場合は code 昇順（A_同順1 < B_同順2）
        assert a_idx < b_idx

    def test_accounts_list_excludes_inactive_accounts(self, api_client, db_session):
        # 仕様: is_active=False の口座は GET /api/v1/accounts から除外される

        # Arrange
        _create_account(db_session, "active_acc", is_active=True)
        _create_account(db_session, "inactive_acc", is_active=False)

        # Act
        response = api_client.get("/api/v1/accounts")

        # Assert
        assert response.status_code == 200
        data = response.json()
        codes = [a["code"] for a in data]
        assert "active_acc" in codes
        assert "inactive_acc" not in codes

    def test_accounts_list_includes_required_fields(self, api_client, db_session):
        # 仕様: レスポンスには start_date, initial_balance, adjustment_amount, classification を含む

        # Arrange
        from datetime import date
        acc = _create_account(db_session, "test_fields", classification="個人")
        acc.start_date = date(2024, 1, 1)
        acc.initial_balance = 10000
        acc.adjustment_amount = -500
        db_session.flush()

        # Act
        response = api_client.get("/api/v1/accounts")

        # Assert
        assert response.status_code == 200
        data = response.json()
        target = next(a for a in data if a["code"] == "test_fields")
        assert target["start_date"] == "2024-01-01"
        assert target["initial_balance"] == 10000
        assert target["adjustment_amount"] == -500
        assert target["classification"] == "個人"


# ─── GET /api/v1/accounts/types ──────────────────────────────────────────────

@pytest.mark.integration
class TestListAccountTypes:
    def test_account_types_list_sorted_by_sort_order_then_code(self, api_client, db_session):
        # 仕様: GET /api/v1/accounts/types が sort_order 昇順、同値は code 昇順で返す

        # Arrange
        _create_account_type(db_session, "z_type", sort_order=20)
        _create_account_type(db_session, "a_type", sort_order=10)
        _create_account_type(db_session, "b_same", sort_order=5)
        _create_account_type(db_session, "a_same", sort_order=5)

        # Act
        response = api_client.get("/api/v1/accounts/types")

        # Assert
        assert response.status_code == 200
        data = response.json()
        codes = [t["code"] for t in data]
        a_same_idx = codes.index("a_same")
        b_same_idx = codes.index("b_same")
        a_type_idx = codes.index("a_type")
        z_type_idx = codes.index("z_type")
        assert a_same_idx < b_same_idx < a_type_idx < z_type_idx


# ─── POST /api/v1/accounts/types ────────────────────────────────────────────

@pytest.mark.integration
class TestCreateAccountType:
    def test_account_type_create_with_valid_data_returns_201(self, api_client):
        # チェックリスト: 種別管理：「＋ 種別を追加」で新しいタイプ（コード・ラベル・表示順）を登録できること

        # Arrange
        payload = {"code": "bank", "label": "銀行", "sort_order": 10}

        # Act
        response = api_client.post("/api/v1/accounts/types", json=payload)

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["code"] == "bank"
        assert data["label"] == "銀行"
        assert data["sort_order"] == 10

    def test_account_type_create_with_duplicate_code_returns_409(self, api_client, db_session):
        # チェックリスト: 種別管理：同じコードで追加しようとするとエラーメッセージが表示されること

        # Arrange
        _create_account_type(db_session, "cash", label="現金")
        payload = {"code": "cash", "label": "別の現金"}

        # Act
        response = api_client.post("/api/v1/accounts/types", json=payload)

        # Assert
        assert response.status_code == 409


# ─── PUT /api/v1/accounts/types/{type_id} ───────────────────────────────────

@pytest.mark.integration
class TestUpdateAccountType:
    def test_account_type_update_with_valid_data_returns_200(self, api_client, db_session):
        # チェックリスト: 種別管理：既存タイプの「編集」ボタンでインライン編集モードに切り替わり、保存できること

        # Arrange
        at = _create_account_type(db_session, "old_card", label="カード", sort_order=0)
        payload = {"code": "old_card", "label": "クレジットカード", "sort_order": 5}

        # Act
        response = api_client.put(f"/api/v1/accounts/types/{at.id}", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["label"] == "クレジットカード"
        assert data["sort_order"] == 5

    def test_account_type_update_code_cascades_to_accounts(self, api_client, db_session):
        # チェックリスト: 種別管理：コードを変更して保存すると、そのタイプを使用していた口座の種別も新コードに更新されること

        # Arrange
        at = _create_account_type(db_session, "old_code", label="旧種別")
        acc = _create_account(db_session, "10_財布", account_type="old_code")
        payload = {"code": "new_code", "label": "旧種別", "sort_order": 0}

        # Act
        response = api_client.put(f"/api/v1/accounts/types/{at.id}", json=payload)

        # Assert
        assert response.status_code == 200
        db_session.expire_all()
        acc_refreshed = db_session.get(Account, acc.id)
        assert acc_refreshed.account_type == "new_code"

    def test_account_type_update_with_nonexistent_id_returns_404(self, api_client):
        # 仕様: PUT /api/v1/accounts/types/{type_id} で存在しない ID は 404

        # Arrange
        payload = {"code": "ghost", "label": "存在しない", "sort_order": 0}

        # Act
        response = api_client.put("/api/v1/accounts/types/999999", json=payload)

        # Assert
        assert response.status_code == 404

    def test_account_type_update_with_duplicate_code_returns_409(self, api_client, db_session):
        # 仕様: code を変更する場合、変更後の code が既存の別レコードと重複するときは 409

        # Arrange
        _create_account_type(db_session, "existing_code", label="既存種別")
        at = _create_account_type(db_session, "target_code", label="対象種別")
        payload = {"code": "existing_code", "label": "対象種別", "sort_order": 0}

        # Act
        response = api_client.put(f"/api/v1/accounts/types/{at.id}", json=payload)

        # Assert
        assert response.status_code == 409


# ─── DELETE /api/v1/accounts/types/{type_id} ────────────────────────────────

@pytest.mark.integration
class TestDeleteAccountType:
    def test_account_type_delete_in_use_returns_409(self, api_client, db_session):
        # チェックリスト: 種別管理：口座に使用中の種別を削除しようとすると「使用中」エラーが表示されること

        # Arrange
        at = _create_account_type(db_session, "cash", label="現金")
        _create_account(db_session, "10_財布", account_type="cash")

        # Act
        response = api_client.delete(f"/api/v1/accounts/types/{at.id}")

        # Assert
        assert response.status_code == 409

    def test_account_type_delete_unused_returns_204_and_removed_from_list(
        self, api_client, db_session
    ):
        # チェックリスト: 種別管理：使用中でない種別を削除すると一覧から消えること

        # Arrange
        at = _create_account_type(db_session, "unused_type", label="未使用種別")

        # Act
        delete_response = api_client.delete(f"/api/v1/accounts/types/{at.id}")

        # Assert
        assert delete_response.status_code == 204
        list_response = api_client.get("/api/v1/accounts/types")
        codes = [t["code"] for t in list_response.json()]
        assert "unused_type" not in codes

    def test_account_type_delete_with_nonexistent_id_returns_404(self, api_client):
        # 仕様: DELETE /api/v1/accounts/types/{type_id} で存在しない ID は 404

        # Act
        response = api_client.delete("/api/v1/accounts/types/999999")

        # Assert
        assert response.status_code == 404


# ─── PUT /api/v1/accounts/{account_id} ──────────────────────────────────────

@pytest.mark.integration
class TestUpdateAccount:
    def test_account_update_with_all_fields_returns_200(self, api_client, db_session):
        # チェックリスト: 口座一覧：各行の「編集」ボタンで種別・分類・開始日・初期残高・調整金額のインライン編集ができること

        # Arrange
        at = _create_account_type(db_session, "bank", label="銀行")
        acc = _create_account(db_session, "20_銀行")
        payload = {
            "account_type": "bank",
            "start_date": "2024-01-01",
            "initial_balance": 50000,
            "adjustment_amount": -1000,
            "classification": "個人",
        }

        # Act
        response = api_client.put(f"/api/v1/accounts/{acc.id}", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["account_type"] == "bank"
        assert data["start_date"] == "2024-01-01"
        assert data["initial_balance"] == 50000
        assert data["adjustment_amount"] == -1000
        assert data["classification"] == "個人"

    def test_account_update_response_reflects_updated_values(self, api_client, db_session):
        # チェックリスト: 口座一覧：「保存」後に更新した値が即座に画面に反映されること
        # レスポンスに最新の値が含まれることで即時反映を保証する

        # Arrange
        _create_account_type(db_session, "card", label="クレカ")
        acc = _create_account(db_session, "30_カード", account_type="other", classification="共通")
        payload = {
            "account_type": "card",
            "start_date": "2025-04-01",
            "initial_balance": 0,
            "adjustment_amount": 200,
            "classification": "個人",
        }

        # Act
        response = api_client.put(f"/api/v1/accounts/{acc.id}", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["account_type"] == "card"
        assert data["classification"] == "個人"
        assert data["adjustment_amount"] == 200

    def test_account_update_with_nonexistent_id_returns_404(self, api_client):
        # 仕様: 対象口座が存在しない場合は HTTP 404

        # Arrange
        payload = {"account_type": None, "start_date": None, "initial_balance": 0,
                   "adjustment_amount": 0, "classification": None}

        # Act
        response = api_client.put("/api/v1/accounts/999999", json=payload)

        # Assert
        assert response.status_code == 404

    def test_account_update_with_invalid_account_type_returns_400(self, api_client, db_session):
        # 仕様: account_type が指定された場合、account_types テーブルに該当コードが存在しない場合は 400

        # Arrange
        acc = _create_account(db_session, "10_財布")
        payload = {"account_type": "nonexistent_type"}

        # Act
        response = api_client.put(f"/api/v1/accounts/{acc.id}", json=payload)

        # Assert
        assert response.status_code == 400

    def test_account_update_none_initial_balance_stored_as_zero(self, api_client, db_session):
        # 仕様: initial_balance が None の場合は 0 を格納する

        # Arrange
        acc = _create_account(db_session, "10_財布")
        payload = {"initial_balance": None, "adjustment_amount": None}

        # Act
        response = api_client.put(f"/api/v1/accounts/{acc.id}", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["initial_balance"] == 0
        assert data["adjustment_amount"] == 0

    def test_account_update_empty_classification_stored_as_null(self, api_client, db_session):
        # 仕様: classification が空文字列または None の場合は NULL を格納する

        # Arrange
        acc = _create_account(db_session, "10_財布", classification="個人")
        payload = {"classification": ""}

        # Act
        response = api_client.put(f"/api/v1/accounts/{acc.id}", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["classification"] is None


# ─── PUT /api/v1/accounts/bulk ──────────────────────────────────────────────

@pytest.mark.integration
class TestBulkUpdateAccounts:
    def test_accounts_bulk_update_without_fields_returns_400(self, api_client, db_session):
        # チェックリスト: 一括設定：変更内容（種別・分類）を未選択で「一括設定を実行」するとエラーメッセージが表示されること

        # Arrange
        acc = _create_account(db_session, "10_財布")
        payload = {
            "ids": [acc.id],
            "account_type": None,
            "update_classification": False,
        }

        # Act
        response = api_client.put("/api/v1/accounts/bulk", json=payload)

        # Assert
        assert response.status_code == 400

    def test_accounts_bulk_update_account_type_updates_selected_accounts(
        self, api_client, db_session
    ):
        # チェックリスト: 一括設定：種別を選択して複数口座をチェックし「一括設定を実行」すると該当口座の種別が変わること

        # Arrange
        at = _create_account_type(db_session, "bank", label="銀行")
        acc1 = _create_account(db_session, "10_財布", account_type="other")
        acc2 = _create_account(db_session, "20_通帳", account_type="other")
        acc_other = _create_account(db_session, "30_カード", account_type="other")
        payload = {
            "ids": [acc1.id, acc2.id],
            "account_type": "bank",
            "update_classification": False,
        }

        # Act
        response = api_client.put("/api/v1/accounts/bulk", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        updated_codes = {a["code"] for a in data}
        assert "10_財布" in updated_codes
        assert "20_通帳" in updated_codes
        # 対象外口座は含まれない
        assert "30_カード" not in updated_codes
        # 更新された口座の種別が bank になっている
        assert all(a["account_type"] == "bank" for a in data)

    def test_accounts_bulk_update_classification_updates_accounts(
        self, api_client, db_session
    ):
        # チェックリスト: 一括設定：分類を「値を設定する」にして複数口座に一括設定できること

        # Arrange
        acc1 = _create_account(db_session, "10_財布")
        acc2 = _create_account(db_session, "20_通帳")
        payload = {
            "ids": [acc1.id, acc2.id],
            "account_type": None,
            "update_classification": True,
            "classification": "共通",
        }

        # Act
        response = api_client.put("/api/v1/accounts/bulk", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert all(a["classification"] == "共通" for a in data)

    def test_accounts_bulk_update_clear_classification_sets_null(
        self, api_client, db_session
    ):
        # チェックリスト: 一括設定：分類を「クリアする」にして複数口座の分類を空欄にできること

        # Arrange
        acc1 = _create_account(db_session, "10_財布", classification="個人")
        acc2 = _create_account(db_session, "20_通帳", classification="共通")
        payload = {
            "ids": [acc1.id, acc2.id],
            "account_type": None,
            "update_classification": True,
            "classification": None,
        }

        # Act
        response = api_client.put("/api/v1/accounts/bulk", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert all(a["classification"] is None for a in data)

    def test_accounts_bulk_update_with_invalid_account_type_returns_400(
        self, api_client, db_session
    ):
        # 仕様: account_type が指定された場合、account_types に存在しない場合は 400

        # Arrange
        acc = _create_account(db_session, "10_財布")
        payload = {
            "ids": [acc.id],
            "account_type": "nonexistent_type",
            "update_classification": False,
        }

        # Act
        response = api_client.put("/api/v1/accounts/bulk", json=payload)

        # Assert
        assert response.status_code == 400

    def test_accounts_bulk_update_only_affects_active_accounts(
        self, api_client, db_session
    ):
        # 仕様: ids に指定した口座ID群（is_active=True の口座のみ）に対して更新する

        # Arrange
        at = _create_account_type(db_session, "bank", label="銀行")
        active_acc = _create_account(db_session, "10_財布", is_active=True)
        inactive_acc = _create_account(db_session, "20_休止口座", is_active=False)
        payload = {
            "ids": [active_acc.id, inactive_acc.id],
            "account_type": "bank",
            "update_classification": False,
        }

        # Act
        response = api_client.put("/api/v1/accounts/bulk", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        codes = [a["code"] for a in data]
        assert "10_財布" in codes
        # 非アクティブ口座は更新対象外
        assert "20_休止口座" not in codes
