import io
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from urllib.parse import quote

from app.jst import today_jst, JST

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, extract
from sqlalchemy.orm import Session
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from app.database import get_db
from app.models.category import Category
from app.models.account import Account
from app.models.account_type import AccountType
from app.models.group import Group
from app.models.pattern_group import PatternGroup
from app.models.transaction import ImportLog, Transaction
from app.crud.transaction import get_transactions, get_transaction, get_all_transactions
from app.crud.pattern import get_due_and_unrecorded_patterns
from app.services.report_service import (
    get_monthly_summary,
    get_comparison,
    get_matrix_report,
    get_account_balance_report,
    get_yearly_trend,
    get_annual_report,
    get_account_annual_report,
    get_account_annual_monthly_report,
    get_account_monthly_daily_report,
    get_account_classification_annual_report,
)
from app.services.pdf_service import generate_monthly_report_pdf


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

_JST = JST


def _to_jst(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """UTC datetime を日本時間 (JST) に変換してフォーマットする。"""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_JST).strftime(fmt)


templates.env.filters["jst"] = _to_jst


def _current_ym() -> tuple[int, int]:
    today = today_jst()
    return today.year, today.month


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    year, month = _current_ym()
    summary = get_monthly_summary(db, year, month)
    recent_items, _ = get_transactions(db, year=year, month=month, is_transfer=False, per_page=5)
    today = today_jst()
    due_patterns, unrecorded_patterns = get_due_and_unrecorded_patterns(db, today)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "summary": summary,
            "recent_items": recent_items,
            "year": year,
            "month": month,
            "due_patterns": due_patterns,
            "unrecorded_patterns": unrecorded_patterns,
        },
    )


_VALID_SORT_COLS = {"date", "category", "account", "group", "income_amount", "expense_amount", "created_at"}


