# CLAUDE.md — 家計簿アプリ

## プロジェクト概要

Docker Compose (PostgreSQL + FastAPI) で動作する家計簿管理 Web アプリ。
Actual.TXT（UTF-16LE タブ区切り）からデータをインポートし、カテゴリ階層・月次集計・前年同月比などを管理する。

---

## 技術スタック

| レイヤー | 技術 |
|----------|------|
| Backend | Python 3.12 / FastAPI / SQLAlchemy 2.0 / Alembic |
| Database | PostgreSQL 16 |
| Frontend | Jinja2 テンプレート / Alpine.js (CDN) / Chart.js (CDN) |
| Excel 出力 | openpyxl |
| PDF 出力 | reportlab |
| インフラ | Docker Compose |

---

## 起動方法

```bash
# 初回のみ
cp .env.example .env        # DB_PASSWORD と SECRET_KEY を設定

docker compose up -d
docker compose exec backend alembic upgrade head

# アプリ: http://localhost:8080
# API ドキュメント: http://localhost:8080/docs
```

> **ポート**: DB=5439、Backend=8080（ホスト側ポート競合を避けるため）。どちらも `127.0.0.1` にのみ公開しており、同一マシン以外（LAN 上の他の端末）からは到達できない（[ADR-0006](docs/adr/0006-no-authentication-for-personal-local-use.md)）

---

## よく使うコマンド

```bash
# バックエンドのログを確認
docker compose logs -f backend

# バックエンドを再起動（コード変更を反映）
docker compose restart backend

# DB に直接接続
docker compose exec db psql -U household_user -d household_db

# マイグレーション追加
docker compose exec backend alembic revision --autogenerate -m "説明"
docker compose exec backend alembic upgrade head
```

---

## ディレクトリ構造

```
household-account-book/
├── docker-compose.yml
├── .env.example
├── Actual.TXT                          # 元データ（UTF-16LE TSV）
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/                   # マイグレーションファイル
│   └── app/
│       ├── main.py                     # FastAPI エントリーポイント
│       ├── config.py                   # 環境変数（pydantic-settings）
│       ├── database.py                 # SQLAlchemy セッション
│       ├── jst.py                      # JST タイムゾーンユーティリティ
│       ├── models/                     # ORM モデル
│       ├── schemas/                    # Pydantic スキーマ
│       ├── crud/                       # DB 操作ロジック
│       ├── routers/                    # API + ページルーター
│       ├── services/                   # ビジネスロジック
│       ├── templates/                  # Jinja2 HTML テンプレート
│       └── utils/                      # ユーティリティ（date_utils など）
├── frontend/
│   └── static/css/style.css
└── data/                               # インポートファイル置き場
```

---

## データモデル

### categories（カテゴリ階層）
- `full_path`: `A30_通信費/インターネット` のようにスラッシュで親子を表現
- `parent_id`: 親カテゴリの ID（NULL = 親カテゴリ）
- `is_transfer`: `【資金移動】` カテゴリは TRUE（集計から除外）

### transactions（取引明細）
- `income_amount` / `expense_amount`: 入金・出金（どちらか一方が 0）
- `is_transfer`: 資金移動フラグ（月次集計では除外）
- `transfer_detail`: 資金移動の詳細メモ
- `import_hash`: インポート追跡用（UNIQUE 制約なし、重複インポート可）

### accounts（口座・カード）
- `account_type`: cash / bank / card / e-money / other
- `classification`: 口座分類（任意文字列、例: `個人`, `共通`）
- `start_date`: 残高計算の起算日
- `initial_balance`: 起算日時点の初期残高
- `adjustment_amount`: 残高調整額

### account_types（口座タイプマスタ）
- `code`: タイプコード（例: `cash`, `bank`）
- `label`: 表示ラベル
- `sort_order`: 表示順

### transaction_patterns（定期取引パターン）
- `frequency`: 頻度（`monthly` / `yearly`）
- `payment_day_of_month`: 毎月の支払日
- `payment_month_of_year`: 年1回の場合の支払月
- `typical_amount`: 通常金額
- `is_income`: 収入フラグ
- `pattern_group_id`: 所属パターングループ（SET NULL on delete）
- `is_active`: 有効フラグ

