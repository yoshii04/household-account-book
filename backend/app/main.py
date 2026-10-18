import os

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

from app.routers import import_router, categories, accounts, groups, transactions, reports, patterns, pattern_groups, backup

app = FastAPI(title="家計簿アプリ", version="1.0.0")

# 静的ファイル（Docker ボリュームマウント時のみ存在する）
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# テンプレート
templates = Jinja2Templates(directory="app/templates")

# API ルーター
app.include_router(import_router.router, prefix="/api/v1/import", tags=["import"])
app.include_router(categories.router, prefix="/api/v1/categories", tags=["categories"])
app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["accounts"])
app.include_router(groups.router, prefix="/api/v1/groups", tags=["groups"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["transactions"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["reports"])
app.include_router(patterns.router, prefix="/api/v1/patterns", tags=["patterns"])
app.include_router(pattern_groups.router, prefix="/api/v1/pattern-groups", tags=["pattern-groups"])

# HTML ページルーター
from app.routers import pages, loans
app.include_router(pages.router, tags=["pages"])
app.include_router(loans.router, tags=["loans"])
app.include_router(backup.router, tags=["backup"])
