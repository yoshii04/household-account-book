from datetime import date
from typing import Optional
from sqlalchemy import asc, desc, or_, func, select
from sqlalchemy.orm import Session, joinedload

from app.models.transaction import Transaction
from app.models.category import Category
from app.models.account import Account
from app.models.group import Group
from app.models.pattern import TransactionPattern
from app.schemas.transaction import TransactionCreate, TransactionUpdate, TransferCreate


def _with_joins(query):
    return query.options(
        joinedload(Transaction.category),
        joinedload(Transaction.account),
        joinedload(Transaction.group),
    )


def _to_out_dict(tx: Transaction) -> dict:
    return {
        "id": tx.id,
        "date": tx.date,
        "category_id": tx.category_id,
        "account_id": tx.account_id,
        "income_amount": tx.income_amount,
        "expense_amount": tx.expense_amount,
        "memo": tx.memo,
        "group_id": tx.group_id,
        "is_transfer": tx.is_transfer,
        "transfer_detail": tx.transfer_detail,
        "pattern_id": tx.pattern_id,
        "category_full_path": tx.category.full_path if tx.category else None,
        "account_code": tx.account.code if tx.account else None,
        "group_code": tx.group.code if tx.group else None,
        "parent_category_id": tx.category.parent_id if tx.category else None,
        "created_at": tx.created_at,
    }


def get_transactions(
    db: Session,
    year: Optional[int] = None,
    month: Optional[int] = None,
    category_id: Optional[int] = None,
    account_id: Optional[int] = None,
    group_id: Optional[int] = None,
    is_transfer: Optional[bool] = False,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    sort_by: str = "date",
    sort_dir: str = "desc",
    ids: Optional[list[int]] = None,
) -> tuple[list[dict], int]:
    q = _with_joins(db.query(Transaction))

    if ids is not None:
        q = q.filter(Transaction.id.in_(ids))
    else:
        if year:
            q = q.filter(func.extract("year", Transaction.date) == year)
        if month:
            q = q.filter(func.extract("month", Transaction.date) == month)
        if category_id:
            # 親カテゴリが選択された場合は子カテゴリも含めて絞り込む
            child_ids = db.query(Category.id).filter(Category.parent_id == category_id).subquery()
            q = q.filter(
                or_(
                    Transaction.category_id == category_id,
                    Transaction.category_id.in_(child_ids),
                )
            )
        if account_id:
            q = q.filter(Transaction.account_id == account_id)
        if group_id:
            q = q.filter(Transaction.group_id == group_id)
        if is_transfer is not None:
            q = q.filter(Transaction.is_transfer == is_transfer)
        if search:
            # Category の JOIN は joinedload と重複するためサブクエリで対応
            matched_cat_ids = db.query(Category.id).filter(
                Category.full_path.ilike(f"%{search}%")
            ).subquery()
            q = q.filter(
                or_(
                    Transaction.memo.ilike(f"%{search}%"),
                    Transaction.category_id.in_(matched_cat_ids),
                )
            )

    total = q.count()

    d = desc if sort_dir == "desc" else asc
    if sort_by == "income_amount":
        order = [d(Transaction.income_amount), desc(Transaction.date), desc(Transaction.id)]
    elif sort_by == "expense_amount":
        order = [d(Transaction.expense_amount), desc(Transaction.date), desc(Transaction.id)]
    elif sort_by == "created_at":
        order = [d(Transaction.created_at), desc(Transaction.id)]
    elif sort_by == "category":
        cat_subq = select(Category.full_path).where(Category.id == Transaction.category_id).scalar_subquery()
        order = [d(cat_subq), desc(Transaction.date), desc(Transaction.id)]
    elif sort_by == "account":
        acc_subq = select(Account.code).where(Account.id == Transaction.account_id).scalar_subquery()
        order = [d(acc_subq), desc(Transaction.date), desc(Transaction.id)]
    elif sort_by == "group":
        grp_subq = select(Group.code).where(Group.id == Transaction.group_id).scalar_subquery()
        order = [d(grp_subq), desc(Transaction.date), desc(Transaction.id)]
    else:
        order = [d(Transaction.date), desc(Transaction.id)]

    items = q.order_by(*order).offset((page - 1) * per_page).limit(per_page).all()

    return [_to_out_dict(t) for t in items], total


