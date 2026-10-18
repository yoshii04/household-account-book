"""
月次集計・前年同月比・カテゴリ×グループ マトリックスレポートサービス
"""
import calendar
from collections import defaultdict
from datetime import date
from sqlalchemy import func, extract, case
from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.models.category import Category
from app.models.group import Group
from app.models.account import Account
from app.models.account_type import AccountType


def get_monthly_summary(db: Session, year: int, month: int) -> dict:
    """費目別月次集計"""
    rows = (
        db.query(
            Category.id.label("cat_id"),
            Category.full_path.label("full_path"),
            Category.parent_id.label("parent_id"),
            Category.code.label("code"),
            Category.name.label("name"),
            func.sum(Transaction.income_amount).label("total_income"),
            func.sum(Transaction.expense_amount).label("total_expense"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .filter(
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == month,
            Transaction.is_transfer.is_(False),
        )
        .group_by(Category.id, Category.full_path, Category.parent_id, Category.code, Category.name)
        .order_by(Category.full_path)
        .all()
    )

    # 全体合計（is_transfer=False の全行から算出）
    total_income = sum(r.total_income or 0 for r in rows)
    total_expense = sum(r.total_expense or 0 for r in rows)

    # 子カテゴリが参照している親カテゴリ ID を収集し、DB から取得
    child_rows = [r for r in rows if r.parent_id is not None]
    parent_rows = [r for r in rows if r.parent_id is None]

    parent_map: dict[int, dict] = {}

    # トランザクションに直接紐づく親カテゴリ（parent_id=None）を登録
    for r in parent_rows:
        parent_map[r.cat_id] = {
            "cat_id": r.cat_id,
            "full_path": r.full_path,
            "code": r.code,
            "name": r.name,
            "total_income": r.total_income or 0,
            "total_expense": r.total_expense or 0,
            "children": [],
        }

    # 子カテゴリの親で parent_map に未登録のものを DB から補完
    missing_parent_ids = {
        r.parent_id for r in child_rows if r.parent_id not in parent_map
    }
    if missing_parent_ids:
        parent_cats = (
            db.query(Category)
            .filter(Category.id.in_(missing_parent_ids))
            .all()
        )
        for pc in parent_cats:
            parent_map[pc.id] = {
                "cat_id": pc.id,
                "full_path": pc.full_path,
                "code": pc.code,
                "name": pc.name,
                "total_income": 0,
                "total_expense": 0,
                "children": [],
            }

    # 子カテゴリを親に紐づける
    for r in child_rows:
        entry = {
            "cat_id": r.cat_id,
            "full_path": r.full_path,
            "code": r.code,
            "name": r.name,
            "total_income": r.total_income or 0,
            "total_expense": r.total_expense or 0,
        }
        if r.parent_id in parent_map:
            parent_map[r.parent_id]["children"].append(entry)
            # 親の合計にも加算（親カテゴリ自体に取引がない場合）
            parent_map[r.parent_id]["total_income"] += entry["total_income"]
            parent_map[r.parent_id]["total_expense"] += entry["total_expense"]
        else:
            # 親が見つからない場合はそのまま親として登録
            parent_map[r.cat_id] = {**entry, "children": []}

    all_categories = sorted(parent_map.values(), key=lambda x: x["full_path"])

    # 収入カテゴリ（収入合計 > 0）と支出カテゴリに分類
    income_categories = [c for c in all_categories if c["total_income"] > 0]
    expense_categories = [c for c in all_categories if c["total_income"] == 0]

    return {
        "year": year,
        "month": month,
        "total_income": total_income,
        "total_expense": total_expense,
        "categories": all_categories,
        "income_categories": income_categories,
        "expense_categories": expense_categories,
    }


def get_comparison(db: Session, year: int, month: int) -> dict:
    """前年同月比"""
    rows = (
        db.query(
            Category.id.label("cat_id"),
            Category.full_path.label("full_path"),
            Category.parent_id.label("parent_id"),
            Category.code.label("code"),
            Category.name.label("name"),
            func.sum(
                case((extract("year", Transaction.date) == year, Transaction.expense_amount), else_=0)
            ).label("this_year_expense"),
            func.sum(
                case((extract("year", Transaction.date) == year - 1, Transaction.expense_amount), else_=0)
            ).label("last_year_expense"),
            func.sum(
                case((extract("year", Transaction.date) == year, Transaction.income_amount), else_=0)
            ).label("this_year_income"),
            func.sum(
                case((extract("year", Transaction.date) == year - 1, Transaction.income_amount), else_=0)
            ).label("last_year_income"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .filter(
            extract("month", Transaction.date) == month,
            extract("year", Transaction.date).in_([year, year - 1]),
            Transaction.is_transfer.is_(False),
        )
        .group_by(Category.id, Category.full_path, Category.parent_id, Category.code, Category.name)
        .order_by(Category.full_path)
        .all()
    )

    def _make_item(r_or_cat, this_e=0, last_e=0, this_i=0, last_i=0):
        diff_e = this_e - last_e
        ratio_e = round((this_e / last_e - 1) * 100, 1) if last_e else None
        diff_i = this_i - last_i
        ratio_i = round((this_i / last_i - 1) * 100, 1) if last_i else None
        return {
            "cat_id": r_or_cat.cat_id if hasattr(r_or_cat, "cat_id") else r_or_cat.id,
            "full_path": r_or_cat.full_path,
            "parent_id": r_or_cat.parent_id,
            "code": r_or_cat.code,
            "name": r_or_cat.name,
            "this_year_expense": this_e,
            "last_year_expense": last_e,
            "this_year_income": this_i,
            "last_year_income": last_i,
            "diff_expense": diff_e,
            "ratio_expense": ratio_e,
            "diff_income": diff_i,
            "ratio_income": ratio_i,
            "children": [],
        }

    # 親カテゴリを parent_map に登録
    parent_map: dict[int, dict] = {}
    child_rows = [r for r in rows if r.parent_id is not None]

    for r in rows:
        if r.parent_id is None:
            parent_map[r.cat_id] = _make_item(
                r,
                this_e=r.this_year_expense or 0,
                last_e=r.last_year_expense or 0,
                this_i=r.this_year_income or 0,
                last_i=r.last_year_income or 0,
            )

    # 子カテゴリの親が未登録なら DB から補完
    missing_parent_ids = {r.parent_id for r in child_rows if r.parent_id not in parent_map}
    if missing_parent_ids:
        for pc in db.query(Category).filter(Category.id.in_(missing_parent_ids)).all():
            parent_map[pc.id] = _make_item(pc)

    # 子カテゴリを親に紐づけ、親の合計に加算
    for r in child_rows:
        this_e = r.this_year_expense or 0
        last_e = r.last_year_expense or 0
        this_i = r.this_year_income or 0
        last_i = r.last_year_income or 0
        child = _make_item(r, this_e=this_e, last_e=last_e, this_i=this_i, last_i=last_i)
        child.pop("children")  # 子に children キーは不要

        if r.parent_id in parent_map:
            parent = parent_map[r.parent_id]
            parent["children"].append(child)
            parent["this_year_expense"] += this_e
            parent["last_year_expense"] += last_e
            parent["this_year_income"] += this_i
            parent["last_year_income"] += last_i
        else:
            # 親が見つからない場合は親として登録
            parent_map[r.cat_id] = {**child, "children": []}

    # 子を加算した後に親の diff/ratio を再計算
    for parent in parent_map.values():
        this_e = parent["this_year_expense"]
        last_e = parent["last_year_expense"]
        this_i = parent["this_year_income"]
        last_i = parent["last_year_income"]
        parent["diff_expense"] = this_e - last_e
        parent["ratio_expense"] = round((this_e / last_e - 1) * 100, 1) if last_e else None
        parent["diff_income"] = this_i - last_i
        parent["ratio_income"] = round((this_i / last_i - 1) * 100, 1) if last_i else None
        # 子も full_path でソート
        parent["children"].sort(key=lambda x: x["full_path"])

    all_categories = sorted(parent_map.values(), key=lambda x: x["full_path"])

    # 収入カテゴリ（今年または前年で収入あり）と支出カテゴリに分類
    income_categories = [
        c for c in all_categories
        if c["this_year_income"] > 0 or c["last_year_income"] > 0
    ]
    expense_categories = [
        c for c in all_categories
        if c["this_year_income"] == 0 and c["last_year_income"] == 0
    ]

    # 収入計・支出計・収支の合計
    total_this_income = sum(c["this_year_income"] for c in income_categories)
    total_last_income = sum(c["last_year_income"] for c in income_categories)
    total_this_expense = sum(c["this_year_expense"] for c in expense_categories)
    total_last_expense = sum(c["last_year_expense"] for c in expense_categories)
    total_this_balance = total_this_income - total_this_expense
    total_last_balance = total_last_income - total_last_expense

    return {
        "year": year,
        "last_year": year - 1,
        "month": month,
        "income_categories": income_categories,
        "expense_categories": expense_categories,
        "total_this_income": total_this_income,
        "total_last_income": total_last_income,
        "total_this_expense": total_this_expense,
        "total_last_expense": total_last_expense,
        "total_this_balance": total_this_balance,
        "total_last_balance": total_last_balance,
        "diff_income": total_this_income - total_last_income,
        "diff_expense_total": total_this_expense - total_last_expense,
        "diff_balance": total_this_balance - total_last_balance,
    }


def get_matrix_report(db: Session, year: int, month: int) -> dict:
    """
    カテゴリ(縦) × グループ(横) の金額マトリックス。
    収入カテゴリを上部、支出カテゴリを下部に分けて表示する。
    """

    # カテゴリ × グループ ごとに収入・支出を集計
    rows = (
        db.query(
            Category.id.label("cat_id"),
            Category.full_path.label("full_path"),
            Category.parent_id.label("parent_id"),
            Category.name.label("cat_name"),
            Transaction.group_id.label("group_id"),
            func.sum(Transaction.income_amount).label("total_income"),
            func.sum(Transaction.expense_amount).label("total_expense"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .filter(
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == month,
            Transaction.is_transfer.is_(False),
        )
        .group_by(
            Category.id, Category.full_path, Category.parent_id,
            Category.name, Transaction.group_id,
        )
        .order_by(Category.full_path)
        .all()
    )

    # セルデータを cat_id × group_id で集約（収入・支出それぞれ）
    income_cells: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    expense_cells: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    cat_info: dict[int, dict] = {}
    all_group_ids: set = set()

    for r in rows:
        inc = r.total_income or 0
        exp = r.total_expense or 0
        income_cells[r.cat_id][r.group_id] += inc
        expense_cells[r.cat_id][r.group_id] += exp
        all_group_ids.add(r.group_id)
        if r.cat_id not in cat_info:
            cat_info[r.cat_id] = {
                "cat_id": r.cat_id,
                "full_path": r.full_path,
                "parent_id": r.parent_id,
                "name": r.cat_name,
            }

    # グループ一覧を取得（コード順）
    has_no_group = None in all_group_ids
    group_id_set = all_group_ids - {None}
    groups_out: list[dict] = []
    if group_id_set:
        grps = (
            db.query(Group)
            .filter(Group.id.in_(group_id_set))
            .order_by(Group.code)
            .all()
        )
        groups_out = [{"id": g.id, "code": g.code, "name": g.name} for g in grps]

    # カテゴリを収入/支出に分類（親カテゴリの収入合計で判定）
    # 収入合計 > 0 のカテゴリを収入カテゴリとして扱う
    def _total_income_for(cid: int) -> int:
        return sum(income_cells[cid].values())

    def _total_expense_for(cid: int) -> int:
        return sum(expense_cells[cid].values())

    # 親子構造の組み立て
    child_ids = {cid for cid, info in cat_info.items() if info["parent_id"] is not None}
    parent_ids = {cid for cid, info in cat_info.items() if info["parent_id"] is None}

    def _make_entry(cid: int, cells: dict, total: int) -> dict:
        return {
            "cat_id": cid,
            "full_path": cat_info[cid]["full_path"],
            "name": cat_info[cid]["name"],
            "cells": dict(cells),
            "row_total": total,
        }

    parent_map: dict[int, dict] = {}

    # 親カテゴリ登録（収入/支出のどちらを使うかは後で決定）
    for cid in parent_ids:
        inc_total = _total_income_for(cid)
        exp_total = _total_expense_for(cid)
        is_income = inc_total > 0
        cells = dict(income_cells[cid]) if is_income else dict(expense_cells[cid])
        entry = _make_entry(cid, cells, inc_total if is_income else exp_total)
        entry["children"] = []
        entry["is_income"] = is_income
        parent_map[cid] = entry

    # 子カテゴリの親が未登録なら DB から補完
    missing_parent_ids = {
        cat_info[cid]["parent_id"]
        for cid in child_ids
        if cat_info[cid]["parent_id"] not in parent_map
    }
    if missing_parent_ids:
        for pc in db.query(Category).filter(Category.id.in_(missing_parent_ids)).all():
            parent_map[pc.id] = {
                "cat_id": pc.id,
                "full_path": pc.full_path,
                "name": pc.name,
                "cells": {},
                "row_total": 0,
                "children": [],
                "is_income": False,  # 子の集計後に再判定
            }

    # 子カテゴリを親に紐づけ、親セルに加算
    for cid in child_ids:
        pid = cat_info[cid]["parent_id"]
        inc_total = _total_income_for(cid)
        exp_total = _total_expense_for(cid)
        # 親の収入/支出タイプに合わせてセルを決定（後で親タイプを確定）
        # まず両方の合計で親を更新し、最後にタイプを確定する
        if pid in parent_map:
            parent = parent_map[pid]
            # 子の収入/支出どちらかを集計（親のis_incomeに合わせる）
            # 先に子の income/expense を仮集計して親のタイプを確定
            child_inc_cells = dict(income_cells[cid])
            child_exp_cells = dict(expense_cells[cid])
            # 親のis_incomeは後で確定するので両方保持
            parent.setdefault("_inc_cells", defaultdict(int))
            parent.setdefault("_exp_cells", defaultdict(int))
            for gid, amt in child_inc_cells.items():
                parent["_inc_cells"][gid] += amt
            for gid, amt in child_exp_cells.items():
                parent["_exp_cells"][gid] += amt

            # 子エントリは収入/支出どちらかを使う（子自身で判定）
            is_child_income = inc_total > 0
            cells = child_inc_cells if is_child_income else child_exp_cells
            total = inc_total if is_child_income else exp_total
            child_entry = {
                "cat_id": cid,
                "full_path": cat_info[cid]["full_path"],
                "name": cat_info[cid]["name"],
                "cells": cells,
                "row_total": total,
                "is_income": is_child_income,
            }
            parent["children"].append(child_entry)
        else:
            # 親が見つからない場合は親として登録
            inc_total2 = _total_income_for(cid)
            exp_total2 = _total_expense_for(cid)
            is_income = inc_total2 > 0
            cells = dict(income_cells[cid]) if is_income else dict(expense_cells[cid])
            parent_map[cid] = {
                "cat_id": cid,
                "full_path": cat_info[cid]["full_path"],
                "name": cat_info[cid]["name"],
                "cells": cells,
                "row_total": inc_total2 if is_income else exp_total2,
                "children": [],
                "is_income": is_income,
            }

    # 親カテゴリのセルを子の集計で更新し、収入/支出タイプを確定
    for cid, parent in parent_map.items():
        inc_acc = parent.pop("_inc_cells", defaultdict(int))
        exp_acc = parent.pop("_exp_cells", defaultdict(int))
        total_inc = sum(inc_acc.values()) + sum(
            v for v in parent.get("cells", {}).values()
            if parent.get("is_income", False)
        )
        total_exp = sum(exp_acc.values()) + sum(
            v for v in parent.get("cells", {}).values()
            if not parent.get("is_income", False)
        )
        # 収入合計が1円でもあれば収入カテゴリ
        # ただし親自身の is_income が既に True の場合はそれを優先
        if not parent.get("is_income", False):
            parent["is_income"] = sum(inc_acc.values()) > 0
        is_income = parent["is_income"]
        if inc_acc or exp_acc:
            acc = inc_acc if is_income else exp_acc
            for gid, amt in acc.items():
                parent["cells"][gid] = parent["cells"].get(gid, 0) + amt
            parent["row_total"] += sum(acc.values())

    # 収入カテゴリ・支出カテゴリに分類してソート
    income_categories = sorted(
        [c for c in parent_map.values() if c["is_income"]],
        key=lambda x: x["full_path"],
    )
    expense_categories = sorted(
        [c for c in parent_map.values() if not c["is_income"]],
        key=lambda x: x["full_path"],
    )

    # 列合計（収入セクション・支出セクション別）
    def _col_totals(cats: list[dict]) -> dict:
        totals: dict = defaultdict(int)
        for cat in cats:
            for gid, amt in cat["cells"].items():
                totals[gid] += amt
        return dict(totals)

    income_col_totals = _col_totals(income_categories)
    expense_col_totals = _col_totals(expense_categories)
    income_grand_total = sum(income_col_totals.values())
    expense_grand_total = sum(expense_col_totals.values())

    return {
        "year": year,
        "month": month,
        "groups": groups_out,
        "has_no_group": has_no_group,
        "income_categories": income_categories,
        "expense_categories": expense_categories,
        "income_col_totals": income_col_totals,
        "expense_col_totals": expense_col_totals,
        "income_grand_total": income_grand_total,
        "expense_grand_total": expense_grand_total,
    }


def get_annual_report(db: Session, start_year: int, end_year: int) -> dict:
    """
    start_year〜end_year のカテゴリ別年次収支レポート。
    縦軸: 収入/支出の親・子カテゴリ  横軸: 各年
    """
    years = list(range(start_year, end_year + 1))

    # カテゴリ × 年 で収入・支出を集計
    rows = (
        db.query(
            Category.id.label("cat_id"),
            Category.full_path.label("full_path"),
            Category.parent_id.label("parent_id"),
            Category.name.label("name"),
            extract("year", Transaction.date).label("tx_year"),
            func.sum(Transaction.income_amount).label("total_income"),
            func.sum(Transaction.expense_amount).label("total_expense"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .filter(
            extract("year", Transaction.date) >= start_year,
            extract("year", Transaction.date) <= end_year,
            Transaction.is_transfer.is_(False),
        )
        .group_by(
            Category.id, Category.full_path, Category.parent_id, Category.name,
            extract("year", Transaction.date),
        )
        .order_by(Category.full_path)
        .all()
    )

    # cat_id → year(str) → amount を収入・支出別に集計
    income_data: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    expense_data: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    cat_info: dict[int, dict] = {}

    for r in rows:
        key = str(int(r.tx_year))
        income_data[r.cat_id][key] += r.total_income or 0
        expense_data[r.cat_id][key] += r.total_expense or 0
        if r.cat_id not in cat_info:
            cat_info[r.cat_id] = {
                "cat_id": r.cat_id,
                "full_path": r.full_path,
                "parent_id": r.parent_id,
                "name": r.name,
            }

    child_ids = {cid for cid, info in cat_info.items() if info["parent_id"] is not None}
    parent_ids = {cid for cid, info in cat_info.items() if info["parent_id"] is None}

    # 親マップ初期化
    parent_map: dict[int, dict] = {}
    for cid in parent_ids:
        parent_map[cid] = {
            "cat_id": cid,
            "full_path": cat_info[cid]["full_path"],
            "name": cat_info[cid]["name"],
            "_inc": defaultdict(int),
            "_exp": defaultdict(int),
            "children": [],
        }
        for k, v in income_data[cid].items():
            parent_map[cid]["_inc"][k] += v
        for k, v in expense_data[cid].items():
            parent_map[cid]["_exp"][k] += v

    # 子の親が未登録なら DB から補完
    missing = {
        cat_info[cid]["parent_id"]
        for cid in child_ids
        if cat_info[cid]["parent_id"] not in parent_map
    }
    if missing:
        for pc in db.query(Category).filter(Category.id.in_(missing)).all():
            parent_map[pc.id] = {
                "cat_id": pc.id,
                "full_path": pc.full_path,
                "name": pc.name,
                "_inc": defaultdict(int),
                "_exp": defaultdict(int),
                "children": [],
            }

    # 子カテゴリを親に紐づけ、親の集計に加算
    for cid in child_ids:
        pid = cat_info[cid]["parent_id"]
        child_inc_total = sum(income_data[cid].values())
        child_exp_total = sum(expense_data[cid].values())
        child_is_income = child_inc_total > 0
        child_cells = dict(income_data[cid]) if child_is_income else dict(expense_data[cid])
        child_total = child_inc_total if child_is_income else child_exp_total

        child_entry = {
            "cat_id": cid,
            "full_path": cat_info[cid]["full_path"],
            "name": cat_info[cid]["name"],
            "is_income": child_is_income,
            "cells": child_cells,
            "row_total": child_total,
        }

        if pid in parent_map:
            parent = parent_map[pid]
            parent["children"].append(child_entry)
            for k, v in income_data[cid].items():
                parent["_inc"][k] += v
            for k, v in expense_data[cid].items():
                parent["_exp"][k] += v
        else:
            parent_map[cid] = {**child_entry, "children": []}

    # 親の最終確定
    for cid, parent in list(parent_map.items()):
        if "_inc" not in parent:
            continue
        inc_total = sum(parent["_inc"].values())
        exp_total = sum(parent["_exp"].values())
        is_income = inc_total > 0
        parent["is_income"] = is_income
        parent["cells"] = dict(parent["_inc"] if is_income else parent["_exp"])
        parent["row_total"] = inc_total if is_income else exp_total
        del parent["_inc"]
        del parent["_exp"]
        parent["children"].sort(key=lambda x: x["full_path"])

    all_categories = sorted(parent_map.values(), key=lambda x: x["full_path"])
    income_categories = [c for c in all_categories if c["is_income"]]
    expense_categories = [c for c in all_categories if not c["is_income"]]

    # 年別合計・総計
    income_year_totals: dict[str, int] = defaultdict(int)
    expense_year_totals: dict[str, int] = defaultdict(int)
    for cat in income_categories:
        for k, v in cat["cells"].items():
            income_year_totals[k] += v
    for cat in expense_categories:
        for k, v in cat["cells"].items():
            expense_year_totals[k] += v

    balance_year_totals = {
        str(y): income_year_totals[str(y)] - expense_year_totals[str(y)]
        for y in years
    }
    income_grand_total = sum(income_year_totals.values())
    expense_grand_total = sum(expense_year_totals.values())

    return {
        "start_year": start_year,
        "end_year": end_year,
        "years": years,
        "income_categories": income_categories,
        "expense_categories": expense_categories,
        "income_year_totals": dict(income_year_totals),
        "expense_year_totals": dict(expense_year_totals),
        "balance_year_totals": balance_year_totals,
        "income_grand_total": income_grand_total,
        "expense_grand_total": expense_grand_total,
        "balance_grand_total": income_grand_total - expense_grand_total,
    }


def get_yearly_trend(db: Session, end_year: int, end_month: int) -> dict:
    """
    end_month を終点として過去12ヶ月のカテゴリ別収支トレンド。
    縦軸: 収支の親・子カテゴリ  横軸: 12ヶ月
    """
    # 12ヶ月リストを古い順で生成（string key = "YYYY-M"）
    months_list = []
    y, m = end_year, end_month
    for _ in range(12):
        months_list.append({"year": y, "month": m, "key": f"{y}-{m}"})
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months_list.reverse()

    start_year, start_month = months_list[0]["year"], months_list[0]["month"]
    start_date = date(start_year, start_month, 1)
    last_day = calendar.monthrange(end_year, end_month)[1]
    end_date = date(end_year, end_month, last_day)

    # カテゴリ × 月 で収入・支出を集計
    rows = (
        db.query(
            Category.id.label("cat_id"),
            Category.full_path.label("full_path"),
            Category.parent_id.label("parent_id"),
            Category.name.label("name"),
            extract("year", Transaction.date).label("tx_year"),
            extract("month", Transaction.date).label("tx_month"),
            func.sum(Transaction.income_amount).label("total_income"),
            func.sum(Transaction.expense_amount).label("total_expense"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .filter(
            Transaction.date >= start_date,
            Transaction.date <= end_date,
            Transaction.is_transfer.is_(False),
        )
        .group_by(
            Category.id, Category.full_path, Category.parent_id, Category.name,
            extract("year", Transaction.date),
            extract("month", Transaction.date),
        )
        .order_by(Category.full_path)
        .all()
    )

    # cat_id → key → amount を収入・支出別に集計
    income_data: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    expense_data: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    cat_info: dict[int, dict] = {}

    for r in rows:
        key = f"{int(r.tx_year)}-{int(r.tx_month)}"
        income_data[r.cat_id][key] += r.total_income or 0
        expense_data[r.cat_id][key] += r.total_expense or 0
        if r.cat_id not in cat_info:
            cat_info[r.cat_id] = {
                "cat_id": r.cat_id,
                "full_path": r.full_path,
                "parent_id": r.parent_id,
                "name": r.name,
            }

    child_ids = {cid for cid, info in cat_info.items() if info["parent_id"] is not None}
    parent_ids = {cid for cid, info in cat_info.items() if info["parent_id"] is None}

    # 親マップ初期化（収入・支出の両方を一時的に保持）
    parent_map: dict[int, dict] = {}
    for cid in parent_ids:
        parent_map[cid] = {
            "cat_id": cid,
            "full_path": cat_info[cid]["full_path"],
            "name": cat_info[cid]["name"],
            "_inc": defaultdict(int),
            "_exp": defaultdict(int),
            "children": [],
        }
        for k, v in income_data[cid].items():
            parent_map[cid]["_inc"][k] += v
        for k, v in expense_data[cid].items():
            parent_map[cid]["_exp"][k] += v

    # 子の親が未登録なら DB から補完
    missing = {
        cat_info[cid]["parent_id"]
        for cid in child_ids
        if cat_info[cid]["parent_id"] not in parent_map
    }
    if missing:
        for pc in db.query(Category).filter(Category.id.in_(missing)).all():
            parent_map[pc.id] = {
                "cat_id": pc.id,
                "full_path": pc.full_path,
                "name": pc.name,
                "_inc": defaultdict(int),
                "_exp": defaultdict(int),
                "children": [],
            }

    # 子カテゴリを親に紐づけ、親の集計に加算
    for cid in child_ids:
        pid = cat_info[cid]["parent_id"]
        child_inc_total = sum(income_data[cid].values())
        child_exp_total = sum(expense_data[cid].values())
        child_is_income = child_inc_total > 0
        child_cells = dict(income_data[cid]) if child_is_income else dict(expense_data[cid])
        child_total = child_inc_total if child_is_income else child_exp_total

        child_entry = {
            "cat_id": cid,
            "full_path": cat_info[cid]["full_path"],
            "name": cat_info[cid]["name"],
            "is_income": child_is_income,
            "cells": child_cells,
            "row_total": child_total,
        }

        if pid in parent_map:
            parent = parent_map[pid]
            parent["children"].append(child_entry)
            for k, v in income_data[cid].items():
                parent["_inc"][k] += v
            for k, v in expense_data[cid].items():
                parent["_exp"][k] += v
        else:
            parent_map[cid] = {**child_entry, "children": []}

    # 親の最終確定（収入/支出の分類、cells 決定）
    for cid, parent in list(parent_map.items()):
        if "_inc" not in parent:
            continue  # 子として登録されたケース
        inc_total = sum(parent["_inc"].values())
        exp_total = sum(parent["_exp"].values())
        is_income = inc_total > 0
        parent["is_income"] = is_income
        parent["cells"] = dict(parent["_inc"] if is_income else parent["_exp"])
        parent["row_total"] = inc_total if is_income else exp_total
        del parent["_inc"]
        del parent["_exp"]
        parent["children"].sort(key=lambda x: x["full_path"])

    all_categories = sorted(parent_map.values(), key=lambda x: x["full_path"])
    income_categories = [c for c in all_categories if c["is_income"]]
    expense_categories = [c for c in all_categories if not c["is_income"]]

    # 月別合計・年間計
    income_month_totals: dict[str, int] = defaultdict(int)
    expense_month_totals: dict[str, int] = defaultdict(int)
    for cat in income_categories:
        for k, v in cat["cells"].items():
            income_month_totals[k] += v
    for cat in expense_categories:
        for k, v in cat["cells"].items():
            expense_month_totals[k] += v

    balance_month_totals = {
        ym["key"]: income_month_totals[ym["key"]] - expense_month_totals[ym["key"]]
        for ym in months_list
    }
    income_row_total = sum(income_month_totals.values())
    expense_row_total = sum(expense_month_totals.values())

    # ヘッダー用 年スパン（colspan 計算）
    year_spans: list[dict] = []
    for ym in months_list:
        if year_spans and year_spans[-1]["year"] == ym["year"]:
            year_spans[-1]["count"] += 1
        else:
            year_spans.append({"year": ym["year"], "count": 1})

    return {
        "end_year": end_year,
        "end_month": end_month,
        "months": months_list,
        "year_spans": year_spans,
        "income_categories": income_categories,
        "expense_categories": expense_categories,
        "income_month_totals": dict(income_month_totals),
        "expense_month_totals": dict(expense_month_totals),
        "balance_month_totals": balance_month_totals,
        "income_row_total": income_row_total,
        "expense_row_total": expense_row_total,
        "balance_row_total": income_row_total - expense_row_total,
    }


def get_account_annual_report(db: Session, start_year: int, end_year: int) -> dict:
    """アカウント別年次レポート（累計残高）

    縦軸: 種別／アカウント  横軸: 年
    各セル: 初回取引（または start_date）から各年末時点の累計残高（initial_balance 含む）
    """
    years = list(range(start_year, end_year + 1))

    # 種別ラベル・表示順を DB から取得
    type_rows = db.query(AccountType).order_by(AccountType.sort_order, AccountType.code).all()
    type_labels: dict[str, str] = {t.code: t.label for t in type_rows}
    type_order: list[str] = [t.code for t in type_rows]

    acc_rows = (
        db.query(Account)
        .filter(Account.is_active.is_(True))
        .order_by(Account.sort_order, Account.code)
        .all()
    )

    accounts = []
    for acc in acc_rows:
        # end_year 末までの全取引を年別に集計（start_year より前の年も含む）
        q = (
            db.query(
                extract("year", Transaction.date).label("tx_year"),
                func.sum(Transaction.income_amount).label("total_income"),
                func.sum(Transaction.expense_amount).label("total_expense"),
            )
            .filter(
                Transaction.account_id == acc.id,
                Transaction.date <= date(end_year, 12, 31),
            )
        )
        if acc.start_date:
            q = q.filter(Transaction.date >= acc.start_date)

        q = q.group_by(extract("year", Transaction.date))
        year_rows = q.all()

        yearly_net: dict[int, int] = {}
        for yr in year_rows:
            y = int(yr.tx_year)
            inc = yr.total_income or 0
            exp = yr.total_expense or 0
            yearly_net[y] = inc - exp

        initial_balance = acc.initial_balance or 0
        adjustment_amount = acc.adjustment_amount or 0
        base = initial_balance + adjustment_amount
        has_data = bool(yearly_net) or base != 0
        if not has_data:
            continue

        # 各表示年の累計残高 = initial_balance + adjustment_amount + その年末までの全年次純収支の合計
        cells: dict[str, int] = {}
        for target_year in years:
            cumulative = base + sum(
                v for y, v in yearly_net.items() if y <= target_year
            )
            cells[str(target_year)] = cumulative

        row_total = cells.get(str(end_year), base)
        accounts.append({
            "account_id": acc.id,
            "code": acc.code,
            "name": acc.name,
            "account_type": acc.account_type,
            "start_date": acc.start_date.isoformat() if acc.start_date else None,
            "cells": cells,
            "row_total": row_total,
        })

    # 種別ごとにグループ化
    by_type: dict[str, list] = defaultdict(list)
    for acc in accounts:
        by_type[acc["account_type"]].append(acc)

    grouped = []
    seen_types: set[str] = set()
    for t in type_order:
        if t in by_type:
            seen_types.add(t)
            items = by_type[t]
            subtotal_cells = {
                str(y): sum(a["cells"].get(str(y), 0) for a in items)
                for y in years
            }
            grouped.append({
                "type": t,
                "type_label": type_labels.get(t, t),
                "accounts": items,
                "subtotal_cells": subtotal_cells,
                "subtotal_total": subtotal_cells.get(str(end_year), 0),
            })
    for t, items in by_type.items():
        if t not in seen_types:
            subtotal_cells = {
                str(y): sum(a["cells"].get(str(y), 0) for a in items)
                for y in years
            }
            grouped.append({
                "type": t,
                "type_label": type_labels.get(t, t),
                "accounts": items,
                "subtotal_cells": subtotal_cells,
                "subtotal_total": subtotal_cells.get(str(end_year), 0),
            })

    year_totals: dict[str, int] = {
        str(y): sum(a["cells"].get(str(y), 0) for a in accounts)
        for y in years
    }
    grand_total = year_totals.get(str(end_year), 0)

    return {
        "start_year": start_year,
        "end_year": end_year,
        "years": years,
        "accounts": accounts,
        "grouped": grouped,
        "year_totals": year_totals,
        "grand_total": grand_total,
    }


def get_account_classification_annual_report(db: Session, start_year: int, end_year: int) -> dict:
    """分類別アカウント年次レポート（累計残高）

    縦軸: 分類  横軸: 年
    各セル: 各年末時点の累計残高（initial_balance + adjustment_amount 含む）
    """
    years = list(range(start_year, end_year + 1))

    acc_rows = (
        db.query(Account)
        .filter(Account.is_active.is_(True))
        .order_by(Account.sort_order, Account.code)
        .all()
    )

    # classification → year_str → sum of cumulative balances
    class_data: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    has_any_data = False

    for acc in acc_rows:
        q = (
            db.query(
                extract("year", Transaction.date).label("tx_year"),
                func.sum(Transaction.income_amount).label("total_income"),
                func.sum(Transaction.expense_amount).label("total_expense"),
            )
            .filter(
                Transaction.account_id == acc.id,
                Transaction.date <= date(end_year, 12, 31),
            )
        )
        if acc.start_date:
            q = q.filter(Transaction.date >= acc.start_date)

        year_rows = q.group_by(extract("year", Transaction.date)).all()

        yearly_net: dict[int, int] = {}
        for yr in year_rows:
            y = int(yr.tx_year)
            yearly_net[y] = (yr.total_income or 0) - (yr.total_expense or 0)

        base = (acc.initial_balance or 0) + (acc.adjustment_amount or 0)
        if not yearly_net and base == 0:
            continue

        has_any_data = True
        cls_key = acc.classification or ""

        for target_year in years:
            cumulative = base + sum(v for y, v in yearly_net.items() if y <= target_year)
            class_data[cls_key][str(target_year)] += cumulative

    # 分類ありは名前順、分類なし（""）は末尾
    classified_rows = []
    unclassified_row = None

    for cls in sorted(class_data.keys()):
        cells = dict(class_data[cls])
        row = {
            "classification": cls or None,
            "cells": cells,
            "row_total": cells.get(str(end_year), 0),
        }
        if cls:
            classified_rows.append(row)
        else:
            unclassified_row = row

    all_rows = classified_rows + ([unclassified_row] if unclassified_row else [])

    year_totals = {
        str(y): sum(class_data[cls][str(y)] for cls in class_data)
        for y in years
    }

    return {
        "start_year": start_year,
        "end_year": end_year,
        "years": years,
        "rows": all_rows,
        "year_totals": year_totals,
        "grand_total": year_totals.get(str(end_year), 0),
        "has_data": has_any_data,
    }


def get_account_annual_monthly_report(db: Session, year: int) -> dict:
    """アカウント別月次累計レポート（指定年の1〜12月）

    縦軸: 種別／アカウント  横軸: 1〜12月
    各セル: 初回取引（または start_date）から各月末時点の累計残高（initial_balance 含む）
    """
    months = list(range(1, 13))

    type_rows = db.query(AccountType).order_by(AccountType.sort_order, AccountType.code).all()
    type_labels: dict[str, str] = {t.code: t.label for t in type_rows}
    type_order: list[str] = [t.code for t in type_rows]

    acc_rows = (
        db.query(Account)
        .filter(Account.is_active.is_(True))
        .order_by(Account.sort_order, Account.code)
        .all()
    )

    accounts = []
    for acc in acc_rows:
        q = (
            db.query(
                extract("year", Transaction.date).label("tx_year"),
                extract("month", Transaction.date).label("tx_month"),
                func.sum(Transaction.income_amount).label("total_income"),
                func.sum(Transaction.expense_amount).label("total_expense"),
            )
            .filter(
                Transaction.account_id == acc.id,
                Transaction.date <= date(year, 12, 31),
            )
        )
        if acc.start_date:
            q = q.filter(Transaction.date >= acc.start_date)

        q = q.group_by(
            extract("year", Transaction.date),
            extract("month", Transaction.date),
        )
        month_rows = q.all()

        monthly_net: dict[tuple[int, int], int] = {}
        for mr in month_rows:
            y, m = int(mr.tx_year), int(mr.tx_month)
            monthly_net[(y, m)] = (mr.total_income or 0) - (mr.total_expense or 0)

        initial_balance = acc.initial_balance or 0
        adjustment_amount = acc.adjustment_amount or 0
        base = initial_balance + adjustment_amount
        has_data = bool(monthly_net) or base != 0
        if not has_data:
            continue

        cells: dict[str, int] = {}
        for target_month in months:
            cumulative = base + sum(
                v for (y, m), v in monthly_net.items()
                if y < year or (y == year and m <= target_month)
            )
            cells[str(target_month)] = cumulative

        accounts.append({
            "account_id": acc.id,
            "code": acc.code,
            "name": acc.name,
            "account_type": acc.account_type,
            "start_date": acc.start_date.isoformat() if acc.start_date else None,
            "cells": cells,
            "row_total": cells.get("12", base),
        })

    by_type: dict[str, list] = defaultdict(list)
    for acc in accounts:
        by_type[acc["account_type"]].append(acc)

    grouped = []
    seen_types: set[str] = set()
    for t in type_order:
        if t in by_type:
            seen_types.add(t)
            items = by_type[t]
            subtotal_cells = {
                str(m): sum(a["cells"].get(str(m), 0) for a in items)
                for m in months
            }
            grouped.append({
                "type": t,
                "type_label": type_labels.get(t, t),
                "accounts": items,
                "subtotal_cells": subtotal_cells,
                "subtotal_total": subtotal_cells.get("12", 0),
            })
    for t, items in by_type.items():
        if t not in seen_types:
            subtotal_cells = {
                str(m): sum(a["cells"].get(str(m), 0) for a in items)
                for m in months
            }
            grouped.append({
                "type": t,
                "type_label": type_labels.get(t, t),
                "accounts": items,
                "subtotal_cells": subtotal_cells,
                "subtotal_total": subtotal_cells.get("12", 0),
            })

    month_totals: dict[str, int] = {
        str(m): sum(a["cells"].get(str(m), 0) for a in accounts)
        for m in months
    }

    return {
        "year": year,
        "months": months,
        "accounts": accounts,
        "grouped": grouped,
        "month_totals": month_totals,
        "grand_total": month_totals.get("12", 0),
    }


def get_account_monthly_daily_report(db: Session, year: int, month: int) -> dict:
    """アカウント別日次累計レポート（指定年月の1日〜月末）

    縦軸: 種別／アカウント  横軸: 1〜月末日
    各セル: 初回取引から各日末時点の累計残高（initial_balance 含む）
    """
    days_in_month = calendar.monthrange(year, month)[1]
    days = list(range(1, days_in_month + 1))

    type_rows = db.query(AccountType).order_by(AccountType.sort_order, AccountType.code).all()
    type_labels: dict[str, str] = {t.code: t.label for t in type_rows}
    type_order: list[str] = [t.code for t in type_rows]

    acc_rows = (
        db.query(Account)
        .filter(Account.is_active.is_(True))
        .order_by(Account.sort_order, Account.code)
        .all()
    )

    accounts = []
    for acc in acc_rows:
        # 対象月より前の月別純収支（前月末残高算出用）
        q_monthly = (
            db.query(
                func.sum(Transaction.income_amount).label("total_income"),
                func.sum(Transaction.expense_amount).label("total_expense"),
            )
            .filter(
                Transaction.account_id == acc.id,
                Transaction.date < date(year, month, 1),
            )
        )
        if acc.start_date:
            q_monthly = q_monthly.filter(Transaction.date >= acc.start_date)
        monthly_row = q_monthly.one()
        balance_before_month = (
            (acc.initial_balance or 0)
            + (acc.adjustment_amount or 0)
            + (monthly_row.total_income or 0)
            - (monthly_row.total_expense or 0)
        )

        # 対象月の日別純収支
        q_daily = (
            db.query(
                extract("day", Transaction.date).label("tx_day"),
                func.sum(Transaction.income_amount).label("total_income"),
                func.sum(Transaction.expense_amount).label("total_expense"),
            )
            .filter(
                Transaction.account_id == acc.id,
                Transaction.date >= date(year, month, 1),
                Transaction.date <= date(year, month, days_in_month),
            )
        )
        if acc.start_date:
            q_daily = q_daily.filter(Transaction.date >= acc.start_date)
        q_daily = q_daily.group_by(extract("day", Transaction.date))
        day_rows = q_daily.all()

        daily_net: dict[int, int] = {}
        for dr in day_rows:
            d = int(dr.tx_day)
            daily_net[d] = (dr.total_income or 0) - (dr.total_expense or 0)

        base = (acc.initial_balance or 0) + (acc.adjustment_amount or 0)
        has_data = bool(daily_net) or bool(
            db.query(Transaction.id)
            .filter(
                Transaction.account_id == acc.id,
                Transaction.date < date(year, month, 1),
            )
            .first()
        ) or base != 0
        if not has_data:
            continue

        cells: dict[str, int] = {}
        cumulative = balance_before_month
        for d in days:
            cumulative += daily_net.get(d, 0)
            cells[str(d)] = cumulative

        accounts.append({
            "account_id": acc.id,
            "code": acc.code,
            "name": acc.name,
            "account_type": acc.account_type,
            "start_date": acc.start_date.isoformat() if acc.start_date else None,
            "cells": cells,
            "row_total": cells.get(str(days_in_month), balance_before_month),
        })

    by_type: dict[str, list] = defaultdict(list)
    for acc in accounts:
        by_type[acc["account_type"]].append(acc)

    grouped = []
    seen_types: set[str] = set()
    for t in type_order:
        if t in by_type:
            seen_types.add(t)
            items = by_type[t]
            subtotal_cells = {
                str(d): sum(a["cells"].get(str(d), 0) for a in items)
                for d in days
            }
            grouped.append({
                "type": t,
                "type_label": type_labels.get(t, t),
                "accounts": items,
                "subtotal_cells": subtotal_cells,
                "subtotal_total": subtotal_cells.get(str(days_in_month), 0),
            })
    for t, items in by_type.items():
        if t not in seen_types:
            subtotal_cells = {
                str(d): sum(a["cells"].get(str(d), 0) for a in items)
                for d in days
            }
            grouped.append({
                "type": t,
                "type_label": type_labels.get(t, t),
                "accounts": items,
                "subtotal_cells": subtotal_cells,
                "subtotal_total": subtotal_cells.get(str(days_in_month), 0),
            })

    day_totals: dict[str, int] = {
        str(d): sum(a["cells"].get(str(d), 0) for a in accounts)
        for d in days
    }

    return {
        "year": year,
        "month": month,
        "days": days,
        "days_in_month": days_in_month,
        "accounts": accounts,
        "grouped": grouped,
        "day_totals": day_totals,
        "grand_total": day_totals.get(str(days_in_month), 0),
    }


def get_account_balance_report(db: Session, as_of_date: date, show_zero: bool = False) -> dict:
    """アカウント別金額集計（指定日付時点）

    - start_date が設定されているアカウントはその日以降の取引のみ集計
    - initial_balance + adjustment_amount を残高に加算
    - classification が設定されている場合は分類 → 種別 → 口座の3階層で集計
    - show_zero=False（デフォルト）のとき差引残高が0円の口座を非表示
    """
    # 種別ラベル・表示順を DB から取得
    type_rows = db.query(AccountType).order_by(AccountType.sort_order, AccountType.code).all()
    type_labels: dict[str, str] = {t.code: t.label for t in type_rows}
    type_order: list[str] = [t.code for t in type_rows]

    # アクティブなアカウントを全取得
    acc_rows = (
        db.query(Account)
        .filter(Account.is_active.is_(True))
        .order_by(Account.code)
        .all()
    )

    # アカウントごとに start_date フィルター付きで取引を集計
    accounts = []
    for acc in acc_rows:
        q = (
            db.query(
                func.coalesce(func.sum(Transaction.income_amount), 0).label("total_income"),
                func.coalesce(func.sum(Transaction.expense_amount), 0).label("total_expense"),
            )
            .filter(
                Transaction.account_id == acc.id,
                Transaction.date <= as_of_date,
            )
        )
        if acc.start_date:
            q = q.filter(Transaction.date >= acc.start_date)

        r = q.one()
        total_income = r.total_income or 0
        total_expense = r.total_expense or 0
        initial_balance = acc.initial_balance or 0
        adjustment_amount = acc.adjustment_amount or 0
        balance = initial_balance + adjustment_amount + total_income - total_expense

        # 取引も残高もない場合はスキップ
        if total_income == 0 and total_expense == 0 and initial_balance == 0 and adjustment_amount == 0:
            continue

        # 差引残高が0円の口座は show_zero=False のとき非表示
        if not show_zero and balance == 0:
            continue

        accounts.append({
            "account_id": acc.id,
            "code": acc.code,
            "name": acc.name,
            "account_type": acc.account_type,
            "account_type_label": type_labels.get(acc.account_type, acc.account_type),
            "classification": acc.classification,
            "initial_balance": initial_balance,
            "adjustment_amount": adjustment_amount,
            "total_income": total_income,
            "total_expense": total_expense,
            "balance": balance,
            "start_date": acc.start_date.isoformat() if acc.start_date else None,
        })

    # 口座タイプ別にグループ化（DB の sort_order 順）
    by_type: dict[str, list] = defaultdict(list)
    for acc in accounts:
        by_type[acc["account_type"]].append(acc)

    def _make_type_group(t: str, items: list) -> dict:
        # 種別グループの分類は口座ごとに異なる場合があるため、口座リストをそのまま持つ
        return {
            "type": t,
            "type_label": type_labels.get(t, t),
            "accounts": items,
            "subtotal_initial": sum(a["initial_balance"] for a in items),
            "subtotal_adjustment": sum(a["adjustment_amount"] for a in items),
            "subtotal_income": sum(a["total_income"] for a in items),
            "subtotal_expense": sum(a["total_expense"] for a in items),
            "subtotal_balance": sum(a["balance"] for a in items),
        }

    grouped = []
    seen_types = set()
    for t in type_order:
        if t in by_type:
            seen_types.add(t)
            grouped.append(_make_type_group(t, by_type[t]))
    for t, items in by_type.items():
        if t not in seen_types:
            grouped.append(_make_type_group(t, items))

    # 分類別に口座を集計（口座単位の classification を使用）
    by_class: dict[str, list] = defaultdict(list)
    for a in accounts:
        if a["classification"]:
            by_class[a["classification"]].append(a)

    # 分類別小計（分類名でソート）
    seen_classes: list[str] = []
    for a in accounts:
        c = a["classification"]
        if c and c not in seen_classes:
            seen_classes.append(c)
    seen_classes.sort()

    classified_groups = []
    for c in seen_classes:
        items = by_class[c]
        classified_groups.append({
            "classification": c,
            "subtotal_initial": sum(a["initial_balance"] for a in items),
            "subtotal_adjustment": sum(a["adjustment_amount"] for a in items),
            "subtotal_income": sum(a["total_income"] for a in items),
            "subtotal_expense": sum(a["total_expense"] for a in items),
            "subtotal_balance": sum(a["balance"] for a in items),
        })

    # 分類なしのグループ（種別グループ単位）
    unclassified_account_ids = {a["account_id"] for a in accounts if not a["classification"]}
    unclassified = []
    for g in grouped:
        items = [a for a in g["accounts"] if a["account_id"] in unclassified_account_ids]
        if items:
            unclassified.append({**g, "accounts": items,
                "subtotal_initial": sum(a["initial_balance"] for a in items),
                "subtotal_adjustment": sum(a["adjustment_amount"] for a in items),
                "subtotal_income": sum(a["total_income"] for a in items),
                "subtotal_expense": sum(a["total_expense"] for a in items),
                "subtotal_balance": sum(a["balance"] for a in items),
            })

    grand_initial = sum(a["initial_balance"] for a in accounts)
    grand_adjustment = sum(a["adjustment_amount"] for a in accounts)
    grand_income = sum(a["total_income"] for a in accounts)
    grand_expense = sum(a["total_expense"] for a in accounts)

    return {
        "as_of_date": as_of_date.isoformat(),
        "accounts": accounts,
        "grouped": grouped,
        "classified_groups": classified_groups,
        "unclassified": unclassified,
        "grand_initial": grand_initial,
        "grand_adjustment": grand_adjustment,
        "grand_income": grand_income,
        "grand_expense": grand_expense,
        "grand_balance": grand_initial + grand_adjustment + grand_income - grand_expense,
    }
