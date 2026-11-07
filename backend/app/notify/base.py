"""通知の共通部品: メッセージ、Notifier 抽象、送信失敗の例外、ログ設定。"""
import logging
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.jst import JST

LOGGER_NAMESPACE = "app.notify"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


@dataclass(frozen=True)
class NotificationMessage:
    text: str


class NotificationError(Exception):
    """送信失敗。Webhook URL を含めないため、ステータスコードと例外の型名だけを持つ。

    httpx の例外メッセージには URL が含まれうるので、元の例外は引き継がない。
    """

    def __init__(self, status_code: Optional[int], error_type: str, attempts: int = 1):
        self.status_code = status_code
        self.error_type = error_type
        self.attempts = attempts
        super().__init__(f"status={status_code if status_code is not None else '-'} type={error_type}")


class Notifier(ABC):
    @abstractmethod
    def send(self, message: NotificationMessage) -> None:
        """送信する。失敗時は NotificationError を送出する。"""


def configure_logging() -> None:
    """標準エラーへ JST 表記で出力する（docker compose logs で読める形）。

    INFO にするのは app.notify の名前空間だけ（root のレベルは変えない）。
    すでにハンドラがある場合（再呼び出し、テストの caplog など）は追加しない。
    """
    logging.getLogger(LOGGER_NAMESPACE).setLevel(logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(LOG_FORMAT)
    formatter.converter = lambda ts: datetime.fromtimestamp(ts, JST).timetuple()
    handler.setFormatter(formatter)
    root.addHandler(handler)
