"""
フェーズ3: report_service のユニットテスト

MagicMock を使って DB 依存を切り離し、集計ロジックと
親子カテゴリ組み立てロジックを検証する。

【モックのポイント】
 - メイン集計クエリ: db.query().join().filter().group_by().order_by().all()
 - 親補完クエリ:    db.query().filter().all()
 これらは異なるメソッドチェーンを辿るため、MagicMock 上で干渉しない。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.report_service import get_comparison, get_monthly_summary


def _row(**kwargs) -> SimpleNamespace:
    """SQLAlchemy Row 相当の SimpleNamespace を返すヘルパー"""
    return SimpleNamespace(**kwargs)


def _cat(**kwargs) -> SimpleNamespace:
    """Category ORM 相当の SimpleNamespace を返すヘルパー"""
    return SimpleNamespace(**kwargs)


def _make_db(rows, parent_cats=None) -> MagicMock:
    """
    テスト用 DB モックを返す。

    - メイン集計クエリ (.join().filter()...all()) → rows
    - 親補完クエリ (.filter().all())             → parent_cats
    """
    db = MagicMock()
    (
        db.query.return_value
        .join.return_value
        .filter.return_value
        .group_by.return_value
        .order_by.return_value
        .all.return_value
    ) = rows
    db.query.return_value.filter.return_value.all.return_value = parent_cats or []
    return db


class TestGetMonthlySummary:
    """get_monthly_summary の集計ロジックテスト"""

    def test_empty_rows_returns_zero_totals(self):
        """データなし → 合計 0、カテゴリ空リスト"""
        db = _make_db(rows=[])
        result = get_monthly_summary(db, 2024, 1)

        assert result["total_income"] == 0
        assert result["total_expense"] == 0
        assert result["categories"] == []

    def test_child_categories_aggregated_into_parent(self):
        """子カテゴリ 2 件の合計が親カテゴリに集約される"""
        rows = [
            _row(cat_id=2, full_path="食費/外食", parent_id=1, code="外食",
                 name="外食", total_income=0, total_expense=1000),
            _row(cat_id=3, full_path="食費/スーパー", parent_id=1, code="スーパー",
                 name="スーパー", total_income=0, total_expense=2000),
        ]
        parent = _cat(id=1, full_path="食費", code="食費", name="食費")
        db = _make_db(rows=rows, parent_cats=[parent])

        result = get_monthly_summary(db, 2024, 1)

        assert result["total_expense"] == 3000
        assert len(result["expense_categories"]) == 1
        parent_entry = result["expense_categories"][0]
        assert parent_entry["full_path"] == "食費"
        assert parent_entry["total_expense"] == 3000
        assert len(parent_entry["children"]) == 2

    def test_income_and_expense_categories_separated(self):
        """収入カテゴリと支出カテゴリが別リストに分類される"""
        rows = [
            _row(cat_id=1, full_path="給与", parent_id=None, code="給与",
                 name="給与", total_income=300000, total_expense=0),
            _row(cat_id=2, full_path="食費", parent_id=None, code="食費",
                 name="食費", total_income=0, total_expense=50000),
        ]
        db = _make_db(rows=rows)

        result = get_monthly_summary(db, 2024, 1)

        income_paths = {c["full_path"] for c in result["income_categories"]}
        expense_paths = {c["full_path"] for c in result["expense_categories"]}
        assert "給与" in income_paths
        assert "食費" in expense_paths
        assert "給与" not in expense_paths
        assert "食費" not in income_paths


class TestGetComparison:
    """get_comparison の前年同月比計算テスト"""

    def test_ratio_calculated_correctly(self):
        """前年比 = (今年 / 前年 − 1) × 100 で正しく計算される"""
        rows = [
            _row(cat_id=2, full_path="食費/外食", parent_id=1, code="外食", name="外食",
                 this_year_expense=1200, last_year_expense=1000,
                 this_year_income=0, last_year_income=0),
        ]
        parent = _cat(id=1, full_path="食費", parent_id=None, code="食費", name="食費")
        db = _make_db(rows=rows, parent_cats=[parent])

        result = get_comparison(db, 2024, 1)

        exp_cats = result["expense_categories"]
        assert len(exp_cats) == 1
        p = exp_cats[0]
        assert p["this_year_expense"] == 1200
        assert p["last_year_expense"] == 1000
        # (1200 / 1000 - 1) × 100 = 20.0
        assert p["ratio_expense"] == 20.0

    def test_ratio_is_none_when_no_last_year_data(self):
        """前年データ 0 → ratio_expense は None（ゼロ除算なし）"""
        rows = [
            _row(cat_id=1, full_path="食費", parent_id=None, code="食費", name="食費",
                 this_year_expense=1000, last_year_expense=0,
                 this_year_income=0, last_year_income=0),
        ]
        db = _make_db(rows=rows)

        result = get_comparison(db, 2024, 1)

        exp_cats = result["expense_categories"]
        assert len(exp_cats) == 1
        assert exp_cats[0]["ratio_expense"] is None

    def test_comparison_income_category_separated(self):
        """収入カテゴリは income_categories に分類される"""
        rows = [
            _row(cat_id=2, full_path="給与", parent_id=None, code="給与", name="給与",
                 this_year_expense=0, last_year_expense=0,
                 this_year_income=300000, last_year_income=280000),
        ]
        db = _make_db(rows=rows)

        result = get_comparison(db, 2024, 1)

        assert any(c["full_path"] == "給与" for c in result["income_categories"])
        assert not any(c["full_path"] == "給与" for c in result["expense_categories"])

    def test_comparison_totals_calculated(self):
        """収支合計が正しく計算される"""
        rows = [
            _row(cat_id=1, full_path="給与", parent_id=None, code="給与", name="給与",
                 this_year_expense=0, last_year_expense=0,
                 this_year_income=500000, last_year_income=480000),
            _row(cat_id=2, full_path="食費", parent_id=None, code="食費", name="食費",
                 this_year_expense=50000, last_year_expense=48000,
                 this_year_income=0, last_year_income=0),
        ]
        db = _make_db(rows=rows)

        result = get_comparison(db, 2024, 1)

        assert result["total_this_income"] == 500000
        assert result["total_last_income"] == 480000
        assert result["total_this_expense"] == 50000
        assert result["total_last_expense"] == 48000


class TestOrphanParentHandling:
    """親カテゴリが parent_map にも DB にもない場合の孤立処理テスト"""

    def test_monthly_summary_orphan_child_becomes_root(self):
        """get_monthly_summary: 親 ID が未登録の子は独立した親エントリとして登録される（line 100）"""
        rows = [
            _row(cat_id=5, full_path="食費/外食", parent_id=99,
                 code="外食", name="外食", total_income=0, total_expense=500),
        ]
        # DB からの親補完も空（parent_id=99 は存在しない）
        db = _make_db(rows=rows, parent_cats=[])
        result = get_monthly_summary(db, 2024, 1)

        assert result["total_expense"] == 500
        # 孤立した子が親として expense_categories に登録される
        paths = {c["full_path"] for c in result["expense_categories"]}
        assert "食費/外食" in paths

    def test_comparison_orphan_child_becomes_root(self):
        """get_comparison: 親 ID が未登録の子は独立した親エントリとして登録される（line 212）"""
        rows = [
            _row(cat_id=7, full_path="交通費/電車", parent_id=88,
                 code="電車", name="電車",
                 this_year_expense=1000, last_year_expense=800,
                 this_year_income=0, last_year_income=0),
        ]
        db = _make_db(rows=rows, parent_cats=[])
        result = get_comparison(db, 2024, 1)

        paths = {c["full_path"] for c in result["expense_categories"]}
        assert "交通費/電車" in paths