@router.get("/transactions", response_class=HTMLResponse)
def transactions_page(
    request: Request,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    category_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
    is_transfer: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query(None),
    f: Optional[str] = Query(None),
    ids: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    ids_list = [int(i) for i in ids.split(",") if i.strip().isdigit()] if ids else None

    is_first_visit = not f and not ids_list
    if is_first_visit:
        # 初回アクセス（フォーム未送信・ids 未指定）は当月をデフォルトにする
        cur_year, cur_month = _current_ym()
        year = year or cur_year
        month = month or cur_month

    if is_transfer is None:
        # 初回アクセス時は「資金移動を含む」をデフォルトにする。フォーム送信済み
        # （f=1）でチェックボックスが未チェック（=is_transfer 未送信）なら、
        # 明示的に外したものとして除外する。
        # なお ids 指定時（IDフィルターバナー）はこの値が checked 表示にのみ
        # 影響し、下記クエリでは ids 指定が優先されて is_transfer による絞り込み
        # 自体は行われない（表示対象は ids で一意に確定するため）
        is_transfer = is_first_visit

    # 空文字列は None に変換（HTMLフォームが空文字を送信する場合の対応）
    cat_id = int(category_id) if category_id else None
    acc_id = int(account_id) if account_id else None
    grp_id = int(group_id) if group_id else None

    # is_transfer=True → 資金移動を含む全件表示（フィルターなし）
    # is_transfer=False → 資金移動を除外
    effective_is_transfer = None if is_transfer else False

    resolved_sort_by = sort_by if sort_by in _VALID_SORT_COLS else "created_at"
    resolved_sort_dir = sort_dir if sort_dir in ("asc", "desc") else "desc"

    if ids_list:
        items, total = get_transactions(
            db, ids=ids_list, per_page=len(ids_list),
            sort_by=resolved_sort_by, sort_dir=resolved_sort_dir,
        )
    else:
        items, total = get_transactions(
            db, year, month, cat_id, acc_id, grp_id,
            effective_is_transfer, search, page, per_page=50,
            sort_by=resolved_sort_by, sort_dir=resolved_sort_dir,
        )
    categories = db.query(Category).filter(Category.parent_id.is_(None)).order_by(Category.full_path).all()
    accounts = db.query(Account).filter(Account.is_active.is_(True)).order_by(Account.code).all()
    groups = db.query(Group).order_by(Group.code).all()
    parent_categories_json = [{"id": c.id, "full_path": c.full_path} for c in categories]
    accounts_json = [{"id": a.id, "code": a.code} for a in accounts]
    groups_json = [{"id": g.id, "code": g.code} for g in groups]
    return templates.TemplateResponse(
        request,
        "transactions/list.html",
        {
            "items": items,
            "total": total,
            "page": page,
            "per_page": 50,
            "total_pages": (total + 49) // 50 if not ids_list else 1,
            "categories": categories,
            "accounts": accounts,
            "groups": groups,
            "parent_categories_json": parent_categories_json,
            "accounts_json": accounts_json,
            "groups_json": groups_json,
            "ids_filter": ids,
            "filter": {
                "year": year,
                "month": month,
                "category_id": cat_id,
                "account_id": acc_id,
                "group_id": grp_id,
                "is_transfer": is_transfer,
                "search": search or "",
                "sort_by": resolved_sort_by,
                "sort_dir": resolved_sort_dir,
            },
        },
    )


@router.get("/transactions/export/excel")
def transactions_export_excel(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    category_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
    is_transfer: Optional[bool] = Query(False),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    cat_id = int(category_id) if category_id else None
    acc_id = int(account_id) if account_id else None
    grp_id = int(group_id) if group_id else None
    effective_is_transfer = None if is_transfer else False

    rows = get_all_transactions(db, year, month, cat_id, acc_id, grp_id, effective_is_transfer, search)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "取引一覧"

    # ヘッダー
    headers = ["日付", "カテゴリ", "アカウント", "グループ", "メモ", "収入", "支出"]
    header_fill = PatternFill(fill_type="solid", fgColor="4472C4")
    header_font = Font(bold=True, color="FFFFFF")
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    # データ行
    for row_idx, tx in enumerate(rows, 2):
        ws.cell(row=row_idx, column=1, value=str(tx["date"]))
        ws.cell(row=row_idx, column=2, value=tx["category_full_path"] or "")
        ws.cell(row=row_idx, column=3, value=tx["account_code"] or "")
        ws.cell(row=row_idx, column=4, value=tx["group_code"] or "")
        ws.cell(row=row_idx, column=5, value=tx["memo"] or "")
        income_cell = ws.cell(row=row_idx, column=6, value=tx["income_amount"] or 0)
        expense_cell = ws.cell(row=row_idx, column=7, value=tx["expense_amount"] or 0)
        income_cell.number_format = '#,##0'
        expense_cell.number_format = '#,##0'

    # 列幅自動調整
    col_widths = [12, 40, 20, 20, 30, 14, 14]
    for col, width in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = width

    # ファイル名
    parts = ["transactions"]
    if year:
        parts.append(str(year))
    if month:
        parts.append(f"{month:02d}")
    filename = "_".join(parts) + ".xlsx"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/transactions/new", response_class=HTMLResponse)
def new_transaction_page(
    request: Request,
    copy_from_id: Optional[int] = Query(None),
    return_url: Optional[str] = Query(None),
    pattern_id: Optional[int] = Query(None),
    init_date: Optional[str] = Query(None, alias="date"),
    db: Session = Depends(get_db),
):
    from app.crud.pattern import get_pattern
    parent_categories = db.query(Category).filter(Category.parent_id.is_(None)).order_by(Category.full_path).all()
    accounts = db.query(Account).filter(Account.is_active.is_(True)).order_by(Account.code).all()
    groups = db.query(Group).order_by(Group.code).all()
    today = today_jst().isoformat()
    accounts_data = [{"id": a.id, "code": a.code} for a in accounts]

    # ISO 8601 形式以外の文字列は JS インジェクションにつながるため拒否する
    if init_date:
        try:
            date.fromisoformat(init_date)
        except ValueError:
            init_date = None

    copy_tx = get_transaction(db, copy_from_id) if copy_from_id else None
    _raw_pattern = get_pattern(db, pattern_id) if pattern_id else None
    # datetime / date オブジェクトを除去してテンプレートの tojson でシリアライズできるようにする
    if _raw_pattern:
        init_pattern = {k: v for k, v in _raw_pattern.items() if not isinstance(v, (datetime, date))}
    else:
        init_pattern = None

    return templates.TemplateResponse(
        request,
        "transactions/form.html",
        {
            "mode": "new",
            "parent_categories": parent_categories,
            "accounts": accounts,
            "accounts_data": accounts_data,
            "groups": groups,
            "today": today,
            "tx": copy_tx,
            "return_url": return_url or "",
            "is_copy": copy_tx is not None,
            "init_pattern": init_pattern,
            "initial_date": init_date,
        },
    )


@router.get("/transactions/{tx_id}/edit", response_class=HTMLResponse)
def edit_transaction_page(tx_id: int, request: Request, return_url: Optional[str] = Query(None), db: Session = Depends(get_db)):
    tx = get_transaction(db, tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="取引が見つかりません")
    parent_categories = db.query(Category).filter(Category.parent_id.is_(None)).order_by(Category.full_path).all()
    accounts = db.query(Account).filter(Account.is_active.is_(True)).order_by(Account.code).all()
    groups = db.query(Group).order_by(Group.code).all()
    accounts_data = [{"id": a.id, "code": a.code} for a in accounts]
    return templates.TemplateResponse(
        request,
        "transactions/form.html",
        {
            "mode": "edit",
            "parent_categories": parent_categories,
            "accounts": accounts,
            "accounts_data": accounts_data,
            "groups": groups,
            "today": today_jst().isoformat(),
            "tx": tx,
            "return_url": return_url or "",
            "is_copy": False,
            "initial_date": tx["date"].isoformat() if tx.get("date") else None,
        },
    )


@router.get("/patterns", response_class=HTMLResponse)
def patterns_page(request: Request, db: Session = Depends(get_db)):
    parent_categories = [
        {"id": c.id, "full_path": c.full_path, "is_transfer": c.is_transfer}
        for c in db.query(Category).filter(Category.parent_id.is_(None)).order_by(Category.full_path).all()
    ]
    accounts_data = [
        {"id": a.id, "code": a.code}
        for a in db.query(Account).filter(Account.is_active.is_(True)).order_by(Account.code).all()
    ]
    groups_data = [
        {"id": g.id, "code": g.code}
        for g in db.query(Group).order_by(Group.code).all()
    ]
    pattern_groups_data = [
        {
            "id": pg.id,
            "name": pg.name,
            "description": pg.description or "",
            "sort_order": pg.sort_order,
            "is_transfer_only": pg.is_transfer_only,
        }
        for pg in db.query(PatternGroup).order_by(PatternGroup.sort_order, PatternGroup.id).all()
    ]
    return templates.TemplateResponse(
        request,
        "patterns/index.html",
        {
            "parent_categories": parent_categories,
            "accounts": accounts_data,
            "groups": groups_data,
            "pattern_groups": pattern_groups_data,
        },
    )


@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request, db: Session = Depends(get_db)):
    logs = db.query(ImportLog).order_by(ImportLog.imported_at.desc()).limit(20).all()
    return templates.TemplateResponse(request, "import/index.html", {"logs": logs})


@router.get("/export", response_class=HTMLResponse)
def export_page(request: Request):
    today = today_jst().isoformat()
    return templates.TemplateResponse(request, "export/index.html", {"today": today})


@router.get("/transactions/export/actual_txt")
def transactions_export_actual_txt(
    created_after: Optional[date] = Query(None),
    is_transfer: Optional[bool] = Query(True),
    db: Session = Depends(get_db),
):
    """Actual.TXT形式（UTF-16LE TSV）でエクスポートする。"""
    # is_transfer=True → None（資金移動を含む全件）、False → 通常取引のみ
    effective_is_transfer = None if is_transfer else False
    rows = get_all_transactions(
        db,
        is_transfer=effective_is_transfer,
        created_after=created_after,
        order_asc=True,  # インポート元ファイルに近い日付昇順で出力
    )

    # Actual.TXT ヘッダー（インポート形式と同一、全角スペース使用）
    HEADER = "日　付\tカテゴリー\tアカウント\t入金額\t出金額\tメ　モ\tグループ"

    lines = [HEADER]
    for tx in rows:
        date_str = tx["date"].strftime("%Y/%m/%d") if tx["date"] else ""
        category = tx["category_full_path"] or ""
        account = tx["account_code"] or ""
        income = str(tx["income_amount"]) if tx["income_amount"] else ""
        expense = str(tx["expense_amount"]) if tx["expense_amount"] else ""
        memo = tx["memo"] or ""
        group = tx["group_code"] or ""
        lines.append(f"{date_str}\t{category}\t{account}\t{income}\t{expense}\t{memo}\t{group}")

    content = "\n".join(lines)
    # UTF-16LE + BOM でエンコード
    encoded = content.encode("utf-16-le")
    bom = b"\xff\xfe"
    output = bom + encoded

    filename = "export"
    if created_after:
        filename += f"_{created_after.strftime('%Y%m%d')}"
    filename += ".txt"

    encoded_filename = quote(filename, encoding="utf-8")
    return StreamingResponse(
        io.BytesIO(output),
        media_type="text/plain; charset=utf-16",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@router.get("/reports/monthly", response_class=HTMLResponse)
def monthly_report_page(
    request: Request,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    cur_year, cur_month = _current_ym()
    year = year or cur_year
    month = month or cur_month
    summary = get_monthly_summary(db, year, month)
    return templates.TemplateResponse(
        request,
        "reports/monthly.html",
        {"summary": summary, "year": year, "month": month},
    )


@router.get("/reports/comparison", response_class=HTMLResponse)
def comparison_report_page(
    request: Request,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    cur_year, cur_month = _current_ym()
    year = year or cur_year
    month = month or cur_month
    data = get_comparison(db, year, month)
    return templates.TemplateResponse(
        request,
        "reports/comparison.html",
        {"data": data, "year": year, "month": month},
    )


@router.get("/reports/matrix", response_class=HTMLResponse)
def matrix_report_page(
    request: Request,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    cur_year, cur_month = _current_ym()
    year = year or cur_year
    month = month or cur_month
    data = get_matrix_report(db, year, month)
    return templates.TemplateResponse(
        request,
        "reports/matrix.html",
        {"data": data, "year": year, "month": month},
    )


def _prev_ym() -> tuple[int, int]:
    """前月の年・月を返す"""
    today = today_jst()
    first = today.replace(day=1)
    prev = first - timedelta(days=1)
    return prev.year, prev.month


def _last_day_of_prev_month() -> date:
    today = today_jst()
    return today.replace(day=1) - timedelta(days=1)


@router.get("/accounts", response_class=HTMLResponse)
def accounts_page(request: Request, db: Session = Depends(get_db)):
    accounts = db.query(Account).filter(Account.is_active.is_(True)).order_by(Account.sort_order, Account.code).all()

    # アカウントごとの最古取引日を取得（未設定時のデフォルト候補）
    min_dates = dict(
        db.query(Transaction.account_id, func.min(Transaction.date))
        .group_by(Transaction.account_id)
        .all()
    )

    account_stats = [
        {
            "id": acc.id,
            "code": acc.code,
            "name": acc.name,
            "account_type": acc.account_type,
            "start_date": acc.start_date,
            "initial_balance": acc.initial_balance if acc.initial_balance is not None else 0,
            "adjustment_amount": acc.adjustment_amount if acc.adjustment_amount is not None else 0,
            "oldest_transaction_date": min_dates.get(acc.id),
            "classification": acc.classification,
        }
        for acc in accounts
    ]

    account_types = [
        {"id": t.id, "code": t.code, "label": t.label, "sort_order": t.sort_order}
        for t in db.query(AccountType).order_by(AccountType.sort_order, AccountType.code).all()
    ]

    # account_statsには日付オブジェクトが含まれtojsonが失敗するため、
    # Alpine.js初期化用にid/account_typeだけ抜き出した別リストを渡す
    account_type_map = [
        {"id": a["id"], "account_type": a["account_type"]}
        for a in account_stats
    ]

    return templates.TemplateResponse(
        request,
        "accounts/index.html",
        {
            "accounts": account_stats,
            "account_types": account_types,
            "account_type_map": account_type_map,
        },
    )


@router.get("/reports/annual", response_class=HTMLResponse)
def annual_report_page(
    request: Request,
    start_year: Optional[int] = Query(None),
    end_year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    cur_year = today_jst().year
    # DB に存在する最古年を取得
    min_year_row = db.query(func.min(extract("year", Transaction.date))).filter(
        Transaction.is_transfer.is_(False)
    ).scalar()
    db_min_year = int(min_year_row) if min_year_row else cur_year

    resolved_start = start_year if start_year is not None else db_min_year
    resolved_end = end_year if end_year is not None else cur_year
    # 逆転防止
    if resolved_start > resolved_end:
        resolved_start, resolved_end = resolved_end, resolved_start

    data = get_annual_report(db, resolved_start, resolved_end)
    return templates.TemplateResponse(
        request,
        "reports/annual.html",
        {
            "data": data,
            "start_year": resolved_start,
            "end_year": resolved_end,
            "db_min_year": db_min_year,
        },
    )


@router.get("/reports/yearly-trend", response_class=HTMLResponse)
def yearly_trend_page(
    request: Request,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    if year is None or month is None:
        year, month = _prev_ym()
    data = get_yearly_trend(db, year, month)
    return templates.TemplateResponse(
        request,
        "reports/yearly_trend.html",
        {"data": data, "year": year, "month": month},
    )


@router.get("/reports/yearly-trend-chart", response_class=HTMLResponse)
def yearly_trend_chart_page(
    request: Request,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    if year is None or month is None:
        year, month = _prev_ym()
    data = get_yearly_trend(db, year, month)

    income_top5 = sorted(data["income_categories"], key=lambda c: c["row_total"], reverse=True)[:5]
    expense_b = [c for c in data["expense_categories"] if c["full_path"].startswith("B")]
    expense_top5 = sorted(expense_b, key=lambda c: c["row_total"], reverse=True)[:5]

    return templates.TemplateResponse(
        request,
        "reports/yearly_trend_chart.html",
        {
            "data": data,
            "year": year,
            "month": month,
            "income_top5": income_top5,
            "expense_top5": expense_top5,
        },
    )


@router.get("/reports/account-annual", response_class=HTMLResponse)
def account_annual_page(
    request: Request,
    start_year: Optional[int] = Query(None),
    end_year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    cur_year = today_jst().year
    min_year_row = db.query(func.min(extract("year", Transaction.date))).scalar()
    db_min_year = int(min_year_row) if min_year_row else cur_year

    resolved_start = start_year if start_year is not None else db_min_year
    resolved_end = end_year if end_year is not None else cur_year
    if resolved_start > resolved_end:
        resolved_start, resolved_end = resolved_end, resolved_start

    data = get_account_annual_report(db, resolved_start, resolved_end)
    return templates.TemplateResponse(
        request,
        "reports/account_annual.html",
        {
            "data": data,
            "start_year": resolved_start,
            "end_year": resolved_end,
            "db_min_year": db_min_year,
        },
    )


@router.get("/reports/account-annual/monthly", response_class=HTMLResponse)
def account_annual_monthly_page(
    request: Request,
    year: int = Query(...),
    start_year: Optional[int] = Query(None),
    end_year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    cur_year = today_jst().year
    min_year_row = db.query(func.min(extract("year", Transaction.date))).scalar()
    db_min_year = int(min_year_row) if min_year_row else cur_year

    resolved_start = start_year if start_year is not None else db_min_year
    resolved_end = end_year if end_year is not None else cur_year

    data = get_account_annual_monthly_report(db, year)
    return templates.TemplateResponse(
        request,
        "reports/account_annual_monthly.html",
        {
            "data": data,
            "start_year": resolved_start,
            "end_year": resolved_end,
        },
    )


@router.get("/reports/account-annual/monthly/daily", response_class=HTMLResponse)
def account_monthly_daily_page(
    request: Request,
    year: int = Query(...),
    month: int = Query(...),
    start_year: Optional[int] = Query(None),
    end_year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    cur_year = today_jst().year
    min_year_row = db.query(func.min(extract("year", Transaction.date))).scalar()
    db_min_year = int(min_year_row) if min_year_row else cur_year

    resolved_start = start_year if start_year is not None else db_min_year
    resolved_end = end_year if end_year is not None else cur_year

    data = get_account_monthly_daily_report(db, year, month)
    return templates.TemplateResponse(
        request,
        "reports/account_annual_monthly_daily.html",
        {
            "data": data,
            "start_year": resolved_start,
            "end_year": resolved_end,
        },
    )


@router.get("/reports/annual-chart", response_class=HTMLResponse)
def annual_chart_page(
    request: Request,
    start_year: Optional[int] = Query(None),
    end_year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    cur_year = today_jst().year
    min_year_row = db.query(func.min(extract("year", Transaction.date))).filter(
        Transaction.is_transfer.is_(False)
    ).scalar()
    db_min_year = int(min_year_row) if min_year_row else cur_year

    resolved_start = start_year if start_year is not None else db_min_year
    resolved_end = end_year if end_year is not None else cur_year
    if resolved_start > resolved_end:
        resolved_start, resolved_end = resolved_end, resolved_start

    data = get_annual_report(db, resolved_start, resolved_end)

    income_top5 = sorted(data["income_categories"], key=lambda c: c["row_total"], reverse=True)[:5]
    expense_b = [c for c in data["expense_categories"] if c["full_path"].startswith("B")]
    expense_top5 = sorted(expense_b, key=lambda c: c["row_total"], reverse=True)[:5]

    return templates.TemplateResponse(
        request,
        "reports/annual_chart.html",
        {
            "data": data,
            "start_year": resolved_start,
            "end_year": resolved_end,
            "income_top5": income_top5,
            "expense_top5": expense_top5,
        },
    )


@router.get("/reports/account-classification-annual", response_class=HTMLResponse)
def account_classification_annual_page(
    request: Request,
    start_year: Optional[int] = Query(None),
    end_year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    cur_year = today_jst().year
    min_year_row = db.query(func.min(extract("year", Transaction.date))).scalar()
    db_min_year = int(min_year_row) if min_year_row else cur_year

    resolved_start = start_year if start_year is not None else db_min_year
    resolved_end = end_year if end_year is not None else cur_year
    if resolved_start > resolved_end:
        resolved_start, resolved_end = resolved_end, resolved_start

    data = get_account_classification_annual_report(db, resolved_start, resolved_end)
    return templates.TemplateResponse(
        request,
        "reports/account_classification_annual.html",
        {
            "data": data,
            "start_year": resolved_start,
            "end_year": resolved_end,
            "db_min_year": db_min_year,
        },
    )


@router.get("/reports/account-classification-annual-chart", response_class=HTMLResponse)
def account_classification_annual_chart_page(
    request: Request,
    start_year: Optional[int] = Query(None),
    end_year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    cur_year = today_jst().year
    min_year_row = db.query(func.min(extract("year", Transaction.date))).scalar()
    db_min_year = int(min_year_row) if min_year_row else cur_year

    resolved_start = start_year if start_year is not None else db_min_year
    resolved_end = end_year if end_year is not None else cur_year
    if resolved_start > resolved_end:
        resolved_start, resolved_end = resolved_end, resolved_start

    data = get_account_classification_annual_report(db, resolved_start, resolved_end)
    return templates.TemplateResponse(
        request,
        "reports/account_classification_annual_chart.html",
        {
            "data": data,
            "start_year": resolved_start,
            "end_year": resolved_end,
            "db_min_year": db_min_year,
        },
    )


@router.get("/reports/account-balance", response_class=HTMLResponse)
def account_balance_page(
    request: Request,
    as_of_date: Optional[date] = Query(None),
    show_zero: bool = Query(False),
    db: Session = Depends(get_db),
):
    target_date = as_of_date or today_jst()
    data = get_account_balance_report(db, target_date, show_zero=show_zero)
    return templates.TemplateResponse(
        request,
        "reports/account_balance.html",
        {"data": data, "as_of_date": target_date.isoformat(), "show_zero": show_zero},
    )


@router.get("/reports/export-pdf")
def export_pdf(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """前月末時点の全レポートを 1 PDF ファイルとしてダウンロードする"""
    if year is None or month is None:
        year, month = _prev_ym()

    try:
        pdf_bytes, filename = generate_monthly_report_pdf(db, year, month)
    except Exception:
        logger.exception("PDF生成中にエラーが発生しました year=%s month=%s", year, month)
        raise HTTPException(status_code=500, detail="PDF生成に失敗しました")

    # RFC 5987 形式でファイル名をエンコード（日本語ファイル名対応）
    encoded = quote(filename, encoding="utf-8")

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"
        },
    )
