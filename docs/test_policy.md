# テストコード作成方針

## 1. 目的と基本方針

### 1.1 目的

テストコードを整備することで、以下を実現する。

- 機能の正常動作を継続的に保証する
- リファクタリングや機能追加時のリグレッション（デグレード）を早期に検出する
- コードの設計品質を向上させる（テストしにくいコードは設計上の問題を示すことが多い）
- 仕様をコードとして表現し、ドキュメントとして機能させる

### 1.2 基本方針

| 方針 | 内容 |
|------|------|
| テストファースト | 新機能追加・バグ修正時はテストを先に（または同時に）書く |
| 自動化 | テストはすべて自動実行可能にし、手動確認に依存しない |
| 独立性 | テストは順序や他テストの実行結果に依存しない |
| 冪等性 | 何度実行しても同じ結果になる |
| 高速性 | 単体テストは 1 件あたり数十 ms 以内を目安にする |
| 可読性 | テストコードは仕様のドキュメントとして読める水準を保つ |

---

## 2. テストピラミッド

```
         ┌─────────┐
         │  E2E    │  ← 少数・高コスト・重要なユーザーフローのみ
         ├─────────┤
         │ 結合テスト │  ← API・DB・サービス間の連携を検証
         ├─────────┤
         │ 単体テスト │  ← 大多数・低コスト・ビジネスロジックを中心に
         └─────────┘
```

テストの大部分を単体テストで構成し、結合テスト・E2E テストに向かうほど件数を絞る。
コストの高い E2E テストは「ユーザーにとって重要なシナリオ」に限定する。

---

## 3. テストの種類

### 3.1 単体テスト（Unit Test）

**対象**: 単一の関数・クラス・メソッド

**方針**
- 外部依存（DB・外部 API・ファイル IO）はモック/スタブで置き換える
- 1 テストケース = 1 つの振る舞いを検証する
- 境界値・異常系（None、空文字、範囲外の値など）を網羅する

**主な対象レイヤー**
- `services/` : ビジネスロジック
- `crud/` : DB 操作（単体テストでは DB セッションをモックして検証）
- `utils/` : 日付計算・バリデーション等のユーティリティ
- `schemas/` : Pydantic バリデーションルール

### 3.2 結合テスト（Integration Test）

**対象**: 複数モジュールを組み合わせた動作・API エンドポイント

**方針**
- テスト専用 DB（または `testcontainers` 等）を使い、実際の SQL を発行する
- FastAPI の `TestClient` を使用して HTTP レベルで検証する
- 各テストは DB を初期化（トランザクションロールバック or テーブル truncate）し、独立性を保つ
- 認証・認可が必要なエンドポイントでは、テスト用トークン/セッションを用意する

**主な対象**
- `routers/` : API エンドポイント（正常系・エラー系・バリデーション）
- `crud/` + DB : CRUD 操作の結果が DB に正しく反映されるか
- `services/` + `crud/` : サービスとリポジトリの連携

### 3.3 E2E テスト（End-to-End Test）

**対象**: ブラウザ操作を含む、ユーザー視点のシナリオ全体

**方針**
- コアとなるユーザーフロー（例: 取引登録 → 一覧確認 → 削除）のみを対象とする
- テスト専用環境（専用 DB・専用バックエンドコンテナ）を用意する
- フレームワークは Playwright（Python）を推奨する

**主な対象シナリオ例**
- 取引の新規作成・編集・削除のフロー
- インポートファイルをアップロードして取引が反映されるフロー
- レポート画面でのフィルター・集計表示

---

## 4. 技術スタック

| 種別 | ツール | 用途 |
|------|--------|------|
| テストフレームワーク | pytest | テスト実行・アサーション |
| HTTP テストクライアント | FastAPI `TestClient` (httpx) | API 結合テスト |
| モック | `pytest-mock` / `unittest.mock` | 外部依存の置き換え |
| テスト DB | PostgreSQL（Docker）| 結合テスト用 DB |
| E2E | Playwright (pytest-playwright) | ブラウザ操作テスト |
| カバレッジ | pytest-cov | カバレッジ計測 |
| CI | GitHub Actions | 自動テスト実行 |

---

## 5. pytest 設定

カスタムマーカーを `pyproject.toml` または `pytest.ini` に登録する。
未登録のままでは `PytestUnknownMarkWarning` が発生し、`--strict-markers` 使用時はエラーになる。

