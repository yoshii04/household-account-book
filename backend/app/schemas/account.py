from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


class AccountTypeOut(BaseModel):
    id: int
    code: str
    label: str
    sort_order: int

    model_config = {"from_attributes": True}


class AccountTypeCreate(BaseModel):
    code: str
    label: str
    sort_order: int = 0


class AccountTypeUpdate(BaseModel):
    code: str
    label: str
    sort_order: int = 0


class AccountOut(BaseModel):
    id: int
    code: str
    name: str
    account_type: str
    sort_order: int
    is_active: bool
    start_date: Optional[date] = None
    initial_balance: Optional[int] = None
    adjustment_amount: Optional[int] = None
    classification: Optional[str] = None

    model_config = {"from_attributes": True}


class AccountUpdate(BaseModel):
    account_type: Optional[str] = None
    start_date: Optional[date] = None
    initial_balance: Optional[int] = None
    adjustment_amount: Optional[int] = None
    classification: Optional[str] = None


class AccountBulkUpdate(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)
    account_type: Optional[str] = None   # None = 更新しない
    update_classification: bool = False  # True = classification を更新する
    classification: Optional[str] = None
