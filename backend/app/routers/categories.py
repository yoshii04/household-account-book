from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.category import Category
from app.schemas.category import CategoryOut, CategoryWithChildren

router = APIRouter()


@router.get("", response_model=list[CategoryWithChildren])
def list_categories(db: Session = Depends(get_db)):
    """階層構造付きカテゴリ一覧（親カテゴリのみ返し、children に子を含む）"""
    parents = (
        db.query(Category)
        .filter(Category.parent_id.is_(None))
        .order_by(Category.full_path)
        .all()
    )
    return parents


@router.get("/parents", response_model=list[CategoryOut])
def list_parent_categories(db: Session = Depends(get_db)):
    """親カテゴリのみ一覧"""
    parents = (
        db.query(Category)
        .filter(Category.parent_id.is_(None))
        .order_by(Category.full_path)
        .all()
    )
    return parents


@router.get("/all", response_model=list[CategoryOut])
def list_all_categories(db: Session = Depends(get_db)):
    """全カテゴリ一覧（フラット）"""
    cats = db.query(Category).order_by(Category.full_path).all()
    return cats


@router.get("/{category_id}/children", response_model=list[CategoryOut])
def list_child_categories(category_id: int, db: Session = Depends(get_db)):
    """指定親カテゴリの子カテゴリ一覧"""
    children = (
        db.query(Category)
        .filter(Category.parent_id == category_id)
        .order_by(Category.full_path)
        .all()
    )
    return children


@router.get("/{category_id}", response_model=CategoryOut)
def get_category(category_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="カテゴリが見つかりません")
    return cat
