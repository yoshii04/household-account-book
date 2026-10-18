from datetime import date
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class EarlyRepaymentInput(BaseModel):
    date: date
    amount: int = Field(gt=0)


class LoanInput(BaseModel):
    loan_account_id: int
    repayment_account_id: int
    interest_category_id: Optional[int] = None  # create_interest_transactions=True のとき必須
    borrow_date: date
    borrow_amount: int = Field(gt=0)
    annual_rate: float = Field(ge=0)
    num_payments: int = Field(gt=0)
    repayment_day: int = Field(ge=1, le=31)
    first_payment_date: date
    repayment_method: Literal["equal_installment", "equal_principal", "fixed_payment"]
    holiday_handling: Literal["next", "prev", "none"]
    create_interest_transactions: bool = False
    group_id: Optional[int] = None
    memo_prefix: Optional[str] = None
    early_repayments: List[EarlyRepaymentInput] = []
    early_repayment_type: Literal["shorten", "reduce"] = "shorten"
    first_payment_amount: Optional[int] = Field(default=None, gt=0)
    last_payment_amount: Optional[int] = Field(default=None, gt=0)
    regular_payment_amount: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_interest_category_when_needed(self) -> "LoanInput":
        if self.create_interest_transactions and not self.interest_category_id:
            raise ValueError("利息トランザクションを作成する場合は利息カテゴリを選択してください")
        if self.repayment_method == "fixed_payment" and not self.regular_payment_amount:
            raise ValueError("固定額払い方式では regular_payment_amount を指定してください")
        return self


class RepaymentItemSchema(BaseModel):
    payment_number: int
    payment_date: date
    payment_amount: int
    principal_amount: int
    interest_amount: int
    remaining_balance: int
    is_early_repayment: bool = False


class LoanPreviewResponse(BaseModel):
    schedule: List[RepaymentItemSchema]
    total_payment: int
    total_principal: int
    total_interest: int


class LoanCreateResponse(BaseModel):
    created_principal_count: int
    created_interest_count: int
    created_early_repayment_count: int = 0
    total_principal: int
    total_interest: int