### pattern_groups（パターングループ）
- `name`: グループ名（UNIQUE）
- `is_transfer_only`: 資金移動専用グループフラグ

### その他
- `groups`: 人別・目的別グループ（例: `20_太郎`、`10_必須(通常)`）
- `import_logs`: インポート履歴（total/imported/skipped/error_rows, status）

---

## 主要 API

### インポート
| エンドポイント | 説明 |
|---|---|
| `POST /api/v1/import/upload` | Actual.TXT アップロード・DB 格納 |

### カテゴリ
| エンドポイント | 説明 |
|---|---|
| `GET /api/v1/categories` | カテゴリ一覧（子カテゴリ付き） |
| `GET /api/v1/categories/parents` | 親カテゴリ一覧 |
| `GET /api/v1/categories/all` | 全カテゴリ一覧 |
| `GET /api/v1/categories/{id}/children` | 子カテゴリ一覧 |
| `GET /api/v1/categories/{id}` | カテゴリ詳細 |

### 取引
| エンドポイント | 説明 |
|---|---|
| `GET /api/v1/transactions` | 取引一覧（フィルター・ページング） |
| `GET /api/v1/transactions/recent/by-category/{id}` | カテゴリ別直近N件 |
| `GET /api/v1/transactions/search?q=` | フリーワード検索 |
| `GET /api/v1/transactions/{id}` | 取引詳細 |
| `POST /api/v1/transactions` | 取引作成 |
| `POST /api/v1/transactions/transfer` | 資金移動取引作成 |
| `PUT /api/v1/transactions/{id}` | 取引更新 |
| `DELETE /api/v1/transactions/{id}` | 取引削除 |

### 口座
| エンドポイント | 説明 |
|---|---|
| `GET /api/v1/accounts` | 口座一覧 |
| `PUT /api/v1/accounts/{id}` | 口座更新 |
| `PUT /api/v1/accounts/bulk` | 口座一括更新 |
| `GET /api/v1/accounts/types` | 口座タイプ一覧 |
| `POST /api/v1/accounts/types` | 口座タイプ作成 |
| `PUT /api/v1/accounts/types/{id}` | 口座タイプ更新 |
| `DELETE /api/v1/accounts/types/{id}` | 口座タイプ削除 |

### グループ
| エンドポイント | 説明 |
|---|---|
| `GET /api/v1/groups` | グループ一覧 |

### 定期取引パターン
| エンドポイント | 説明 |
|---|---|
| `GET /api/v1/patterns` | パターン一覧 |
| `GET /api/v1/patterns/analyze` | 履歴からパターン候補を分析 |
| `GET /api/v1/patterns/due` | 今月支払い予定のパターン一覧 |
| `GET /api/v1/patterns/{id}` | パターン詳細 |
| `POST /api/v1/patterns` | パターン作成 |
| `PUT /api/v1/patterns/{id}` | パターン更新 |
| `DELETE /api/v1/patterns/{id}` | パターン削除 |
| `GET /api/v1/pattern-groups` | パターングループ一覧 |
| `GET /api/v1/pattern-groups/{id}` | パターングループ詳細 |
| `POST /api/v1/pattern-groups` | パターングループ作成 |
| `PUT /api/v1/pattern-groups/{id}` | パターングループ更新 |
| `DELETE /api/v1/pattern-groups/{id}` | パターングループ削除 |

### レポート
| エンドポイント | 説明 |
|---|---|
| `GET /api/v1/reports/monthly` | 費目別月次集計 |
| `GET /api/v1/reports/comparison` | 前年同月比 |
| `GET /api/v1/reports/matrix` | カテゴリ×グループ マトリックス |
| `GET /api/v1/reports/annual` | 年次集計 |
| `GET /api/v1/reports/yearly-trend` | 年度別トレンド |
| `GET /api/v1/reports/account-annual` | 口座別年次集計 |
| `GET /api/v1/reports/account-monthly` | 口座別月次集計 |
| `GET /api/v1/reports/account-monthly-daily` | 口座別日次集計 |
| `GET /api/v1/reports/account-classification-annual` | 口座分類別年次集計 |
| `GET /api/v1/reports/account-balance` | 口座残高レポート |

