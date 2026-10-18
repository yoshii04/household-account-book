from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.schemas.loan import LoanInput, LoanPreviewResponse, LoanCreateResponse, RepaymentItemSchema
from app.services.loan_service import calculate_schedule, EarlyRepayment
from app.crud.transaction import upsert_transfer_category

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/loans/new", response_class=HTMLResponse)
def loan_form_page(request: Request, db: Session = Depends(get_db)):
    accounts = db.query(Account).filter(Account.is_active.is_(True)).order_by(Account.code).all()
    interest_categories = (
        db.query(Category)
        .filter(
            Category.full_path.like("A10_ローン/%"),
            Category.parent_id.isnot(None),
        )
        .order_by(Category.full_path)
        .all()
    )
    if not interest_categories:
        interest_categories = (
            db.query(Category)
            .filter(Category.full_path.like("A10_ローン%"))
            .order_by(Category.full_path)
            .all()
        )
    return templates.TemplateResponse(
        request,
        "loans/form.html",
        {
            "accounts": accounts,
            "interest_categories": interest_categories,
        },
    )


def _to_service_early_repayments(data: LoanInput) -> list[EarlyRepayment]:
    return [EarlyRepayment(date=er.date, amount=er.amount) for er in data.early_repayments]


@router.post("/api/v1/loans/preview", response_model=LoanPreviewResponse)
def preview_loan(data: LoanInput, db: Session = Depends(get_db)):
    _validate_accounts(data, db)
    if data.create_interest_transactions:
        _validate_interest_category(data, db)

    try:
        items = calculate_schedule(
            principal=data.borrow_amount,
            annual_rate=data.annual_rate,
            num_payments=data.num_payments,
            repayment_day=data.repayment_day,
            first_payment_date=data.first_payment_date,
            repayment_method=data.repayment_method,
            holiday_handling=data.holiday_handling,
            early_repayments=_to_service_early_repayments(data),
            early_repayment_type=data.early_repayment_type,
            first_payment_amount=data.first_payment_amount,
            last_payment_amount=data.last_payment_amount,
            regular_payment_amount=data.regular_payment_amount,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    schedule = [
        RepaymentItemSchema(
            payment_number=it.payment_number,
            payment_date=it.payment_date,
            payment_amount=it.payment_amount,
            principal_amount=it.principal_amount,
            interest_amount=it.interest_amount,
            remaining_balance=it.remaining_balance,
            is_early_repayment=it.is_early_repayment,
        )
        for it in items
    ]
    regular = [s for s in schedule if not s.is_early_repayment]
    return LoanPreviewResponse(
        schedule=schedule,
        total_payment=sum(s.payment_amount for s in schedule),
        total_principal=sum(s.principal_amount for s in schedule),
        total_interest=sum(s.interest_amount for s in regular),
    )


@router.post("/api/v1/loans/create", response_model=LoanCreateResponse)
def create_loan_transactions(data: LoanInput, db: Session = Depends(get_db)):
    loan_account, repayment_account = _validate_accounts(data, db)
    interest_category = _validate_interest_category(data, db) if data.create_interest_transactions else None

    try:
        items = calculate_schedule(
            principal=data.borrow_amount,
            annual_rate=data.annual_rate,
            num_payments=data.num_payments,
            repayment_day=data.repayment_day,
            first_payment_date=data.first_payment_date,
            repayment_method=data.repayment_method,
            holiday_handling=data.holiday_handling,
            early_repayments=_to_service_early_repayments(data),
            early_repayment_type=data.early_repayment_type,
            first_payment_amount=data.first_payment_amount,
            last_payment_amount=data.last_payment_amount,
            regular_payment_amount=data.regular_payment_amount,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 重複登録ガード（第1回の元本取引が既に存在するか確認）
    prefix = data.memo_prefix or "ローン返済"
    first_regular = next((it for it in items if not it.is_early_repayment), None)
    if first_regular:
        first_memo = f"{prefix} 第1回（元本）"
        duplicate = db.query(Transaction).filter(
            Transaction.memo == first_memo,
            Transaction.account_id == data.repayment_account_id,
            Transaction.date == first_regular.payment_date,
        ).first()
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"このローンのトランザクションは既に登録されています（「{first_memo}」が {first_regular.payment_date} に存在します）",
            )

    # カテゴリの取得はループ外で一度だけ
    expense_cat_path = f"【資金移動】- {loan_account.code}へ -"
    income_cat_path = f"【資金移動】- {repayment_account.code}から -"
    expense_cat = upsert_transfer_category(db, expense_cat_path)
    income_cat = upsert_transfer_category(db, income_cat_path)

    principal_count = 0
    interest_count = 0
    early_repayment_count = 0

    for it in items:
        if it.is_early_repayment:
            label = f"{prefix} 繰り上げ返済（元本）"
            db.add(Transaction(
                date=it.payment_date,
                category_id=expense_cat.id,
                account_id=data.repayment_account_id,
                income_amount=0,
                expense_amount=it.principal_amount,
                memo=label,
                group_id=data.group_id,
                is_transfer=True,
                transfer_detail=expense_cat_path,
            ))
            db.add(Transaction(
                date=it.payment_date,
                category_id=income_cat.id,
                account_id=data.loan_account_id,
                income_amount=it.principal_amount,
                expense_amount=0,
                memo=label,
                group_id=data.group_id,
                is_transfer=True,
                transfer_detail=income_cat_path,
            ))
            early_repayment_count += 1
            continue

        label = f"{prefix} 第{it.payment_number}回"

        if it.principal_amount > 0:
            db.add(Transaction(
                date=it.payment_date,
                category_id=expense_cat.id,
                account_id=data.repayment_account_id,
                income_amount=0,
                expense_amount=it.principal_amount,
                memo=f"{label}（元本）",
                group_id=data.group_id,
                is_transfer=True,
                transfer_detail=expense_cat_path,
            ))
            db.add(Transaction(
                date=it.payment_date,
                category_id=income_cat.id,
                account_id=data.loan_account_id,
                income_amount=it.principal_amount,
                expense_amount=0,
                memo=f"{label}（元本）",
                group_id=data.group_id,
                is_transfer=True,
                transfer_detail=income_cat_path,
            ))
            principal_count += 1

        if interest_category and it.interest_amount > 0:
            db.add(Transaction(
                date=it.payment_date,
                category_id=interest_category.id,
                account_id=data.repayment_account_id,
                income_amount=0,
                expense_amount=it.interest_amount,
                memo=f"{label}（利息）",
                group_id=data.group_id,
                is_transfer=False,
            ))
            interest_count += 1

    db.commit()

    regular_items = [it for it in items if not it.is_early_repayment]
    return LoanCreateResponse(
        created_principal_count=principal_count,
        created_interest_count=interest_count,
        created_early_repayment_count=early_repayment_count,
        total_principal=sum(it.principal_amount for it in items),
        total_interest=sum(it.interest_amount for it in regular_items),
    )


def _validate_accounts(data: LoanInput, db: Session) -> tuple[Account, Account]:
    loan_account = db.query(Account).filter(Account.id == data.loan_account_id).first()
    if not loan_account:
        raise HTTPException(status_code=400, detail="ローン口座が見つかりません")
    repayment_account = db.query(Account).filter(Account.id == data.repayment_account_id).first()
    if not repayment_account:
        raise HTTPException(status_code=400, detail="返済口座が見つかりません")
    if data.loan_account_id == data.repayment_account_id:
        raise HTTPException(status_code=400, detail="ローン口座と返済口座は異なるアカウントを指定してください")
    return loan_account, repayment_account


def _validate_interest_category(data: LoanInput, db: Session) -> Category:
    if not data.interest_category_id:
        raise HTTPException(status_code=400, detail="利息カテゴリを選択してください")
    cat = db.query(Category).filter(Category.id == data.interest_category_id).first()
    if not cat:
        raise HTTPException(status_code=400, detail="利息カテゴリが見つかりません")
    return cat
