from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.group import Group
from app.schemas.group import GroupOut

router = APIRouter()


@router.get("", response_model=list[GroupOut])
def list_groups(db: Session = Depends(get_db)):
    return db.query(Group).order_by(Group.sort_order, Group.code).all()
