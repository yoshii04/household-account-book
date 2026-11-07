"""Slack Incoming Webhook への送信。

Webhook URL は秘密情報（ADR-0007 決定 6）。ログ・例外・トレースバックのどこにも出さない。
"""
import logging
import time
from typing import Callable, Optional
from urllib.parse import urlsplit

import httpx

from app.notify.base import NotificationError, NotificationMessage, Notifier

# httpx は INFO レベルで "HTTP Request: POST <URL> ..." を出力し、URL がログに残る。
# どこから SlackNotifier を使っても保護されるよう、モジュール読み込み時に抑制する。
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0  # 1 回目の失敗後に 1 秒、2 回目の失敗後に 2 秒


def is_valid_webhook_url(url: str) -> bool:
    """Incoming Webhook の URL（https://hooks.slack.com/services/...）だけを許可する。

    .env の誤記や改ざんで、本文が Slack 以外のホストへ送られるのを防ぐ。
    """
    if not url or not url.isprintable() or " " in url:
        return False
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.hostname == "hooks.slack.com"
            and parts.path.startswith("/services/")
            and parts.username is None
            and parts.password is None
            and parts.port is None
        )
    except ValueError:
        return False


class SlackNotifier(Notifier):
    def __init__(
        self,
        webhook_url: str,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not is_valid_webhook_url(webhook_url):
            # 入力値は URL の一部かもしれないのでメッセージに含めない
            raise ValueError("Webhook URL の形式が不正です")
        self._url = webhook_url
        self._transport = transport
        self._sleep = sleep

    def send(self, message: NotificationMessage) -> None:
        status_code: Optional[int] = None
        error_type = ""
        attempt = 0
        while attempt < MAX_ATTEMPTS:
            attempt += 1
            status_code, error_type, retryable = self._post_once(message)
            if status_code is not None and 200 <= status_code < 300:
                return
            if not retryable or attempt >= MAX_ATTEMPTS:
                break
            self._sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
        # except ブロックの外で送出する（元の例外を __context__ に残さない）
        raise NotificationError(status_code, error_type, attempts=attempt)

    def _post_once(self, message: NotificationMessage) -> tuple[Optional[int], str, bool]:
        """1 回送って (ステータスコード, 失敗時の型名, リトライするか) を返す。成功時の型名は空。"""
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
                response = client.post(self._url, json={"text": message.text})
            code = response.status_code
            if 200 <= code < 300:
                return code, "", False
            return code, "HTTPStatusError", code >= 500 or code == 429
        except httpx.TransportError as exc:
            return None, type(exc).__name__, True
        except Exception as exc:  # httpx.InvalidURL 等。メッセージに URL が含まれうるので型名だけ残す
            return None, type(exc).__name__, False
