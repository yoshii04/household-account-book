"""
loan_service.py の純粋関数に対するユニットテスト

DB 接続不要で実行できるテストのみ含む。
"""
from datetime import date

import pytest

from app.services.loan_service import (
    _adjust_for_holiday,
    _payment_date_for_month,
    calculate_schedule,
    EarlyRepayment,
)


# ─── _adjust_for_holiday ─────────────────────────────────────────────────────

class TestAdjustForHoliday:
    # 2024-06-01 = 土曜, 2024-06-02 = 日曜, 2024-06-03 = 月曜, 2024-05-31 = 金曜

    def test_saturday_next_moves_to_monday(self):
        d = date(2024, 6, 1)  # 土曜
        assert _adjust_for_holiday(d, "next") == date(2024, 6, 3)

    def test_sunday_next_moves_to_monday(self):
        d = date(2024, 6, 2)  # 日曜
        assert _adjust_for_holiday(d, "next") == date(2024, 6, 3)

    def test_saturday_prev_moves_to_friday(self):
        d = date(2024, 6, 1)  # 土曜
        assert _adjust_for_holiday(d, "prev") == date(2024, 5, 31)

    def test_sunday_prev_moves_to_friday(self):
        d = date(2024, 6, 2)  # 日曜
        assert _adjust_for_holiday(d, "prev") == date(2024, 5, 31)

    def test_monday_next_unchanged(self):
        d = date(2024, 6, 3)  # 月曜
        assert _adjust_for_holiday(d, "next") == date(2024, 6, 3)

    def test_friday_prev_unchanged(self):
        d = date(2024, 5, 31)  # 金曜
        assert _adjust_for_holiday(d, "prev") == date(2024, 5, 31)

    def test_none_does_not_adjust_saturday(self):
        d = date(2024, 6, 1)  # 土曜
        assert _adjust_for_holiday(d, "none") == date(2024, 6, 1)

    def test_none_does_not_adjust_sunday(self):
        d = date(2024, 6, 2)  # 日曜
        assert _adjust_for_holiday(d, "none") == date(2024, 6, 2)


# ─── _payment_date_for_month ──────────────────────────────────────────────────

class TestPaymentDateForMonth:
    def test_normal_day_in_month(self):
        result = _payment_date_for_month(2024, 3, 15, "none")
        assert result == date(2024, 3, 15)

    def test_day_exceeds_month_end_uses_last_day(self):
        # 2月に31日を指定 → 2月末日になる
        result = _payment_date_for_month(2024, 2, 31, "none")
        assert result == date(2024, 2, 29)  # 2024年は閏年

    def test_day_exceeds_month_end_non_leap(self):
        result = _payment_date_for_month(2023, 2, 31, "none")
        assert result == date(2023, 2, 28)

    def test_day_30_in_april(self):
        # 4月に31日指定 → 4月30日
        result = _payment_date_for_month(2024, 4, 31, "none")
        assert result == date(2024, 4, 30)

    def test_holiday_adjustment_applied(self):
        # 2024-06-25 は火曜なので調整なし
        result = _payment_date_for_month(2024, 6, 25, "next")
        assert result == date(2024, 6, 25)

    def test_saturday_adjusted_to_next_monday(self):
        # 2024-06-01 は土曜 → 月曜 (06-03)
        result = _payment_date_for_month(2024, 6, 1, "next")
        assert result == date(2024, 6, 3)


# ─── calculate_schedule（元利均等）────────────────────────────────────────────

