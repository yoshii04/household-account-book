from fastapi import APIRouter, Depends, HTTPException

from app.jst import today_jst
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.pattern import PatternCreate, PatternUpdate, PatternOut, PatternAnalyzeSuggestion
from app.crud.pattern import (
    get_patterns,
    get_pattern,
    create_pattern,
    update_pattern,
    delete_pattern,
    analyze_patterns,
    get_due_patterns,
)

router = APIRouter()


@router.get("", response_model=list[PatternOut], tags=["patterns"])
def list_patterns(include_inactive: bool = False, db: Session = Depends(get_db)):
    return get_patterns(db, include_inactive=include_inactive)


# 固定パスのエンドポイントを /{pattern_id} より先に定義してルーティング競合を防ぐ
@router.get("/analyze", response_model=list[PatternAnalyzeSuggestion], tags=["patterns"])
def analyze_pattern_suggestions(db: Session = Depends(get_db)):
    return analyze_patterns(db)


@router.get("/due", response_model=list[PatternOut], tags=["patterns"])
def due_patterns(db: Session = Depends(get_db)):
    """今日が支払日のパターン一覧を返す。"""
    return get_due_patterns(db, today_jst())


@router.get("/{pattern_id}", response_model=PatternOut, tags=["patterns"])
def get_pattern_endpoint(pattern_id: int, db: Session = Depends(get_db)):
    p = get_pattern(db, pattern_id)
    if not p:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return p


@router.post("", response_model=PatternOut, status_code=201, tags=["patterns"])
def create_pattern_endpoint(data: PatternCreate, db: Session = Depends(get_db)):
    try:
        return create_pattern(db, data)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e.orig))


@router.put("/{pattern_id}", response_model=PatternOut, tags=["patterns"])
def update_pattern_endpoint(pattern_id: int, data: PatternUpdate, db: Session = Depends(get_db)):
    p = update_pattern(db, pattern_id, data)
    if not p:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return p


@router.delete("/{pattern_id}", status_code=204, tags=["patterns"])
def delete_pattern_endpoint(pattern_id: int, db: Session = Depends(get_db)):
    if not delete_pattern(db, pattern_id):
        raise HTTPException(status_code=404, detail="Pattern not found")