```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: 結合テスト（実 DB を使用）",
    "e2e: E2E テスト（Playwright 使用）",
]
```

---

## 6. ディレクトリ構成

```
backend/
└── tests/
    ├── conftest.py              # 共通フィクスチャ（DBセッション、TestClientなど）
    ├── unit/
    │   ├── services/
    │   │   └── test_report_service.py
    │   ├── crud/
    │   │   └── test_transaction_crud.py
    │   ├── utils/
    │   │   └── test_date_utils.py
    │   └── schemas/
    │       └── test_transaction_schema.py
    ├── integration/
    │   ├── routers/
    │   │   ├── test_transactions_router.py
    │   │   ├── test_accounts_router.py
    │   │   └── test_import_router.py
    │   └── services/
    │       └── test_import_service.py
    └── e2e/
        └── test_transaction_flow.py
```

---

## 7. 命名規則

### 7.1 ファイル名

`test_` プレフィックスを付ける。テスト対象のモジュール名に対応させる。

```
# テスト対象: app/services/report_service.py
# テストファイル: tests/unit/services/test_report_service.py
```

### 7.2 テスト関数名

`test_` プレフィックスを付け、**対象・条件・期待結果**の構造で命名する。

```
# パターン: test_<対象>_<条件>_<期待結果>

def test_get_monthly_report_when_no_transactions_returns_empty():
def test_create_transaction_with_invalid_amount_raises_validation_error():
def test_import_file_with_duplicate_hash_allows_reimport():
```

### 7.3 フィクスチャ名

スコープを名前から推測できるようにする。

```python
# セッションスコープ（DB接続など）
@pytest.fixture(scope="session")
def db_engine(): ...

# 関数スコープ（各テストで初期化）
@pytest.fixture
def db_session(): ...

# テストデータ
@pytest.fixture
def sample_transaction(): ...
```

---

## 8. テストコードの構造（AAA パターン）

全てのテストは **Arrange（準備）→ Act（実行）→ Assert（検証）** の順で記述する。

```python
def test_calculate_monthly_expense_excludes_transfer():
    # Arrange
    transactions = [
        Transaction(expense_amount=1000, is_transfer=False),
        Transaction(expense_amount=5000, is_transfer=True),   # 資金移動は除外
    ]

    # Act
    result = calculate_monthly_expense(transactions)

    # Assert
    assert result == 1000
```

**ガイドライン**
- 各セクションを空行で区切り、必要に応じてコメントを付ける
- 1 テスト関数で検証するアサーションは原則 1 つの振る舞いに絞る
- `assert` を多数並べる場合は、テストケースの分割を検討する

---

## 9. テストデータの管理

### 9.1 フィクスチャによるデータ準備

テストデータは `conftest.py` または各テストファイル内のフィクスチャで管理する。
ハードコードは最小限に留め、フィクスチャで再利用可能にする。

```python
# conftest.py
@pytest.fixture
def sample_category(db_session):
    category = Category(full_path="食費/外食", parent_id=None)  # 説明用に parent_id は省略
    db_session.add(category)
    db_session.flush()
    return category
```

### 9.2 テスト DB の初期化

- 結合テストは各テスト関数の前後で DB をクリーンな状態に戻す
- 推奨: トランザクションをロールバックする方式（高速）

```python
@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

### 9.3 本番データ・個人情報の使用禁止

テストデータには本番データや個人情報を使用しない。
匿名化したダミーデータまたはランダム生成データを使用する。

---

## 10. モック・スタブの使用方針

### 10.1 モックを使うべき場合

- 外部 API・外部サービスへの通信
- ファイル IO（大容量ファイルの読み書き等）
- メール送信・通知処理
- 現在日時（`today_jst()`、`now_jst()` など）

### 10.2 モックを使わない（実物を使う）べき場合

- DB 操作（結合テストでは実 DB を使う）
- 自プロジェクト内のモジュール間連携（単体テスト以外）

### 10.3 使用例

```python
from unittest.mock import patch

def test_get_due_patterns_returns_only_this_month(db_session):
    with patch("app.services.pattern_service.today_jst") as mock_today:
        mock_today.return_value = date(2026, 6, 1)

        result = get_due_patterns(db_session)

        assert all(p.payment_day_of_month is not None for p in result)
