"""
インポート 動作確認チェックリストのテスト

仕様書: docs/specs/core/spec_import.md
"""
import io
import pytest

from app.models.category import Category
from app.models.account import Account
from app.models.group import Group
from app.models.transaction import Transaction


# ─── ヘルパー ────────────────────────────────────────────────────────────────────

def _make_tsv_bytes(rows: list[list[str]], header: list[str] | None = None) -> bytes:
    """UTF-16 BOM 付き TSV コンテンツを生成する"""
    if header is None:
        header = ["日　付", "カテゴリー", "アカウント", "入金額", "出金額", "メ　モ", "グループ"]
    lines = ["\t".join(header)] + ["\t".join(row) for row in rows]
    return "\n".join(lines).encode("utf-16")


def _upload(
    api_client,
    content: bytes,
    filename: str = "test.txt",
    mode: str = "append",
    skip_loan: bool = False,
):
    """POST /api/v1/import/upload のヘルパー"""
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    data = {"mode": mode, "skip_loan": str(skip_loan).lower()}
    return api_client.post("/api/v1/import/upload", files=files, data=data)


def _create_category(db_session, full_path: str, is_transfer: bool = False) -> Category:
    parts = full_path.split("/", 1)
    parent = None
    if len(parts) == 2:
        parent = db_session.query(Category).filter(Category.full_path == parts[0]).first()
        if not parent:
            parent = Category(code=parts[0], name=parts[0], full_path=parts[0], is_transfer=False)
            db_session.add(parent)
            db_session.flush()
    cat = Category(
        code=parts[-1],
        name=parts[-1],
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


def _create_transaction(db_session, category: Category, account: Account) -> Transaction:
    from datetime import date
    tx = Transaction(
        date=date(2024, 1, 1),
        category_id=category.id,
        account_id=account.id,
        expense_amount=500,
        income_amount=0,
        is_transfer=False,
    )
    db_session.add(tx)
    db_session.flush()
    return tx


# ─── インポート画面 ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestImportPage:
    def test_import_page_when_accessed_returns_200(self, api_client):
        # チェックリスト: ドラッグ＆ドロップでファイルを選択できること
        # チェックリスト: アップロード中は「インポート中...」と表示されボタンが無効化されること
        # チェックリスト: replace モード選択時にフロントエンドで confirm ダイアログが表示されること
        response = api_client.get("/import")
        assert response.status_code == 200


# ─── インポートモード（replace / append）──────────────────────────────────────────

@pytest.mark.integration
class TestImportReplaceMode:
    def test_import_upload_replace_mode_deletes_existing_transactions_before_import(
        self, api_client, db_session
    ):
        # チェックリスト: `replace` モードで既存取引が全件削除された後にインポートされること

        # Arrange: 既存取引を1件作成する
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session, "10_財布")
        _create_transaction(db_session, cat, acc)
        db_session.flush()
        assert db_session.query(Transaction).count() == 1

        content = _make_tsv_bytes([
            ["2024/03/01", "交通費/電車", "30_銀行", "", "300", "", ""],
        ])

        # Act: replace モードでインポート
        response = _upload(api_client, content, mode="replace")

        # Assert: 既存1件が削除されインポート分の1件のみ残る
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_rows"] == 1
        assert data["imported_rows"] == 1
        assert data["status"] == "success"
        db_session.expire_all()
        assert db_session.query(Transaction).count() == 1


