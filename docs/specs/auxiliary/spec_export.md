# 仕様：C-2 エクスポート

## 概要

取引データを Excel（.xlsx）または Actual.TXT（UTF-16LE TSV）形式でダウンロードする機能。
ユーザーは年・月・カテゴリ・口座・グループ・検索ワードなどの条件で絞り込んだうえでエクスポートでき、外部ツールや他の家計簿ソフトへのデータ連携に利用する。
エクスポート画面から各形式のリンク・フォームにアクセスし、ファイルを直接ダウンロードする。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/export` | エクスポート画面（形式選択・条件指定フォーム） |
| API | `GET /transactions/export/excel` | Excel（.xlsx）形式でエクスポート |
| API | `GET /transactions/export/actual_txt` | Actual.TXT（UTF-16LE TSV）形式でエクスポート |

---

## 対象ファイル

- `backend/app/routers/pages.py` — `/export`・`/transactions/export/excel`・`/transactions/export/actual_txt` ルートの実装
- `backend/app/templates/export/index.html` — エクスポート画面の Jinja2 テンプレート

---

## データモデル

エクスポート対象は `transactions` テーブル。以下のフィールドを出力に使用する。

| フィールド | 型 | 説明 |
|---|---|---|
| `date` | date | 取引日 |
| `category_full_path` | str（JOIN） | カテゴリのフルパス（例: `A30_通信費/インターネット`） |
| `account_code` | str（JOIN） | 口座コード |
| `group_code` | str（JOIN） | グループコード |
| `memo` | str | メモ |
| `income_amount` | int | 収入金額（0 の場合は空出力） |
| `expense_amount` | int | 支出金額（0 の場合は空出力） |
| `is_transfer` | bool | 資金移動フラグ（集計・出力制御に使用） |
| `created_at` | datetime | 作成日時（Actual.TXT の `created_after` フィルターに使用） |

---

## 機能仕様

### エクスポート画面（`/export`）

- `today_jst().isoformat()` で取得した本日日付をテンプレートに渡す。
- テンプレートは各エクスポート形式へのリンク・フォームを提供する。
- テンプレート内で Alpine.js バインディングを使用する場合は、シングルクォート属性でバインドする（後述の注意点参照）。

---

### Excel エクスポート（`GET /transactions/export/excel`）

#### クエリパラメータ

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `year` | int | なし | 絞り込み年 |
| `month` | int | なし | 絞り込み月（`year` と併用） |
| `category_id` | str → int | なし | カテゴリ ID |
| `account_id` | str → int | なし | 口座 ID |
| `group_id` | str → int | なし | グループ ID |
| `is_transfer` | bool | `False` | 資金移動を含むか |
| `search` | str | なし | フリーワード検索 |

#### 資金移動フラグの変換ロジック

| リクエスト値 | `effective_is_transfer` | 意味 |
|---|---|---|
| `False`（デフォルト） | `False` | 資金移動を除外 |
| `True` | `None` | 全件（資金移動を含む） |

#### データ取得

- `get_all_transactions` を呼び出して全件取得する（ページングなし）。
- カテゴリによる絞り込みはサブクエリで実装する（`joinedload` との重複 JOIN を避けるため）。

#### 出力ファイル仕様

| 項目 | 仕様 |
|---|---|
| シート名 | 「取引一覧」 |
| 列順 | 日付 / カテゴリ / アカウント / グループ / メモ / 収入 / 支出 |
| ヘッダースタイル | 青背景（`#4472C4`）、白文字、太字、センタリング |
| 収入・支出の数値書式 | `#,##0` |
| 列幅（文字数） | `[12, 40, 20, 20, 30, 14, 14]` |
| Content-Type | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |

#### ファイル名の決定ルール

| 条件 | ファイル名 |
|---|---|
| 年・月ともに未指定 | `transactions.xlsx` |
| 年のみ指定 | `transactions_YYYY.xlsx` |
| 年・月ともに指定 | `transactions_YYYY_MM.xlsx` |

---

### Actual.TXT エクスポート（`GET /transactions/export/actual_txt`）

#### クエリパラメータ

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `created_after` | date | なし | 指定日以降に作成された取引のみ出力 |
| `is_transfer` | bool | `True` | 資金移動を含むか |

#### 資金移動フラグの変換ロジック

| リクエスト値 | `effective_is_transfer` | 意味 |
|---|---|---|
| `True`（デフォルト） | `None` | 全件（資金移動を含む） |
| `False` | `False` | 資金移動を除外 |

#### データ取得