def get_all_transactions(
    db: Session,
    year: Optional[int] = None,
    month: Optional[int] = None,
    category_id: Optional[int] = None,
    account_id: Optional[int] = None,
    group_id: Optional[int] = None,
    is_transfer: Optional[bool] = False,
    search: Optional[str] = None,
    created_after: Optional[date] = None,
    order_asc: bool = False,
) -> list[dict]:
    """Excel出力・エクスポート用：フィルター条件に合致する全件を返す（ページングなし）"""
    q = _with_joins(db.query(Transaction))

    if year:
        q = q.filter(func.extract("year", Transaction.date) == year)
    if month:
        q = q.filter(func.extract("month", Transaction.date) == month)
    if category_id:
        child_ids = db.query(Category.id).filter(Category.parent_id == category_id).subquery()
        q = q.filter(
            or_(
                Transaction.category_id == category_id,
                Transaction.category_id.in_(child_ids),
            )
        )
    if account_id:
        q = q.filter(Transaction.account_id == account_id)
    if group_id:
        q = q.filter(Transaction.group_id == group_id)
    if is_transfer is not None:
        q = q.filter(Transaction.is_transfer == is_transfer)
    if search:
        matched_cat_ids = db.query(Category.id).filter(
            Category.full_path.ilike(f"%{search}%")
        ).subquery()
        q = q.filter(
            or_(
                Transaction.memo.ilike(f"%{search}%"),
                Transaction.category_id.in_(matched_cat_ids),
            )
        )
    if created_after:
        # UTC で保存された created_at を JST に変換してから日付比較する
        jst_date = func.date(
            Transaction.created_at.op("AT TIME ZONE")("UTC").op("AT TIME ZONE")("Asia/Tokyo")
        )
        q = q.filter(jst_date >= created_after)

    if order_asc:
        items = q.order_by(Transaction.date.asc(), Transaction.id.asc()).all()
    else:
        items = q.order_by(Transaction.date.desc(), Transaction.id.desc()).all()
    return [_to_out_dict(t) for t in items]


def get_recent_by_category(db: Session, category_id: int, limit: int = 10) -> list[dict]:
    items = (
        _with_joins(db.query(Transaction))
        .filter(Transaction.category_id == category_id, Transaction.is_transfer.is_(False))
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(limit)
        .all()
    )
    return [_to_out_dict(t) for t in items]


def search_recent(db: Session, q: str, limit: int = 10) -> list[dict]:
    items = (
        _with_joins(db.query(Transaction))
        .join(Category, Transaction.category_id == Category.id)
        .join(Account, Transaction.account_id == Account.id)
        .filter(
            Transaction.is_transfer.is_(False),
            or_(
                Transaction.memo.ilike(f"%{q}%"),
                Category.full_path.ilike(f"%{q}%"),
                Account.code.ilike(f"%{q}%"),
            ),
        )
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(limit)
        .all()
    )
    return [_to_out_dict(t) for t in items]


def _validate_pattern_id(
    db: Session, pattern_id: Optional[int], category_id: int, account_id: int
) -> None:
    """pattern_id が指定されている場合、そのパターンの category_id / account_id と
    実際に保存する取引の category_id / account_id が一致することを検証する。

    検証しないと、パターン適用後に category/account だけ変更して送信された取引にも
    無関係な pattern_id がそのまま保存され、crud/pattern.py の _build_recorded_lookup
    （pattern_id 一致を最優先する判定）が誤って「記録済み」と判定してしまう。
    """
    if pattern_id is None:
        return
    pattern = db.query(TransactionPattern).filter(TransactionPattern.id == pattern_id).first()
    if not pattern:
        raise ValueError("指定されたパターンが見つかりません")
    if pattern.category_id != category_id or pattern.account_id != account_id:
        raise ValueError("pattern_id が category_id / account_id と一致しません")