class TestCalculateScheduleEqualInstallment:

    @pytest.fixture
    def schedule_3m(self):
        return calculate_schedule(
            principal=1_000_000,
            annual_rate=1.2,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 2, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
        )

    def test_payment_count_matches_num_payments(self, schedule_3m):
        assert len(schedule_3m) == 3

    def test_total_principal_equals_borrow_amount(self, schedule_3m):
        assert sum(it.principal_amount for it in schedule_3m) == 1_000_000

    def test_remaining_balance_is_zero_after_last_payment(self, schedule_3m):
        assert schedule_3m[-1].remaining_balance == 0

    def test_payment_numbers_are_sequential(self, schedule_3m):
        for i, item in enumerate(schedule_3m, 1):
            assert item.payment_number == i

    def test_all_interest_amounts_non_negative(self, schedule_3m):
        for item in schedule_3m:
            assert item.interest_amount >= 0

    def test_all_principal_amounts_positive(self, schedule_3m):
        for item in schedule_3m:
            assert item.principal_amount > 0

    def test_intermediate_payments_are_equal(self, schedule_3m):
        # 元利均等: 最終回以外の返済額は一定
        non_last = [it.payment_amount for it in schedule_3m[:-1]]
        assert len(set(non_last)) == 1

    def test_last_payment_clears_remainder(self, schedule_3m):
        # 最終回後の残高は必ず 0
        assert schedule_3m[-1].remaining_balance == 0

    def test_payment_amount_equals_principal_plus_interest(self, schedule_3m):
        last = schedule_3m[-1]
        assert last.payment_amount == last.principal_amount + last.interest_amount

    def test_zero_interest_rate_no_interest(self):
        schedule = calculate_schedule(
            principal=300_000,
            annual_rate=0,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 2, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
        )
        for item in schedule:
            assert item.interest_amount == 0

    def test_zero_interest_rate_equal_payments(self):
        schedule = calculate_schedule(
            principal=300_000,
            annual_rate=0,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 2, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
        )
        assert sum(it.principal_amount for it in schedule) == 300_000
        assert schedule[-1].remaining_balance == 0

    def test_single_payment_clears_entire_balance(self):
        schedule = calculate_schedule(
            principal=500_000,
            annual_rate=1.2,
            num_payments=1,
            repayment_day=25,
            first_payment_date=date(2024, 3, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
        )
        assert len(schedule) == 1
        assert schedule[0].remaining_balance == 0
        assert schedule[0].principal_amount == 500_000

    def test_month_rollover_across_year_end(self):
        schedule = calculate_schedule(
            principal=600_000,
            annual_rate=0,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 11, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
        )
        dates = [it.payment_date for it in schedule]
        assert dates[0] == date(2024, 11, 25)
        assert dates[1] == date(2024, 12, 25)
        assert dates[2] == date(2025, 1, 25)

    def test_holiday_adjustment_applied_in_schedule(self):
        # 2024年6月1日は土曜 → 翌営業日 (6/3 月曜)
        schedule = calculate_schedule(
            principal=300_000,
            annual_rate=0,
            num_payments=1,
            repayment_day=1,
            first_payment_date=date(2024, 6, 1),
            repayment_method="equal_installment",
            holiday_handling="next",
        )
        assert schedule[0].payment_date == date(2024, 6, 3)

    def test_february_day_capped_at_month_end(self):
        schedule = calculate_schedule(
            principal=600_000,
            annual_rate=0,
            num_payments=2,
            repayment_day=31,
            first_payment_date=date(2024, 2, 28),
            repayment_method="equal_installment",
            holiday_handling="none",
        )
        # 2024年2月は29日まで（閏年）
        assert schedule[0].payment_date == date(2024, 2, 29)
        # 3月は31日まで
        assert schedule[1].payment_date == date(2024, 3, 31)


# ─── calculate_schedule（元金均等）────────────────────────────────────────────

class TestCalculateScheduleEqualPrincipal:

    @pytest.fixture
    def schedule_3m(self):
        return calculate_schedule(
            principal=900_000,
            annual_rate=1.2,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 2, 25),
            repayment_method="equal_principal",
            holiday_handling="none",
        )

    def test_payment_count_matches_num_payments(self, schedule_3m):
        assert len(schedule_3m) == 3

    def test_total_principal_equals_borrow_amount(self, schedule_3m):
        assert sum(it.principal_amount for it in schedule_3m) == 900_000

    def test_remaining_balance_is_zero_after_last_payment(self, schedule_3m):
        assert schedule_3m[-1].remaining_balance == 0

    def test_intermediate_principal_amounts_are_equal(self, schedule_3m):
        # 元金均等: 最終回以外の元本は一定
        non_last_principals = [it.principal_amount for it in schedule_3m[:-1]]
        assert len(set(non_last_principals)) == 1

    def test_interest_decreases_over_time(self, schedule_3m):
        # 残高が減るにつれ利息も減る
        interests = [it.interest_amount for it in schedule_3m]
        assert interests[0] >= interests[1] >= interests[2]

    def test_payment_amount_equals_principal_plus_interest_each_month(self, schedule_3m):
        for item in schedule_3m:
            assert item.payment_amount == item.principal_amount + item.interest_amount

    def test_zero_interest_rate_equal_payments_each_month(self):
        schedule = calculate_schedule(
            principal=600_000,
            annual_rate=0,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 2, 25),
            repayment_method="equal_principal",
            holiday_handling="none",
        )
        for item in schedule:
            assert item.interest_amount == 0
        assert sum(it.principal_amount for it in schedule) == 600_000