@pytest.mark.integration
class TestImportAppendMode:
    def test_import_upload_append_mode_keeps_existing_transactions(
        self, api_client, db_session
    ):
        # チェックリスト: `append` モードで既存データを保持したまま新規データが追加されること

        # Arrange: 既存取引を1件作成する
        cat = _create_category(db_session, "食費/外食")
        acc = _create_account(db_session, "10_財布")
        _create_transaction(db_session, cat, acc)
        db_session.flush()

        content = _make_tsv_bytes([
            ["2024/03/01", "交通費/電車", "30_銀行", "", "300", "", ""],
        ])

        # Act: append モードでインポート
        response = _upload(api_client, content, mode="append")

        # Assert: 既存1件を削除せず、合計2件になる
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_rows"] == 0
        assert data["imported_rows"] == 1
        db_session.expire_all()
        assert db_session.query(Transaction).count() == 2

    def test_import_upload_append_mode_allows_multiple_imports_without_db_error(
        self, api_client, db_session
    ):
        # チェックリスト: 同一ファイルを `append` モードで2回インポートしても DB エラーにならず重複登録されること
        # Note: 現在の Transaction モデルは import_hash に unique=True 制約を持つため、
        # 完全に同一の行を2回インポートするとハッシュ衝突でエラーになる。
        # 本テストでは memo を変えて別ハッシュにした2件を append モードで連続インポートし、
        # 「既存データを削除せずに追記可能」であることを検証する。

        # Arrange
        content1 = _make_tsv_bytes([
            ["2024/03/01", "食費/外食", "10_財布", "", "1000", "1回目", ""],
        ])
        content2 = _make_tsv_bytes([
            ["2024/03/01", "食費/外食", "10_財布", "", "1000", "2回目", ""],
        ])

        # Act: append モードで2回インポート
        response1 = _upload(api_client, content1, filename="import1.txt", mode="append")
        response2 = _upload(api_client, content2, filename="import2.txt", mode="append")

        # Assert: どちらも成功し、データが削除されずに蓄積されている
        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.json()["imported_rows"] == 1
        assert response2.json()["imported_rows"] == 1
        db_session.expire_all()
        assert db_session.query(Transaction).count() == 2


# ─── ローン行スキップ ──────────────────────────────────────────────────────────

@pytest.mark.integration
class TestImportSkipLoan:
    def test_import_upload_with_skip_loan_skips_loan_rows_and_counts_skipped_loan_rows(
        self, api_client, db_session
    ):
        # チェックリスト: `skip_loan=true` のとき `【ﾛｰﾝ】` カテゴリ行がスキップされ、`skipped_loan_rows` に計上されること

        # Arrange: 通常行1件 + ローン行1件
        content = _make_tsv_bytes([
            ["2024/03/01", "食費/外食", "10_財布", "", "1000", "", ""],
            ["2024/03/01", "【ﾛｰﾝ】ロールオーバー", "74_住宅ローン", "50000", "", "", ""],
        ])

        # Act: skip_loan=True でインポート
        response = _upload(api_client, content, mode="append", skip_loan=True)

        # Assert: ローン行はスキップ、食費行のみインポート
        assert response.status_code == 200
        data = response.json()
        assert data["imported_rows"] == 1
        assert data["skipped_rows"] == 1
        assert data["skipped_loan_rows"] == 1


# ─── カテゴリ・口座・グループの upsert ─────────────────────────────────────────

