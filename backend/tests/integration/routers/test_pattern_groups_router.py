"""
パターングループ API の結合テスト。

IntegrityError → db.rollback() の経路を通るテストを含む。
この経路は、テスト用 DB 側でスキーマ作成（DDL）がコミットされていないと、
PostgreSQL ではロールバックでテーブルごと消える（SQLite では DDL が
トランザクション外のため気づけない）。
"""


class TestCreatePatternGroupDuplicateName:
    def test_duplicate_name_returns_400_and_db_remains_usable(self, api_client):
        first = api_client.post("/api/v1/pattern-groups", json={"name": "固定費"})
        assert first.status_code == 201

        duplicate = api_client.post("/api/v1/pattern-groups", json={"name": "固定費"})
        assert duplicate.status_code == 400

        # ロールバック後もテーブルが存在し、最初のグループが取得できること
        listed = api_client.get("/api/v1/pattern-groups")
        assert listed.status_code == 200
        assert [g["name"] for g in listed.json()] == ["固定費"]