```

---

## 11. テストカバレッジ

### 11.1 目標値

| レイヤー | 目標カバレッジ |
|----------|--------------|
| `services/` | 80% 以上 |
| `crud/` | 70% 以上 |
| `utils/` | 90% 以上 |
| `routers/` | 70% 以上 |
| `schemas/` | 80% 以上 |
| 全体 | 70% 以上 |

### 11.2 カバレッジの計測

```bash
pytest --cov=app --cov-report=html tests/
```

### 11.3 カバレッジに関する注意

- カバレッジ達成が目的ではなく、**品質の担保**が目的であることを常に意識する
- カバレッジが高くても意味のないアサーション（`assert True` 等）は不可
- 意図的にテストしない箇所（`# pragma: no cover`）は理由をコメントで明示する

---

## 12. テストコードの品質基準

### 12.1 DO（やること）

- テスト名から「何をテストしているか」が一目で分かるようにする
- 正常系と異常系（エラーケース・境界値）の両方をテストする
- テスト同士は完全に独立させる（順序依存・共有状態を持たない）
- フィクスチャを活用して重複コードを減らす

### 12.2 DON'T（やらないこと）

- テスト対象の実装詳細（プライベートメソッド、内部変数）に依存する
- `time.sleep()` でタイミングを合わせる
- テスト内でテスト対象の実装をコピー・再実装する
- 1 つのテスト関数で複数の独立した振る舞いを同時に検証する
- テストのために本番コードに不必要な public API を追加する

---

## 13. CI パイプラインへの組み込み

### 13.1 実行タイミング

| タイミング | 実行するテスト |
|------------|--------------|
| プルリクエスト作成・更新時 | 単体テスト + 結合テスト |
| main ブランチへのマージ時 | 単体テスト + 結合テスト + E2E テスト |

### 13.2 CI での失敗時の対応

- テストが 1 件でも失敗した場合、CI はエラー終了とし、マージをブロックする
- フレイキーテスト（不安定なテスト）は即座に修正することを原則とする。修正が遅れる場合は `pytest.mark.skip(reason="...")` で理由を明記してスキップし、Issue を起票して追跡する

### 13.3 実行コマンド

```bash
# 単体テストのみ
pytest tests/unit/ -v

# 結合テスト
pytest tests/integration/ -v

# 全テスト（カバレッジ付き）
pytest tests/ --cov=app --cov-report=term-missing -v
```

---

## 14. テストコードのレビュー基準

プルリクエストのレビュー時は以下の観点でテストコードを確認する。

| 観点 | 確認内容 |
|------|--------|
| 網羅性 | 正常系・異常系・境界値が適切にカバーされているか |
| 独立性 | テスト間に依存関係がないか |
| 可読性 | テスト名と内容が一致しており、意図が明確か |
| 保守性 | 重複が少なく、フィクスチャを適切に活用しているか |
| 速度 | 不必要に遅いテストがないか（DB アクセスの最小化など） |
| 信頼性 | アサーションが意味のある内容か（常に成功するテストになっていないか） |

---

## 15. 本プロジェクト固有の注意事項

### 15.1 JST タイムゾーン

`today_jst()` / `now_jst()` のテストでは必ずモックで固定日時を指定し、
テスト実行日時に依存しないようにする。

### 15.2 インポートサービス

UTF-16LE ファイルのテストには、`io.BytesIO` で疑似ファイルを生成する。

```python
content = "日付\t金額\n2026-01-01\t1000\n".encode("utf-16")
fake_file = io.BytesIO(content)
```

### 15.3 資金移動の除外

月次集計テストでは `is_transfer=True` の取引が集計から除外されることを
必ず検証するケースを含める。

### 15.4 DB 操作のカテゴリ検索

`joinedload` との重複 JOIN を避けるため、カテゴリ絞り込みはサブクエリを使用する実装になっている。
結合テストでは JOIN ではなくサブクエリが使われていることを前提とした SQL ログ検証を行わない
（実装詳細への依存を避けるため）。

### 15.5 Alembic マイグレーション

結合テストの `db_engine` フィクスチャでは `alembic upgrade head` を適用したスキーマを使用する。
マイグレーションファイル単独のテストは必須ではないが、CI で `upgrade` / `downgrade` の往復が
エラーなく完了することを確認するジョブを設けることを推奨する。

---

*このドキュメントはプロジェクトの成長に合わせて随時更新する。*
