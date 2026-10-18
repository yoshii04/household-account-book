from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import List, Optional
from dataclasses import dataclass, field

from app.utils.date_utils import clamp_day_to_month


@dataclass
class EarlyRepayment:
    date: date
    amount: int


@dataclass
class RepaymentItem:
    payment_number: int
    payment_date: date
    payment_amount: int
    principal_amount: int
    interest_amount: int
    remaining_balance: int
    is_early_repayment: bool = False


def _adjust_for_holiday(d: date, holiday_handling: str) -> date:
    if holiday_handling == "next":
        while d.weekday() >= 5:
            d += timedelta(days=1)
    elif holiday_handling == "prev":
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d


def _payment_date_for_month(year: int, month: int, day: int, holiday_handling: str) -> date:
    d = clamp_day_to_month(year, month, day)
    return _adjust_for_holiday(d, holiday_handling)


def calculate_schedule(
    principal: int,
    annual_rate: float,
    num_payments: int,
    repayment_day: int,
    first_payment_date: date,
    repayment_method: str,
    holiday_handling: str,
    early_repayments: Optional[List[EarlyRepayment]] = None,
    early_repayment_type: str = "shorten",
    first_payment_amount: Optional[int] = None,
    last_payment_amount: Optional[int] = None,
    regular_payment_amount: Optional[int] = None,
) -> List[RepaymentItem]:
    """
    返済スケジュールを計算する。端数は最終回に繰入れ。

    repayment_method:
        "equal_installment" = 元利均等
        "equal_principal"   = 元金均等
        "fixed_payment"     = 固定額払い（2回目〜最終回-1は指定額、最終回は残高一括）
    holiday_handling: "next"=翌営業日, "prev"=前営業日, "none"=調整なし
    early_repayment_type: "shorten"=期間短縮型, "reduce"=返済額軽減型
    first_payment_amount:   初回返済額を明示指定（日割り利息等）
    last_payment_amount:    最終回返済額を明示指定（銀行の端数処理等）
    regular_payment_amount: fixed_payment 方式での 2回目〜最終回-1 の返済額
    """
    r = Decimal(str(annual_rate)) / Decimal("100") / Decimal("12")
    n = num_payments

    def _calc_fixed(rem: int, payments_left: int) -> int:
        if r == 0:
            return int(Decimal(str(rem)) // payments_left)
        p = Decimal(str(rem))
        rn = (1 + r) ** payments_left
        return int((p * r * rn / (rn - 1)).to_integral_value(ROUND_DOWN))

    if repayment_method == "equal_installment":
        fixed_payment = _calc_fixed(principal, n)
    elif repayment_method == "fixed_payment":
        if not regular_payment_amount:
            raise ValueError("fixed_payment 方式では regular_payment_amount を指定してください")
        fixed_payment = regular_payment_amount
    else:
        base_principal = principal // n

    pending_early = sorted(early_repayments or [], key=lambda x: x.date)
    schedule: List[RepaymentItem] = []
    remaining = principal
    cur_year, cur_month = first_payment_date.year, first_payment_date.month
    payment_num = 0

    for i in range(1, n + 1):
        pay_date = _payment_date_for_month(cur_year, cur_month, repayment_day, holiday_handling)

        # 今回の返済日までの繰り上げ返済を適用
        applied = [er for er in pending_early if er.date <= pay_date]
        pending_early = [er for er in pending_early if er.date > pay_date]

        for er in applied:
            er_amount = min(er.amount, remaining)
            remaining -= er_amount
            schedule.append(RepaymentItem(
                payment_number=0,
                payment_date=er.date,
                payment_amount=er_amount,
                principal_amount=er_amount,
                interest_amount=0,
                remaining_balance=max(0, remaining),
                is_early_repayment=True,
            ))
            if remaining <= 0:
                break

            # 返済額軽減型: 繰り上げ後に毎月の支払額を再計算
            if early_repayment_type == "reduce":
                payments_left = n - i + 1
                if repayment_method == "equal_installment":
                    fixed_payment = _calc_fixed(remaining, payments_left)
                elif repayment_method == "fixed_payment":
                    pass  # 固定額払いは繰り上げ後も返済額は変えない（残高一括の最終回で吸収）
                else:
                    base_principal = remaining // payments_left

        if remaining <= 0:
            break

        interest = int((Decimal(str(remaining)) * r).to_integral_value(ROUND_DOWN))
        payment_num += 1

        # is_last を先に確定させてから返済額を決定する
        if repayment_method in ("equal_installment", "fixed_payment"):
            is_last = (i == n) or (remaining <= fixed_payment - interest)
        else:
            is_last = (i == n) or (remaining <= base_principal)

        if i == 1 and first_payment_amount is not None:
            payment_amount = first_payment_amount
            principal_amount = min(payment_amount - interest, remaining)
            if principal_amount < 1:
                raise ValueError(
                    f"初回返済額（{first_payment_amount:,}円）が初回利息額（{interest:,}円）以下です。"
                    "初回返済額を増やしてください。"
                )
        elif is_last and last_payment_amount is not None:
            payment_amount = last_payment_amount
            principal_amount = min(payment_amount - interest, remaining)
            if principal_amount < 1:
                raise ValueError(
                    f"最終回返済額（{last_payment_amount:,}円）が最終回利息額（{interest:,}円）以下です。"
                    "最終回返済額を増やしてください。"
                )
        elif repayment_method in ("equal_installment", "fixed_payment"):
            if is_last:
                principal_amount = remaining
                payment_amount = principal_amount + interest
            else:
                principal_amount = max(1, fixed_payment - interest)
                payment_amount = fixed_payment
        else:
            principal_amount = remaining if is_last else base_principal
            payment_amount = principal_amount + interest

        remaining -= principal_amount

        schedule.append(RepaymentItem(
            payment_number=payment_num,
            payment_date=pay_date,
            payment_amount=payment_amount,
            principal_amount=principal_amount,
            interest_amount=interest,
            remaining_balance=max(0, remaining),
        ))

        if remaining <= 0:
            break

        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1

    return schedule
