from typing import Optional
from sqlalchemy.orm import Session

from app.models.pattern_group import PatternGroup
from app.schemas.pattern_group import PatternGroupCreate, PatternGroupUpdate


def get_pattern_groups(db: Session) -> list[PatternGroup]:
    return db.query(PatternGroup).order_by(PatternGroup.sort_order, PatternGroup.id).all()


def get_pattern_group(db: Session, group_id: int) -> Optional[PatternGroup]:
    return db.query(PatternGroup).filter(PatternGroup.id == group_id).first()


def create_pattern_group(db: Session, data: PatternGroupCreate) -> PatternGroup:
    pg = PatternGroup(**data.model_dump())
    db.add(pg)
    db.commit()
    db.refresh(pg)
    return pg


def update_pattern_group(db: Session, group_id: int, data: PatternGroupUpdate) -> Optional[PatternGroup]:
    pg = db.query(PatternGroup).filter(PatternGroup.id == group_id).first()
    if not pg:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(pg, field, value)
    db.commit()
    db.refresh(pg)
    return pg


def delete_pattern_group(db: Session, group_id: int) -> bool:
    pg = db.query(PatternGroup).filter(PatternGroup.id == group_id).first()
    if not pg:
        return False
    db.delete(pg)
    db.commit()
    return True
