import os
import subprocess
import tempfile
from urllib.parse import urlparse

from app.config import settings
from app.jst import now_jst


def _db_params() -> dict:
    parsed = urlparse(settings.database_url)
    return {
        "host": parsed.hostname or "db",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "household_user",
        "password": parsed.password or "",
        "dbname": (parsed.path or "/household_db").lstrip("/"),
    }


def create_dump_to_tempfile() -> tuple[str, str]:
    """pg_dump を実行して一時ファイルに出力し (filepath, filename) を返す。"""
    db = _db_params()
    now = now_jst().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{now}.sql"

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".sql", prefix="household_backup_")
    os.close(tmp_fd)

    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"]

    cmd = [
        "pg_dump",
        "-h", db["host"],
        "-p", db["port"],
        "-U", db["user"],
        "-d", db["dbname"],
        "--clean",
        "--if-exists",
        "-f", tmp_path,
    ]

    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        os.unlink(tmp_path)
        raise RuntimeError(result.stderr.strip() or "pg_dump が失敗しました")

    return tmp_path, filename


def restore_from_file(filepath: str) -> None:
    """psql でダンプファイルを復元する。"""
    db = _db_params()
    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"]

    cmd = [
        "psql",
        "-h", db["host"],
        "-p", db["port"],
        "-U", db["user"],
        "-d", db["dbname"],
        "--single-transaction",
        "-f", filepath,
    ]

    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "psql の復元が失敗しました")
