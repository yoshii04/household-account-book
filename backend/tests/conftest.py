import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app


def pytest_configure(config):
    """TEST_DATABASE_URL が開発・本番用 DB を指していないことを確認する。

    db_engine フィクスチャは、指定された DB に対して drop_all を実行する。
    誤って実データのある DB を指定すると全テーブルが消えるため、
    テストを1件も実行する前に拒否する。
    """
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        return
    target = make_url(test_url)
    app_db = make_url(settings.database_url)
    if (target.host, target.port, target.database) == (app_db.host, app_db.port, app_db.database):
        raise pytest.UsageError(
            "TEST_DATABASE_URL がアプリの DATABASE_URL と同じ DB を指しています。"
            "テストはテーブルを作成・削除するため、専用の DB を指定してください。"
        )
    if "test" not in (target.database or ""):
        raise pytest.UsageError(
            f"TEST_DATABASE_URL の DB 名 '{target.database}' に 'test' が含まれていません。"
            "テストはテーブルを作成・削除するため、専用のテスト DB を指定してください。"
        )

# ── フェーズ1〜3 向け（既存）──────────────────────────────────────────────────

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ── フェーズ4 統合テスト向け ──────────────────────────────────────────────────
# SQLite in-memory DB を使い、テストごとにクリーンな状態を保証する。
#
# 注意: `sqlite://` はコネクションごとに別の DB インスタンスになる。
# そのため単一のコネクションを保持し、セッションをそのコネクションにバインドする。

@pytest.fixture
def db_engine():
    """テスト用 DB エンジン。全テーブルを作成した永続コネクションを返す。

    既定は SQLite in-memory。環境変数 TEST_DATABASE_URL に PostgreSQL の URL を
    指定すると、その DB に対して同じテストを実行する（CI で使用）。
    TEST_DATABASE_URL の DB は各テストでテーブルを作成・削除するため、
    本番・開発用 DB を指定してはならない。"""
    # 全モデルを Base.metadata に登録するため明示的にインポートする
    import app.models.account_type  # noqa: F401
    import app.models.account       # noqa: F401
    import app.models.category      # noqa: F401
    import app.models.group         # noqa: F401
    import app.models.pattern_group # noqa: F401
    import app.models.pattern       # noqa: F401
    import app.models.transaction   # noqa: F401

    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if test_database_url:
        engine = create_engine(test_database_url)
        conn = engine.connect()
        # 前回の異常終了で残ったテーブルがあっても、毎回クリーンな状態から始める
        Base.metadata.drop_all(bind=conn)
        conn.commit()
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        # コネクションを保持し続けることで in-memory DB が消えないようにする
        conn = engine.connect()
        # SQLite は既定で FK 制約を強制しないため、ondelete="SET NULL" 等を
        # 本番（PostgreSQL）と同様にテストで検証できるよう明示的に有効化する
        conn.execute(text("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(bind=conn)
    # スキーマ作成をコミットして、コネクション側の外側トランザクションを閉じる。
    # これを怠ると、セッションの rollback()（IntegrityError 処理など）が
    # テーブル作成や先にコミット済みのデータごと巻き戻してしまう
    # （PostgreSQL は DDL もトランザクション内のため、テーブルが消える）。
    conn.commit()
    yield conn
    # 未コミットのトランザクションを破棄してから、テーブルを削除する
    conn.rollback()
    Base.metadata.drop_all(bind=conn)
    conn.commit()
    conn.close()
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """テスト用 DB セッション。同一コネクションにバインドして
    api_client から同じ in-memory DB を参照できるようにする。"""
    session = Session(db_engine)
    yield session
    session.close()


@pytest.fixture
def api_client(db_session):
    """get_db を テスト用セッションで上書きした TestClient。"""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
