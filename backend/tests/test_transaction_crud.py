"""
crud/transaction.py のユニットテスト

_to_out_dict の純粋関数テストと、
各 CRUD 関数のモック DB テストを含む。

【モックのポイント】
 - _to_out_dict: Transaction の属性を MagicMock でシミュレート
 - get_transactions: _with_joins(db.query()) の filter チェーンを
   mock_q.filter.return_value = mock_q（自己参照）で再現
 - get_all_transactions: order_by().all() チェーンを別途設定
 - get_recent_by_category: order_by().limit().all() チェーンを設定
"""
from datetime import date
from unittest.mock import MagicMock

from app.crud.transaction import (
    _to_out_dict,
    get_transactions,
    get_all_transactions,
    get_recent_by_category,
    search_recent,
    create_transaction,
    update_transaction,
    delete_transaction,
    get_transaction,
    upsert_transfer_category,
    create_transfer,
)
from app.schemas.transaction import TransactionCreate, TransactionUpdate, TransferCreate


def _make_tx(**overrides) -> MagicMock:
    """
    Transaction ORM モックを返すヘルパー。
    group は None がデフォルト（グループなし）。
    """
    tx = MagicMock()
    tx.id = overrides.get("id", 1)
    tx.date = overrides.get("date", date(2024, 1, 15))
    tx.category_id = overrides.get("category_id", 1)
    tx.account_id = overrides.get("account_id", 1)
    tx.income_amount = overrides.get("income_amount", 0)
    tx.expense_amount = overrides.get("expense_amount", 1000)
    tx.memo = overrides.get("memo", "テスト")
    tx.group_id = overrides.get("group_id", None)
    tx.is_transfer = overrides.get("is_transfer", False)
    tx.transfer_detail = overrides.get("transfer_detail", None)
    tx.category.full_path = overrides.get("category_full_path", "食費/外食")
    tx.category.parent_id = overrides.get("parent_category_id", 10)
    tx.account.code = overrides.get("account_code", "10_財布")
    tx.group = None  # デフォルトはグループなし
    return tx


def _make_db_all(items=None) -> MagicMock:
    """get_all_transactions 用: order_by().all() チェーンを設定"""
    db = MagicMock()
    mock_q = MagicMock()
    db.query.return_value.options.return_value = mock_q
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value.all.return_value = items or []
    return db


def _make_db_recent(items=None) -> MagicMock:
    """get_recent_by_category 用: order_by().limit().all() チェーンを設定"""
    db = MagicMock()
    mock_q = MagicMock()
    db.query.return_value.options.return_value = mock_q
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value.limit.return_value.all.return_value = items or []
    return db


def _make_db(items=None) -> MagicMock:
    """
    get_transactions 用の DB モックを返す。

    _with_joins が db.query().options() を返すため、
    options().return_value を mock_q として設定し、
    mock_q.filter.return_value = mock_q で filter チェーンを実現する。
    """
    db = MagicMock()
    mock_q = MagicMock()
    db.query.return_value.options.return_value = mock_q
    mock_q.filter.return_value = mock_q  # filter を何度呼んでも同じ mock_q を返す
    mock_q.count.return_value = len(items or [])
    (
        mock_q.order_by.return_value
        .offset.return_value
        .limit.return_value
        .all.return_value
    ) = items or []
    return db


