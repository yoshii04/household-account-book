"""通知 CLI。

    python -m app.notify.run daily            # 判定して送る（1 回実行して終了）
    python -m app.notify.run daily --dry-run  # 送らずに本文を標準出力へ出す
    python -m app.notify.run test             # 疎通確認用のテストメッセージを送る

終了コード: 0=成功・対象 0 件・機能無効・dry-run / 1=送信失敗・設定ミス・想定外の例外 / 2=引数の誤り
"""
import argparse
import logging
import sys
from datetime import date
from typing import Optional, TextIO

from app.crud.pattern import get_due_and_unrecorded_patterns
from app.jst import now_jst, today_jst
from app.notify.base import NotificationError, Notifier, configure_logging
from app.notify.messages import build_daily_message, build_test_message
from app.notify.slack import SlackNotifier, is_valid_webhook_url

logger = logging.getLogger("app.notify.run")  # -m で実行すると __name__ は __main__ になるため固定する


def parse_show_amount(value: str) -> Optional[bool]:
    """true / false（大文字小文字を区別しない）だけを受け付ける。それ以外は None。

    不正値を既定（true）に読み替えない（金額を隠したいのに誤記で出てしまうのを避ける: fail-closed）。
    """
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _safe_detail(exc: Exception) -> str:
    """ログに出す詳細。SQLAlchemy の例外は str() に SQL 文とバインド値を含むため、
    DB ドライバ自身のメッセージ（exc.orig）の 1 行目だけを、長さを抑えて出す。"""
    detail = str(getattr(exc, "orig", None) or exc)
    lines = detail.splitlines()
    return (lines[0] if lines else "")[:200]


def run_daily(
    db,
    notifier: Optional[Notifier],
    *,
    today: date,
    show_amount: bool,
    dry_run: bool = False,
    out: Optional[TextIO] = None,
) -> int:
    """判定して送る。終了コードを返す。dry_run のときは送らずに本文を out へ出す。"""
    out = out or sys.stdout
    due, unrecorded = get_due_and_unrecorded_patterns(db, today)
    message = build_daily_message(due, unrecorded, show_amount, today)

    if dry_run:
        print(message.text if message else "送信対象はありません", file=out)
        return 0
    if message is None:
        logger.info("送信対象なし")
        return 0
    if notifier is None:
        raise ValueError("notifier が必要です")

    try:
        notifier.send(message)
    except NotificationError as exc:
        logger.error("Slack への通知に失敗しました: %s attempts=%d", exc, exc.attempts)
        return 1
    logger.info("通知を送信しました: due=%d unrecorded=%d", len(due), len(unrecorded))
    return 0


def _command_daily(args, cfg) -> int:
    show_amount = parse_show_amount(cfg.notify_show_amount)
    if show_amount is None:
        logger.error("NOTIFY_SHOW_AMOUNT が不正です（true / false を指定してください）")
        return 1

    notifier: Optional[Notifier] = None
    if not args.dry_run:
        url = cfg.slack_webhook_url.strip()
        if not url:
            logger.info("通知は無効です（SLACK_WEBHOOK_URL 未設定）")
            return 0
        if not is_valid_webhook_url(url):
            logger.error("SLACK_WEBHOOK_URL の形式が不正です")
            return 1
        notifier = SlackNotifier(url)

    try:
        from app.database import SessionLocal  # 通知が無効なときや test では DB に触れない

        db = SessionLocal()
        try:
            return run_daily(
                db, notifier, today=today_jst(), show_amount=show_amount, dry_run=args.dry_run
            )
        finally:
            db.close()
    except Exception as exc:  # DB 取得・本文の組み立て段階の想定外の例外（送信段階は NotificationError に変換済み）
        logger.error("想定外のエラー: type=%s message=%s", type(exc).__name__, _safe_detail(exc))
        return 1


def _command_test(args, cfg) -> int:
    url = cfg.slack_webhook_url.strip()
    if not url:
        logger.error("SLACK_WEBHOOK_URL が未設定です")
        return 1
    if not is_valid_webhook_url(url):
        logger.error("SLACK_WEBHOOK_URL の形式が不正です")
        return 1
    try:
        SlackNotifier(url).send(build_test_message(now_jst()))
    except NotificationError as exc:
        logger.error("Slack への通知に失敗しました: %s attempts=%d", exc, exc.attempts)
        return 1
    logger.info("テストメッセージを送信しました")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.notify.run", description="定期支払いの通知")
    sub = parser.add_subparsers(dest="command", required=True)
    daily = sub.add_parser("daily", help="判定して送る（1 回実行して終了）")
    daily.add_argument("--dry-run", action="store_true", help="送らずに本文を標準出力へ出す")
    sub.add_parser("test", help="疎通確認用のテストメッセージを送る")
    return parser


def main(argv: Optional[list[str]] = None, cfg=None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    if cfg is None:
        from app.config import settings as cfg
    if args.command == "daily":
        return _command_daily(args, cfg)
    return _command_test(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