# ─── 端数処理 ─────────────────────────────────────────────────────────────────

class TestRounding:
    def test_total_principal_always_exact(self):
        """端数が生じても元本合計は必ず借入額と一致する"""
        for principal in (1_000_001, 3_000_007, 999_999):
            schedule = calculate_schedule(
                principal=principal,
                annual_rate=1.5,
                num_payments=7,
                repayment_day=25,
                first_payment_date=date(2024, 1, 25),
                repayment_method="equal_installment",
                holiday_handling="none",
            )
            assert sum(it.principal_amount for it in schedule) == principal

    def test_remaining_balance_zero_regardless_of_rounding(self):
        """端数処理後、残高は必ず 0 になる"""
        for principal in (100_001, 500_003, 1_234_567):
            schedule = calculate_schedule(
                principal=principal,
                annual_rate=2.1,
                num_payments=5,
                repayment_day=28,
                first_payment_date=date(2024, 3, 28),
                repayment_method="equal_principal",
                holiday_handling="none",
            )
            assert schedule[-1].remaining_balance == 0


# ─── 繰り上げ返済 ─────────────────────────────────────────────────────────────

class TestEarlyRepayment:
    """繰り上げ返済あり・なしのスケジュール計算テスト"""

    @pytest.fixture
    def base_args(self):
        return dict(
            principal=900_000,
            annual_rate=0,
            num_payments=6,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
        )

    # ── 後方互換: 繰り上げなしは従来と同じ ───────────────────────────────────

    def test_no_early_repayment_same_as_original(self, base_args):
        s1 = calculate_schedule(**base_args)
        s2 = calculate_schedule(**base_args, early_repayments=[])
        assert [(it.payment_number, it.remaining_balance) for it in s1] == \
               [(it.payment_number, it.remaining_balance) for it in s2]

    # ── 期間短縮型（shorten）────────────────────────────────────────────────

    def test_shorten_reduces_total_payment_count(self, base_args):
        er = [EarlyRepayment(date=date(2024, 3, 1), amount=300_000)]
        schedule = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="shorten")
        regular = [it for it in schedule if not it.is_early_repayment]
        assert len(regular) < 6

    def test_shorten_total_principal_still_equals_borrow_amount(self, base_args):
        er = [EarlyRepayment(date=date(2024, 3, 1), amount=300_000)]
        schedule = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="shorten")
        assert sum(it.principal_amount for it in schedule) == 900_000

    def test_shorten_remaining_balance_zero_at_end(self, base_args):
        er = [EarlyRepayment(date=date(2024, 3, 1), amount=300_000)]
        schedule = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="shorten")
        assert schedule[-1].remaining_balance == 0

    def test_shorten_early_repayment_item_marked(self, base_args):
        er = [EarlyRepayment(date=date(2024, 3, 1), amount=300_000)]
        schedule = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="shorten")
        early_items = [it for it in schedule if it.is_early_repayment]
        assert len(early_items) == 1
        assert early_items[0].payment_number == 0
        assert early_items[0].principal_amount == 300_000
        assert early_items[0].interest_amount == 0

    def test_shorten_early_repayment_appears_before_next_regular_payment(self, base_args):
        er = [EarlyRepayment(date=date(2024, 3, 1), amount=100_000)]
        schedule = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="shorten")
        early_idx = next(i for i, it in enumerate(schedule) if it.is_early_repayment)
        # 繰り上げ返済の次のアイテムは通常の返済（第3回以降）
        next_item = schedule[early_idx + 1]
        assert not next_item.is_early_repayment
        assert next_item.payment_date > schedule[early_idx].payment_date

    def test_shorten_full_payoff_by_early_repayment(self, base_args):
        # 繰り上げで全額返済 → 通常回が残らない
        er = [EarlyRepayment(date=date(2024, 2, 1), amount=900_000)]
        schedule = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="shorten")
        regular = [it for it in schedule if not it.is_early_repayment]
        # 第1回（1月25日）は繰り上げ前なので存在する
        assert schedule[-1].remaining_balance == 0
        assert sum(it.principal_amount for it in schedule) == 900_000

    def test_shorten_early_repayment_capped_at_remaining(self, base_args):
        # 残高より大きい繰り上げ額は残高で打ち切られる
        er = [EarlyRepayment(date=date(2024, 6, 1), amount=999_999_999)]
        schedule = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="shorten")
        assert schedule[-1].remaining_balance == 0
        assert sum(it.principal_amount for it in schedule) == 900_000

    def test_shorten_multiple_early_repayments(self, base_args):
        ers = [
            EarlyRepayment(date=date(2024, 2, 15), amount=100_000),
            EarlyRepayment(date=date(2024, 4, 15), amount=200_000),
        ]
        schedule = calculate_schedule(**base_args, early_repayments=ers, early_repayment_type="shorten")
        early_items = [it for it in schedule if it.is_early_repayment]
        assert len(early_items) == 2
        assert sum(it.principal_amount for it in schedule) == 900_000
        assert schedule[-1].remaining_balance == 0

    # ── 返済額軽減型（reduce）────────────────────────────────────────────────

    def test_reduce_total_payment_count_same_as_original(self, base_args):
        er = [EarlyRepayment(date=date(2024, 3, 1), amount=300_000)]
        schedule = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="reduce")
        regular = [it for it in schedule if not it.is_early_repayment]
        # 返済額軽減型は回数が変わらない（残高が減るまで続く）
        assert len(regular) <= 6

    def test_reduce_payment_after_early_repayment_is_smaller(self, base_args):
        er = [EarlyRepayment(date=date(2024, 3, 1), amount=300_000)]
        no_er = calculate_schedule(**base_args)
        with_er = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="reduce")
        regular_with_er = [it for it in with_er if not it.is_early_repayment]
        # 繰り上げ後（第3回以降）の元本返済額が通常より小さい
        assert regular_with_er[2].payment_amount < no_er[2].payment_amount

    def test_reduce_total_principal_equals_borrow_amount(self, base_args):
        er = [EarlyRepayment(date=date(2024, 3, 1), amount=300_000)]
        schedule = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="reduce")
        assert sum(it.principal_amount for it in schedule) == 900_000

    def test_reduce_remaining_balance_zero_at_end(self, base_args):
        er = [EarlyRepayment(date=date(2024, 3, 1), amount=300_000)]
        schedule = calculate_schedule(**base_args, early_repayments=er, early_repayment_type="reduce")
        assert schedule[-1].remaining_balance == 0

    # ── 利率ありでの繰り上げ返済 ─────────────────────────────────────────────

    def test_shorten_with_interest_total_principal_correct(self):
        er = [EarlyRepayment(date=date(2024, 4, 1), amount=200_000)]
        schedule = calculate_schedule(
            principal=600_000,
            annual_rate=1.2,
            num_payments=6,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
            early_repayments=er,
            early_repayment_type="shorten",
        )
        assert sum(it.principal_amount for it in schedule) == 600_000
        assert schedule[-1].remaining_balance == 0


