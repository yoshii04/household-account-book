from typing import Optional, List
from pydantic import BaseModel


class CategoryBase(BaseModel):
    code: str
    name: str
    full_path: str
    is_transfer: bool = False
    sort_order: int = 0


class CategoryCreate(CategoryBase):
    parent_id: Optional[int] = None


class CategoryOut(CategoryBase):
    id: int
    parent_id: Optional[int] = None

    model_config = {"from_attributes": True}


class CategoryWithChildren(CategoryOut):
    children: List["CategoryWithChildren"] = []

    model_config = {"from_attributes": True}
