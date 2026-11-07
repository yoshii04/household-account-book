"""通知本文の組み立て（純粋関数）。

本文に載せるのはパターン名・支払日・金額・収入の目印だけ。
口座名・カテゴリ階層・メモは載せない（ADR-0007 決定 4）。
"""
from datetime import date, datetime
from typing import Optional

from app.notify.base import NotificationMessage


def _escape(text: str) -> str:
    """名前を本文に載せる形にする。改行などの空白は 1 つの空白にまとめる
    （名前の途中の改行で、箇条書きや見出しの行を偽装されないようにする）。
    そのうえで Slack の制御文字をエスケープする（& を先に置換する）。"""
    text = " ".join(text.split())
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_date(d: date) -> str:
    return f"{d.month:02d}/{d.day:02d}"


def _line(pattern: dict, show_amount: bool, with_payment_date: bool) -> str:
    text = f"• {_escape(pattern['name']) or '（名称なし）'}"
    if pattern.get("is_income"):
        text += "（収入）"
    amount = pattern.get("typical_amount")
    if show_amount and amount:
        text += f" — {amount:,}円"
    payment_date = pattern.get("next_payment_date")
    if with_payment_date and payment_date:
        text += f"（支払日: {_format_date(payment_date)}）"
    return text


def build_daily_message(
    due: list[dict], unrecorded: list[dict], show_amount: bool, today: date
) -> Optional[NotificationMessage]:
    """両方とも 0 件なら None（何も送らない）。件数 0 のセクションは省略する。"""
    sections = []
    if due:
        lines = [f"■ 今日が支払日（まだ未記録 {len(due)}件）"]
        lines += [_line(p, show_amount, with_payment_date=False) for p in due]
        sections.append("\n".join(lines))
    if unrecorded:
        lines = [f"■ 支払日を過ぎて未記録（{len(unrecorded)}件）"]
        lines += [_line(p, show_amount, with_payment_date=True) for p in unrecorded]
        sections.append("\n".join(lines))
    if not sections:
        return None
    header = f"【家計簿】{today.isoformat()} の支払いリマインド"
    return NotificationMessage("\n\n".join([header] + sections))


def build_test_message(now: datetime) -> NotificationMessage:
    """疎通確認用。DB の内容は一切含めない。"""
    return NotificationMessage(f"【家計簿】テスト通知です（{now:%Y-%m-%d %H:%M} JST）")
