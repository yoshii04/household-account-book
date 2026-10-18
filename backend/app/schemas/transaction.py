from datetime import date as Date, datetime
from typing import Optional
from pydantic import BaseModel


class TransactionBase(BaseModel):
    date: Date
    category_id: int
    account_id: int
    income_amount: int = 0
    expense_amount: int = 0
    memo: Optional[str] = None
    group_id: Optional[int] = None
    is_transfer: bool = False
    transfer_detail: Optional[str] = None
    pattern_id: Optional[int] = None


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(BaseModel):
    date: Optional[Date] = None
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    income_amount: Optional[int] = None
    expense_amount: Optional[int] = None
    memo: Optional[str] = None
    group_id: Optional[int] = None


class TransactionOut(TransactionBase):
    id: int
    category_full_path: Optional[str] = None
    account_code: Optional[str] = None
    group_code: Optional[str] = None
    parent_category_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TransactionListOut(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    per_page: int


class TransferCreate(BaseModel):
    date: Date
    from_account_id: int
    to_account_id: int
    amount: int
    memo: Optional[str] = None
    group_id: Optional[int] = None
    pattern_id: Optional[int] = None


class TransferOut(BaseModel):
    expense_tx: TransactionOut
    income_tx: TransactionOut