### バックアップ・ローン
| エンドポイント | 説明 |
|---|---|
| `POST /api/v1/backup/dump` | DB バックアップ（pg_dump） |
| `POST /api/v1/backup/restore` | DB リストア |
| `POST /api/v1/loans/preview` | ローン返済シミュレーション |
| `POST /api/v1/loans/create` | ローン取引を一括作成 |

---

## 画面一覧

| パス | 説明 |
|------|------|
| `/` | ダッシュボード（当月収支 + 円グラフ） |
| `/transactions` | 取引一覧（フィルター・検索・削除・Excel/Actual.TXT エクスポート） |
| `/transactions/new` | 取引入力（入力補助：直近10件表示） |
| `/transactions/{id}/edit` | 取引編集 |
| `/export` | エクスポート画面 |
| `/accounts` | 口座管理（タイプ・初期残高・分類の編集） |
| `/patterns` | 定期取引パターン管理 |
| `/reports/monthly` | 月次集計（親クリックで子展開） |
| `/reports/comparison` | 前年同月比 |
| `/reports/matrix` | カテゴリ×グループ マトリックス |
| `/reports/annual` | 年次集計 |
| `/reports/annual-chart` | 年次集計グラフ |
| `/reports/yearly-trend` | 年度別トレンド |
| `/reports/yearly-trend-chart` | 年度別トレンドグラフ |
| `/reports/account-annual` | 口座別年次集計 |
| `/reports/account-annual/monthly` | 口座別月次明細 |
| `/reports/account-annual/monthly/daily` | 口座別日次明細 |
| `/reports/account-classification-annual` | 口座分類別年次集計 |
| `/reports/account-classification-annual-chart` | 口座分類別年次グラフ |
| `/reports/account-balance` | 口座残高一覧 |
| `/import` | Actual.TXT インポート + 履歴 |
| `/backup` | DB バックアップ・リストア |
| `/loans/new` | ローン返済シミュレーション・一括取引作成 |
| `/reports/export-pdf` | 前月末レポート PDF ダウンロード（グラフ付き） |

---

## 実装上の注意点

### カテゴリ検索は JOIN でなくサブクエリを使うこと
`get_transactions` では `joinedload` による JOIN が既に発生している。
カテゴリで絞り込む場合は重複 JOIN を避けるためサブクエリを使用する。

```python
# OK
matched_cat_ids = db.query(Category.id).filter(
    Category.full_path.ilike(f"%{search}%")
).subquery()
q = q.filter(Transaction.category_id.in_(matched_cat_ids))

# NG（joinedload と重複して SQLエラーになる）
q = q.join(Category).filter(Category.full_path.ilike(...))
```

### JST タイムゾーン（jst.py）
`date.today()` や `datetime.now()` はサーバーのタイムゾーンに依存するため、
**必ず `jst.py` の関数を使うこと。**

```python
from app.jst import today_jst, now_jst

today = today_jst()   # date.today() の代わり
now   = now_jst()     # datetime.now() の代わり
```

### インポートサービス（import_service.py）
- `content.decode('utf-16')` で BOM 付き UTF-16LE を自動認識
- カテゴリ階層は `full_path.split('/', 1)` で親子を分割
- 資金移動判定: `full_path.startswith('【資金移動】')`
- `import_hash` に UNIQUE 制約なし → 同一ファイルの複数回インポート可

### 月次集計（report_service.py）
- トランザクションには**子カテゴリ**のみ紐づく（親カテゴリは直接使われない）
- 集計後に親カテゴリを DB から補完して親子構造を組み立てる

### ローンサービス（loan_service.py）
- 元利均等返済の計算を行い、`RepaymentItem` のリストを返す
- 繰上返済（`EarlyRepayment`）を途中に挿入可能
- 支払日が月末を超える場合は `utils/date_utils.py` の `clamp_day_to_month` で月末に丸める

### PDF サービス（pdf_service.py）
- reportlab を使い、前月末時点の月次レポートを A4 PDF に生成
- 円グラフ・棒グラフを含む（親カテゴリのみ集計）
- `/reports/export-pdf` から直接ダウンロードされる（テンプレートなし）

### 資金移動の作成（crud/transaction.py）
`POST /api/v1/transactions/transfer` は 1 リクエストで出金・入金の **2 件**の Transaction を作成する。
カテゴリは `upsert_transfer_category` で `【資金移動】/{from}→{to}` の形式で自動生成・再利用する。

