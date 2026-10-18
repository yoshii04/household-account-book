"""
フェーズ3: import_service の拡充ユニットテスト

純粋関数テスト（_parse_amount, _extract_display_name, _make_transfer_counterpart）と
モック DB を使ったパースロジックテスト（import_actual_txt）を含む。
"""
import asyncio
from unittest.mock import MagicMock, patch

from app.services.import_service import (
    _extract_display_name,
    _make_transfer_counterpart,
    _parse_amount,
    import_actual_txt,
)


class TestParseAmount:
    """_parse_amount の境界値・異常系テスト"""

    def test_integer_string(self):
        assert _parse_amount("1000") == 1000

    def test_comma_separated(self):
        assert _parse_amount("1,234,567") == 1234567

    def test_empty_string_returns_zero(self):
        assert _parse_amount("") == 0

    def test_whitespace_only_returns_zero(self):
        assert _parse_amount("   ") == 0

    def test_invalid_string_returns_zero(self):
        assert _parse_amount("abc") == 0

    def test_leading_trailing_spaces_trimmed(self):
        assert _parse_amount("  500  ") == 500


class TestExtractDisplayName:
    """_extract_display_name の変換テスト"""

    def test_returns_code_as_is(self):
        assert _extract_display_name("A30_通信費") == "A30_通信費"

    def test_simple_name_unchanged(self):
        assert _extract_display_name("食費") == "食費"


class TestMakeTransferCounterpart:
    """_make_transfer_counterpart の資金移動対向データ生成テスト"""

    def test_transfer_to_generates_income_counterpart(self):
        """「〜へ」側（送金）→ 受取側の対向データ（入金）を生成"""
        result = _make_transfer_counterpart(
            date_str="2024/01/15",
            category_path="【資金移動】- 30_銀行へ -",
            account_code="10_財布",
            income_str="",
            expense_str="5000",
            income=0,
            expense=5000,
            memo="財布から銀行",
            group_code="20_太郎",
        )
        assert result is not None
        assert result["account_code"] == "30_銀行"   # 対向は送金先アカウント
        assert result["income"] == 5000              # 受取側は入金
        assert result["expense"] == 0
        assert "から" in result["category_path"]     # 対向カテゴリは「〜から」

    def test_transfer_from_generates_expense_counterpart(self):
        """「〜から」側（受取）→ 送金側の対向データ（出金）を生成"""
        result = _make_transfer_counterpart(
            date_str="2024/01/15",
            category_path="【資金移動】- 10_財布から -",
            account_code="30_銀行",
            income_str="5000",
            expense_str="",
            income=5000,
            expense=0,
            memo="銀行から財布",
            group_code="",
        )
        assert result is not None
        assert result["account_code"] == "10_財布"  # 対向は送金元アカウント
        assert result["income"] == 0
        assert result["expense"] == 5000            # 送金側は出金
        assert "へ" in result["category_path"]      # 対向カテゴリは「〜へ」

    def test_non_transfer_category_returns_none(self):
        """通常カテゴリは対向データなし（None を返す）"""
        result = _make_transfer_counterpart(
            date_str="2024/01/15",
            category_path="食費/外食",
            account_code="10_財布",
            income_str="",
            expense_str="1000",
            income=0,
            expense=1000,
            memo="ランチ",
            group_code="",
        )
        assert result is None

    def test_same_input_produces_same_hash(self):
        """同一入力から決定論的なハッシュが生成される"""
        kwargs = dict(
            date_str="2024/01/15",
            category_path="【資金移動】- 30_銀行へ -",
            account_code="10_財布",
            income_str="",
            expense_str="5000",
            income=0,
            expense=5000,
            memo="test",
            group_code="",
        )
        r1 = _make_transfer_counterpart(**kwargs)
        r2 = _make_transfer_counterpart(**kwargs)
        assert r1["hash"] == r2["hash"]


