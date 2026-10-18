import calendar
from datetime import date


def clamp_day_to_month(year: int, month: int, day: int) -> date:
    """支払日が月末を超える場合（例: 31日→2月）は月末にクランプして返す。"""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """指定した年月の月初日・月末日を返す。"""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)
