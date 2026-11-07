"""notify/messages.py の本文組み立てのテスト

対象ADR: docs/adr/0007-pattern-payment-notification-via-slack.md
仕様書: docs/specs/auxiliary/spec_notifications.md
"""
from datetime import date, datetime

from app.jst import JST
from app.notify.messages import build_daily_message, build_test_message

TODAY = date(2026, 11, 3)


def _pattern(name="家賃", amount=80000, is_income=False, next_payment_date=None, **extra):
    return {
        "name": name,
        "typical_amount": amount,
        "is_income": is_income,
        "next_payment_date": next_payment_date,
        **extra,
    }


class TestBuildDailyMessage:
    def test_matches_adr_example(self):
        due = [_pattern("家賃", 80000)]
        unrecorded = [
            _pattern("通信費", 5500, next_payment_date=date(2026, 11, 1)),
            _pattern("保険料", 12000, next_payment_date=date(2026, 10, 25)),
        ]

        message = build_daily_message(due, unrecorded, True, TODAY)

        assert message.text == (
            "【家計簿】2026-11-03 の支払いリマインド\n"
            "\n"
            "■ 今日が支払日（まだ未記録 1件）\n"
            "• 家賃 — 80,000円\n"
            "\n"
            "■ 支払日を過ぎて未記録（2件）\n"
            "• 通信費 — 5,500円（支払日: 11/01）\n"
            "• 保険料 — 12,000円（支払日: 10/25）"
        )

    def test_returns_none_when_both_empty(self):
        assert build_daily_message([], [], True, TODAY) is None

    def test_due_only_omits_unrecorded_section(self):
        message = build_daily_message([_pattern()], [], True, TODAY)

        assert "■ 今日が支払日" in message.text
        assert "支払日を過ぎて未記録" not in message.text

    def test_unrecorded_only_omits_due_section(self):
        message = build_daily_message(
            [], [_pattern(next_payment_date=date(2026, 11, 1))], True, TODAY
        )

        assert "■ 支払日を過ぎて未記録（1件）" in message.text
        assert "今日が支払日" not in message.text

    def test_show_amount_false_hides_amount_but_keeps_payment_date(self):
        message = build_daily_message(
            [_pattern("家賃")],
            [_pattern("通信費", next_payment_date=date(2026, 11, 1))],
            False,
            TODAY,
        )

        assert "• 家賃\n" in message.text
        assert "• 通信費（支払日: 11/01）" in message.text
        assert "円" not in message.text

    def test_missing_amount_is_omitted_with_separator(self):
        for amount in (None, 0):
            message = build_daily_message(
                [_pattern("家賃", amount)],
                [_pattern("通信費", amount, next_payment_date=date(2026, 11, 1))],
                True,
                TODAY,
            )

            assert "• 家賃\n" in message.text
            assert "• 通信費（支払日: 11/01）" in message.text
            assert "—" not in message.text

    def test_payment_date_is_zero_padded(self):
        message = build_daily_message(
            [], [_pattern(next_payment_date=date(2026, 1, 5))], True, TODAY
        )

        assert "（支払日: 01/05）" in message.text

    def test_income_pattern_gets_marker_without_sign(self):
        message = build_daily_message([_pattern("給与", 300000, is_income=True)], [], True, TODAY)

        assert "• 給与（収入） — 300,000円" in message.text
        assert "+" not in message.text and "-300" not in message.text

    def test_name_is_escaped_for_slack(self):
        message = build_daily_message([_pattern("A&B <!channel> >")], [], True, TODAY)

        assert "• A&amp;B &lt;!channel&gt; &gt; — 80,000円" in message.text
        assert "<!channel>" not in message.text

    def test_newlines_in_name_cannot_forge_lines(self):
        message = build_daily_message([_pattern("家賃\n■ 偽の見出し\r\n• 偽の項目")], [], True, TODAY)

        assert message.text.count("\n") == 3  # 見出し行・空行・セクション見出し・項目の区切りだけ
        assert "• 家賃 ■ 偽の見出し • 偽の項目 — 80,000円" in message.text

    def test_blank_name_gets_placeholder(self):
        message = build_daily_message([_pattern(" \n ", 1000)], [], True, TODAY)

        assert "• （名称なし） — 1,000円" in message.text

    def test_ampersand_is_not_double_escaped(self):
        message = build_daily_message([_pattern("&lt;")], [], True, TODAY)

        assert "&amp;lt;" in message.text

    def test_does_not_include_account_category_or_memo(self):
        pattern = _pattern(
            category_full_path="目印カテゴリ/子",
            account_code="目印口座",
            to_account_code="目印移動先",
            memo_template="目印メモ",
            group_code="目印グループ",
        )

        message = build_daily_message([pattern], [dict(pattern, next_payment_date=date(2026, 11, 1))], True, TODAY)

        for marker in ("目印カテゴリ", "目印口座", "目印移動先", "目印メモ", "目印グループ"):
            assert marker not in message.text

    def test_no_trailing_newline(self):
        message = build_daily_message([_pattern()], [], True, TODAY)

        assert not message.text.endswith("\n")


class TestBuildTestMessage:
    def test_contains_only_timestamp(self):
        now = datetime(2026, 11, 3, 22, 30, 15, tzinfo=JST)

        assert build_test_message(now).text == "【家計簿】テスト通知です（2026-11-03 22:30 JST）"