class TestImportActualTxtParse:
    """import_actual_txt のパースロジックをモック DB で検証するテスト"""

    @staticmethod
    def _make_db():
        """最小限の DB モックを返す"""
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        return db

    @staticmethod
    def _utf16(lines: list[str]) -> bytes:
        """UTF-16 BOM 付きバイト列を生成するヘルパー"""
        return "\n".join(lines).encode("utf-16")

    def test_empty_file_returns_error_status(self):
        """空ファイルは status='error' を返す"""
        db = self._make_db()
        result = asyncio.run(import_actual_txt(db, "".encode("utf-16"), "empty.txt"))
        assert result.status == "error"
        assert result.total_rows == 0

    @patch("app.services.import_service._upsert_category")
    @patch("app.services.import_service._upsert_account")
    @patch("app.services.import_service._upsert_group")
    def test_valid_row_imported_successfully(
        self, mock_upsert_group, mock_upsert_account, mock_upsert_category
    ):
        """正常な1行が imported_rows=1 でインポートされる"""
        mock_upsert_category.return_value = (MagicMock(id=1), True)
        mock_upsert_account.return_value = (MagicMock(id=2), True)
        mock_upsert_group.return_value = (MagicMock(id=3), True)

        db = self._make_db()
        content = self._utf16([
            "日　付\tカテゴリー\tアカウント\t入金額\t出金額\tメ　モ\tグループ",
            "2024/01/15\t食費/外食\t10_財布\t\t1000\tランチ\t20_太郎",
        ])

        result = asyncio.run(import_actual_txt(db, content, "test.txt"))
        assert result.imported_rows == 1
        assert result.error_rows == 0

    @patch("app.services.import_service._upsert_category")
    @patch("app.services.import_service._upsert_account")
    @patch("app.services.import_service._upsert_group")
    def test_invalid_date_format_counted_as_error(
        self, mock_upsert_group, mock_upsert_account, mock_upsert_category
    ):
        """YYYY-MM-DD など不正な日付フォーマットはエラー行として記録される"""
        db = self._make_db()
        content = self._utf16([
            "日　付\tカテゴリー\tアカウント\t入金額\t出金額\tメ　モ\tグループ",
            "2024-01-15\t食費/外食\t10_財布\t\t1000\tランチ\t",  # ハイフン区切りは不正
        ])

        result = asyncio.run(import_actual_txt(db, content, "test.txt"))
        assert result.imported_rows == 0
        assert result.error_rows >= 1

    @patch("app.services.import_service._upsert_category")
    @patch("app.services.import_service._upsert_account")
    @patch("app.services.import_service._upsert_group")
    def test_transfer_row_sets_is_transfer_true(
        self, mock_upsert_group, mock_upsert_account, mock_upsert_category
    ):
        """【資金移動】カテゴリの行は is_transfer=True で Transaction が追加される"""
        mock_upsert_category.return_value = (MagicMock(id=1), True)
        mock_upsert_account.return_value = (MagicMock(id=2), True)

        db = self._make_db()
        content = self._utf16([
            "日　付\tカテゴリー\tアカウント\t入金額\t出金額\tメ　モ\tグループ",
            "2024/01/15\t【資金移動】- 30_銀行へ -\t10_財布\t\t5000\t\t",
        ])

        result = asyncio.run(import_actual_txt(db, content, "test.txt"))
        assert result.imported_rows >= 1

        # db.add() に渡された Transaction オブジェクトを確認
        added = [call.args[0] for call in db.add.call_args_list if hasattr(call.args[0], "is_transfer")]
        assert any(tx.is_transfer for tx in added), "is_transfer=True の Transaction が存在しない"

    @patch("app.services.import_service._upsert_category")
    @patch("app.services.import_service._upsert_account")
    def test_loan_row_with_short_columns_imported_without_error(
        self, mock_upsert_account, mock_upsert_category
    ):
        """【ﾛｰﾝ】行は末尾列がなくてもエラーなくインポートされる（Noneによる AttributeError 修正）"""
        mock_upsert_category.return_value = (MagicMock(id=1), True)
        mock_upsert_account.return_value = (MagicMock(id=2), True)

        db = self._make_db()
        # 末尾タブなし（出金額・メモ・グループが欠落 = None になる行）
        content = self._utf16([
            "日　付\tカテゴリー\tアカウント\t入金額\t出金額\tメ　モ\tグループ",
            "2024/03/26\t【ﾛｰﾝ】ロールオーバー\t74_サンプル銀行(住宅ローン)\t71508",
        ])

        result = asyncio.run(import_actual_txt(db, content, "test.txt"))
        assert result.imported_rows == 1, f"imported_rows should be 1, got {result.imported_rows}"
        assert result.error_rows == 0, f"error_rows should be 0, got: {result.error_detail}"

    @patch("app.services.import_service._upsert_category")
    @patch("app.services.import_service._upsert_account")
    def test_loan_row_sets_is_transfer_true(
        self, mock_upsert_account, mock_upsert_category
    ):
        """【ﾛｰﾝ】カテゴリの行は is_transfer=True で Transaction が追加される"""
        mock_upsert_category.return_value = (MagicMock(id=1), True)
        mock_upsert_account.return_value = (MagicMock(id=2), True)

        db = self._make_db()
        content = self._utf16([
            "日　付\tカテゴリー\tアカウント\t入金額\t出金額\tメ　モ\tグループ",
            "2024/03/26\t【ﾛｰﾝ】ロールオーバー\t74_サンプル銀行(住宅ローン)\t71508\t\t\t",
        ])

        result = asyncio.run(import_actual_txt(db, content, "test.txt"))
        added = [call.args[0] for call in db.add.call_args_list if hasattr(call.args[0], "is_transfer")]
        loan_txs = [tx for tx in added if hasattr(tx, "is_transfer")]
        assert any(tx.is_transfer for tx in loan_txs), "【ﾛｰﾝ】行は is_transfer=True でなければならない"

    @patch("app.services.import_service._upsert_category")
    @patch("app.services.import_service._upsert_account")
    def test_loan_row_suppresses_duplicate_counterpart(
        self, mock_upsert_account, mock_upsert_category
    ):
        """【ﾛｰﾝ】行がある場合、対応する【資金移動】の対向が自動生成されない"""
        mock_upsert_category.return_value = (MagicMock(id=1), True)
        mock_upsert_account.return_value = (MagicMock(id=2), True)

        db = self._make_db()
        content = self._utf16([
            "日　付\tカテゴリー\tアカウント\t入金額\t出金額\tメ　モ\tグループ",
            # 銀行側：ローン口座へ送金
            "2024/03/26\t【資金移動】- 74_住宅ローンへ -\t59_サンプル銀行\t\t87245\t\t",
            # ローン口座側：【ﾛｰﾝ】受取
            "2024/03/26\t【ﾛｰﾝ】ロールオーバー\t74_住宅ローン\t71508\t\t\t",
        ])

        result = asyncio.run(import_actual_txt(db, content, "test.txt"))
        # 2行（銀行送金 + ローン受取）のみ、余分な自動対向は生成されない
        assert result.imported_rows == 2, (
            f"imported_rows should be 2 (no extra counterpart), got {result.imported_rows}"
        )
