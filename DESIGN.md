# 家計簿アプリ 設計書

> 作成日: 2026-04-11  
> 最終更新: 2026-04-22  
> ブランチ: feature/update-design-doc

---

## 目次

1. [システム全体構成](#1-システム全体構成)
2. [インフラ・起動設定](#2-インフラ起動設定)
3. [バックエンド層](#3-バックエンド層)
   - 3.1 [エントリーポイント](#31-エントリーポイント--appmainpy)
   - 3.2 [設定管理](#32-設定管理--appconfigpy)
   - 3.3 [データベース接続](#33-データベース接続--appdatabasepy)
4. [データモデル層（models/）](#4-データモデル層models)
5. [スキーマ層（schemas/）](#5-スキーマ層schemas)
6. [CRUD層（crud/）](#6-crud層crud)
7. [サービス層（services/）](#7-サービス層services)
8. [ルーター層（routers/）](#8-ルーター層routers)
9. [テンプレート層（templates/）](#9-テンプレート層templates)
10. [データベースマイグレーション（alembic/）](#10-データベースマイグレーションalembic)
11. [フロントエンド静的ファイル](#11-フロントエンド静的ファイル)
12. [テスト・CI](#12-テストci)
13. [データフロー図](#13-データフロー図)
14. [API エンドポイント一覧](#14-api-エンドポイント一覧)
15. [環境変数・設定値](#15-環境変数設定値)

---

## 1. システム全体構成

```
ブラウザ (Alpine.js / Chart.js / Jinja2)
    │ HTTP :8080
    ▼
[Docker: backend]
    FastAPI (Uvicorn)
    │
    ├── routers/      ← HTTP リクエストの受け口
    ├── services/     ← ビジネスロジック
    ├── crud/         ← DB 操作の抽象化
    ├── models/       ← SQLAlchemy ORM
    ├── schemas/      ← Pydantic バリデーション
    └── templates/    ← Jinja2 HTML レンダリング
    │
    │ PostgreSQL :5432 (ホスト側 :5439)
    ▼
[Docker: db]
    PostgreSQL 16
    （categories / accounts / account_types / groups / transactions / import_logs）
```

**技術スタック**

| 役割 | 技術・バージョン |
|------|----------------|
| Web フレームワーク | FastAPI 0.143.0 / Starlette 1.7.0 |
| ASGI サーバー | Uvicorn 0.32.1 |
| ORM | SQLAlchemy 2.0.36 |
| マイグレーション | Alembic 1.14.0 |
| DB ドライバー | psycopg2-binary 2.9.10 |
| バリデーション | Pydantic 2.10.3 / pydantic-settings 2.6.1 |
| テンプレートエンジン | Jinja2 3.1.6 |
| Excel 出力 | openpyxl 3.1.5 |
| JS ライブラリ | Alpine.js (CDN) / Chart.js (CDN) |
| DB | PostgreSQL 16 |
| コンテナ | Docker Compose |
| テスト | pytest 9.1.1 / pytest-cov 7.1.0 / httpx 0.28.1 |
| CI | GitHub Actions |

---

## 2. インフラ・起動設定

### `docker-compose.yml`

**役割:** 2つのサービス（`db`・`backend`）を定義し、開発環境をワンコマンドで起動する。

| サービス | イメージ / ビルド | ポート | 役割 |
|----------|-----------------|--------|------|
| `db` | postgres:16-alpine | 127.0.0.1:5439:5432 | PostgreSQL データベース |
| `backend` | `./backend/Dockerfile` | 127.0.0.1:8080:8000 | FastAPI アプリ本体 |

**重要な設定:**
- `backend` は `db` のヘルスチェック通過後に起動（`depends_on: condition: service_healthy`）
- `./backend` をコンテナ `/app` にボリュームマウント → コード変更が即時反映（`--reload`）
- `./frontend/static` → `/app/static` にマウントして静的ファイルを共有
- `./data` → `/data` にマウントしてインポートファイルを配置可能

### `backend/Dockerfile`

**役割:** Python 3.12 ベースの FastAPI 実行環境をビルドする。`requirements.txt` に従い依存パッケージをインストールし、Uvicorn でアプリを起動する。

### `.env.example` / `.env`

**役割:** 環境変数のテンプレート。`.env` は `.gitignore` 対象。

```
DB_PASSWORD=（PostgreSQL パスワード）
SECRET_KEY=（セッション等の秘密鍵）
DEBUG=true
```

### `db/init.sql`

**役割:** PostgreSQL コンテナ初回起動時に実行される初期化 SQL。ユーザー・DB はコンテナの環境変数で作成されるため、追加の初期設定を記述する場所。

---

## 3. バックエンド層

### 3.1 エントリーポイント — `app/main.py`

**役割:** FastAPI アプリケーションの起動点。静的ファイルのマウント、テンプレートエンジンの設定、各ルーターの登録を行う。

```
app = FastAPI(title="家計簿アプリ", version="1.0.0")
  ├── /static            ← 静的ファイル（CSS等）
  ├── /api/v1/import     ← import_router
  ├── /api/v1/categories ← categories router
  ├── /api/v1/accounts   ← accounts router
  ├── /api/v1/groups     ← groups router
  ├── /api/v1/transactions ← transactions router
  ├── /api/v1/reports    ← reports router
  └── /（HTMLページ）    ← pages router
```

**依存関係:** 全ルーターモジュールをインポートして `include_router` で登録する。

---

### 3.2 設定管理 — `app/config.py`

**役割:** pydantic-settings を使って環境変数を型安全に読み込む。`.env` ファイルを自動で読み込む。

| 設定項目 | 型 | デフォルト値 | 説明 |
|---------|-----|------------|------|
| `database_url` | str | `postgresql://household_user:password@db:5432/household_db` | DB 接続 URL |
| `secret_key` | str | `dev-secret-key` | セキュリティキー |
| `debug` | bool | `False` | デバッグモード |

**利用方法:** `from app.config import settings` でシングルトンとしてアクセスする。

---

### 3.3 データベース接続 — `app/database.py`

**役割:** SQLAlchemy エンジン・セッション・ORM ベースクラスを生成する。FastAPI の依存性注入で使用するセッション取得関数 `get_db()` を提供する。

| エクスポート | 型 | 用途 |
|------------|-----|------|
| `engine` | Engine | DB 接続エンジン |
| `SessionLocal` | sessionmaker | セッションファクトリ |
| `Base` | DeclarativeBase | ORM モデルの基底クラス |
| `get_db()` | Generator | FastAPI `Depends()` で DB セッションを注入 |

**セッションライフサイクル:** リクエスト開始時に `SessionLocal()` を生成し、レスポンス後（`finally`）に `db.close()` を呼び出す。

---

## 4. データモデル層（models/）

SQLAlchemy 2.0 の `Mapped` / `mapped_column` 形式で定義されたORMモデル群。すべて `app/database.py` の `Base` を継承する。

---

### `models/category.py` — カテゴリモデル

**テーブル名:** `categories`  
**役割:** 支出・収入の費目を階層構造（親子）で管理する。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | 主キー |
| `code` | String(50) | NOT NULL | カテゴリコード（例: `A30_通信費`） |
| `name` | String(100) | NOT NULL | 表示名 |
| `parent_id` | Integer | FK→categories.id, nullable | 親カテゴリ ID（NULL = 親カテゴリ） |
| `full_path` | String(200) | NOT NULL, UNIQUE | 完全パス（例: `A30_通信費/インターネット`） |
| `is_transfer` | Boolean | NOT NULL, default=False | 資金移動フラグ（集計除外） |
| `sort_order` | Integer | NOT NULL, default=0 | 表示順 |
| `created_at` | DateTime(tz) | server_default=now() | 作成日時 |
| `updated_at` | DateTime(tz) | server_default=now(), onupdate=now() | 更新日時 |

**リレーション:**
- `parent` → 自己参照（親カテゴリ）
- `children` → 自己参照（子カテゴリ一覧）、cascade=all, delete-orphan
- `transactions` → Transaction 一覧

**設計ポイント:**
- `full_path` の UNIQUE 制約によりカテゴリの重複登録を防止
- `is_transfer = True` は「資金移動」カテゴリ。月次集計・レポートから除外される

---

### `models/account.py` — 口座・決済手段モデル

**テーブル名:** `accounts`  
**役割:** 現金・銀行口座・クレジットカード・電子マネー等の決済手段を管理する。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | 主キー |
| `code` | String(50) | NOT NULL, UNIQUE | アカウントコード（例: `10_財布`） |
| `name` | String(100) | NOT NULL | 表示名 |
| `account_type` | String(20) | NOT NULL, default="other" | 種別コード（account_types.code を参照） |
| `sort_order` | Integer | NOT NULL, default=0 | 表示順 |
| `is_active` | Boolean | NOT NULL, default=True | 有効フラグ |
| `start_date` | Date | nullable | 残高計算の開始日 |
| `initial_balance` | Integer | nullable, default=0 | 開始日時点の初期残高（円） |
| `adjustment_amount` | Integer | nullable, default=0 | 残高調整額（円） |
| `created_at` | DateTime(tz) | server_default=now() | 作成日時 |

**リレーション:**
- `transactions` → Transaction 一覧

**設計ポイント:**
- `account_type` はインポート時にコードのプレフィックスから自動推定される
- `start_date` + `initial_balance` + `adjustment_amount` を使って口座残高を計算する（口座残高レポート）

---

### `models/account_type.py` — 口座種別マスターモデル

**テーブル名:** `account_types`  
**役割:** 口座・決済手段の種別マスターデータを管理する。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | 主キー |
| `code` | String(50) | NOT NULL, UNIQUE | 種別コード（例: `cash`, `bank`, `card`） |
| `label` | String(100) | NOT NULL | 表示ラベル（例: `現金`, `銀行口座`） |
| `sort_order` | Integer | NOT NULL, default=0 | 表示順 |

**設計ポイント:**
- `Account.account_type` はこのテーブルの `code` を文字列参照する（外部キー制約なし）
- マイグレーション 0006 で追加

---

### `models/group.py` — グループモデル

**テーブル名:** `groups`  
**役割:** 人別・目的別のグループ分けを管理する（例: `20_太郎`、`10_必須(通常)`）。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | 主キー |
| `code` | String(50) | NOT NULL, UNIQUE | グループコード |
| `name` | String(100) | NOT NULL | 表示名（コードからプレフィックスを除去） |
| `sort_order` | Integer | NOT NULL, default=0 | 表示順 |
| `created_at` | DateTime(tz) | server_default=now() | 作成日時 |

**リレーション:**
- `transactions` → Transaction 一覧

---

### `models/transaction.py` — 取引明細・インポートログモデル

**テーブル名:** `transactions` / `import_logs`  
**役割:** 家計の収支取引を格納する中核テーブル。同ファイルにインポート履歴も定義。

#### Transaction テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | 主キー |
| `date` | Date | NOT NULL, indexed | 取引日 |
| `category_id` | Integer | FK→categories.id, NOT NULL, indexed | カテゴリ |
| `account_id` | Integer | FK→accounts.id, NOT NULL | 口座・決済手段 |
| `income_amount` | Integer | NOT NULL, default=0 | 入金額（円） |
| `expense_amount` | Integer | NOT NULL, default=0 | 出金額（円） |
| `memo` | String(500) | nullable | メモ |
| `group_id` | Integer | FK→groups.id, nullable | グループ |
| `is_transfer` | Boolean | NOT NULL, default=False, indexed | 資金移動フラグ |
| `transfer_detail` | String(200) | nullable | 資金移動詳細（元のカテゴリパス） |
| `import_hash` | String(64) | nullable | 重複インポート検出用 SHA-256（UNIQUE 制約なし） |
| `created_at` | DateTime(tz) | server_default=now() | 作成日時 |
| `updated_at` | DateTime(tz) | server_default=now(), onupdate=now() | 更新日時 |

**設計ポイント:**
- `income_amount` と `expense_amount` はどちらか一方のみが非ゼロ（Actual.TXT の列構造に対応）
- `import_hash` の UNIQUE 制約はマイグレーション 0002 で削除済み → 同一ファイルの複数回インポートが可能

#### ImportLog テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | 主キー |
| `filename` | String(255) | NOT NULL | インポートしたファイル名 |
| `imported_at` | DateTime(tz) | server_default=now() | インポート日時 |
| `total_rows` | Integer | NOT NULL, default=0 | 総行数 |
| `imported_rows` | Integer | NOT NULL, default=0 | インポート成功行数 |
| `skipped_rows` | Integer | NOT NULL, default=0 | スキップ行数 |
| `error_rows` | Integer | NOT NULL, default=0 | エラー行数 |
| `status` | String(20) | NOT NULL, default="success" | 結果（success/partial/error） |
| `error_detail` | Text | nullable | エラー詳細メッセージ |

---

## 5. スキーマ層（schemas/）

Pydantic v2 によるリクエスト/レスポンスの型定義と入力バリデーション。`model_config = {"from_attributes": True}` で ORM オブジェクトからの変換を有効化。

---

### `schemas/category.py`

| クラス | 用途 |
|--------|------|
| `CategoryBase` | code / name / full_path / is_transfer / sort_order の共通フィールド |
| `CategoryCreate` | 作成リクエスト（parent_id を追加） |
| `CategoryOut` | レスポンス（id / parent_id を追加） |
| `CategoryWithChildren` | 階層構造レスポンス（children: List[CategoryWithChildren] を再帰的に保持） |

---

### `schemas/account.py`

| クラス | 用途 |
|--------|------|
| `AccountTypeOut` | 口座種別レスポンス（id / code / label / sort_order） |
| `AccountTypeCreate` | 口座種別作成リクエスト（code / label / sort_order） |
| `AccountOut` | 口座情報レスポンス（id / code / name / account_type / sort_order / is_active / start_date / initial_balance / adjustment_amount） |
| `AccountUpdate` | 口座更新リクエスト（account_type / start_date / initial_balance / adjustment_amount、全フィールド Optional） |

---

### `schemas/group.py`

| クラス | 用途 |
|--------|------|
| `GroupOut` | グループ情報レスポンス（id / code / name / sort_order） |

---

### `schemas/transaction.py`

| クラス | 用途 |
|--------|------|
| `TransactionBase` | 取引の共通フィールド（date / category_id / account_id / income_amount / expense_amount / memo / group_id / is_transfer / transfer_detail） |
| `TransactionCreate` | 作成リクエスト（TransactionBase をそのまま継承） |
| `TransactionUpdate` | 更新リクエスト（全フィールド Optional、部分更新対応） |
| `TransactionOut` | レスポンス（id + 結合フィールド: category_full_path / account_code / group_code） |
| `TransactionListOut` | 一覧レスポンス（items / total / page / per_page） |

---

### `schemas/import_result.py`

| クラス | 用途 |
|--------|------|
| `ImportResult` | インポート実行結果（status / filename / total_rows / imported_rows / skipped_rows / error_rows / new_categories / new_accounts / new_groups / error_detail） |
| `ImportLogOut` | インポート履歴レスポンス（ImportLog テーブルの読み出し用） |

---

## 6. CRUD層（crud/）

SQLAlchemy セッションを受け取り、DB 操作を抽象化する関数群。ビジネスロジックは持たない。

---

### `crud/transaction.py`

**役割:** `transactions` テーブルに対する CRUD 操作を提供する。

#### 内部ヘルパー

| 関数 | 説明 |
|------|------|
| `_with_joins(query)` | category / account / group を `joinedload` で事前ロードするクエリを返す |
| `_to_out_dict(tx)` | Transaction ORM オブジェクトを辞書（TransactionOut互換）に変換する |

#### 公開関数

| 関数 | 説明 |
|------|------|
| `get_transactions(db, year, month, category_id, account_id, group_id, is_transfer, search, page, per_page)` | フィルター・ページングに対応した取引一覧取得。カテゴリ検索はサブクエリで実装（JOIN 二重化防止）。返値: `(list[dict], total)` |
| `get_all_transactions(db, year, month, category_id, account_id, group_id, is_transfer, search)` | Excel 出力用：フィルター条件に合致する全件取得（ページングなし） |
| `get_recent_by_category(db, category_id, limit)` | カテゴリ別直近 N 件取得（is_transfer=False のみ） |
| `search_recent(db, q, limit)` | memo / category_full_path / account_code をキーワード検索（直近 N 件） |
| `create_transaction(db, data)` | 取引を DB に作成し、ORM オブジェクトを返す |
| `update_transaction(db, tx_id, data)` | 指定 ID の取引を部分更新（exclude_unset で未指定フィールドを無視） |
| `delete_transaction(db, tx_id)` | 指定 ID の取引を削除。成功で True、未存在で False |
| `get_transaction(db, tx_id)` | 指定 ID の取引を辞書で返す。未存在で None |

**注意点:** `get_transactions` では `joinedload` と JOIN が競合するため、カテゴリ検索にはサブクエリを使用する（CLAUDE.md 参照）。

---

## 7. サービス層（services/）

ビジネスロジックを担う層。DB 操作は直接 SQLAlchemy を利用する場合もある。

---

### `services/import_service.py`

**役割:** Actual.TXT（UTF-16LE タブ区切り）を解析して DB に格納するインポートサービス。

#### 処理フロー

```
1. UTF-16 デコード（BOM 自動認識、失敗時 UTF-8 フォールバック）
2. ヘッダー行解析（全角スペース等を正規化してフィールド名を特定）
3. 各行をループ処理
   ├── 必須項目チェック（date / category / account）
   ├── 日付パース（%Y/%m/%d）
   ├── 金額パース（カンマ除去→整数変換）
   ├── import_hash 生成（SHA-256）
   ├── カテゴリ upsert（_upsert_category）
   ├── アカウント upsert（_upsert_account）
   ├── グループ upsert（_upsert_group）
   └── Transaction レコード作成
4. ImportLog に結果を記録し DB コミット
5. ImportResult を返す
```

#### 内部ヘルパー

| 関数 | 説明 |
|------|------|
| `_guess_account_type(code)` | コードのプレフィックスから account_type を推定（`10_`→cash, `30_`→bank, `26_`→e-money, `40_`→card） |
| `_make_hash(...)` | 行データ（日付/カテゴリ/アカウント/金額/メモ）から SHA-256 ハッシュを生成 |
| `_upsert_category(db, full_path)` | `full_path` で既存カテゴリを検索し、未存在なら再帰的に親子を作成。`(Category, is_new)` を返す |
| `_extract_display_name(code)` | コードをそのまま表示名として返す |
| `_upsert_account(db, code)` | コードで既存アカウントを検索し、未存在なら作成。`(Account, is_new)` を返す |
| `_upsert_group(db, code)` | コードで既存グループを検索し、未存在なら作成。`(Group, is_new)` を返す |
| `_parse_amount(value)` | 金額文字列（カンマあり可）を整数に変換。空・変換不能は 0 |

#### 主要関数

```python
async def import_actual_txt(db, content: bytes, filename: str) -> ImportResult
```

---

### `services/report_service.py`

**役割:** 各種レポートデータを生成するサービス。

#### 主要関数

| 関数 | 説明 |
|------|------|
| `get_monthly_summary(db, year, month)` | 指定年月の費目別月次集計。子カテゴリを親カテゴリに集約して階層構造で返す |
| `get_comparison(db, year, month)` | 指定年月と前年同月の費目別支出を比較。差額・増減率を付与して返す |
| `get_matrix_report(db, year, month)` | 指定年月のカテゴリ × グループのクロス集計（マトリックスレポート）を返す |
| `get_annual_report(db, start_year, end_year)` | 指定年度範囲の費目別年次集計（収入・支出）を返す |
| `get_yearly_trend(db, end_year, end_month)` | 指定月を終端とした12ヶ月間のカテゴリ別月次推移を返す |
| `get_account_annual_report(db, start_year, end_year)` | 指定年度範囲の口座別年次収支集計を返す |
| `get_account_balance_report(db, as_of_date)` | 指定日時点の口座別残高を計算して返す（初期残高 + 入出金合計 + 調整額） |

**設計ポイント:**
- トランザクションに直接紐づくのは**子カテゴリ**のみ
- 集計クエリで子カテゴリを取得後、親カテゴリ ID を使って DB から親を補完
- `is_transfer=False` 条件で資金移動を除外
- 口座残高 = `initial_balance` + `start_date` 以降の収支合計 + `adjustment_amount`

**`get_monthly_summary` 返値構造:**
```json
{
  "year": 2026, "month": 4,
  "total_income": 300000, "total_expense": 200000,
  "categories": [
    {
      "cat_id": 1, "full_path": "A10_食費", "code": "A10_食費", "name": "A10_食費",
      "total_income": 0, "total_expense": 50000,
      "children": [
        {"cat_id": 10, "full_path": "A10_食費/外食", ...}
      ]
    }
  ]
}
```

---

## 8. ルーター層（routers/）

FastAPI の `APIRouter` を使ったエンドポイント定義。APIルーターとHTMLページルーターに分離。

---

### `routers/pages.py` — HTMLページルーター

**役割:** Jinja2 テンプレートをレンダリングして HTML を返す画面用エンドポイント群。JST 変換フィルター（`jst`）を Jinja2 環境に登録している。

| パス | メソッド | テンプレート | 説明 |
|------|---------|------------|------|
| `/` | GET | `index.html` | ダッシュボード（当月収支 + 直近5件取引） |
| `/transactions` | GET | `transactions/list.html` | 取引一覧（フィルター・ページング） |
| `/transactions/export/excel` | GET | — | 取引一覧を Excel ファイルでダウンロード（openpyxl） |
| `/transactions/new` | GET | `transactions/form.html` | 取引新規入力フォーム |
| `/transactions/{tx_id}/edit` | GET | `transactions/form.html` | 取引編集フォーム |
| `/import` | GET | `import/index.html` | インポート画面（直近20件のログ表示） |
| `/accounts` | GET | `accounts/index.html` | 口座設定画面（種別・開始日・初期残高・調整額） |
| `/reports/monthly` | GET | `reports/monthly.html` | 月次集計レポート |
| `/reports/comparison` | GET | `reports/comparison.html` | 前年同月比レポート |
| `/reports/matrix` | GET | `reports/matrix.html` | カテゴリ × グループ マトリックスレポート |
| `/reports/annual` | GET | `reports/annual.html` | 費目別年次レポート（複数年比較） |
| `/reports/annual-chart` | GET | `reports/annual_chart.html` | 費目別年次レポート（チャート付き） |
| `/reports/yearly-trend` | GET | `reports/yearly_trend.html` | 直近12ヶ月カテゴリ別月次推移 |
| `/reports/yearly-trend-chart` | GET | `reports/yearly_trend_chart.html` | 直近12ヶ月推移（チャート付き、収入/支出 Top5） |
| `/reports/account-annual` | GET | `reports/account_annual.html` | 口座別年次収支レポート |
| `/reports/account-balance` | GET | `reports/account_balance.html` | 指定日時点の口座別残高レポート |

---

### `routers/transactions.py` — 取引 API ルーター

**プレフィックス:** `/api/v1/transactions`

| パス | メソッド | 説明 |
|------|---------|------|
| `` | GET | 取引一覧（フィルター・ページング） |
| `/recent/by-category/{category_id}` | GET | カテゴリ別直近 N 件 |
| `/search` | GET | キーワード検索（直近 N 件） |
| `/{tx_id}` | GET | 取引詳細 |
| `` | POST | 取引作成（201 返却） |
| `/{tx_id}` | PUT | 取引更新 |
| `/{tx_id}` | DELETE | 取引削除（204 返却） |

---

### `routers/categories.py` — カテゴリ API ルーター

**プレフィックス:** `/api/v1/categories`

| パス | メソッド | 説明 |
|------|---------|------|
| `` | GET | 親カテゴリ一覧（children 付き階層構造） |
| `/parents` | GET | 親カテゴリのみフラット一覧 |
| `/all` | GET | 全カテゴリフラット一覧 |
| `/{category_id}/children` | GET | 指定親の子カテゴリ一覧 |
| `/{category_id}` | GET | カテゴリ詳細 |

---

### `routers/accounts.py` — 口座 API ルーター

**プレフィックス:** `/api/v1/accounts`

| パス | メソッド | 説明 |
|------|---------|------|
| `` | GET | 有効な口座一覧（sort_order → code 順） |
| `/types` | GET | 口座種別マスター一覧 |
| `/types` | POST | 口座種別作成（409: コード重複時） |
| `/{account_id}` | PUT | 口座の種別・開始日・初期残高・調整額を更新 |

---

### `routers/groups.py` — グループ API ルーター

**プレフィックス:** `/api/v1/groups`

| パス | メソッド | 説明 |
|------|---------|------|
| `` | GET | グループ一覧（sort_order → code 順） |

---

### `routers/import_router.py` — インポート API ルーター

**プレフィックス:** `/api/v1/import`

| パス | メソッド | 説明 |
|------|---------|------|
| `/upload` | POST | Actual.TXT をアップロードして DB にインポート |
| `/logs` | GET | インポート履歴一覧（直近50件） |
| `/logs/{log_id}` | GET | インポート履歴詳細 |

---

### `routers/reports.py` — レポート API ルーター

**プレフィックス:** `/api/v1/reports`

| パス | メソッド | 説明 |
|------|---------|------|
| `/monthly` | GET | 費目別月次集計（year / month 必須） |
| `/comparison` | GET | 前年同月比（year / month 必須） |
| `/matrix` | GET | カテゴリ × グループ クロス集計（year / month 必須） |
| `/annual` | GET | 費目別年次集計（start_year / end_year 必須） |
| `/yearly-trend` | GET | 直近12ヶ月月次推移（year / month 必須） |
| `/account-annual` | GET | 口座別年次収支（start_year / end_year 必須） |
| `/account-balance` | GET | 口座別残高（as_of_date オプション、省略時は前月末） |

---

## 9. テンプレート層（templates/）

Jinja2 テンプレートエンジンによる HTML レンダリング。Alpine.js・Chart.js を CDN から読み込む。

---

### `templates/base.html`

**役割:** 全画面の共通レイアウト（ヘッダー・ナビゲーション・フッター）。CSS・JS の読み込みもここで定義。各ページは `{% extends "base.html" %}` で継承する。

---

### `templates/index.html` — ダッシュボード

**役割:** 当月の収支サマリー（収入合計・支出合計・残高）と費目別円グラフ（Chart.js）、直近5件の取引を表示する。

---

### `templates/transactions/list.html` — 取引一覧

**役割:** 年月・カテゴリ・口座・グループ・フリーワードでフィルタリングできる取引一覧。ページネーション対応。各行から削除ボタン（確認ダイアログ付き）で取引を削除可能。Excel ダウンロードボタンから現在のフィルター条件で取引を xlsx 出力できる。

---

### `templates/transactions/form.html` — 取引入力・編集フォーム

**役割:** 取引の新規作成・編集フォーム。Alpine.js により以下のインタラクティブな操作を実現：
- 親カテゴリ選択 → 子カテゴリを API から動的取得
- 子カテゴリ選択 → 直近10件の取引を API から取得・表示
- 「コピー」ボタンで過去取引の金額・メモをフォームに転記
- フォーム送信は `fetch` + JSON（通常の form submit ではない）

---

### `templates/import/index.html` — インポート画面

**役割:** Actual.TXT ファイルのアップロードフォームとインポート履歴テーブルを表示する。インポート結果（成功/部分成功/エラー行数）をリアルタイムで表示する。

---

### `templates/accounts/index.html` — 口座設定画面

**役割:** 有効な口座一覧を表示し、各口座の種別・開始日・初期残高・調整額をインライン編集できる。口座種別マスターの追加フォームも備える。Alpine.js で API を叩いて更新する。

---

### `templates/reports/monthly.html` — 月次集計レポート

**役割:** 指定年月の費目別支出・収入を表形式で表示。親カテゴリをクリックすると子カテゴリの詳細行をアコーディオン展開（Alpine.js）。

---

### `templates/reports/comparison.html` — 前年同月比レポート

**役割:** 当年と前年の同月の費目別支出を並べて比較表示。差額・増減率（%）をカラーで視覚化。

---

### `templates/reports/matrix.html` — マトリックスレポート

**役割:** 指定年月のカテゴリ（行）× グループ（列）のクロス集計を表形式で表示。費目ごとにグループ別の支出を一目で把握できる。

---

### `templates/reports/annual.html` — 費目別年次レポート

**役割:** 指定年度範囲の費目別収入・支出を年ごとに並べて比較表示。複数年のトレンドを費目単位で確認できる。

---

### `templates/reports/annual_chart.html` — 費目別年次レポート（チャート）

**役割:** 年次レポートのデータを Chart.js で可視化。収入 Top5・支出 Top5（B カテゴリ）の推移を折れ線グラフで表示する。

---

### `templates/reports/yearly_trend.html` — 直近12ヶ月推移レポート

**役割:** 指定月を終端とした直近12ヶ月のカテゴリ別月次支出推移を表形式で表示。

---

### `templates/reports/yearly_trend_chart.html` — 直近12ヶ月推移チャート

**役割:** 直近12ヶ月の月次推移を Chart.js で可視化。収入 Top5・支出 Top5 の推移を折れ線グラフで表示する。

---

### `templates/reports/account_annual.html` — 口座別年次レポート

**役割:** 指定年度範囲の口座別収入・支出・純額を年ごとに表示する。

---

### `templates/reports/account_balance.html` — 口座別残高レポート

**役割:** 指定日時点の口座別残高（初期残高 + 期間内収支 + 調整額）を一覧表示する。

---

## 10. データベースマイグレーション（alembic/）

Alembic による DB スキーマのバージョン管理。

---

### `alembic/env.py`

**役割:** Alembic の実行環境設定。SQLAlchemy の `Base.metadata` を参照し、ORM モデルから自動でマイグレーションを生成できるよう設定する。

---

### `alembic/versions/0001_initial_schema.py`

**役割:** 初期スキーマの作成マイグレーション。以下の全テーブルと主要インデックスを定義：

- `categories`（idx_categories_parent_id / code / is_transfer）
- `accounts`（idx_accounts_code）
- `groups`
- `transactions`（idx_transactions_date / category_id / is_transfer）
- `import_logs`

---

### `alembic/versions/0002_remove_import_hash_unique.py`

**役割:** `transactions.import_hash` の UNIQUE 制約を削除するマイグレーション。同一ファイルの複数回インポートを許可するための変更。

---

### `alembic/versions/0003_add_account_start_date_initial_balance.py`

**役割:** `accounts` テーブルに `start_date`（残高計算開始日）と `initial_balance`（開始時残高）カラムを追加する。

---

### `alembic/versions/0004_drop_account_start_date_initial_balance.py`

**役割:** 0003 で追加したカラムを一度削除するマイグレーション（設計変更による再定義）。

---

### `alembic/versions/0005_readd_account_start_date_initial_balance.py`

**役割:** `start_date` と `initial_balance` を最終的な型・デフォルト値で再追加する。

---

### `alembic/versions/0006_add_account_types_and_adjustment.py`

**役割:** `account_types` テーブルを新規作成し、`accounts` に `adjustment_amount` カラムを追加する。

---

## 11. フロントエンド静的ファイル

### `frontend/static/css/style.css`

**役割:** アプリ全体のカスタムスタイルシート。`base.html` から読み込まれ、テーブル・フォーム・カード等の共通デザインを定義する。

---

## 12. テスト・CI

### テスト構成（`backend/tests/`）

| ファイル | 内容 |
|---------|------|
| `conftest.py` | pytest フィクスチャ定義（SQLite in-memory DB または `TEST_DATABASE_URL` の PostgreSQL、TestClient、api_client） |
| `test_import_service.py` | import_service の基本ユニットテスト |
| `test_import_service_phase3.py` | import_service の拡充テスト（境界値・異常系・モック） |
| `test_report_service.py` | report_service のユニットテスト |
| `test_transaction_crud.py` | crud/transaction のユニットテスト |
| `test_api_phase4.py` | API エンドポイントの結合テスト（`db_engine` の DB。既定は SQLite in-memory） |
| `integration/routers/` | ルーター単位の API・画面の結合テスト |
| `integration/routers/test_pages_smoke.py` | 全ページ・ファイル出力ルートが HTTP 200 を返すことを確認するスモークテスト（OpenAPI から自動列挙） |

**フィクスチャ:**
- `client` — 通常の TestClient（DB は本番環境依存のため単体テスト向け）
- `db_engine` — テスト用エンジン。既定は SQLite in-memory、環境変数 `TEST_DATABASE_URL` を指定すると PostgreSQL（テストごとにテーブルを作成・削除する。本番・開発用 DB は指定しないこと）
- `db_session` — db_engine にバインドしたテスト用セッション
- `api_client` — get_db を db_session で差し替えた TestClient（結合テスト向け）

**テスト実行:**
```bash
docker compose exec backend pytest          # カバレッジ付き実行
docker compose exec backend pytest -v       # 詳細出力
docker compose exec backend pytest tests/test_api_phase4.py  # 特定ファイル

# PostgreSQL で実行する場合（CI と同じ。専用の DB を用意すること）
TEST_DATABASE_URL=postgresql://test:test@localhost:5432/test pytest
```

**カバレッジ設定（`backend/pytest.ini`）:**
- 計測対象: `app/` 配下全体
- 出力形式: ターミナル（--cov-report=term-missing）/ HTML（htmlcov/）/ XML（coverage.xml）
- 閾値: 15%（未達で CI 失敗）

---

### CI 設定（`.github/workflows/test.yml`）

**役割:** GitHub Actions による自動テスト実行と依存脆弱性スキャン。`main` ブランチへの push および PR をトリガーに実行する。

**ワークフロー:**
1. Python 3.12 環境を構築（pip キャッシュ有効）
2. `backend/requirements.txt` の依存パッケージをインストール
3. PostgreSQL 16 のサービスコンテナに対して `pytest --tb=short` を実行（カバレッジはこの実行で計測）
4. SQLite in-memory に対して `pytest --tb=short --no-cov` を実行（ローカル開発の既定構成の確認）
5. HTML カバレッジレポートを Artifact として7日間保存

**`audit` ジョブ（`test` ジョブと並行して実行）:** `pip-audit -r backend/requirements.txt` で既知の脆弱性を検査する。検出されたら失敗する（[ADR-0005](docs/adr/0005-ci-dependency-audit-and-ai-review-workflow.md)）。テストとは別ジョブにしているため、脆弱性が公表されてもテスト結果は独立して得られる。

**環境変数（CI 実行時）:**

| 変数 | 値 | 説明 |
|------|-----|------|
| `DATABASE_URL` | `sqlite://` | アプリ本体の接続先（テストはフィクスチャが DB を作るため実質使われない） |
| `TEST_DATABASE_URL` | `postgresql://test:test@localhost:5432/test` | PostgreSQL 実行ステップのみ指定。サービスコンテナの DB に接続する |
| `SECRET_KEY` | `ci-secret-key` | CI 用ダミーキー |
| `DEBUG` | `false` | — |

---

## 13. データフロー図

### インポートフロー

```
ブラウザ
  └─ POST /api/v1/import/upload (multipart/form-data)
       └─ import_router.py: upload_file()
            └─ import_service.py: import_actual_txt()
                 ├─ UTF-16 デコード
                 ├─ TSV パース
                 ├─ _upsert_category() → categories テーブル
                 ├─ _upsert_account()  → accounts テーブル
                 ├─ _upsert_group()    → groups テーブル
                 ├─ Transaction 作成  → transactions テーブル
                 └─ ImportLog 作成    → import_logs テーブル
```

### 取引入力フロー（Alpine.js）

```
ブラウザ（transactions/form.html）
  ├─ 親カテゴリ選択 → GET /api/v1/categories/{id}/children
  ├─ 子カテゴリ選択 → GET /api/v1/transactions/recent/by-category/{id}
  │   └─ 直近10件を画面下部に表示
  ├─ 「コピー」クリック → フォームに金額・メモを自動入力
  └─ 「保存」クリック → POST /api/v1/transactions (fetch + JSON)
       └─ transactions.py: create_tx()
            └─ crud/transaction.py: create_transaction()
```

### Excel エクスポートフロー

```
ブラウザ（transactions/list.html）
  └─ GET /transactions/export/excel?year=&month=&... （現在のフィルター条件）
       └─ pages.py: transactions_export_excel()
            └─ crud/transaction.py: get_all_transactions()（全件取得）
            └─ openpyxl でワークブック生成
            └─ StreamingResponse で xlsx ファイルを返す
```

### レポート表示フロー

```
ブラウザ
  └─ GET /reports/monthly?year=2026&month=4
       └─ pages.py: monthly_report_page()
            └─ report_service.py: get_monthly_summary()
                 ├─ transactions × categories JOIN クエリ（月・is_transfer でフィルタ）
                 ├─ 子カテゴリ → 親カテゴリ補完（DB ルックアップ）
                 └─ 親子階層構造を組み立てて返す
            └─ reports/monthly.html レンダリング（Alpine.js でアコーディオン）
```

### 口座残高計算フロー

```
ブラウザ
  └─ GET /reports/account-balance?as_of_date=2026-03-31
       └─ pages.py: account_balance_page()
            └─ report_service.py: get_account_balance_report()
                 ├─ accounts テーブルから initial_balance / start_date / adjustment_amount 取得
                 ├─ start_date 以降の transactions を集計（account_id でグループ化）
                 └─ 残高 = initial_balance + (収入合計 - 支出合計) + adjustment_amount
            └─ reports/account_balance.html レンダリング
```

---

## 14. API エンドポイント一覧

| メソッド | パス | 認証 | 説明 |
|---------|------|------|------|
| GET | `/` | - | ダッシュボード（HTML） |
| GET | `/transactions` | - | 取引一覧画面（HTML） |
| GET | `/transactions/export/excel` | - | 取引一覧 Excel ダウンロード |
| GET | `/transactions/new` | - | 取引新規入力フォーム（HTML） |
| GET | `/transactions/{tx_id}/edit` | - | 取引編集フォーム（HTML） |
| GET | `/import` | - | インポート画面（HTML） |
| GET | `/accounts` | - | 口座設定画面（HTML） |
| GET | `/reports/monthly` | - | 月次集計レポート（HTML） |
| GET | `/reports/comparison` | - | 前年同月比レポート（HTML） |
| GET | `/reports/matrix` | - | マトリックスレポート（HTML） |
| GET | `/reports/annual` | - | 費目別年次レポート（HTML） |
| GET | `/reports/annual-chart` | - | 費目別年次チャート（HTML） |
| GET | `/reports/yearly-trend` | - | 直近12ヶ月推移レポート（HTML） |
| GET | `/reports/yearly-trend-chart` | - | 直近12ヶ月推移チャート（HTML） |
| GET | `/reports/account-annual` | - | 口座別年次レポート（HTML） |
| GET | `/reports/account-balance` | - | 口座別残高レポート（HTML） |
| POST | `/api/v1/import/upload` | - | Actual.TXT インポート |
| GET | `/api/v1/import/logs` | - | インポート履歴一覧（JSON） |
| GET | `/api/v1/import/logs/{id}` | - | インポート履歴詳細（JSON） |
| GET | `/api/v1/categories` | - | カテゴリ階層一覧（JSON） |
| GET | `/api/v1/categories/parents` | - | 親カテゴリ一覧（JSON） |
| GET | `/api/v1/categories/all` | - | 全カテゴリフラット（JSON） |
| GET | `/api/v1/categories/{id}/children` | - | 子カテゴリ一覧（JSON） |
| GET | `/api/v1/categories/{id}` | - | カテゴリ詳細（JSON） |
| GET | `/api/v1/accounts` | - | 口座一覧（JSON） |
| GET | `/api/v1/accounts/types` | - | 口座種別マスター一覧（JSON） |
| POST | `/api/v1/accounts/types` | - | 口座種別作成（JSON） |
| PUT | `/api/v1/accounts/{id}` | - | 口座更新（JSON） |
| GET | `/api/v1/groups` | - | グループ一覧（JSON） |
| GET | `/api/v1/transactions` | - | 取引一覧（JSON・フィルター対応） |
| GET | `/api/v1/transactions/recent/by-category/{id}` | - | カテゴリ別直近 N 件（JSON） |
| GET | `/api/v1/transactions/search` | - | キーワード検索（JSON） |
| GET | `/api/v1/transactions/{tx_id}` | - | 取引詳細（JSON） |
| POST | `/api/v1/transactions` | - | 取引作成（JSON） |
| PUT | `/api/v1/transactions/{tx_id}` | - | 取引更新（JSON） |
| DELETE | `/api/v1/transactions/{tx_id}` | - | 取引削除（204） |
| GET | `/api/v1/reports/monthly` | - | 月次集計（JSON） |
| GET | `/api/v1/reports/comparison` | - | 前年同月比（JSON） |
| GET | `/api/v1/reports/matrix` | - | マトリックス集計（JSON） |
| GET | `/api/v1/reports/annual` | - | 費目別年次集計（JSON） |
| GET | `/api/v1/reports/yearly-trend` | - | 直近12ヶ月推移（JSON） |
| GET | `/api/v1/reports/account-annual` | - | 口座別年次収支（JSON） |
| GET | `/api/v1/reports/account-balance` | - | 口座別残高（JSON） |
| GET | `/docs` | - | FastAPI 自動生成 Swagger UI |

---

## 15. 環境変数・設定値

| 変数名 | 設定場所 | デフォルト | 説明 |
|--------|---------|-----------|------|
| `DATABASE_URL` | docker-compose.yml / .env | `postgresql://household_user:{DB_PASSWORD}@db:5432/household_db` | DB 接続 URL |
| `DB_PASSWORD` | .env | （必須） | PostgreSQL パスワード |
| `SECRET_KEY` | .env | `dev-secret-key` | セキュリティキー |
| `DEBUG` | .env | `false` | デバッグモード |

**ポート対応表:**

| サービス | コンテナ内ポート | ホスト側ポート |
|---------|---------------|-------------|
| PostgreSQL | 5432 | 5439 |
| FastAPI (Uvicorn) | 8000 | 8080 |