- `order_asc=True` で日付昇順に取得する（Actual へのインポート時の整合性を保つため）。

#### 出力ファイル仕様

| 項目 | 仕様 |
|---|---|
| ヘッダー行 | `日　付\tカテゴリー\tアカウント\t入金額\t出金額\tメ　モ\tグループ`（「日　付」「メ　モ」は全角スペース） |
| 日付フォーマット | `YYYY/MM/DD` |
| 金額フォーマット | 0 の場合は空文字、それ以外は数値をそのまま出力 |
| エンコード | UTF-16LE + BOM（`\xff\xfe`） |
| Content-Type | `text/plain; charset=utf-16` |
| ファイル名（RFC 5987） | URL エンコード形式で `Content-Disposition` ヘッダーに指定 |

#### ファイル名の決定ルール

| 条件 | ファイル名 |
|---|---|
| `created_after` 未指定 | `export.txt` |
| `created_after` 指定 | `export_YYYYMMDD.txt`（指定日の日付を使用） |

---

## 実装上の注意点

- **日付処理**: `date.today()` や `datetime.now()` は使用せず、必ず `jst.py` の `today_jst()` / `now_jst()` を使うこと。エクスポート画面で本日日付をテンプレートに渡す際も同様。
- **カテゴリ検索のサブクエリ**: `get_all_transactions` でカテゴリによる絞り込みを行う場合、`joinedload` による JOIN と重複しないようサブクエリを使用すること。
  ```python
  # OK
  matched_cat_ids = db.query(Category.id).filter(
      Category.full_path.ilike(f"%{search}%")
  ).subquery()
  q = q.filter(Transaction.category_id.in_(matched_cat_ids))

  # NG（joinedload と重複して SQLエラーになる）
  q = q.join(Category).filter(Category.full_path.ilike(...))
  ```
- **Jinja2 テンプレートの Alpine.js バインディング**: JSON データを HTML 属性に埋め込む場合はシングルクォート属性を使用し、`tojson` フィルターで出力すること。
  ```html
  {# OK #}
  <div x-data='myComponent({{ data | tojson }})'>

  {# NG — JSON の " が属性を途中で切る #}
  <div x-data="myComponent({{ data | tojson }})">
  ```
- **Actual.TXT のエンコード**: UTF-16LE + BOM（`\xff\xfe`）で出力すること。Python の `'utf-16'` コーデックを使用すると BOM が自動付与される。
- **ファイル名の RFC 5987 エンコード**: `Content-Disposition` ヘッダーには RFC 5987 形式（`filename*=UTF-8''...`）でファイル名を URLエンコードして指定すること。日本語ファイル名の文字化けを防ぐ。

---

## 動作確認チェックリスト

- [ ] `/export` 画面が正常に表示され、本日日付が渡されている
- [ ] Excel エクスポートがパラメータなしで正常にダウンロードできる（ファイル名: `transactions.xlsx`）
- [ ] Excel エクスポートで年のみ指定するとファイル名が `transactions_YYYY.xlsx` になる
- [ ] Excel エクスポートで年・月を指定するとファイル名が `transactions_YYYY_MM.xlsx` になる
- [ ] Excel のヘッダー行が青背景・白文字・太字・センタリングで表示される
- [ ] Excel の収入・支出列が `#,##0` 形式（カンマ区切り）で表示される
- [ ] Excel エクスポートで `is_transfer=False`（デフォルト）のとき資金移動取引が除外される
- [ ] Excel エクスポートで `is_transfer=True` のとき資金移動取引が含まれる
- [ ] Excel エクスポートでカテゴリ・口座・グループ・フリーワードによる絞り込みが正しく機能する
- [ ] Actual.TXT エクスポートがパラメータなしで正常にダウンロードできる（ファイル名: `export.txt`）
- [ ] Actual.TXT エクスポートで `created_after` を指定するとファイル名が `export_YYYYMMDD.txt` になる
- [ ] Actual.TXT が UTF-16LE + BOM で出力され、Actual に再インポートできる
- [ ] Actual.TXT のヘッダー行に全角スペースが含まれている（`日　付`・`メ　モ`）
- [ ] Actual.TXT エクスポートで `is_transfer=True`（デフォルト）のとき資金移動取引が含まれる
- [ ] Actual.TXT エクスポートで `is_transfer=False` のとき資金移動取引が除外される
- [ ] Actual.TXT の出力が日付昇順になっている
- [ ] 金額が 0 の場合、Actual.TXT の該当セルが空文字になっている
