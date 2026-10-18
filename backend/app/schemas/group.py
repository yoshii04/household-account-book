from pydantic import BaseModel


class GroupOut(BaseModel):
    id: int
    code: str
    name: str
    sort_order: int

    model_config = {"from_attributes": True}
