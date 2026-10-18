# 仕様：インポート

## 概要

Actual.TXT（UTF-16LE BOM 付きタブ区切りファイル）をアップロードして取引データを DB に一括登録する機能。カテゴリ・口座・グループが未登録の場合は自動作成（upsert）される。インポート結果はログとして保存され、画面から履歴を確認できる。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/import` | Actual.TXT アップロード・モード選択・結果表示・インポート履歴 |
| API | `POST /api/v1/import/upload` | ファイルアップロード・DB 格納 |
| API | `GET /api/v1/import/logs` | インポート履歴一覧（最新50件） |
| API | `GET /api/v1/import/logs/{log_id}` | インポート履歴詳細 |

---

## 対象ファイル

- `backend/app/routers/import_router.py` — API ルーター
- `backend/app/services/import_service.py` — インポートビジネスロジック
- `backend/app/schemas/import_result.py` — Pydantic スキーマ（ImportResult・ImportLogOut・SkippedRow）
- `backend/app/models/transaction.py` — Transaction・ImportLog ORM モデル
- `backend/app/templates/import/index.html` — インポート画面テンプレート

---

## データモデル

### import_logs テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | ログID |
| `filename` | String | NOT NULL | アップロードされたファイル名 |
| `imported_at` | DateTime(timezone=True) | server_default=now() | インポート実行日時 |
| `total_rows` | Integer | NOT NULL | ファイル内のデータ行数（ヘッダー除く） |
| `imported_rows` | Integer | NOT NULL | DB に登録できた行数 |
| `skipped_rows` | Integer | NOT NULL | スキップした行数（エラー行を含む） |
| `error_rows` | Integer | NOT NULL | エラーが発生した行数 |
| `status` | String | NOT NULL | `success` / `partial` / `error` |
| `error_detail` | Text | nullable | エラーメッセージの改行結合文字列 |

### transactions テーブル（インポート関連カラム）

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `import_hash` | String(64) | nullable | インポート行を識別する SHA-256 ハッシュ。UNIQUE 制約なし |
| `is_transfer` | Boolean | NOT NULL | 資金移動フラグ（`【資金移動】` または `【ﾛｰﾝ】` カテゴリは True） |
| `transfer_detail` | String(200) | nullable | 資金移動行のカテゴリパスをそのまま格納 |

---

## 機能仕様

### Actual.TXT のファイル仕様

- **エンコーディング：** UTF-16LE（BOM 付き）
- **区切り文字：** タブ（TSV）
- **ヘッダー行：** 1行目がヘッダー。カラム名に全角スペースを含む場合がある（`日　付`、`メ　モ`）
- **カラム定義：**

| カラム名（ファイル） | 対応フィールド | 必須 | 説明 |
|---|---|---|---|
| `日　付`（`日付`） | `date` | 必須 | `YYYY/MM/DD` 形式 |
| `カテゴリー` | `category_id` | 必須 | スラッシュ区切りの階層パス |
| `アカウント` | `account_id` | 必須 | 口座コード |
| `入金額` | `income_amount` | 任意 | 空または `1,234` 形式の整数 |
| `出金額` | `expense_amount` | 任意 | 空または `1,234` 形式の整数 |
| `メ　モ`（`メモ`） | `memo` | 任意 | 自由テキスト |
| `グループ` | `group_id` | 任意 | グループコード |

- **ヘッダー認識：** カラム名を正規化（全角スペース・半角スペースを除去）してマッピング。認識できない場合は列位置（0〜6番目）で代替マッピングする

### インポートモード

| モード | `mode` パラメータ値 | 動作 |
|------|---|------|
| 置換 | `replace` | インポート前に既存 transactions を全件削除（`db.query(Transaction).delete()`）してからインポート |
| 追加 | `append` | 既存データを保持したまま新規追加。重複チェックなし |

- デフォルトは `replace`（フロントエンドの初期値）
- `replace` モード実行時はフロントエンドで confirm ダイアログを表示して確認を求める

### ローンデータの扱い（`skip_loan` オプション）

- `skip_loan=True` のとき、`【ﾛｰﾝ】` で始まるカテゴリパスの行をスキップする
- スキップした行は `skipped_rows` と `skipped_loan_rows` のカウントに加算される
- 「ローン登録」機能で元本を登録済みの場合に使用する

### カテゴリ階層の解析と upsert

- カテゴリパスを `full_path.split("/", 1)` で親（`parts[0]`）と子（`parts[1]`）に分割する
- 子カテゴリの場合、親カテゴリを先に upsert してから子カテゴリを作成する（再帰呼び出し）
- 既存の `full_path` と一致するカテゴリがあれば再利用し、なければ新規作成する
- `full_path` が親カテゴリのみ（スラッシュなし）の場合は親カテゴリ自体として登録する
- 新規作成されたカテゴリパスは `ImportResult.new_categories` に列挙される

### 資金移動の判定

- カテゴリパスが `【資金移動】` で始まる場合：`is_transfer=True`
- カテゴリパスが `【ﾛｰﾝ】` で始まる場合：`is_transfer=True`
- `is_transfer=True` の取引は月次集計から除外される
- `transfer_detail` にはカテゴリパス全体をそのまま格納する

### 資金移動の対向トランザクション自動生成

- `【資金移動】- {X}へ -`（送金側）の行を読み込んだとき、`【資金移動】- {送金元アカウント}から -` の対向レコードを自動生成する
- `【資金移動】- {X}から -`（受取側）の行を読み込んだとき、`【資金移動】- {受取アカウント}へ -` の対向レコードを自動生成する
- 対向のハッシュがファイル内にすでに存在する場合、または DB に登録済みの場合は生成をスキップする
- `【ﾛｰﾝ】` 行が存在する場合、対応する資金移動の対向生成を抑制する（ローン口座への二重登録防止）
- 対向生成による取引も `imported_rows` のカウントに含まれる

### 口座・グループの upsert

- **口座（Account）：** `code` で検索し、なければ `code` からプレフィックスを除去した名前で新規作成する
- **口座タイプの自動推定：** アカウントコードのプレフィックス（`10_`〜`13_` → cash、`30_`/`34_`/`54_`/`59_`/`5D_` → bank、`26_`/`28_`/`2b_`/`2B_` → e-money、`40_`〜`4N_` → card、それ以外 → other）
- **グループ（Group）：** `code` で検索し、なければコードから数字プレフィックスを除去した名前（例: `20_太郎` → `太郎`）で新規作成する

### ハッシュの算出

- `import_hash = SHA-256("{date}|{category}|{account}|{income}|{expense}|{memo}")`
- 対向トランザクションのハッシュは対向データから同じ方法で算出する
- `import_hash` に UNIQUE 制約はないため、同一ハッシュのレコードが複数存在しうる

### エラー行の扱い

| エラー種別 | 動作 |
|---|---|
| 必須項目不足（日付・カテゴリ・アカウントのいずれか空） | `errors += 1`・`skipped += 1`・`skipped_detail` に追加し次行へ |
| 日付フォーマットエラー（`YYYY/MM/DD` 以外） | `errors += 1`・`skipped += 1`・`skipped_detail` に追加し次行へ |
| その他の例外 | `errors += 1`・`error_messages` に追加し次行へ |
| 対向トランザクション生成失敗 | `errors += 1`・`error_messages` に追加して継続 |

- スキップされた行の詳細（行番号・日付・カテゴリ・アカウント・理由）は `ImportResult.skipped_detail` に格納され、画面にテーブル表示される

### インポートログの記録

- インポート完了後（コミット前）に `ImportLog` を作成・保存する
- `status` の決定ルール：
  - `errors == 0` → `"success"`
  - `errors > 0` かつ `imported > 0` → `"partial"`
  - `errors > 0` かつ `imported == 0` → `"error"`
- `error_detail` はエラーメッセージを改行で結合した文字列（なければ `None`）

### ImportResult レスポンス

| フィールド | 型 | 説明 |
|---|---|---|
| `status` | str | `success` / `partial` / `error` |
| `filename` | str | アップロードされたファイル名 |
| `mode` | str | `append` / `replace` |
| `total_rows` | int | ファイル内の総データ行数 |
| `imported_rows` | int | DB に登録できた行数（対向自動生成分を含む） |
| `skipped_rows` | int | スキップした行数 |
| `skipped_loan_rows` | int | `skip_loan=True` でスキップしたローン行数 |
| `error_rows` | int | エラーが発生した行数 |
| `deleted_rows` | int | `replace` モードで削除した件数 |
| `new_categories` | list[str] | 新規作成されたカテゴリパス一覧（重複除去済み） |
| `new_accounts` | list[str] | 新規作成されたアカウントコード一覧（重複除去済み） |
| `new_groups` | list[str] | 新規作成されたグループコード一覧（重複除去済み） |
| `error_detail` | str \| None | エラーメッセージの改行結合文字列 |
| `skipped_detail` | list[SkippedRow] | スキップされた行の詳細（行番号・日付・カテゴリ・アカウント・理由） |

### インポート画面（`/import`）

- **ファイル選択：** ドラッグ＆ドロップまたはファイル選択ボタン（`.txt`, `.TXT`, `.tsv`, `.csv` を受付）
- **モード選択：** ラジオボタンで `replace` / `append` を選択（デフォルト `replace`）
- **ローンオプション：** ラジオボタンで `skip_loan` を選択（デフォルト `false`）
- **インポート実行：** Alpine.js の `doUpload()` 関数が `FormData` で `POST /api/v1/import/upload` を呼び出す。`replace` モード時は confirm ダイアログを表示
- **結果表示：** レスポンスの `status` に応じて成功・一部成功・エラーを色分け表示。スキップ行の詳細テーブルも表示
- **成功後リロード：** `res.ok` の場合 `location.reload()` でインポート履歴を最新化
- **インポート履歴：** `GET /api/v1/import/logs` から取得した最新50件を Jinja2 でサーバーサイドレンダリング

---

## 実装上の注意点

- **UTF-16 デコード：** `content.decode("utf-16")` で BOM 付き UTF-16LE を自動認識する。デコード失敗時は UTF-8（`errors="replace"`）にフォールバックする
- **ヘッダーの BOM 除去：** `lines[0].lstrip("﻿").lstrip("​")` でヘッダー先頭の BOM 文字を除去してから CSV パースに渡す
- **カテゴリ分割：** `full_path.split("/", 1)` で 1 回だけ分割する（第2引数 `maxsplit=1` が必須）
- **資金移動判定：** `full_path.startswith("【資金移動】")` または `full_path.startswith("【ﾛｰﾝ】")` で判定する
- **`import_hash` の UNIQUE 制約なし：** 同一ファイルを複数回インポートしても DB エラーにならない。重複排除は `replace` モードで行う設計
- **Jinja2 テンプレートの Alpine.js バインディング：** `index.html` ではシングルクォート属性（`x-data="importForm()"`）を使用しているが、Alpine.js コンポーネント引数に Jinja2 の `tojson` を埋め込む場合はシングルクォート属性にすること
- **`imported_at` の表示：** テンプレートで `| jst` フィルターを使って JST 変換して表示している

---

## 動作確認チェックリスト

- [ ] `replace` モードで既存取引が全件削除された後にインポートされること
- [ ] `append` モードで既存データを保持したまま新規データが追加されること
- [ ] `replace` モード選択時にフロントエンドで confirm ダイアログが表示されること
- [ ] `skip_loan=true` のとき `【ﾛｰﾝ】` カテゴリ行がスキップされ、`skipped_loan_rows` に計上されること
- [ ] 同一ファイルを `append` モードで2回インポートしても DB エラーにならず重複登録されること
- [ ] カテゴリパスがスラッシュ区切りで親・子カテゴリに分割されて登録されること
- [ ] 未登録のカテゴリ・口座・グループが自動作成されること
- [ ] `new_categories` / `new_accounts` / `new_groups` に新規作成されたものが列挙されること
- [ ] `【資金移動】- {X}へ -` の行に対して `【資金移動】- {送金元}から -` の対向が自動生成されること
- [ ] 対向がファイル内に存在する場合は二重生成されないこと
- [ ] 必須項目（日付・カテゴリ・アカウント）が空の行がエラーとしてスキップされること
- [ ] `YYYY/MM/DD` 以外の日付フォーマットの行がエラーとしてスキップされること
- [ ] スキップされた行の詳細（行番号・理由）が結果テーブルに表示されること
- [ ] インポート完了後にステータス（success / partial / error）が正しく記録されること
- [ ] インポート履歴一覧に最新のインポート結果が表示されること
- [ ] ドラッグ＆ドロップでファイルを選択できること
- [ ] アップロード中は「インポート中...」と表示されボタンが無効化されること