def create_transaction(db: Session, data: TransactionCreate) -> Transaction:
    _validate_pattern_id(db, data.pattern_id, data.category_id, data.account_id)
    tx = Transaction(**data.model_dump())
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def update_transaction(db: Session, tx_id: int, data: TransactionUpdate) -> Optional[Transaction]:
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tx, field, value)
    db.commit()
    db.refresh(tx)
    return tx


def delete_transaction(db: Session, tx_id: int) -> bool:
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        return False
    db.delete(tx)
    db.commit()
    return True


def get_transaction(db: Session, tx_id: int) -> Optional[dict]:
    tx = _with_joins(db.query(Transaction)).filter(Transaction.id == tx_id).first()
    if not tx:
        return None
    return _to_out_dict(tx)


def upsert_transfer_category(db: Session, full_path: str) -> Category:
    """資金移動カテゴリを取得または作成する。"""
    existing = db.query(Category).filter(Category.full_path == full_path).first()
    if existing:
        return existing

    # 親カテゴリ（【資金移動】）を取得または作成
    parent_path = "【資金移動】"
    parent = db.query(Category).filter(Category.full_path == parent_path).first()
    if not parent:
        parent = Category(
            code=parent_path,
            name=parent_path,
            full_path=parent_path,
            is_transfer=True,
        )
        db.add(parent)
        db.flush()

    child_name = full_path.split("/", 1)[1] if "/" in full_path else full_path
    cat = Category(
        code=child_name,
        name=child_name,
        parent_id=parent.id,
        full_path=full_path,
        is_transfer=True,
    )
    db.add(cat)
    db.flush()
    return cat


def create_transfer(db: Session, data: TransferCreate) -> tuple[Transaction, Transaction]:
    """資金移動の出金・入金ペアを作成する。"""
    from_account = db.query(Account).filter(Account.id == data.from_account_id).first()
    to_account = db.query(Account).filter(Account.id == data.to_account_id).first()
    if not from_account:
        raise ValueError("送金元アカウントが見つかりません")
    if not to_account:
        raise ValueError("送金先アカウントが見つかりません")

    if data.pattern_id is not None:
        pattern = db.query(TransactionPattern).filter(TransactionPattern.id == data.pattern_id).first()
        if not pattern:
            raise ValueError("指定されたパターンが見つかりません")
        if pattern.account_id != data.from_account_id or pattern.to_account_id != data.to_account_id:
            raise ValueError("pattern_id が from_account_id / to_account_id と一致しません")

    # インポート形式に合わせたカテゴリパス
    expense_cat_path = f"【資金移動】- {to_account.code}へ -"
    income_cat_path = f"【資金移動】- {from_account.code}から -"

    expense_cat = upsert_transfer_category(db, expense_cat_path)
    income_cat = upsert_transfer_category(db, income_cat_path)

    tx_out = Transaction(
        date=data.date,
        category_id=expense_cat.id,
        account_id=data.from_account_id,
        income_amount=0,
        expense_amount=data.amount,
        memo=data.memo,
        group_id=data.group_id,
        is_transfer=True,
        transfer_detail=expense_cat_path,
        pattern_id=data.pattern_id,
    )
    tx_in = Transaction(
        date=data.date,
        category_id=income_cat.id,
        account_id=data.to_account_id,
        income_amount=data.amount,
        expense_amount=0,
        memo=data.memo,
        group_id=data.group_id,
        is_transfer=True,
        transfer_detail=income_cat_path,
        pattern_id=data.pattern_id,
    )
    db.add(tx_out)
    db.add(tx_in)
    db.commit()
    db.refresh(tx_out)
    db.refresh(tx_in)
    return tx_out, tx_in