# ─── 初回指定（first_payment_amount）─────────────────────────────────────────

class TestFirstPaymentAmount:

    @pytest.fixture
    def schedule_3m(self):
        """元利均等3回、年利1.2%、初回を指定"""
        return calculate_schedule(
            principal=900_000,
            annual_rate=1.2,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
            first_payment_amount=200_000,  # 通常より少ない初回
        )

    def test_first_payment_uses_specified_amount(self, schedule_3m):
        assert schedule_3m[0].payment_amount == 200_000

    def test_first_payment_interest_deducted_from_principal(self, schedule_3m):
        interest_first = schedule_3m[0].interest_amount
        assert schedule_3m[0].principal_amount == 200_000 - interest_first

    def test_total_principal_still_equals_borrow_amount(self, schedule_3m):
        assert sum(it.principal_amount for it in schedule_3m) == 900_000

    def test_last_payment_clears_remaining_balance(self, schedule_3m):
        assert schedule_3m[-1].remaining_balance == 0

    def test_second_payment_uses_normal_fixed_amount(self):
        # 2回目以降は元の定額で計算される
        without_override = calculate_schedule(
            principal=900_000,
            annual_rate=1.2,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
        )
        with_override = calculate_schedule(
            principal=900_000,
            annual_rate=1.2,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
            first_payment_amount=200_000,
        )
        # 2回目の支払額は通常と同じ定額
        assert with_override[1].payment_amount == without_override[1].payment_amount

    def test_no_override_same_as_original(self):
        s1 = calculate_schedule(
            principal=600_000, annual_rate=1.2, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
        )
        s2 = calculate_schedule(
            principal=600_000, annual_rate=1.2, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
            first_payment_amount=None,
        )
        assert [(it.payment_amount, it.principal_amount) for it in s1] == \
               [(it.payment_amount, it.principal_amount) for it in s2]

    def test_first_payment_above_normal_reduces_subsequent_last(self):
        # 初回を通常より多く払った場合、最終回が少なくなる
        normal = calculate_schedule(
            principal=900_000, annual_rate=0, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
        )
        override = calculate_schedule(
            principal=900_000, annual_rate=0, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
            first_payment_amount=400_000,
        )
        # 初回に多く払ったので最終回は減る
        assert override[-1].payment_amount < normal[-1].payment_amount
        assert override[-1].remaining_balance == 0

    def test_first_payment_below_interest_raises_value_error(self):
        with pytest.raises(ValueError, match="初回返済額"):
            calculate_schedule(
                principal=1_000_000,
                annual_rate=12.0,  # 高利率：月利1% → 初月利息10,000円
                num_payments=3,
                repayment_day=25,
                first_payment_date=date(2024, 1, 25),
                repayment_method="equal_installment",
                holiday_handling="none",
                first_payment_amount=5_000,  # 利息10,000円未満 → エラー
            )

    def test_equal_principal_with_first_payment_override(self):
        schedule = calculate_schedule(
            principal=900_000, annual_rate=0, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_principal", holiday_handling="none",
            first_payment_amount=200_000,
        )
        assert schedule[0].payment_amount == 200_000
        assert sum(it.principal_amount for it in schedule) == 900_000
        assert schedule[-1].remaining_balance == 0

    def test_first_payment_with_early_repayment_combined(self):
        er = [EarlyRepayment(date=date(2024, 2, 1), amount=100_000)]
        schedule = calculate_schedule(
            principal=900_000, annual_rate=0, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
            first_payment_amount=150_000,
            early_repayments=er,
            early_repayment_type="shorten",
        )
        assert schedule[0].payment_amount == 150_000
        assert sum(it.principal_amount for it in schedule) == 900_000
        assert schedule[-1].remaining_balance == 0


