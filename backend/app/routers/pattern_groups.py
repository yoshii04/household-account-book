from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.pattern_group import PatternGroupCreate, PatternGroupUpdate, PatternGroupOut
from app.crud.pattern_group import (
    get_pattern_groups,
    get_pattern_group,
    create_pattern_group,
    update_pattern_group,
    delete_pattern_group,
)

router = APIRouter()


@router.get("", response_model=list[PatternGroupOut], tags=["pattern-groups"])
def list_pattern_groups(db: Session = Depends(get_db)):
    return get_pattern_groups(db)


@router.get("/{group_id}", response_model=PatternGroupOut, tags=["pattern-groups"])
def get_pattern_group_endpoint(group_id: int, db: Session = Depends(get_db)):
    pg = get_pattern_group(db, group_id)
    if not pg:
        raise HTTPException(status_code=404, detail="Pattern group not found")
    return pg


@router.post("", response_model=PatternGroupOut, status_code=201, tags=["pattern-groups"])
def create_pattern_group_endpoint(data: PatternGroupCreate, db: Session = Depends(get_db)):
    try:
        return create_pattern_group(db, data)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e.orig))


@router.put("/{group_id}", response_model=PatternGroupOut, tags=["pattern-groups"])
def update_pattern_group_endpoint(group_id: int, data: PatternGroupUpdate, db: Session = Depends(get_db)):
    pg = update_pattern_group(db, group_id, data)
    if not pg:
        raise HTTPException(status_code=404, detail="Pattern group not found")
    return pg


@router.delete("/{group_id}", status_code=204, tags=["pattern-groups"])
def delete_pattern_group_endpoint(group_id: int, db: Session = Depends(get_db)):
    if not delete_pattern_group(db, group_id):
        raise HTTPException(status_code=404, detail="Pattern group not found")
