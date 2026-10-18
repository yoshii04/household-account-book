# 仕様：カテゴリ管理

## 概要

取引を分類するカテゴリを管理する機能。カテゴリは親子2階層で構成され、`full_path` によって一意に識別される。カテゴリ自体の作成・編集・削除はUIから行えず、Actual.TXTインポートまたは資金移動取引作成時に自動的に生成・更新される。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | なし | カテゴリ専用のUI画面は存在しない |
| API | `GET /api/v1/categories` | 親カテゴリ一覧（子カテゴリをネストして含む） |
| API | `GET /api/v1/categories/parents` | 親カテゴリのみ一覧（フラット） |
| API | `GET /api/v1/categories/all` | 全カテゴリ一覧（フラット） |
| API | `GET /api/v1/categories/{category_id}/children` | 指定親カテゴリの子カテゴリ一覧 |
| API | `GET /api/v1/categories/{category_id}` | カテゴリ詳細 |

---

## 対象ファイル

- `backend/app/routers/categories.py` — APIルーター
- `backend/app/models/category.py` — ORMモデル
- `backend/app/schemas/category.py` — Pydanticスキーマ
- `backend/app/services/import_service.py` — カテゴリ upsert（`_upsert_category` 関数）
- `backend/app/crud/transaction.py` — 資金移動カテゴリ upsert（`upsert_transfer_category` 関数）

---

## データモデル

### categories テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | カテゴリID |
| `code` | String(50) | NOT NULL | カテゴリコード（例：`A30_通信費`、`インターネット`） |
| `name` | String(100) | NOT NULL | カテゴリ名（例：`A30_通信費`、`インターネット`） |
| `parent_id` | Integer | FK(categories.id, ondelete=SET NULL), nullable | 親カテゴリID。NULL の場合は親カテゴリ（ルート） |
| `full_path` | String(200) | NOT NULL, UNIQUE | 階層パス（例：`A30_通信費/インターネット`） |
| `is_transfer` | Boolean | NOT NULL, default=False | 資金移動フラグ。True の場合は集計から除外 |
| `sort_order` | Integer | NOT NULL, default=0 | 表示順 |
| `created_at` | DateTime(timezone=True) | server_default=now() | 作成日時 |
| `updated_at` | DateTime(timezone=True) | server_default=now(), onupdate=now() | 更新日時 |

**リレーション：**
- `parent`：自己参照（`Category.id` への FK、`remote_side="Category.id"`）
- `children`：自己参照の逆方向（`cascade="all, delete-orphan"`）
- `transactions`：`Transaction` への1対多

---

## 機能仕様

### full_path の形式

- 親カテゴリ：`A30_通信費`（スラッシュなし）
- 子カテゴリ：`A30_通信費/インターネット`（`親/子` 形式）
- スラッシュは1つのみ。`split("/", 1)` で親コードと子名に分割できる
- `full_path` に UNIQUE 制約があるため、同じパスのカテゴリは重複して作成されない

### 親子関係の表現

- `parent_id` が NULL のカテゴリが親カテゴリ（ルート）
- `parent_id` に親カテゴリの `id` を持つカテゴリが子カテゴリ
- 取引（Transaction）は必ず**子カテゴリ**に紐づく（親カテゴリは直接使われない）
- 子カテゴリが存在しない親カテゴリに取引が直接紐づくケースも実装上は許容されている

### is_transfer フラグ

- `full_path` が `【資金移動】` で始まるカテゴリは `is_transfer=True`
- `full_path` が `【ﾛｰﾝ】` で始まるカテゴリも `is_transfer=True`
- `is_transfer=True` のカテゴリに紐づく取引は月次集計から除外される
- フロントエンドの取引入力フォームでは、親カテゴリの `is_transfer` フラグを `data` 属性で保持し、資金移動フォームへの切り替え判定に使用する

### カテゴリの作成経路

カテゴリはUIから直接作成・編集・削除できない。以下の2つの経路でのみ生成される。

