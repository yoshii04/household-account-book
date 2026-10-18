"""JST (UTC+9) 日時ユーティリティ。date.today() や datetime.now() の代わりに使用する。"""
from datetime import date, datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))


def today_jst() -> date:
    """日本時間（JST）での今日の日付を返す。"""
    return datetime.now(tz=JST).date()


def now_jst() -> datetime:
    """日本時間（JST）での現在日時を返す。"""
    return datetime.now(tz=JST)
