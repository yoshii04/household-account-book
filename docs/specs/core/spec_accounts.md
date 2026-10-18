# 仕様：口座管理

## 概要

家計簿に登録されている口座・カード・電子マネー等のアカウント情報を一元管理する機能。インポートで自動生成された口座に対して、残高計算に必要な開始日・初期残高・調整金額・種別・分類を設定する。口座タイプ（種別）はマスタとして独立管理され、追加・編集・削除が可能。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/accounts` | 口座管理（種別管理・一括設定・口座一覧・インライン編集） |
| API | `GET /api/v1/accounts` | 有効な口座一覧（sort_order, code 順） |
| API | `PUT /api/v1/accounts/{account_id}` | 口座単体更新（種別・開始日・初期残高・調整金額・分類） |
| API | `PUT /api/v1/accounts/bulk` | 口座一括更新（種別・分類を複数口座に適用） |
| API | `GET /api/v1/accounts/types` | 口座タイプ一覧（sort_order, code 順） |
| API | `POST /api/v1/accounts/types` | 口座タイプ作成 |
| API | `PUT /api/v1/accounts/types/{type_id}` | 口座タイプ更新 |
| API | `DELETE /api/v1/accounts/types/{type_id}` | 口座タイプ削除 |

---

## 対象ファイル

- `backend/app/routers/accounts.py` — APIルーター
- `backend/app/routers/pages.py` — ページルーター（`/accounts` ルート）
- `backend/app/models/account.py` — Account ORMモデル
- `backend/app/models/account_type.py` — AccountType ORMモデル
- `backend/app/schemas/account.py` — Pydanticスキーマ
- `backend/app/templates/accounts/index.html` — 口座管理テンプレート

---

## データモデル

### accounts テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | 口座ID |
| `code` | String(50) | NOT NULL, UNIQUE | 口座コード（インポート元の識別子） |
| `name` | String(100) | NOT NULL | 口座名 |
| `account_type` | String(20) | NOT NULL, default="other" | 口座タイプコード（`account_types.code` を参照するが FK 制約なし） |
| `sort_order` | Integer | NOT NULL, default=0 | 表示順 |
| `is_active` | Boolean | NOT NULL, default=True | 有効フラグ |
| `start_date` | Date | nullable | 残高計算の起算日 |
| `initial_balance` | Integer | nullable, default=0 | 起算日時点の初期残高（円） |
| `adjustment_amount` | Integer | nullable, default=0 | 残高調整額（円）。初期残高とは別に加算される補正値 |
| `classification` | String(100) | nullable | 口座分類（任意文字列。例: `個人`, `共通`） |
| `created_at` | DateTime(timezone=True) | server_default=now() | 作成日時 |

**リレーション：** `transactions`（Transaction のリスト）

**補足：**
- `code` と `name` はインポート処理で自動生成される。管理画面からの新規作成・削除エンドポイントは存在しない
- `is_active=False` の口座は一覧取得（`GET /api/v1/accounts`）から除外される
- `account_type` の値は `account_types.code` の値を文字列で格納するが、外部キー制約はない

### account_types テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | タイプID |
| `code` | String(50) | NOT NULL, UNIQUE | タイプコード（例: `cash`, `bank`, `card`, `e-money`, `other`） |
| `label` | String(100) | NOT NULL | 表示ラベル（例: `現金`, `銀行`, `クレカ`） |
| `sort_order` | Integer | NOT NULL, default=0 | 表示順 |

---

## 機能仕様

### 口座一覧取得（`GET /api/v1/accounts`）

- `is_active=True` の口座のみを返す
- `sort_order` 昇順、同値の場合は `code` 昇順でソートする
- レスポンスには `start_date`、`initial_balance`、`adjustment_amount`、`classification` を含む

### 口座管理画面（`/accounts`）

- ページ表示時に `is_active=True` の全口座を `sort_order, code` 順で取得する
- 各口座の**最古取引日**（`func.min(Transaction.date)` を account_id でグループ化）も同時に取得し、`oldest_transaction_date` としてテンプレートに渡す
- `account_type_map`（`id` と `account_type` のみ）を Alpine.js バインディング用に別途生成する（date オブジェクトを含む `account_stats` をそのまま `tojson` に渡すと TypeError になるため）
- `account_types` は `<script>` ブロック内で `Alpine.store('accountTypes', ...)` に渡す

**画面構成：**
1. 種別管理カード（`AccountType` のCRUD操作）
2. 一括設定カード（種別・分類を選択口座にまとめて適用）
3. 口座一覧テーブル（種別フィルター・チェックボックス選択・インライン編集）

### 口座単体更新（`PUT /api/v1/accounts/{account_id}`）

- 対象口座が存在しない場合は HTTP 404 を返す
- `account_type` が指定された場合、`account_types` テーブルに該当コードが存在するか検証し、存在しない場合は HTTP 400 を返す
- `initial_balance` / `adjustment_amount` が `None` の場合は 0 を格納する
- `classification` が空文字列または `None` の場合は `NULL` を格納する
- `code`・`name`・`sort_order`・`is_active` は更新対象外

**`AccountUpdate` リクエストボディ：**

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `account_type` | str | 任意 | 口座タイプコード（`account_types.code` に存在する値） |
| `start_date` | date | 任意 | 残高計算の起算日 |
| `initial_balance` | int | 任意 | 起算日時点の初期残高（円） |
| `adjustment_amount` | int | 任意 | 残高調整額（円） |
| `classification` | str | 任意 | 口座分類 |

### 口座一括更新（`PUT /api/v1/accounts/bulk`）

- `ids` に指定した口座ID群（`is_active=True` の口座のみ）に対して、種別・分類をまとめて更新する
- 更新フィールドが1つも指定されていない場合（`account_type` が `None` かつ `update_classification` が `False`）は HTTP 400 を返す
- `account_type` が指定された場合、`account_types` に存在するか検証し、存在しない場合は HTTP 400 を返す
- `update_classification=True` の場合のみ `classification` を更新する。`classification` が空文字列または `None` のときは `NULL` を格納する
- 更新後、対象口座のリストを返す
- 成功後、フロントエンドは 1.2 秒後に `window.location.reload()` でページをリロードする

**`AccountBulkUpdate` リクエストボディ：**

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `ids` | list[int] | 必須（1〜500件） | 更新対象の口座IDリスト |
| `account_type` | str | 任意 | 新しい口座タイプコード。`None` のとき種別を変更しない |
| `update_classification` | bool | 任意（default=False） | `True` のとき `classification` を更新する |
| `classification` | str | 任意 | 新しい分類値。`update_classification=True` のときのみ有効 |

### 口座タイプ管理

#### タイプ一覧（`GET /api/v1/accounts/types`）

- `sort_order` 昇順、同値の場合は `code` 昇順でソートして全件返す

#### タイプ作成（`POST /api/v1/accounts/types`）

- `code` が既存と重複する場合は HTTP 409 を返す
- 作成成功時は HTTP 201 を返す

**`AccountTypeCreate` リクエストボディ：**

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `code` | str | 必須 | タイプコード（UNIQUE） |
| `label` | str | 必須 | 表示ラベル |
| `sort_order` | int | 任意（default=0） | 表示順 |

#### タイプ更新（`PUT /api/v1/accounts/types/{type_id}`）

- 対象タイプが存在しない場合は HTTP 404 を返す
- `code` を変更する場合、変更後の `code` が既存の別レコードと重複するときは HTTP 409 を返す
- `code` を変更した場合、`accounts` テーブルで旧コードを使用している全口座の `account_type` を新コードに一括更新する（カスケード更新）

#### タイプ削除（`DELETE /api/v1/accounts/types/{type_id}`）

- 対象タイプが存在しない場合は HTTP 404 を返す
- `accounts` テーブルで当該 `code` を使用している口座が1件でも存在する場合は HTTP 409 を返す（使用中の種別は削除不可）
- 削除成功時は HTTP 204 を返す

### 開始日・初期残高・調整金額の残高計算への影響

- **`start_date`（起算日）：** 残高計算の基準となる日付。未設定の場合、口座の最古取引日（`oldest_transaction_date`）がフォールバックとして使われる
- **`initial_balance`（初期残高）：** 起算日時点での口座残高（円）。デフォルト 0
- **`adjustment_amount`（調整金額）：** 残高のズレを補正するための固定値。初期残高とは**別に加算**される（デフォルト 0。正値なら残高を増やし、負値なら減らす）
- 口座残高 ＝ `initial_balance` ＋ `adjustment_amount` ＋ 起算日以降の取引差額

### インライン編集（フロントエンド）

- 口座一覧テーブルの各行は Alpine.js の `accountRow()` コンポーネントで管理し、「編集」ボタンでインライン編集モードに切り替える
- 保存時は `PUT /api/v1/accounts/{id}` を `fetch` + JSON で呼び出す
- 保存成功後に `accountSaved`・`accountRowSaved` カスタムイベントをディスパッチし、一括管理コンポーネントのメモリ内リストを更新する
- 種別フィルター変更時にチェックボックスの選択状態をクリアする
- ヘッダーのチェックボックスは表示中（フィルター後）の口座を全選択・全解除する

---

## 実装上の注意点

- **`account_type` は FK 制約なし：** `accounts.account_type` は `account_types.code` の値を文字列で保持するが、DB レベルでの外部キー制約はない。API 側で存在確認を行う
- **口座の新規作成・削除エンドポイントなし：** 口座はインポート処理でのみ生成される。管理画面では編集（種別・開始日・初期残高・調整金額・分類）のみ可能
- **`is_active` フラグ：** 非アクティブ化エンドポイントは現状存在しないが、`is_active=False` の口座は `GET /api/v1/accounts` および管理画面から除外される
- **`account_type_map` の分離：** `accounts_page` では `account_stats` に `start_date`（`date` 型）が含まれるため `tojson` が失敗する。Alpine.js の `x-data` 属性に渡す用に `id` と `account_type` だけを抜き出した `account_type_map` を別途生成する
- **Alpine.js バインディングのシングルクォート：** `x-data='accountBulkManager({{ account_type_map | tojson }})'` のように `x-data` 属性はシングルクォートを使うこと。ダブルクォートにすると JSON の `"` が属性を途中で切る
- **`<script>` ブロックへの埋め込み：** `account_types` は `<script>` ブロック内の `Alpine.store('accountTypes', {{ account_types | tojson }})` で渡す。`date`/`datetime` オブジェクトを含まないため `tojson` のみで問題ない
- **`classification` の `forceescape`：** テンプレートの行データ属性では `{{ acc.classification | tojson | forceescape }}` を使用して HTML エンティティ化している
- **口座タイプコード変更のカスケード：** `PUT /api/v1/accounts/types/{type_id}` でコードを変更すると `accounts` テーブルの `account_type` 列が一括更新される。コード変更は慎重に行うこと
- **JST タイムゾーン：** 本機能に日付の自動生成処理はないが、将来的に `start_date` デフォルト値を設定する場合は `today_jst()` を使うこと

