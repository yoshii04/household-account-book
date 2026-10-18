from datetime import date
from typing import Optional
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session, joinedload

from app.jst import today_jst
from app.models.pattern import TransactionPattern
from app.models.transaction import Transaction
from app.models.category import Category
from app.models.account import Account
from app.models.group import Group
from app.schemas.pattern import PatternCreate, PatternUpdate
from app.utils.date_utils import clamp_day_to_month, month_bounds


# recorded_lookup にパターンIDが存在しない場合のデフォルト値（未記録扱い）。
# _to_dict / _filter_due / _filter_unrecorded で共通利用し、リテラルの重複を避ける。
# 呼び出し側は読み取り専用で使うため、単一インスタンスの共有で問題ない。
_DEFAULT_RECORDED_INFO: dict = {"recorded": False, "transaction_id": None}


def _patterns_query(db: Session):
    """パターン取得時の joinedload オプションを共通化する（get_due_patterns /
    get_unrecorded_patterns / get_patterns / get_pattern で重複していたブロックを集約）。
    """
    return db.query(TransactionPattern).options(
        joinedload(TransactionPattern.category),
        joinedload(TransactionPattern.account),
        joinedload(TransactionPattern.to_account),
        joinedload(TransactionPattern.group),
        joinedload(TransactionPattern.pattern_group),
    )


def _target_period(p: TransactionPattern, today: date) -> Optional[tuple[date, date, date]]:
    """当月（対象期間）の記録状況チェック対象期間 (開始日, 終了日, 支払日) を返す。
    daily/other 頻度、payment_day_of_month 未設定、annual で payment_month_of_year
    未設定の場合は判定対象外として None を返す。
    """
    if not p.payment_day_of_month:
        return None

    if p.frequency == "monthly":
        year, month = today.year, today.month
    elif p.frequency == "annual":
        if not p.payment_month_of_year:
            return None
        year, month = today.year, p.payment_month_of_year
    else:
        return None

    start, end = month_bounds(year, month)
    payment_date = clamp_day_to_month(year, month, p.payment_day_of_month)
    return start, end, payment_date


