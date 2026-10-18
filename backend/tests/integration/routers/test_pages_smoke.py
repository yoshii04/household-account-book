"""
HTML ページ・ファイル出力ルートのスモークテスト。

OpenAPI スキーマから `/api` 以外の GET ルートを列挙し、データがある状態で
すべて HTTP 200 を返すことを確認する。

目的は、テンプレートのレンダリング時にだけ発生するエラー（例: Starlette 1.x で
廃止された `TemplateResponse(name, {"request": ...})` の旧シグネチャ）を、
個別のテストが無いルートも含めて CI で検出すること。
新しいページルートは自動的に対象になる。パスパラメータを持つルートを追加した場合は、
`_path_params` に値を追加すること（追加しないとテストが失敗する）。
"""
import pytest

from app.jst import today_jst
from app.main import app
from app.models.account import Account
from app.models.category import Category
from app.models.group import Group
from app.models.pattern import TransactionPattern
from app.models.transaction import Transaction


def _page_paths() -> list[str]:
    paths = app.openapi()["paths"]
    return sorted(p for p, ops in paths.items() if "get" in ops and not p.startswith("/api"))


def _required_query_names(path: str) -> list[str]:
    parameters = app.openapi()["paths"][path]["get"].get("parameters", [])
    return [p["name"] for p in parameters if p["in"] == "query" and p.get("required")]


@pytest.fixture
def seeded(db_session):
    """全ページが描画対象のデータを持つよう、最小限の取引・パターンを登録する。"""
    parent = Category(code="A10_食費", name="A10_食費", full_path="A10_食費")
    db_session.add(parent)
    db_session.flush()
    child = Category(code="食料品", name="食料品", full_path="A10_食費/食料品", parent_id=parent.id)
    account = Account(code="10_財布", name="財布", account_type="cash")
    group = Group(code="10_生活費", name="生活費")
    db_session.add_all([child, account, group])
    db_session.flush()

    today = today_jst()
    tx = Transaction(
        date=today, category_id=child.id, account_id=account.id, group_id=group.id,
        expense_amount=1200, memo="スモークテスト",
    )
    pattern = TransactionPattern(
        name="毎月の支払い", frequency="monthly", category_id=child.id, account_id=account.id,
        payment_day_of_month=today.day,
    )
    db_session.add_all([tx, pattern])
    db_session.commit()
    return {"tx": tx}


def _path_params(seeded) -> dict:
    return {"tx_id": seeded["tx"].id}


def _query_params(path: str) -> dict:
    """必須のクエリパラメータに、シード済みデータの年月を渡す。"""
    today = today_jst()
    known = {"year": today.year, "month": today.month, "start_year": today.year, "end_year": today.year}
    return {name: known[name] for name in _required_query_names(path)}


def test_page_routes_are_discovered():
    # 列挙が空になると下の parametrize が何も検証しなくなるため、件数を確認する
    assert len(_page_paths()) >= 20


@pytest.mark.integration
@pytest.mark.parametrize("path", _page_paths())
def test_page_route_returns_200(api_client, seeded, path):
    url = path.format(**_path_params(seeded))
    response = api_client.get(url, params=_query_params(path))
    assert response.status_code == 200, f"{url} -> {response.status_code}"