**1. Actual.TXT インポート時（`import_service.py` の `_upsert_category`）：**
- インポートデータの各行の `category_path` をもとに `_upsert_category` を呼び出す
- `full_path` で既存カテゴリを検索し、存在すれば再利用、なければ新規作成（upsert）
- 子カテゴリを作成する際は親カテゴリを先に upsert してから `parent_id` を設定する
- `【資金移動】` または `【ﾛｰﾝ】` 始まりの `full_path` は `is_transfer=True` で作成

**2. 資金移動取引作成時（`crud/transaction.py` の `upsert_transfer_category`）：**
- `POST /api/v1/transactions/transfer` リクエスト時に自動生成
- 出金側：`【資金移動】- {to_account.code}へ -`
- 入金側：`【資金移動】- {from_account.code}から -`
- 親カテゴリ `【資金移動】` が存在しない場合は同時に作成される
- 生成されるすべてのカテゴリは `is_transfer=True`

### APIレスポンスの構造

**`CategoryOut` スキーマ（フラット形式）：**
```json
{
  "id": 1,
  "code": "A30_通信費",
  "name": "A30_通信費",
  "full_path": "A30_通信費",
  "is_transfer": false,
  "sort_order": 0,
  "parent_id": null
}
```

**`CategoryWithChildren` スキーマ（ネスト形式、`GET /api/v1/categories` で使用）：**
```json
{
  "id": 1,
  "code": "A30_通信費",
  "name": "A30_通信費",
  "full_path": "A30_通信費",
  "is_transfer": false,
  "sort_order": 0,
  "parent_id": null,
  "children": [
    {
      "id": 2,
      "code": "インターネット",
      "name": "インターネット",
      "full_path": "A30_通信費/インターネット",
      "is_transfer": false,
      "sort_order": 0,
      "parent_id": 1,
      "children": []
    }
  ]
}
```

### ソート順

すべてのカテゴリ一覧APIは `full_path` の昇順でソートされる。`sort_order` カラムは現状ソートに使用されていない。

---

## 実装上の注意点

- **カテゴリ検索はサブクエリを使うこと：** `get_transactions` では `joinedload` による JOIN が既に発生しているため、カテゴリで絞り込む場合は重複 JOIN を避けるためサブクエリを使用する。`q.join(Category)` は使用禁止で、`db.query(Category.id).filter(...).subquery()` + `Transaction.category_id.in_(...)` の形で実装すること
- **取引には子カテゴリのみ紐づく：** 月次集計（`report_service.py`）では、取引が子カテゴリにのみ紐づくことを前提として集計後に親カテゴリを DB から補完して親子構造を組み立てる
- **`is_transfer` の判定：** `full_path.startswith("【資金移動】")` または `full_path.startswith("【ﾛｰﾝ】")` で判定する。モデルの `is_transfer` フラグと一致している前提で動作しているが、手動でレコードを書き換えた場合の整合性は保証されない
- **`full_path` のUNIQUE制約：** カテゴリの重複は `full_path` の一致で防ぐ。`code` や `name` には UNIQUE 制約がないため、同名カテゴリが別 `full_path` で作成されることは許容されている

---

## 動作確認チェックリスト

- [ ] `GET /api/v1/categories` が親カテゴリのみを返し、各親の `children` に子カテゴリが含まれること
- [ ] `GET /api/v1/categories/parents` が `parent_id=null` の親カテゴリのみをフラットで返すこと
- [ ] `GET /api/v1/categories/all` が親・子を含む全カテゴリをフラットで返すこと
- [ ] `GET /api/v1/categories/{id}/children` が指定IDの子カテゴリのみを返すこと
- [ ] `GET /api/v1/categories/{id}` が存在しないIDで 404 を返すこと
- [ ] Actual.TXT インポート後に新規カテゴリが `full_path` UNIQUE 制約に従い重複なく作成されること
- [ ] 同じファイルを2回インポートしてもカテゴリが重複しないこと（upsert 動作）
- [ ] 資金移動取引作成後に `【資金移動】- {code}へ -` / `- {code}から -` カテゴリが自動生成されること
- [ ] `is_transfer=True` のカテゴリに紐づく取引が月次集計レポートに含まれないこと
- [ ] 取引入力フォームで `is_transfer=True` の親カテゴリを選択した際に資金移動フォームに切り替わること
