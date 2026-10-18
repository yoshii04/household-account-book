from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.account import Account
from app.models.account_type import AccountType
from app.schemas.account import AccountOut, AccountUpdate, AccountBulkUpdate, AccountTypeOut, AccountTypeCreate, AccountTypeUpdate

router = APIRouter()


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return (
        db.query(Account)
        .filter(Account.is_active.is_(True))
        .order_by(Account.sort_order, Account.code)
        .all()
    )


@router.get("/types", response_model=list[AccountTypeOut])
def list_account_types(db: Session = Depends(get_db)):
    return db.query(AccountType).order_by(AccountType.sort_order, AccountType.code).all()


@router.post("/types", response_model=AccountTypeOut, status_code=201)
def create_account_type(payload: AccountTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(AccountType).filter(AccountType.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=409, detail="同じコードの種別が既に存在します")
    at = AccountType(**payload.model_dump())
    db.add(at)
    db.commit()
    db.refresh(at)
    return at


@router.put("/types/{type_id}", response_model=AccountTypeOut)
def update_account_type(type_id: int, payload: AccountTypeUpdate, db: Session = Depends(get_db)):
    at = db.query(AccountType).filter(AccountType.id == type_id).first()
    if not at:
        raise HTTPException(status_code=404, detail="種別が見つかりません")
    if payload.code != at.code:
        conflict = db.query(AccountType).filter(AccountType.code == payload.code).first()
        if conflict:
            raise HTTPException(status_code=409, detail="同じコードの種別が既に存在します")
        db.query(Account).filter(Account.account_type == at.code).update(
            {"account_type": payload.code}
        )
    at.code = payload.code
    at.label = payload.label
    at.sort_order = payload.sort_order
    db.commit()
    db.refresh(at)
    return at


@router.delete("/types/{type_id}", status_code=204)
def delete_account_type(type_id: int, db: Session = Depends(get_db)):
    at = db.query(AccountType).filter(AccountType.id == type_id).first()
    if not at:
        raise HTTPException(status_code=404, detail="種別が見つかりません")
    in_use = db.query(Account).filter(Account.account_type == at.code).first()
    if in_use:
        raise HTTPException(status_code=409, detail=f"種別「{at.label}」は使用中のアカウントがあるため削除できません")
    db.delete(at)
    db.commit()


@router.put("/bulk", response_model=list[AccountOut])
def bulk_update_accounts(payload: AccountBulkUpdate, db: Session = Depends(get_db)):
    if payload.account_type is None and not payload.update_classification:
        raise HTTPException(status_code=400, detail="更新するフィールドを指定してください")

    if payload.account_type is not None:
        type_exists = db.query(AccountType).filter(AccountType.code == payload.account_type).first()
        if not type_exists:
            raise HTTPException(status_code=400, detail="指定された種別コードが存在しません")

    accounts = db.query(Account).filter(
        Account.id.in_(payload.ids),
        Account.is_active.is_(True),
    ).all()

    for account in accounts:
        if payload.account_type is not None:
            account.account_type = payload.account_type
        if payload.update_classification:
            account.classification = (payload.classification or '').strip() or None

    db.commit()
    for account in accounts:
        db.refresh(account)
    return accounts


@router.put("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, payload: AccountUpdate, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="アカウントが見つかりません")
    if payload.account_type is not None:
        type_exists = db.query(AccountType).filter(AccountType.code == payload.account_type).first()
        if not type_exists:
            raise HTTPException(status_code=400, detail="指定された種別コードが存在しません")
        account.account_type = payload.account_type
    account.start_date = payload.start_date
    account.initial_balance = payload.initial_balance if payload.initial_balance is not None else 0
    account.adjustment_amount = payload.adjustment_amount if payload.adjustment_amount is not None else 0
    account.classification = payload.classification or None
    db.commit()
    db.refresh(account)
    return account