def _build_recorded_lookup(
    db: Session, patterns: list[TransactionPattern], today: date
) -> dict[int, dict]:
    """パターン群の対象期間の記録状況をまとめて1クエリで判定する（N+1回避）。

    判定方式（ハイブリッド）:
      1. 優先: 対象期間内に transactions.pattern_id が一致する取引が存在するか
      2. フォールバック: pattern_id が NULL でも、category_id + account_id が
         一致する取引が対象期間内に存在するか
         （資金移動パターンは category_id が to_account 側の情報を含めて動的生成されるため、
          category_id + account_id の一致だけで to_account_id の一致も担保される）
         さらに、パターンの group_id が設定されている場合のみ、取引側の group_id も
         同じ値であることを要求する（非対称マッチング）。パターンの group_id が NULL の
         場合は、従来通り取引側の group_id を問わない（ADR-0002）。

    戻り値: {pattern.id: {"recorded": bool, "transaction_id": Optional[int]}}
    """
    applicable = [(p, _target_period(p, today)) for p in patterns]
    applicable = [(p, tp) for p, tp in applicable if tp is not None]
    if not applicable:
        return {}

    # パターンごとの対象期間で個別に絞り込む（全パターンの期間を包含する
    # min〜max の範囲で一括取得すると、対象月がバラける annual パターンが
    # 複数存在する場合に年間全体の取引をスキャンしてしまうため、
    # パターンごとの期間を OR で結合して必要な範囲だけに絞り込む）。
    period_conditions = [
        and_(
            Transaction.date >= start,
            Transaction.date <= end,
            or_(
                Transaction.pattern_id == p.id,
                and_(
                    Transaction.pattern_id.is_(None),
                    Transaction.category_id == p.category_id,
                    Transaction.account_id == p.account_id,
                    *([Transaction.group_id == p.group_id] if p.group_id is not None else []),
                ),
            ),
        )
        for p, (start, end, _pd) in applicable
    ]

    candidates = (
        db.query(Transaction)
        .filter(or_(*period_conditions))
        .order_by(Transaction.date.asc(), Transaction.id.asc())
        .all()
    )

    # パターンID一致は (pattern_id)、フォールバックは group_id 未指定パターンにも
    # 対応できるよう (category_id, account_id) と (category_id, account_id, group_id)
    # の二段階でそれぞれ O(1) 参照できるよう索引化する
    by_pattern_id: dict[int, list[Transaction]] = {}
    by_cat_acc: dict[tuple[int, int], list[Transaction]] = {}
    by_cat_acc_group: dict[tuple[int, int, int], list[Transaction]] = {}
    for tx in candidates:
        if tx.pattern_id is not None:
            by_pattern_id.setdefault(tx.pattern_id, []).append(tx)
        else:
            by_cat_acc.setdefault((tx.category_id, tx.account_id), []).append(tx)
            if tx.group_id is not None:
                by_cat_acc_group.setdefault((tx.category_id, tx.account_id, tx.group_id), []).append(tx)

    lookup: dict[int, dict] = {}
    for p, (start, end, _pd) in applicable:
        # by_pattern_id は tx.pattern_id という取引固有の値で索引化されている。
        # pattern_id が p.id と一致する取引が candidates に含まれているのは、
        # 上記クエリの p 自身の OR 節（date range込み）がマッチしたときだけなので、
        # ここでの日付範囲の再チェックは不要（常に真になる）。
        # 一方 by_cat_acc / by_cat_acc_group は pattern_id が NULL の取引を索引化しており、
        # 同じキーが「別パターンの日付範囲」経由で candidates に含まれている可能性が
        # あるため、こちらは日付範囲の再チェックが必要。
        match = next(iter(by_pattern_id.get(p.id, [])), None)
        if not match:
            # group_id 指定パターンは取引側の group_id も同じ値であることを要求し、
            # group_id 未指定パターンは従来通り取引側の group_id を問わない（非対称マッチング、ADR-0002）。
            key = (p.category_id, p.account_id, p.group_id) if p.group_id is not None else None
            fallback_candidates = by_cat_acc_group.get(key, []) if key else by_cat_acc.get((p.category_id, p.account_id), [])
            match = next((tx for tx in fallback_candidates if start <= tx.date <= end), None)
        lookup[p.id] = {
            "recorded": match is not None,
            "transaction_id": match.id if match else None,
        }
    return lookup


def _resolve_last_next(
    prev_period: date, this_period: date, next_period: date, recorded: bool, today: date
) -> tuple[date, date]:
    """(last_payment_date, next_payment_date) を確定する。

    対象期間内が未記録の場合、next は対象期間内の支払日のまま据え置く（先送りしない）。
    記録済みの場合は支払日ベースで進める（従来ロジック）。
    """
    if not recorded:
        return prev_period, this_period
    if this_period <= today:
        return this_period, next_period
    return prev_period, this_period


def _calc_payment_dates(
    p: TransactionPattern, today: date, recorded: bool
) -> tuple[Optional[date], Optional[date]]:
    """(last_payment_date, next_payment_date) を返す。
    payment_day_of_month 未設定、または daily/other 頻度の場合は (None, None)。
    """
    tp = _target_period(p, today)
    if not tp:
        return None, None
    _start, _end, this_period = tp

    if p.frequency == "monthly":
        prev_y, prev_m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        prev_period = clamp_day_to_month(prev_y, prev_m, p.payment_day_of_month)
        next_y, next_m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        next_period = clamp_day_to_month(next_y, next_m, p.payment_day_of_month)
    else:  # annual（_target_period が None を返さない時点で payment_month_of_year は設定済み）
        prev_period = clamp_day_to_month(today.year - 1, p.payment_month_of_year, p.payment_day_of_month)
        next_period = clamp_day_to_month(today.year + 1, p.payment_month_of_year, p.payment_day_of_month)

    return _resolve_last_next(prev_period, this_period, next_period, recorded, today)