class TestToOutDict:
    """_to_out_dict の純粋関数テスト（DB 不要）"""

    def test_basic_expense_transaction(self):
        """支出トランザクションの全フィールドが正しく変換される"""
        tx = _make_tx(
            id=42,
            date=date(2024, 3, 1),
            expense_amount=500,
            memo="コーヒー",
            category_full_path="食費/カフェ",
            account_code="10_財布",
        )
        result = _to_out_dict(tx)

        assert result["id"] == 42
        assert result["expense_amount"] == 500
        assert result["memo"] == "コーヒー"
        assert result["category_full_path"] == "食費/カフェ"
        assert result["account_code"] == "10_財布"
        assert result["is_transfer"] is False

    def test_no_group_returns_none_for_group_code(self):
        """group が None のとき group_code は None"""
        tx = _make_tx()
        tx.group = None

        result = _to_out_dict(tx)

        assert result["group_code"] is None

    def test_transfer_transaction(self):
        """資金移動トランザクションは is_transfer=True、transfer_detail が設定される"""
        tx = _make_tx(
            is_transfer=True,
            transfer_detail="【資金移動】- 30_銀行へ -",
            category_full_path="【資金移動】- 30_銀行へ -",
        )
        result = _to_out_dict(tx)

        assert result["is_transfer"] is True
        assert result["transfer_detail"] == "【資金移動】- 30_銀行へ -"


class TestGetTransactions:
    """get_transactions のフィルター動作をモック DB で検証するテスト"""

    def test_returns_empty_list_when_no_data(self):
        """データなし → 空リストと件数 0 が返る"""
        db = _make_db(items=[])
        results, total = get_transactions(db)

        assert results == []
        assert total == 0

    def test_returns_converted_dicts(self):
        """取得した Transaction が辞書に変換されて返る"""
        tx = _make_tx(id=99, expense_amount=2000, category_full_path="交通費/電車")
        db = _make_db(items=[tx])

        results, total = get_transactions(db)

        assert total == 1
        assert results[0]["id"] == 99
        assert results[0]["expense_amount"] == 2000
        assert results[0]["category_full_path"] == "交通費/電車"

    def test_filter_method_is_called(self):
        """is_transfer=False フィルターなど、filter が必ず呼ばれること"""
        db = _make_db()
        get_transactions(db, is_transfer=False)

        mock_q = db.query.return_value.options.return_value
        assert mock_q.filter.called

    def test_filter_with_category_id(self):
        """category_id 指定時は子カテゴリを含むサブクエリで絞り込まれる"""
        tx = _make_tx(id=10, expense_amount=800)
        db = _make_db(items=[tx])
        results, total = get_transactions(db, category_id=1)
        assert total == 1
        assert results[0]["id"] == 10

    def test_filter_with_account_id(self):
        """account_id フィルターが適用される"""
        tx = _make_tx(id=11)
        db = _make_db(items=[tx])
        results, total = get_transactions(db, account_id=2)
        assert total == 1

    def test_filter_with_group_id(self):
        """group_id フィルターが適用される"""
        tx = _make_tx(id=12)
        db = _make_db(items=[tx])
        results, total = get_transactions(db, group_id=3)
        assert total == 1

    def test_filter_with_search(self):
        """search キーワードでメモ・カテゴリをサブクエリ検索"""
        tx = _make_tx(id=13, memo="テスト")
        db = _make_db(items=[tx])
        results, total = get_transactions(db, search="テスト")
        assert total == 1


class TestGetAllTransactions:
    """get_all_transactions のモック DB テスト（ページングなし全件取得）"""

    def test_returns_empty_when_no_data(self):
        """データなし → 空リストが返る"""
        db = _make_db_all()
        results = get_all_transactions(db)
        assert results == []

    def test_returns_all_items(self):
        """取得した Transaction がすべて辞書に変換されて返る"""
        tx1 = _make_tx(id=1, expense_amount=500)
        tx2 = _make_tx(id=2, expense_amount=300)
        db = _make_db_all(items=[tx1, tx2])
        results = get_all_transactions(db)
        assert len(results) == 2

    def test_filter_with_year(self):
        """year フィルターが適用される（filter が呼ばれる）"""
        db = _make_db_all()
        get_all_transactions(db, year=2024)
        mock_q = db.query.return_value.options.return_value
        assert mock_q.filter.called

    def test_filter_with_month(self):
        """month フィルターが適用される"""
        db = _make_db_all()
        get_all_transactions(db, month=3)
        mock_q = db.query.return_value.options.return_value
        assert mock_q.filter.called

    def test_filter_with_category_id(self):
        """category_id 指定で子カテゴリ込みサブクエリが使われる"""
        tx = _make_tx(id=5)
        db = _make_db_all(items=[tx])
        results = get_all_transactions(db, category_id=1)
        assert len(results) == 1

    def test_filter_with_account_id(self):
        tx = _make_tx(id=6)
        db = _make_db_all(items=[tx])
        results = get_all_transactions(db, account_id=2)
        assert len(results) == 1

    def test_filter_with_group_id(self):
        tx = _make_tx(id=7)
        db = _make_db_all(items=[tx])
        results = get_all_transactions(db, group_id=3)
        assert len(results) == 1

    def test_filter_with_search(self):
        tx = _make_tx(id=8)
        db = _make_db_all(items=[tx])
        results = get_all_transactions(db, search="食費")
        assert len(results) == 1


