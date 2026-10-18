import os
import tempfile
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.backup_service import create_dump_to_tempfile, restore_from_file

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/backup", response_class=HTMLResponse)
def backup_page(request: Request):
    return templates.TemplateResponse(request, "backup/index.html")


@router.post("/api/v1/backup/dump")
def create_backup(background_tasks: BackgroundTasks):
    try:
        tmp_path, filename = create_dump_to_tempfile()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    background_tasks.add_task(os.unlink, tmp_path)
    return FileResponse(
        path=tmp_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.post("/api/v1/backup/restore")
async def restore_backup(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".sql"):
        raise HTTPException(status_code=400, detail=".sql ファイルを選択してください")

    content = await file.read()
    tmp_path = os.path.join(tempfile.gettempdir(), f"restore_{uuid.uuid4().hex}.sql")
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        restore_from_file(tmp_path)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return {"message": "復元が完了しました"}