# ─── 最終回指定（last_payment_amount）────────────────────────────────────────

class TestLastPaymentAmount:

    @pytest.fixture
    def schedule_3m(self):
        """元利均等3回、年利0%（利息なし）、最終回を指定"""
        return calculate_schedule(
            principal=900_000,
            annual_rate=0,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
            last_payment_amount=100_000,
        )

    def test_last_payment_uses_specified_amount(self, schedule_3m):
        assert schedule_3m[-1].payment_amount == 100_000

    def test_last_payment_principal_equals_amount_minus_interest(self, schedule_3m):
        last = schedule_3m[-1]
        assert last.principal_amount == last.payment_amount - last.interest_amount

    def test_no_override_same_as_original(self):
        s1 = calculate_schedule(
            principal=600_000, annual_rate=1.2, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
        )
        s2 = calculate_schedule(
            principal=600_000, annual_rate=1.2, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
            last_payment_amount=None,
        )
        assert [(it.payment_amount, it.principal_amount) for it in s1] == \
               [(it.payment_amount, it.principal_amount) for it in s2]

    def test_last_payment_with_interest_rate_within_remaining(self):
        # last_payment_amount が残高+利息以内のケース: principal = payment - interest
        schedule = calculate_schedule(
            principal=900_000,
            annual_rate=1.2,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
            last_payment_amount=299_000,  # 残高より少ない → 残高に満たない支払い
        )
        last = schedule[-1]
        assert last.payment_amount == 299_000
        assert last.principal_amount == 299_000 - last.interest_amount

    def test_last_payment_exceeding_remaining_is_capped(self):
        # last_payment_amount が残高+利息を超えるケース: principal は残高でキャップ
        schedule = calculate_schedule(
            principal=900_000,
            annual_rate=1.2,
            num_payments=3,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment",
            holiday_handling="none",
            last_payment_amount=305_000,  # 残高+利息(≈300,774)を超える
        )
        last = schedule[-1]
        assert last.payment_amount == 305_000
        # キャップにより残高がゼロになり、元本合計は借入額以下
        assert last.remaining_balance == 0
        assert sum(it.principal_amount for it in schedule) == 900_000

    def test_last_payment_below_interest_raises_value_error(self):
        with pytest.raises(ValueError, match="最終回返済額"):
            calculate_schedule(
                principal=1_000_000,
                annual_rate=12.0,  # 月利1%
                num_payments=3,
                repayment_day=25,
                first_payment_date=date(2024, 1, 25),
                repayment_method="equal_installment",
                holiday_handling="none",
                last_payment_amount=100,  # 利息より少ない → エラー
            )

    def test_equal_principal_with_last_payment_override(self):
        schedule = calculate_schedule(
            principal=900_000, annual_rate=0, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_principal", holiday_handling="none",
            last_payment_amount=250_000,
        )
        assert schedule[-1].payment_amount == 250_000

    def test_first_and_last_both_specified(self):
        schedule = calculate_schedule(
            principal=900_000, annual_rate=0, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
            first_payment_amount=200_000,
            last_payment_amount=250_000,
        )
        assert schedule[0].payment_amount == 200_000
        assert schedule[-1].payment_amount == 250_000
        # 中間回は通常の定額
        normal = calculate_schedule(
            principal=900_000, annual_rate=0, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
        )
        assert schedule[1].payment_amount == normal[1].payment_amount

    def test_last_payment_larger_than_remaining_does_not_inflate_total(self):
        # last_payment_amount が残高+利息より大きくても元本合計は借入額以下
        schedule = calculate_schedule(
            principal=900_000, annual_rate=0, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
            last_payment_amount=999_999,  # 残高(300,000)より大幅に大きい
        )
        assert sum(it.principal_amount for it in schedule) <= 900_000
        assert schedule[-1].remaining_balance == 0

    def test_last_payment_with_early_repayment(self):
        er = [EarlyRepayment(date=date(2024, 2, 1), amount=100_000)]
        schedule = calculate_schedule(
            principal=900_000, annual_rate=0, num_payments=3,
            repayment_day=25, first_payment_date=date(2024, 1, 25),
            repayment_method="equal_installment", holiday_handling="none",
            early_repayments=er, early_repayment_type="shorten",
            last_payment_amount=50_000,
        )
        # 最終の通常回返済に last_payment_amount が適用される
        regular_items = [it for it in schedule if not it.is_early_repayment]
        assert regular_items[-1].payment_amount == 50_000


