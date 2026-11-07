"""notify/slack.py（SlackNotifier）のテスト。外部通信は httpx.MockTransport で置き換える。

対象ADR: docs/adr/0007-pattern-payment-notification-via-slack.md
仕様書: docs/specs/auxiliary/spec_notifications.md
"""
import json
import logging
import traceback

import httpx
import pytest

from app.notify.base import NotificationError, NotificationMessage
from app.notify.slack import SlackNotifier, is_valid_webhook_url

URL = "https://hooks.slack.com/services/T0SECRET/B0SECRET/xxxxSECRETxxxx"
SECRET_PARTS = ("T0SECRET", "B0SECRET", "xxxxSECRETxxxx", "hooks.slack.com/services")
MESSAGE = NotificationMessage("こんにちは")


def _notifier(handler, sleeps=None):
    waits = sleeps if sleeps is not None else []
    return SlackNotifier(URL, transport=httpx.MockTransport(handler), sleep=waits.append), waits


def _status_sequence(*codes):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(codes[min(len(calls), len(codes)) - 1], text="body")

    return handler, calls


def _assert_no_secret(text):
    for part in SECRET_PARTS:
        assert part not in text


class TestSend:
    def test_success_posts_json_text(self):
        handler, calls = _status_sequence(200)
        notifier, waits = _notifier(handler)

        notifier.send(MESSAGE)

        assert len(calls) == 1
        assert calls[0].method == "POST"
        assert str(calls[0].url) == URL
        assert json.loads(calls[0].content) == {"text": "こんにちは"}
        assert waits == []

    def test_retries_5xx_then_succeeds_with_backoff(self):
        handler, calls = _status_sequence(500, 500, 200)
        notifier, waits = _notifier(handler)

        notifier.send(MESSAGE)

        assert len(calls) == 3
        assert waits == [1.0, 2.0]

    def test_raises_after_three_failed_attempts(self):
        handler, calls = _status_sequence(500)
        notifier, waits = _notifier(handler)

        with pytest.raises(NotificationError) as exc_info:
            notifier.send(MESSAGE)

        assert len(calls) == 3
        assert waits == [1.0, 2.0]
        assert exc_info.value.status_code == 500
        assert exc_info.value.attempts == 3
        assert str(exc_info.value) == "status=500 type=HTTPStatusError"

    def test_retries_429(self):
        handler, calls = _status_sequence(429, 200)
        notifier, _ = _notifier(handler)

        notifier.send(MESSAGE)

        assert len(calls) == 2

    @pytest.mark.parametrize("status", [400, 403, 404, 302])
    def test_does_not_retry_4xx_or_3xx(self, status):
        handler, calls = _status_sequence(status)
        notifier, waits = _notifier(handler)

        with pytest.raises(NotificationError) as exc_info:
            notifier.send(MESSAGE)

        assert len(calls) == 1
        assert waits == []
        assert exc_info.value.status_code == status

    @pytest.mark.parametrize("exc_class", [httpx.ConnectError, httpx.ReadTimeout])
    def test_retries_transport_errors(self, exc_class):
        calls = []

        def handler(request):
            calls.append(request)
            raise exc_class(f"failed for {request.url}", request=request)

        notifier, waits = _notifier(handler)

        with pytest.raises(NotificationError) as exc_info:
            notifier.send(MESSAGE)

        assert len(calls) == 3
        assert waits == [1.0, 2.0]
        assert exc_info.value.status_code is None
        assert exc_info.value.error_type == exc_class.__name__
        assert str(exc_info.value) == f"status=- type={exc_class.__name__}"

    def test_non_transport_exception_is_converted_without_retry(self):
        calls = []

        def handler(request):
            calls.append(request)
            raise httpx.InvalidURL(f"Invalid URL {request.url}")

        notifier, waits = _notifier(handler)

        with pytest.raises(NotificationError) as exc_info:
            notifier.send(MESSAGE)

        assert len(calls) == 1
        assert waits == []
        assert exc_info.value.status_code is None
        assert exc_info.value.error_type == "InvalidURL"
        assert "Invalid URL" not in str(exc_info.value)


class TestSecretNotLeaked:
    """Webhook URL は str()・ログ・トレースバック（__context__ を含む）のどこにも出さない。"""

    def _failing_notifier(self):
        def handler(request):
            raise httpx.ConnectError(f"connection failed: {request.url}", request=request)

        return _notifier(handler)[0]

    def test_error_text_and_traceback_do_not_contain_url(self):
        with pytest.raises(NotificationError) as exc_info:
            self._failing_notifier().send(MESSAGE)

        error = exc_info.value
        _assert_no_secret(str(error))
        assert error.__cause__ is None
        assert error.__context__ is None
        _assert_no_secret("".join(traceback.format_exception(error)))

    def test_logs_do_not_contain_url_on_success_and_failure(self, caplog):
        caplog.set_level(logging.DEBUG)

        handler, _ = _status_sequence(200)
        _notifier(handler)[0].send(MESSAGE)
        with pytest.raises(NotificationError):
            self._failing_notifier().send(MESSAGE)

        _assert_no_secret(caplog.text)

    def test_httpx_loggers_are_quiet_by_default(self):
        for name in ("httpx", "httpcore"):
            assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


class TestWebhookUrlValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "https://hooks.slack.com/services/T0/B0/xxxx",
            "https://HOOKS.slack.com/services/T0/B0/xxxx",
        ],
    )
    def test_accepts_slack_webhook_url(self, url):
        assert is_valid_webhook_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "http://hooks.slack.com/services/T0/B0/xxxx",
            "https://example.com/services/T0/B0/xxxx",
            "https://hooks.slack.com.evil.example/services/T0/B0/xxxx",
            "https://hooks.slack.com@evil.example/services/T0/B0/xxxx",
            "https://user:pass@hooks.slack.com/services/T0/B0/xxxx",
            "https://hooks.slack.com:8443/services/T0/B0/xxxx",
            "https://hooks.slack.com/other/T0/B0/xxxx",
            "https://hooks.slack.com/services/T0/B0/xx xx",
            "https://hooks.slack.com/services/T0/B0/xx\nxx",
            "hooks.slack.com/services/T0/B0/xxxx",
        ],
    )
    def test_rejects_other_urls(self, url):
        assert not is_valid_webhook_url(url)

    def test_constructor_rejects_invalid_url_without_echoing_it(self):
        with pytest.raises(ValueError) as exc_info:
            SlackNotifier("https://example.com/services/SECRETVALUE")

        assert "SECRETVALUE" not in str(exc_info.value)
