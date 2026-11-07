"""毎日 NOTIFY_TIME（JST）に `python -m app.notify.run daily` を実行し続ける薄い常駐プロセス。

標準ライブラリのみで実装する（cron 系・APScheduler 等の依存は追加しない。ADR-0007 決定 3）。
追い送信はしない: 起動時に今日の NOTIFY_TIME を過ぎていれば、今日の分は実行済みとして扱う。
"""
import logging
import re
import signal
import subprocess
import sys
import time as time_module
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

from app.jst import now_jst
from app.notify.base import configure_logging

logger = logging.getLogger("app.notify.scheduler")  # -m で実行すると __name__ は __main__ になるため固定する

POLL_INTERVAL_SECONDS = 30
LATE_TOLERANCE = timedelta(minutes=10)  # スリープ復帰などで実行時刻を過ぎて起きたときの許容遅延
DAILY_TIMEOUT_SECONDS = 120

_NOTIFY_TIME_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")  # ASCII の数字だけ（全角を受け付けない）


def parse_notify_time(value: str) -> Optional[time]:
    """HH:MM（00:00〜23:59）だけを受け付ける。不正なら None。"""
    match = _NOTIFY_TIME_PATTERN.match(value.strip())
    if not match:
        return None
    return time(int(match.group(1)), int(match.group(2)))


def _target(now: datetime, notify_time: time) -> datetime:
    return datetime.combine(now.date(), notify_time, tzinfo=now.tzinfo)


def initial_handled_date(now: datetime, notify_time: time) -> Optional[date]:
    """起動時にすでに今日の実行時刻を過ぎていれば、今日は処理済み（追い送信しない）。"""
    return now.date() if now >= _target(now, notify_time) else None


def decide(
    now: datetime, notify_time: time, last_handled_date: Optional[date], tolerance: timedelta
) -> str:
    """"run"（実行する）/ "skip"（実行時刻を大きく過ぎたので今日は送らない）/ "wait"（待つ）。"""
    target = _target(now, notify_time)
    if last_handled_date == now.date() or now < target:
        return "wait"
    return "run" if now - target <= tolerance else "skip"


def run_daily_subprocess() -> Optional[int]:
    """daily を別プロセスで実行する。実行のたびに新しい DB 接続を作るため、
    長時間アイドルで切れた接続や DB の再起動の影響を受けない。
    戻り値は終了コード。タイムアウトや起動失敗は None。"""
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "app.notify.run", "daily"], timeout=DAILY_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        logger.error("daily がタイムアウトしました（%d 秒）", DAILY_TIMEOUT_SECONDS)
        return None
    except OSError as exc:
        logger.error("daily を起動できませんでした: type=%s", type(exc).__name__)
        return None
    return completed.returncode


def main(
    cfg=None,
    *,
    now_fn: Callable[[], datetime] = now_jst,
    sleep: Callable[[float], None] = time_module.sleep,
    runner: Callable[[], Optional[int]] = run_daily_subprocess,
    max_loops: Optional[int] = None,
) -> int:
    configure_logging()
    if cfg is None:
        from app.config import settings as cfg

    notify_time = parse_notify_time(cfg.notify_time)
    if notify_time is None:
        logger.error("NOTIFY_TIME が不正です（HH:MM, 00:00〜23:59 で指定してください）")
        return 2

    now = now_fn()
    handled = initial_handled_date(now, notify_time)
    next_day = now.date() + timedelta(days=1) if handled else now.date()
    logger.info(
        "scheduler を開始しました: 実行時刻 %s JST, 次回実行予定 %s %s",
        notify_time.strftime("%H:%M"), next_day.isoformat(), notify_time.strftime("%H:%M"),
    )

    loops = 0
    while max_loops is None or loops < max_loops:
        loops += 1
        try:
            now = now_fn()
            action = decide(now, notify_time, handled, LATE_TOLERANCE)
            if action == "run":
                handled = now.date()
                code = runner()
                if code == 0:
                    logger.info("daily が完了しました")
                elif code is not None:
                    logger.error("daily が失敗しました: exit=%d", code)
            elif action == "skip":
                handled = now.date()
                logger.warning("実行時刻を大きく過ぎたため、今日は送信しません")
        except Exception as exc:  # 1 回の反復の失敗でプロセスを落とさない（ADR-0007 決定 7）
            logger.error("scheduler の処理で想定外のエラー: type=%s", type(exc).__name__)
        sleep(POLL_INTERVAL_SECONDS)
    return 0


def _exit_on_sigterm(signum, frame):
    raise SystemExit(0)


if __name__ == "__main__":
    # コンテナでは PID 1 になり、ハンドラがないと SIGTERM が無視されて docker stop が 10 秒待たされる
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    sys.exit(main())
