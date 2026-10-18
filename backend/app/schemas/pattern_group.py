from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PatternGroupBase(BaseModel):
    name: str
    description: Optional[str] = None
    sort_order: int = 0
    is_transfer_only: bool = False


class PatternGroupCreate(PatternGroupBase):
    pass


class PatternGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_transfer_only: Optional[bool] = None


class PatternGroupOut(PatternGroupBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