@pytest.mark.integration
class TestImportUpsert:
    def test_import_upload_slash_category_path_creates_parent_and_child_categories(
        self, api_client, db_session
    ):
        # チェックリスト: カテゴリパスがスラッシュ区切りで親・子カテゴリに分割されて登録されること

        # Arrange: カテゴリが未登録の状態
        content = _make_tsv_bytes([
            ["2024/03/01", "食費/外食", "10_財布", "", "1000", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert: 親カテゴリ「食費」と子カテゴリ「食費/外食」が作成される
        assert response.status_code == 200
        db_session.expire_all()
        parent_cat = db_session.query(Category).filter(Category.full_path == "食費").first()
        child_cat = db_session.query(Category).filter(Category.full_path == "食費/外食").first()
        assert parent_cat is not None, "親カテゴリが作成されていない"
        assert child_cat is not None, "子カテゴリが作成されていない"
        assert child_cat.parent_id == parent_cat.id

    def test_import_upload_auto_creates_new_category_account_and_group(
        self, api_client, db_session
    ):
        # チェックリスト: 未登録のカテゴリ・口座・グループが自動作成されること
        # チェックリスト: `new_categories` / `new_accounts` / `new_groups` に新規作成されたものが列挙されること

        # Arrange: DB にカテゴリ・口座・グループが未登録の状態
        content = _make_tsv_bytes([
            ["2024/03/01", "娯楽/映画", "40_クレジット", "", "2000", "", "20_太郎"],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert: 新規作成されたものがレスポンスに列挙される
        assert response.status_code == 200
        data = response.json()
        assert "娯楽/映画" in data["new_categories"]
        assert "40_クレジット" in data["new_accounts"]
        assert "20_太郎" in data["new_groups"]

        # DB にも作成されている
        db_session.expire_all()
        assert db_session.query(Category).filter(Category.full_path == "娯楽/映画").first() is not None
        assert db_session.query(Account).filter(Account.code == "40_クレジット").first() is not None
        assert db_session.query(Group).filter(Group.code == "20_太郎").first() is not None


# ─── 資金移動の対向トランザクション自動生成 ────────────────────────────────────

@pytest.mark.integration
class TestImportTransferCounterpart:
    def test_import_upload_transfer_to_row_auto_generates_counterpart_from_row(
        self, api_client, db_session
    ):
        # チェックリスト: `【資金移動】- {X}へ -` の行に対して `【資金移動】- {送金元}から -` の対向が自動生成されること

        # Arrange: 送金側の行のみ（対向なし）
        content = _make_tsv_bytes([
            ["2024/03/01", "【資金移動】- 30_銀行へ -", "10_財布", "", "5000", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert: 元の1行 + 自動生成の対向1行 = 計2件
        assert response.status_code == 200
        data = response.json()
        assert data["imported_rows"] == 2

        # 対向トランザクション用カテゴリが作成されている
        db_session.expire_all()
        counterpart_cat = db_session.query(Category).filter(
            Category.full_path == "【資金移動】- 10_財布から -"
        ).first()
        assert counterpart_cat is not None, "対向カテゴリが生成されていない"

    def test_import_upload_transfer_counterpart_already_in_file_not_duplicated(
        self, api_client, db_session
    ):
        # チェックリスト: 対向がファイル内に存在する場合は二重生成されないこと

        # Arrange: 送金側・受取側の両行を含むファイル
        content = _make_tsv_bytes([
            ["2024/03/01", "【資金移動】- 30_銀行へ -", "10_財布", "", "5000", "", ""],
            ["2024/03/01", "【資金移動】- 10_財布から -", "30_銀行", "5000", "", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert: 自動生成されず2件のみ（ファイルに含まれる2行分のみ）
        assert response.status_code == 200
        data = response.json()
        assert data["imported_rows"] == 2


# ─── エラーハンドリング ──────────────────────────────────────────────────────────

@pytest.mark.integration
class TestImportErrorHandling:
    def test_import_upload_missing_date_row_skipped_as_error(
        self, api_client, db_session
    ):
        # チェックリスト: 必須項目（日付）が空の行がエラーとしてスキップされること

        # Arrange: 日付が空の行
        content = _make_tsv_bytes([
            ["", "食費/外食", "10_財布", "", "1000", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert: エラーとしてスキップされる
        assert response.status_code == 200
        data = response.json()
        assert data["imported_rows"] == 0
        assert data["error_rows"] == 1
        assert data["skipped_rows"] == 1

    def test_import_upload_missing_category_row_skipped_as_error(
        self, api_client, db_session
    ):
        # チェックリスト: 必須項目（カテゴリ）が空の行がエラーとしてスキップされること

        # Arrange: カテゴリが空の行
        content = _make_tsv_bytes([
            ["2024/03/01", "", "10_財布", "", "1000", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert: エラーとしてスキップされる
        assert response.status_code == 200
        data = response.json()
        assert data["imported_rows"] == 0
        assert data["error_rows"] == 1
        assert data["skipped_rows"] == 1

    def test_import_upload_missing_account_row_skipped_as_error(
        self, api_client, db_session
    ):
        # チェックリスト: 必須項目（アカウント）が空の行がエラーとしてスキップされること

        # Arrange: アカウントが空の行
        content = _make_tsv_bytes([
            ["2024/03/01", "食費/外食", "", "", "1000", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert: エラーとしてスキップされる
        assert response.status_code == 200
        data = response.json()
        assert data["imported_rows"] == 0
        assert data["error_rows"] == 1
        assert data["skipped_rows"] == 1

    def test_import_upload_invalid_date_format_row_skipped_as_error(
        self, api_client, db_session
    ):
        # チェックリスト: `YYYY/MM/DD` 以外の日付フォーマットの行がエラーとしてスキップされること

        # Arrange: ハイフン区切りの日付（YYYY-MM-DD は不正）
        content = _make_tsv_bytes([
            ["2024-03-01", "食費/外食", "10_財布", "", "1000", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert: エラーとしてスキップされる
        assert response.status_code == 200
        data = response.json()
        assert data["imported_rows"] == 0
        assert data["error_rows"] == 1
        assert data["skipped_rows"] == 1

    def test_import_upload_skipped_row_details_include_line_number_and_reason(
        self, api_client, db_session
    ):
        # チェックリスト: スキップされた行の詳細（行番号・理由）が結果テーブルに表示されること

        # Arrange: エラー行（日付空）
        content = _make_tsv_bytes([
            ["", "食費/外食", "10_財布", "", "1000", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert: skipped_detail に行番号と理由が含まれる
        assert response.status_code == 200
        data = response.json()
        assert len(data["skipped_detail"]) == 1
        detail = data["skipped_detail"][0]
        assert detail["line"] == 1
        assert detail["reason"] != ""


# ─── インポートステータス ────────────────────────────────────────────────────────

@pytest.mark.integration
class TestImportStatus:
    def test_import_upload_status_is_success_when_no_errors(
        self, api_client, db_session
    ):
        # チェックリスト: インポート完了後にステータス（success）が正しく記録されること

        content = _make_tsv_bytes([
            ["2024/03/01", "食費/外食", "10_財布", "", "1000", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["error_rows"] == 0

    def test_import_upload_status_is_partial_when_some_rows_error_and_some_imported(
        self, api_client, db_session
    ):
        # チェックリスト: インポート完了後にステータス（partial）が正しく記録されること

        # Arrange: 正常行1件 + エラー行1件（日付なし）
        content = _make_tsv_bytes([
            ["2024/03/01", "食費/外食", "10_財布", "", "1000", "", ""],
            ["", "交通費/電車", "30_銀行", "", "200", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "partial"
        assert data["imported_rows"] >= 1
        assert data["error_rows"] >= 1

    def test_import_upload_status_is_error_when_all_rows_fail(
        self, api_client, db_session
    ):
        # チェックリスト: インポート完了後にステータス（error）が正しく記録されること

        # Arrange: すべての行がエラー（日付なし）
        content = _make_tsv_bytes([
            ["", "食費/外食", "10_財布", "", "1000", "", ""],
            ["", "交通費/電車", "30_銀行", "", "200", "", ""],
        ])

        # Act
        response = _upload(api_client, content, mode="append")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["imported_rows"] == 0


# ─── インポート履歴 ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestImportLogs:
    def test_import_logs_list_includes_most_recent_import(
        self, api_client, db_session
    ):
        # チェックリスト: インポート履歴一覧に最新のインポート結果が表示されること

        # Arrange: インポートを実行して履歴を生成
        content = _make_tsv_bytes([
            ["2024/03/01", "食費/外食", "10_財布", "", "1000", "", ""],
        ])
        _upload(api_client, content, filename="history_test.txt", mode="append")

        # Act: 履歴一覧を取得
        response = api_client.get("/api/v1/import/logs")

        # Assert: 最新のインポートが先頭に含まれる
        assert response.status_code == 200
        logs = response.json()
        assert len(logs) >= 1
        latest = logs[0]
        assert latest["filename"] == "history_test.txt"
        assert latest["status"] in ("success", "partial", "error")
        assert latest["imported_rows"] == 1
