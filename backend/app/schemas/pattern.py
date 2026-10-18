from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel

FrequencyType = Literal["monthly", "annual", "daily", "other"]


class PatternBase(BaseModel):
    name: str
    frequency: FrequencyType = "monthly"
    category_id: int
    account_id: int
    to_account_id: Optional[int] = None
    group_id: Optional[int] = None
    pattern_group_id: Optional[int] = None
    typical_amount: int = 0
    is_income: bool = False
    memo_template: Optional[str] = None
    payment_day_of_month: Optional[int] = None
    payment_month_of_year: Optional[int] = None
    sort_order: int = 0
    is_active: bool = True


class PatternCreate(PatternBase):
    pass


class PatternUpdate(BaseModel):
    name: Optional[str] = None
    frequency: Optional[FrequencyType] = None
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    to_account_id: Optional[int] = None
    group_id: Optional[int] = None
    pattern_group_id: Optional[int] = None
    typical_amount: Optional[int] = None
    is_income: Optional[bool] = None
    memo_template: Optional[str] = None
    payment_day_of_month: Optional[int] = None
    payment_month_of_year: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class PatternOut(PatternBase):
    id: int
    category_full_path: Optional[str] = None
    parent_category_id: Optional[int] = None
    category_is_transfer: bool = False
    account_code: Optional[str] = None
    to_account_code: Optional[str] = None
    group_code: Optional[str] = None
    pattern_group_name: Optional[str] = None
    last_payment_date: Optional[date] = None
    next_payment_date: Optional[date] = None
    is_current_period_recorded: bool = False
    current_period_transaction_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PatternAnalyzeSuggestion(BaseModel):
    category_id: int
    category_full_path: str
    parent_category_id: Optional[int] = None
    is_transfer: bool = False
    account_id: int
    account_code: str
    group_id: Optional[int] = None
    group_code: Optional[str] = None
    typical_amount: int
    is_income: bool
    memo_template: Optional[str] = None
    frequency: FrequencyType
    occurrence_count: int
    suggested_name: str
