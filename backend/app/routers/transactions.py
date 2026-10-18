from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud.transaction import (
    get_transactions, get_recent_by_category, search_recent,
    create_transaction, update_transaction, delete_transaction, get_transaction,
    create_transfer,
)
from app.schemas.transaction import (
    TransactionCreate, TransactionUpdate, TransactionOut, TransactionListOut,
    TransferCreate, TransferOut,
)

router = APIRouter()


@router.get("", response_model=TransactionListOut)
def list_transactions(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    category_id: Optional[int] = Query(None),
    account_id: Optional[int] = Query(None),
    group_id: Optional[int] = Query(None),
    is_transfer: Optional[bool] = Query(False),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = get_transactions(
        db, year, month, category_id, account_id, group_id,
        is_transfer, search, page, per_page,
    )
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/recent/by-category/{category_id}", response_model=list[TransactionOut])
def recent_by_category(category_id: int, limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    return get_recent_by_category(db, category_id, limit)


@router.get("/search", response_model=list[TransactionOut])
def search_transactions(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    return search_recent(db, q, limit)


@router.get("/{tx_id}", response_model=TransactionOut)
def get_tx(tx_id: int, db: Session = Depends(get_db)):
    tx = get_transaction(db, tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="取引が見つかりません")
    return tx


@router.post("/transfer", response_model=TransferOut, status_code=201)
def create_transfer_tx(data: TransferCreate, db: Session = Depends(get_db)):
    try:
        tx_out, tx_in = create_transfer(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "expense_tx": get_transaction(db, tx_out.id),
        "income_tx": get_transaction(db, tx_in.id),
    }


@router.post("", response_model=TransactionOut, status_code=201)
def create_tx(data: TransactionCreate, db: Session = Depends(get_db)):
    try:
        tx = create_transaction(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = get_transaction(db, tx.id)
    return result


@router.put("/{tx_id}", response_model=TransactionOut)
def update_tx(tx_id: int, data: TransactionUpdate, db: Session = Depends(get_db)):
    tx = update_transaction(db, tx_id, data)
    if not tx:
        raise HTTPException(status_code=404, detail="取引が見つかりません")
    return get_transaction(db, tx.id)


@router.delete("/{tx_id}", status_code=204)
def delete_tx(tx_id: int, db: Session = Depends(get_db)):
    ok = delete_transaction(db, tx_id)
    if not ok:
        raise HTTPException(status_code=404, detail="取引が見つかりません")