---

## 動作確認チェックリスト

- [ ] `/accounts` にアクセスして口座一覧が `sort_order`, `code` 順で表示されること
- [ ] 種別管理：「＋ 種別を追加」で新しいタイプ（コード・ラベル・表示順）を登録できること
- [ ] 種別管理：同じコードで追加しようとするとエラーメッセージが表示されること
- [ ] 種別管理：既存タイプの「編集」ボタンでインライン編集モードに切り替わり、保存できること
- [ ] 種別管理：コードを変更して保存すると、そのタイプを使用していた口座の種別も新コードに更新されること
- [ ] 種別管理：口座に使用中の種別を削除しようとすると「使用中」エラーが表示されること
- [ ] 種別管理：使用中でない種別を削除すると一覧から消えること
- [ ] 口座一覧：「種別で絞り込み」セレクトで表示口座がフィルタリングされること
- [ ] 口座一覧：フィルター変更時にチェックボックスの選択状態がクリアされること
- [ ] 口座一覧：各行の「編集」ボタンで種別・分類・開始日・初期残高・調整金額のインライン編集ができること
- [ ] 口座一覧：`start_date` 未設定時の編集モードで「最古取引日を使用」のヒントが表示されること
- [ ] 口座一覧：「保存」後に更新した値が即座に画面に反映されること
- [ ] 一括設定：チェックボックス未選択で「一括設定を実行」するとエラーメッセージが表示されること
- [ ] 一括設定：変更内容（種別・分類）を未選択で「一括設定を実行」するとエラーメッセージが表示されること
- [ ] 一括設定：種別を選択して複数口座をチェックし「一括設定を実行」すると該当口座の種別が変わること
- [ ] 一括設定：分類を「値を設定する」にして複数口座に一括設定できること
- [ ] 一括設定：分類を「クリアする」にして複数口座の分類を空欄にできること
- [ ] 一括設定：ヘッダーのチェックボックスで表示中の全口座を一括選択・解除できること
- [ ] 一括設定：成功後 1.2 秒でページがリロードされ、更新内容が反映されること