def _to_dict(
    p: TransactionPattern,
    today: Optional[date] = None,
    recorded_lookup: Optional[dict[int, dict]] = None,
) -> dict:
    if today is None:
        today = today_jst()
    info = (recorded_lookup or {}).get(p.id, _DEFAULT_RECORDED_INFO)
    last_pd, next_pd = _calc_payment_dates(p, today, info["recorded"])
    return {
        "id": p.id,
        "name": p.name,
        "frequency": p.frequency,
        "category_id": p.category_id,
        "account_id": p.account_id,
        "to_account_id": p.to_account_id,
        "group_id": p.group_id,
        "pattern_group_id": p.pattern_group_id,
        "typical_amount": p.typical_amount,
        "is_income": p.is_income,
        "memo_template": p.memo_template,
        "payment_day_of_month": p.payment_day_of_month,
        "payment_month_of_year": p.payment_month_of_year,
        "sort_order": p.sort_order,
        "is_active": p.is_active,
        "category_full_path": p.category.full_path if p.category else None,
        "parent_category_id": p.category.parent_id if p.category else None,
        "category_is_transfer": p.category.is_transfer if p.category else False,
        "account_code": p.account.code if p.account else None,
        "to_account_code": p.to_account.code if p.to_account else None,
        "group_code": p.group.code if p.group else None,
        "pattern_group_name": p.pattern_group.name if p.pattern_group else None,
        "last_payment_date": last_pd,
        "next_payment_date": next_pd,
        "is_current_period_recorded": info["recorded"],
        "current_period_transaction_id": info["transaction_id"],
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def _filter_due(
    patterns: list[TransactionPattern], check_date: date, recorded_lookup: dict[int, dict]
) -> list[TransactionPattern]:
    """アクティブパターン群から「今日が支払日」かつ「対象期間が未記録」のものだけを抽出する。"""
    result = []
    for p in patterns:
        if p.payment_day_of_month != check_date.day:
            continue
        if not (
            p.frequency == "monthly"
            or (p.frequency == "annual" and p.payment_month_of_year == check_date.month)
        ):
            continue
        info = recorded_lookup.get(p.id, _DEFAULT_RECORDED_INFO)
        if info["recorded"]:
            continue
        result.append(p)
    return result


def _filter_unrecorded(
    patterns: list[TransactionPattern], today: date, recorded_lookup: dict[int, dict]
) -> list[TransactionPattern]:
    """アクティブパターン群から「対象期間の支払日を過ぎてもなお未記録」のものだけを抽出する。

    daily/other 頻度のパターンは対象外。猶予期間は設けず、支払日を過ぎた
    （today が支払日より後の）時点で即座に対象となる。
    """
    result = []
    for p in patterns:
        tp = _target_period(p, today)
        if not tp:
            continue
        _start, _end, payment_date = tp
        if payment_date >= today:
            continue  # 支払日がまだ過ぎていない
        info = recorded_lookup.get(p.id, _DEFAULT_RECORDED_INFO)
        if info["recorded"]:
            continue
        result.append(p)
    return result


def get_due_patterns(db: Session, check_date: date) -> list[dict]:
    """今日が支払日かつ対象期間が未記録のアクティブパターンを返す。"""
    patterns = (
        _patterns_query(db)
        .filter(
            TransactionPattern.is_active.is_(True),
            TransactionPattern.payment_day_of_month == check_date.day,
        )
        .order_by(TransactionPattern.sort_order, TransactionPattern.id)
        .all()
    )
    recorded_lookup = _build_recorded_lookup(db, patterns, check_date)
    due = _filter_due(patterns, check_date, recorded_lookup)
    return [_to_dict(p, today=check_date, recorded_lookup=recorded_lookup) for p in due]


def get_unrecorded_patterns(db: Session, today: date) -> list[dict]:
    """対象期間の支払日を過ぎてもなお未記録のアクティブパターンを返す。

    daily/other 頻度のパターンは対象外。猶予期間は設けず、支払日を過ぎた
    （today が支払日より後の）時点で即座に対象となる。
    """
    patterns = (
        _patterns_query(db)
        .filter(TransactionPattern.is_active.is_(True))
        .order_by(TransactionPattern.sort_order, TransactionPattern.id)
        .all()
    )
    recorded_lookup = _build_recorded_lookup(db, patterns, today)
    unrecorded = _filter_unrecorded(patterns, today, recorded_lookup)
    return [_to_dict(p, today, recorded_lookup) for p in unrecorded]


def get_due_and_unrecorded_patterns(db: Session, today: date) -> tuple[list[dict], list[dict]]:
    """ダッシュボード用: 「今日の支払いパターン」と「今月未記録のパターン」を
    アクティブパターンの取得・記録状況クエリをそれぞれ1回だけ実行して両方算出する。

    get_due_patterns() と get_unrecorded_patterns() を別々に呼ぶと、
    どちらも独立に「アクティブパターン一覧のクエリ」＋「記録状況の一括判定クエリ」を
    実行してしまい、同じ today に対してダッシュボード表示だけで DB ラウンドトリップが
    2 倍になるため、それを避けるために両者が内部で使う抽出ロジック
    （_filter_due / _filter_unrecorded）だけを共有する。
    """
    patterns = (
        _patterns_query(db)
        .filter(TransactionPattern.is_active.is_(True))
        .order_by(TransactionPattern.sort_order, TransactionPattern.id)
        .all()
    )
    recorded_lookup = _build_recorded_lookup(db, patterns, today)

    due = _filter_due(patterns, today, recorded_lookup)
    unrecorded = _filter_unrecorded(patterns, today, recorded_lookup)

    due_patterns = [_to_dict(p, today=today, recorded_lookup=recorded_lookup) for p in due]
    unrecorded_patterns = [_to_dict(p, today, recorded_lookup) for p in unrecorded]
    return due_patterns, unrecorded_patterns


def get_patterns(db: Session, include_inactive: bool = False) -> list[dict]:
    q = _patterns_query(db)
    if not include_inactive:
        q = q.filter(TransactionPattern.is_active.is_(True))
    patterns = q.order_by(TransactionPattern.sort_order, TransactionPattern.id).all()
    today = today_jst()
    recorded_lookup = _build_recorded_lookup(db, patterns, today)
    return [_to_dict(p, today, recorded_lookup) for p in patterns]


def get_pattern(db: Session, pattern_id: int) -> Optional[dict]:
    p = (
        _patterns_query(db)
        .filter(TransactionPattern.id == pattern_id)
        .first()
    )
    if not p:
        return None
    today = today_jst()
    recorded_lookup = _build_recorded_lookup(db, [p], today)
    return _to_dict(p, today, recorded_lookup)


def create_pattern(db: Session, data: PatternCreate) -> dict:
    p = TransactionPattern(**data.model_dump())
    db.add(p)
    db.commit()
    return get_pattern(db, p.id)


def update_pattern(db: Session, pattern_id: int, data: PatternUpdate) -> Optional[dict]:
    p = db.query(TransactionPattern).filter(TransactionPattern.id == pattern_id).first()
    if not p:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(p, field, value)
    db.commit()
    return get_pattern(db, pattern_id)


def delete_pattern(db: Session, pattern_id: int) -> bool:
    p = db.query(TransactionPattern).filter(TransactionPattern.id == pattern_id).first()
    if not p:
        return False
    db.delete(p)
    db.commit()
    return True


def analyze_patterns(db: Session) -> list[dict]:
    # 閾値 6 件以上（月次なら半年分相当）に絞り込み
    groups = (
        db.query(
            Transaction.category_id,
            Transaction.account_id,
            Transaction.group_id,
            func.count(Transaction.id).label("cnt"),
            func.max(Transaction.date).label("max_date"),
            func.min(Transaction.date).label("min_date"),
            func.sum(Transaction.expense_amount).label("total_expense"),
            func.sum(Transaction.income_amount).label("total_income"),
        )
        .group_by(Transaction.category_id, Transaction.account_id, Transaction.group_id)
        .having(func.count(Transaction.id) >= 6)
        .all()
    )

    if not groups:
        return []

    # カテゴリ・アカウント・グループを一括取得（N+1 解消）
    cat_ids = {g.category_id for g in groups}
    acc_ids = {g.account_id for g in groups}
    grp_ids = {g.group_id for g in groups if g.group_id}

    cats = {c.id: c for c in db.query(Category).filter(Category.id.in_(cat_ids)).all()}
    accs = {a.id: a for a in db.query(Account).filter(Account.id.in_(acc_ids)).all()}
    grps = (
        {g.id: g for g in db.query(Group).filter(Group.id.in_(grp_ids)).all()}
        if grp_ids
        else {}
    )

    # グループごとの最頻出メモを一括取得（N+1 解消）
    memo_rows = (
        db.query(
            Transaction.category_id,
            Transaction.account_id,
            Transaction.group_id,
            Transaction.memo,
            func.count(Transaction.memo).label("c"),
        )
        .filter(
            Transaction.memo.isnot(None),
            Transaction.memo != "",
        )
        .group_by(
            Transaction.category_id,
            Transaction.account_id,
            Transaction.group_id,
            Transaction.memo,
        )
        .order_by(func.count(Transaction.memo).desc())
        .all()
    )
    memo_lookup: dict[tuple, str] = {}
    for row in memo_rows:
        key = (row.category_id, row.account_id, row.group_id)
        if key not in memo_lookup:
            memo_lookup[key] = row.memo

    suggestions = []
    for g in groups:
        category = cats.get(g.category_id)
        account = accs.get(g.account_id)
        if not category or not account:
            continue

        group = grps.get(g.group_id) if g.group_id else None

        date_range = (g.max_date - g.min_date).days
        avg_gap = date_range / (g.cnt - 1) if g.cnt > 1 and date_range > 0 else 0

        if 20 <= avg_gap <= 45:
            frequency = "monthly"
        elif 300 <= avg_gap <= 400:
            frequency = "annual"
        elif 0 < avg_gap < 20 and g.cnt >= 5:
            frequency = "daily"
        else:
            frequency = "other"

        avg_expense = g.total_expense / g.cnt if g.cnt else 0
        avg_income = g.total_income / g.cnt if g.cnt else 0
        is_income = avg_income > avg_expense
        typical_amount = int(avg_income if is_income else avg_expense)

        cat_name = category.full_path.split("/")[-1] if "/" in category.full_path else category.full_path
        freq_label = {"monthly": "月次", "annual": "年次", "daily": "日次", "other": "その他"}.get(frequency, "")
        suggested_name = f"{freq_label}_{cat_name}" if freq_label else cat_name

        suggestions.append(
            {
                "category_id": g.category_id,
                "category_full_path": category.full_path,
                "parent_category_id": category.parent_id,
                "is_transfer": category.is_transfer,
                "account_id": g.account_id,
                "account_code": account.code,
                "group_id": g.group_id,
                "group_code": group.code if group else None,
                "typical_amount": typical_amount,
                "is_income": is_income,
                "memo_template": memo_lookup.get((g.category_id, g.account_id, g.group_id)),
                "frequency": frequency,
                "occurrence_count": g.cnt,
                "suggested_name": suggested_name,
            }
        )

    freq_order = {"monthly": 0, "annual": 1, "daily": 2, "other": 3}
    suggestions.sort(key=lambda x: (freq_order.get(x["frequency"], 9), -x["occurrence_count"]))
    return suggestions