class TestGetRecentByCategory:
    """get_recent_by_category のモック DB テスト"""

    def test_returns_items(self):
        tx = _make_tx(id=20, expense_amount=300)
        db = _make_db_recent(items=[tx])
        results = get_recent_by_category(db, category_id=1)
        assert len(results) == 1
        assert results[0]["expense_amount"] == 300

    def test_returns_empty_for_no_data(self):
        db = _make_db_recent()
        results = get_recent_by_category(db, category_id=99)
        assert results == []

    def test_custom_limit_accepted(self):
        txs = [_make_tx(id=i) for i in range(5)]
        db = _make_db_recent(items=txs)
        results = get_recent_by_category(db, category_id=1, limit=5)
        assert len(results) == 5


class TestSearchRecent:
    """search_recent のモック DB テスト"""

    def test_returns_empty_list_for_no_match(self):
        """ヒットなし（モック全体が空 iterator）→ 空リストが返る"""
        db = MagicMock()
        results = search_recent(db, "存在しないキーワード")
        assert results == []

    def test_returns_converted_items(self):
        """ヒットあり → 辞書リストが返る"""
        tx = _make_tx(id=30, memo="テスト検索")
        db = MagicMock()
        mock_q = MagicMock()
        db.query.return_value.options.return_value = mock_q
        (
            mock_q.join.return_value
            .join.return_value
            .filter.return_value
            .order_by.return_value
            .limit.return_value
            .all.return_value
        ) = [tx]
        results = search_recent(db, "テスト")
        assert len(results) == 1
        assert results[0]["memo"] == "テスト検索"


class TestCRUDOperations:
    """create / update / delete / get の各操作テスト"""

    def test_create_transaction(self):
        """create_transaction は db.add → commit → refresh を実行する"""
        db = MagicMock()
        data = TransactionCreate(
            date=date(2024, 1, 15),
            category_id=1,
            account_id=2,
            income_amount=0,
            expense_amount=1000,
        )
        create_transaction(db, data)
        assert db.add.called
        assert db.commit.called
        assert db.refresh.called

    def test_update_transaction_not_found_returns_none(self):
        """存在しない ID は None を返す"""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        result = update_transaction(db, 999, TransactionUpdate())
        assert result is None

    def test_update_transaction_found_commits(self):
        """存在する TX は更新されて commit / refresh される"""
        db = MagicMock()
        mock_tx = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = mock_tx
        update_transaction(db, 1, TransactionUpdate(memo="更新後"))
        assert db.commit.called
        assert db.refresh.called

    def test_delete_transaction_not_found_returns_false(self):
        """存在しない TX は False を返す"""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        assert delete_transaction(db, 999) is False

    def test_delete_transaction_found_returns_true(self):
        """存在する TX は削除後 True を返す"""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock()
        assert delete_transaction(db, 1) is True
        assert db.delete.called
        assert db.commit.called

    def test_get_transaction_not_found_returns_none(self):
        """存在しない ID は None を返す"""
        db = MagicMock()
        db.query.return_value.options.return_value.filter.return_value.first.return_value = None
        assert get_transaction(db, 999) is None

    def test_get_transaction_found_returns_dict(self):
        """存在する TX は辞書として返る"""
        db = MagicMock()
        tx = _make_tx(id=42, expense_amount=500)
        db.query.return_value.options.return_value.filter.return_value.first.return_value = tx
        result = get_transaction(db, 42)
        assert result is not None
        assert result["id"] == 42
        assert result["expense_amount"] == 500


