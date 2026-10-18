from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class SkippedRow(BaseModel):
    line: int
    date: str
    category: str
    account: str
    reason: str


class ImportResult(BaseModel):
    status: str
    filename: str
    mode: str = "append"
    total_rows: int
    imported_rows: int
    skipped_rows: int
    skipped_loan_rows: int = 0
    error_rows: int
    deleted_rows: int = 0
    new_categories: List[str] = []
    new_accounts: List[str] = []
    new_groups: List[str] = []
    error_detail: Optional[str] = None
    skipped_detail: List[SkippedRow] = []


class ImportLogOut(BaseModel):
    id: int
    filename: str
    imported_at: datetime
    total_rows: int
    imported_rows: int
    skipped_rows: int
    error_rows: int
    status: str

    model_config = {"from_attributes": True}