# ─── 固定額払い（fixed_payment）────────────────────────────────────────────────

class TestFixedPaymentMethod:

    @pytest.fixture
    def schedule_5m(self):
        """固定額払い5回、中間返済額 100,000円、年利0%"""
        return calculate_schedule(
            principal=600_000,
            annual_rate=0,
            num_payments=5,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="fixed_payment",
            holiday_handling="none",
            regular_payment_amount=100_000,
        )

    def test_payment_count_matches_num_payments(self, schedule_5m):
        assert len(schedule_5m) == 5

    def test_middle_payments_use_regular_amount(self, schedule_5m):
        # 2回目〜最終回-1 はすべて regular_payment_amount
        for item in schedule_5m[1:-1]:
            assert item.payment_amount == 100_000

    def test_last_payment_clears_remaining_balance(self, schedule_5m):
        assert schedule_5m[-1].remaining_balance == 0

    def test_total_principal_equals_borrow_amount(self, schedule_5m):
        assert sum(it.principal_amount for it in schedule_5m) == 600_000

    def test_last_payment_is_larger_than_regular(self, schedule_5m):
        # 最終回は残高一括なので regular より大きくなる（残高が多く残った場合）
        assert schedule_5m[-1].payment_amount > 100_000

    def test_with_interest_rate_middle_payments_fixed(self):
        schedule = calculate_schedule(
            principal=600_000,
            annual_rate=1.2,
            num_payments=4,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="fixed_payment",
            holiday_handling="none",
            regular_payment_amount=80_000,
        )
        # 2〜3回目は payment_amount == 80,000
        for item in schedule[1:-1]:
            assert item.payment_amount == 80_000
        # 元本合計 == 借入額
        assert sum(it.principal_amount for it in schedule) == 600_000
        assert schedule[-1].remaining_balance == 0

    def test_first_payment_override_applies(self):
        schedule = calculate_schedule(
            principal=600_000,
            annual_rate=0,
            num_payments=4,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="fixed_payment",
            holiday_handling="none",
            regular_payment_amount=100_000,
            first_payment_amount=50_000,
        )
        assert schedule[0].payment_amount == 50_000
        # 2〜3回目は regular
        for item in schedule[1:-1]:
            assert item.payment_amount == 100_000
        assert schedule[-1].remaining_balance == 0
        assert sum(it.principal_amount for it in schedule) == 600_000

    def test_last_payment_override_applies(self):
        schedule = calculate_schedule(
            principal=600_000,
            annual_rate=0,
            num_payments=4,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="fixed_payment",
            holiday_handling="none",
            regular_payment_amount=100_000,
            last_payment_amount=250_000,
        )
        assert schedule[-1].payment_amount == 250_000

    def test_missing_regular_payment_amount_raises_error(self):
        with pytest.raises(ValueError, match="regular_payment_amount"):
            calculate_schedule(
                principal=600_000,
                annual_rate=0,
                num_payments=3,
                repayment_day=25,
                first_payment_date=date(2024, 1, 25),
                repayment_method="fixed_payment",
                holiday_handling="none",
            )

    def test_payment_numbers_are_sequential(self, schedule_5m):
        for i, item in enumerate(schedule_5m, 1):
            assert item.payment_number == i

    def test_early_repayment_with_fixed_payment(self):
        er = [EarlyRepayment(date=date(2024, 3, 1), amount=100_000)]
        schedule = calculate_schedule(
            principal=600_000,
            annual_rate=0,
            num_payments=5,
            repayment_day=25,
            first_payment_date=date(2024, 1, 25),
            repayment_method="fixed_payment",
            holiday_handling="none",
            regular_payment_amount=100_000,
            early_repayments=er,
            early_repayment_type="shorten",
        )
        assert sum(it.principal_amount for it in schedule) == 600_000
        assert schedule[-1].remaining_balance == 0
