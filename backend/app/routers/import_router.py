from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.transaction import ImportLog
from app.schemas.import_result import ImportResult, ImportLogOut
from app.services.import_service import import_actual_txt

router = APIRouter()


@router.post("/upload", response_model=ImportResult)
async def upload_file(
    file: UploadFile = File(...),
    mode: str = Form("append"),
    skip_loan: bool = Form(False),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="ファイルが選択されていません")
    if mode not in ("replace", "append"):
        raise HTTPException(status_code=400, detail="mode は 'replace' または 'append' を指定してください")

    content = await file.read()
    result = await import_actual_txt(db, content, file.filename, mode=mode, skip_loan=skip_loan)
    return result


@router.get("/logs", response_model=list[ImportLogOut])
def get_import_logs(db: Session = Depends(get_db)):
    logs = db.query(ImportLog).order_by(ImportLog.imported_at.desc()).limit(50).all()
    return logs


@router.get("/logs/{log_id}", response_model=ImportLogOut)
def get_import_log(log_id: int, db: Session = Depends(get_db)):
    log = db.query(ImportLog).filter(ImportLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="ログが見つかりません")
    return log
