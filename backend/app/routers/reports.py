from datetime import date, timedelta
from typing import Optional

from app.jst import today_jst

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
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

router = APIRouter()


def _last_day_of_prev_month():
    today = today_jst()
    return today.replace(day=1) - timedelta(days=1)


@router.get("/monthly")
def monthly_report(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    return get_monthly_summary(db, year, month)


@router.get("/comparison")
def comparison_report(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    return get_comparison(db, year, month)


@router.get("/matrix")
def matrix_report(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    return get_matrix_report(db, year, month)


@router.get("/annual")
def annual_report(
    start_year: int = Query(...),
    end_year: int = Query(...),
    db: Session = Depends(get_db),
):
    return get_annual_report(db, start_year, end_year)


@router.get("/yearly-trend")
def yearly_trend_report(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    return get_yearly_trend(db, year, month)


@router.get("/account-annual")
def account_annual_report(
    start_year: int = Query(...),
    end_year: int = Query(...),
    db: Session = Depends(get_db),
):
    return get_account_annual_report(db, start_year, end_year)


@router.get("/account-monthly")
def account_monthly_report(
    year: int = Query(...),
    db: Session = Depends(get_db),
):
    return get_account_annual_monthly_report(db, year)


@router.get("/account-monthly-daily")
def account_monthly_daily_report(
    year: int = Query(...),
    month: int = Query(...),
    db: Session = Depends(get_db),
):
    return get_account_monthly_daily_report(db, year, month)


@router.get("/account-classification-annual")
def account_classification_annual_report(
    start_year: int = Query(...),
    end_year: int = Query(...),
    db: Session = Depends(get_db),
):
    return get_account_classification_annual_report(db, start_year, end_year)


@router.get("/account-balance")
def account_balance_report(
    as_of_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    target_date = as_of_date or _last_day_of_prev_month()
    return get_account_balance_report(db, target_date)