class TestUpsertTransferCategory:
    """upsert_transfer_category の動作テスト"""

    def test_returns_existing_category(self):
        """既存カテゴリがあれば DB 検索結果をそのまま返す"""
        db = MagicMock()
        existing_cat = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing_cat
        result = upsert_transfer_category(db, "【資金移動】- 30_銀行へ -")
        assert result is existing_cat

    def test_creates_new_category_with_parent(self):
        """カテゴリ未存在 + 親も未存在 → 親と子を両方作成"""
        db = MagicMock()
        # 1回目 (existing check): None, 2回目 (parent check): None
        db.query.return_value.filter.return_value.first.side_effect = [None, None]
        mock_parent = MagicMock()
        mock_parent.id = 10

        original_add = db.add.side_effect
        def add_side_effect(obj):
            # 親 Category に id を付与するためのモック
            if hasattr(obj, 'full_path') and obj.full_path == "【資金移動】":
                obj.id = 10
        db.add.side_effect = add_side_effect

        result = upsert_transfer_category(db, "【資金移動】- 30_銀行へ -")
        assert db.add.call_count >= 2
        assert db.flush.call_count >= 1

    def test_creates_child_when_parent_exists(self):
        """カテゴリ未存在 + 親は存在 → 子のみ作成"""
        db = MagicMock()
        mock_parent = MagicMock()
        mock_parent.id = 5
        # 1回目 (existing check): None, 2回目 (parent check): mock_parent
        db.query.return_value.filter.return_value.first.side_effect = [None, mock_parent]
        result = upsert_transfer_category(db, "【資金移動】- 30_銀行へ -")
        assert db.add.call_count == 1  # 子カテゴリのみ追加


class TestCreateTransfer:
    """create_transfer の動作テスト"""

    def test_raises_when_from_account_not_found(self):
        """送金元アカウント不在は ValueError"""
        import pytest
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        data = TransferCreate(
            date=date(2024, 1, 15),
            from_account_id=1,
            to_account_id=2,
            amount=5000,
        )
        with pytest.raises(ValueError, match="送金元"):
            create_transfer(db, data)

    def test_raises_when_to_account_not_found(self):
        """送金先アカウント不在は ValueError"""
        import pytest
        db = MagicMock()
        from_acc = MagicMock()
        from_acc.code = "10_財布"
        # 1回目(from): from_acc, 2回目(to): None
        db.query.return_value.filter.return_value.first.side_effect = [from_acc, None]
        data = TransferCreate(
            date=date(2024, 1, 15),
            from_account_id=1,
            to_account_id=2,
            amount=5000,
        )
        with pytest.raises(ValueError, match="送金先"):
            create_transfer(db, data)

    def test_creates_both_transactions_on_success(self):
        """成功時は出金・入金の 2 件の Transaction を作成して返す"""
        db = MagicMock()
        from_acc = MagicMock()
        from_acc.code = "10_財布"
        to_acc = MagicMock()
        to_acc.code = "30_銀行"
        # Account クエリ
        db.query.return_value.filter.return_value.first.side_effect = [
            from_acc, to_acc,   # from/to account lookups
            None, None,         # upsert_transfer_category existing checks
            None, None,         # upsert_transfer_category parent checks
        ]
        data = TransferCreate(
            date=date(2024, 1, 15),
            from_account_id=1,
            to_account_id=2,
            amount=5000,
            memo="テスト送金",
        )
        tx_out, tx_in = create_transfer(db, data)
        assert db.add.call_count >= 2
        assert db.commit.called