### フロントエンドのフォーム送信
- 取引入力フォームは Alpine.js で `fetch` + JSON 送信（通常の form submit ではない）
- 親カテゴリ選択 → 子カテゴリ取得 → 直近10件表示 → コピーボタンで転記

### Jinja2 テンプレートへの JSON 埋め込み

JSON を HTML 属性に埋め込む場合、`tojson` が出力するダブルクォートが属性区切りと衝突する。
**必ずシングルクォート属性を使うこと。**

```html
{# OK: シングルクォート属性 #}
<div x-data='myComponent({{ data | tojson }})'>

{# NG: ダブルクォート属性 — JSON の " が属性を途中で切る #}
<div x-data="myComponent({{ data | tojson }})">

{# 代替: forceescape で HTML エンティティ化（&quot;）も可 #}
<span x-data="{{ data | tojson | forceescape }}">
```

`<script>` タグ内への埋め込みは `tojson` のみで問題ない（HTML エスケープ不要）。

### TemplateResponse は `request` を第1引数にする
Starlette 1.x で `TemplateResponse(name, {"request": request, ...})` の旧シグネチャは使えない
（`TypeError: unhashable type: 'dict'` になる）。**`request` を第1引数に渡すこと。**
context に `"request"` を入れる必要はない。

```python
# OK
return templates.TemplateResponse(request, "index.html", {"summary": summary})

# NG（Starlette 1.x ではエラー）
return templates.TemplateResponse("index.html", {"request": request, "summary": summary})
```

### Jinja2 テンプレートへの日付渡し
Python の `date` / `datetime` オブジェクトをそのまま `tojson` に渡すと
`TypeError` になる（JSON シリアライズ不可）。
テンプレートへ渡す前に文字列（`str(date_obj)` や `.isoformat()`）に変換すること。

---

## テスト・CI・レビュー運用

```bash
cd backend
pytest                      # 既定は SQLite in-memory（PostgreSQL 不要）

# PostgreSQL で実行する（CI と同じ。専用 DB を用意すること。テーブルを作成・削除する）
TEST_DATABASE_URL=postgresql://test:test@localhost:5432/test pytest

pip install pip-audit && pip-audit -r requirements.txt   # 依存の脆弱性検査（CI と同じ）
```

- CI（`.github/workflows/test.yml`）は、`audit` ジョブ（`pip-audit`、ブロッキング）と `test` ジョブ（PostgreSQL → SQLite の順でテスト）を並行して実行する。**脆弱性が検出されると CI が失敗する**ため、依存を追加・更新したら手元で `pip-audit` を実行すること
- CI の `forbidden-terms` ジョブは、実名・実在の取引先名など公開したくない語が追跡ファイルに無いことを検査する（`scripts/check_forbidden_terms.sh`）。**語の一覧はリポジトリに置かず**、GitHub の Secret `FORBIDDEN_TERMS`（改行区切り）で渡す。手元では `FORBIDDEN_TERMS=$'語1\n語2' scripts/check_forbidden_terms.sh` で実行できる。サンプルデータ・テスト・ドキュメントには、実名由来の名前ではなく `太郎` `サンプル銀行` のような架空の名前を使うこと
- `TEST_DATABASE_URL` はテスト実行前に検証され、アプリの `DATABASE_URL` と同じ DB や、DB 名に `test` を含まない DB は拒否される（テストはテーブルを作成・削除するため）
- 新しいページルートを追加すると、`tests/integration/routers/test_pages_smoke.py` が自動的に HTTP 200 を検証する。パスパラメータを持つルートは、同ファイルの `_path_params` に値を追加すること
- **PR 作成前に `/code-review` を手動で実行し、指摘事項に対応すること。** AI レビューの CI 自動実行は見送っている（[ADR-0005](docs/adr/0005-ci-dependency-audit-and-ai-review-workflow.md)）。PR テンプレートの「`/code-review` 実行済み」は自己申告で、CI では強制されない

---

## 環境変数（.env）

```
DB_PASSWORD=（PostgreSQL パスワード）
SECRET_KEY=（任意の文字列）
DEBUG=true
```
