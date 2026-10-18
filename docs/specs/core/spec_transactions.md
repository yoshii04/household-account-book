# 仕様：取引管理

## 概要

家計簿の収支取引を管理する中核機能。取引の一覧表示・新規入力・編集・削除に加え、定期取引パターンや過去取引からのコピー入力、複数取引の一括登録をサポートする。資金移動（口座間の振替）は通常取引と区別して2件ペアで作成される。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/transactions` | 取引一覧（フィルター・検索・ソート・削除・Excel出力） |
| 画面 | `/transactions/new` | 取引入力（パターン適用・コピー・一括登録） |
| 画面 | `/transactions/{tx_id}/edit` | 取引編集 |
| API | `GET /api/v1/transactions` | 取引一覧（フィルター・ページング） |
| API | `GET /api/v1/transactions/{tx_id}` | 取引詳細 |
| API | `GET /api/v1/transactions/recent/by-category/{category_id}` | カテゴリ別直近N件 |
| API | `GET /api/v1/transactions/search` | フリーワード検索 |
| API | `POST /api/v1/transactions` | 取引作成 |
| API | `POST /api/v1/transactions/transfer` | 資金移動取引作成 |
| API | `PUT /api/v1/transactions/{tx_id}` | 取引更新 |
| API | `DELETE /api/v1/transactions/{tx_id}` | 取引削除 |
| API | `GET /transactions/export/excel` | Excel エクスポート（ページルーター） |

---

## 対象ファイル

- `backend/app/routers/transactions.py` — APIルーター
- `backend/app/crud/transaction.py` — DBアクセス・ビジネスロジック
- `backend/app/models/transaction.py` — ORMモデル
- `backend/app/schemas/transaction.py` — Pydanticスキーマ
- `backend/app/routers/pages.py` — ページルーター（取引関連ルート）
- `backend/app/templates/transactions/list.html` — 取引一覧テンプレート
- `backend/app/templates/transactions/form.html` — 取引入力・編集テンプレート

---

## データモデル

### transactions テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | 取引ID |
| `date` | Date | NOT NULL, index | 取引日 |
| `category_id` | Integer | FK(categories.id), NOT NULL, index | カテゴリ（必ず子カテゴリを指す） |
| `account_id` | Integer | FK(accounts.id), NOT NULL | 口座 |
| `income_amount` | Integer | NOT NULL, default=0 | 入金額（円）。収入なら正値、支出なら0 |
| `expense_amount` | Integer | NOT NULL, default=0 | 出金額（円）。支出なら正値、収入なら0 |
| `memo` | String(500) | nullable | メモ |
| `group_id` | Integer | FK(groups.id), nullable | グループ |
| `is_transfer` | Boolean | NOT NULL, default=False, index | 資金移動フラグ |
| `transfer_detail` | String(200) | nullable | 資金移動の詳細メモ（カテゴリパスを格納） |
| `pattern_id` | Integer | FK(transaction_patterns.id), nullable, ondelete="SET NULL" | 紐付け元の定期取引パターン（パターン経由で作成された取引に設定される） |
| `import_hash` | String(64) | nullable, unique | インポート元レコードの識別ハッシュ |
| `created_at` | DateTime(timezone=True) | server_default=now() | 作成日時 |
| `updated_at` | DateTime(timezone=True) | server_default=now(), onupdate=now() | 更新日時 |

**リレーション：** `category`（Category）、`account`（Account）、`group`（Group）、`pattern`（TransactionPattern）

**補足：**
- `income_amount` と `expense_amount` のどちらか一方が正値で、もう一方は必ず 0
- `import_hash` は UNIQUE 制約あり（nullable のため NULL 値には制約が適用されない）
- 資金移動取引は `is_transfer=True` で識別され、月次集計から除外される
- `pattern_id` は `pattern_group_id`（transaction_patterns → pattern_groups）と同様に `SET NULL` とし、パターン削除時に紐付いていた取引は削除されない。パターンを使わない自由入力の場合は `NULL` のまま（必須ではない）
- `pattern_id` は「当月（対象期間）の記録状況チェック」機能で使用される（詳細は [spec_patterns.md](../auxiliary/spec_patterns.md) 参照）。既存取引への遡及的なバックフィルは行わない

---

## 機能仕様

### 取引一覧（`/transactions`）

- 初回アクセス時（フィルタパラメータなし）はデフォルトで**当月**を表示（`year`, `month` を `today_jst()` から設定）し、「資金移動を含む」チェックボックスもデフォルトで**オン**（`is_transfer=True` 扱い）にする
- フィルタパラメータ `f=1` が付与されている場合はデフォルト絞り込みを行わず、送信値をそのまま使用する。ただし `is_transfer` はチェックボックスの仕様上「未チェックで送信」すると値自体が送信されないため、`f=1` かつ `is_transfer` 未指定の場合は「明示的にチェックを外した」とみなして `False`（資金移動を除外）として扱う（`ids` 指定時も `is_transfer` の解決値自体は同様に `False` になるが、後述のとおり `ids` 指定時はこの値がクエリの絞り込みには使われない）
- `ids` パラメータ（カンマ区切りの取引ID）が指定された場合、IDフィルターバナーを表示し、ページネーションを無効化する。この場合、指定された ID の取引をそのまま取得するため `is_transfer` によるフィルタリングは行われない（`year`/`month`/`category_id` 等の他のフィルターも同様に適用されない）

**フィルター条件（`GET /api/v1/transactions` の Query パラメータ）：**

| パラメータ | 型 | 説明 |
|---|---|---|
| `year` | int | 取引日の年（省略時は全年） |
| `month` | int | 取引日の月（省略時は全月） |
| `category_id` | int | カテゴリID（親カテゴリ指定時は子カテゴリも含む） |
| `account_id` | int | 口座ID |
| `group_id` | int | グループID |
| `is_transfer` | bool | False（デフォルト）で資金移動を除外、True で全件表示。**この API 単体のデフォルトは常に `False`。**`/transactions` ページ（画面）では上記「初回アクセス時」のロジックにより初回のみ `True` がデフォルトになる点に注意（後述） |
| `search` | str | フリーワード検索（memo または category.full_path に部分一致） |
| `page` | int | ページ番号（1始まり、デフォルト=1） |
| `per_page` | int | 1ページの件数（デフォルト=50、最大=200） |
| `sort_by` | str | ソート列（`date`, `income_amount`, `expense_amount`, `created_at`, `category`, `account`, `group`） |
| `sort_dir` | str | ソート方向（`asc`, `desc`） |

**「資金移動を含む」チェックボックスのデフォルト値（`/transactions` ページ固有）：**

HTML の `<input type="checkbox">` は未チェック時にパラメータ自体を送信しないため、「初回アクセスで `is_transfer` が未指定」と「フォーム送信でチェックを外して `is_transfer` が未指定」を区別する必要がある。`/transactions` ページ（`backend/app/routers/pages.py` の `transactions_page()`）は、`year`/`month` の初回デフォルト判定と同じ `f`（フォーム送信フラグ）を用いて、次のように `is_transfer` のデフォルト値（`is_first_visit = not f and not ids`）を解決する。

| 状況 | `is_transfer` パラメータ | 解決される値 |
|---|---|---|
| 初回アクセス（`f` なし・`ids` なし） | 未指定 | `True` |
| 初回アクセス（`f` なし・`ids` なし） | 指定あり（`true`/`false`） | 送信値をそのまま使用 |
| フォーム送信済み（`f=1`）または `ids` 指定 | 未指定（チェックを外して送信） | `False` |
| フォーム送信済み（`f=1`）または `ids` 指定 | 指定あり（`true`） | `True` |
| フォーム送信済み（`f=1`）または `ids` 指定 | 指定あり（`false`） | `False` |

**`ids` 指定時の注意（重要）：** 上表の「解決される値」はチェックボックスの `checked` 表示にのみ使われ、`ids` 指定時のクエリ自体には適用されない。`ids` 指定時は `get_transactions()` が指定された ID の取引をそのまま取得するため（`year`/`month`/`category_id` 等の他のフィルターと同様）、資金移動取引であっても `ids` に含まれていれば表示される。レポート画面のドリルダウン経由（`ids` 指定）で実際に資金移動が表示されないのは、ドリルダウン元のレポート集計が資金移動を除外した上で ID を渡しているためであり、`is_transfer` フィルターによるものではない。

- この解決ロジックは `/transactions` ページ（HTML画面）のみに適用される。**`GET /api/v1/transactions`（JSON API）単体を呼び出した場合のデフォルトは常に `False`**（上記フィルター条件表のとおり）であり、この非対称デフォルトの対象外。レポート画面のドリルダウンモーダル（`base.html`）はこの JSON API を `is_transfer` 未指定で直接呼び出しており、月次集計（資金移動除外）との整合を前提にしているため変更しない
- `GET /transactions/export/excel`（Excel エクスポート）のエンドポイント自体のデフォルトも `False` のまま変更しない。「Excel出力」ボタンはクリック時点のフィルターフォームの実際のチェック状態をそのままクエリパラメータとして渡す実装（`exportExcel()` 関数）のため、ページ側の初期表示が資金移動を含む状態になれば、Excel出力もそれに追従する
- 「リセット」リンク（パラメータなしで `/transactions` へ遷移）、および「フィルターを解除」リンク（IDフィルターバナーの解除、同じくパラメータなしで `/transactions` へ遷移）は、いずれも初回アクセス扱いとなるため、遷移後は資金移動を含む表示に戻る

**ソート仕様：**
- デフォルト：`sort_by=created_at`, `sort_dir=desc`（ページ画面では `created_at` がデフォルト）
- `category`・`account`・`group` のソートはスカラーサブクエリを使用（JOIN は `joinedload` と重複するため不可）
- 主キー（`id`）を補助ソートとして常に末尾に追加し、同値行の順序を安定させる

**カテゴリフィルターの実装：**
- 親カテゴリIDが指定された場合、子カテゴリIDのサブクエリを使って `category_id IN (子ID一覧) OR category_id == 親ID` で絞り込む

**フリーワード検索の実装：**
- `Transaction.memo` に `ILIKE %search%`
- `Category.full_path` に `ILIKE %search%`（JOIN でなくサブクエリで対応）
- 上記を OR 条件で検索

**レスポンス（`TransactionListOut`）：**
```json
{
  "items": [...],
  "total": 123,
  "page": 1,
  "per_page": 50
}
```

各アイテムに `category_full_path`、`account_code`、`group_code`、`parent_category_id` を付加。

### 取引一覧の Excel エクスポート（`/transactions/export/excel`）

- 取引一覧と同じフィルター条件（`year`, `month`, `category_id`, `account_id`, `group_id`, `is_transfer`, `search`）を受け付ける
- ページネーションなしで全件を取得・出力する
- ヘッダー：日付・カテゴリ・アカウント・グループ・メモ・収入・支出
- ファイル名：`transactions[_年][_月].xlsx`（フィルター条件により可変）
- 収入・支出列は `#,##0` 形式
- フロントエンドから `exportExcel()` 関数経由で呼び出し、現在のフィルターフォーム値をクエリパラメータとして付与

### カテゴリ別直近N件（`GET /api/v1/transactions/recent/by-category/{category_id}`）

- 指定カテゴリの最新N件（デフォルト10件、最大50件）を取得する
- `is_transfer=False` の取引のみを対象とする
- 取引入力フォームでカテゴリ選択後に自動呼び出しされ、過去取引の参照・コピーを補助する

### フリーワード検索（`GET /api/v1/transactions/search`）

- クエリパラメータ `q`（最小長1）でメモ・カテゴリ・口座コードを横断検索する
- `is_transfer=False` の取引のみを対象とする
- 取引入力フォームの「フリーワード検索」セクションで使用し、過去取引の一括選択・コピーを補助する
- `Category` と `Account` は JOIN で取得（`is_transfer=False` のみ対象のため `joinedload` との重複なし）

### 取引作成（`/transactions/new`）

**通常取引の入力フォーム項目：**

| 項目 | 必須 | バリデーション |
|------|------|---------------|
| 日付 | 必須 | ISO 8601 形式（デフォルト：今日） |
| 親カテゴリ | 必須 | セレクトボックス（is_transfer フラグを data 属性で保持） |
| 子カテゴリ | 任意 | 親選択後に `/api/v1/categories/{id}/children` から動的取得。子がない場合は親カテゴリを直接使用 |
| アカウント | 必須 | is_active=True の口座のみ表示 |
| 出金額 | 任意 | 0以上の整数 |
| 入金額 | 任意 | 0以上の整数 |
| メモ | 任意 | 最大500文字 |
| グループ | 任意 | |

**フォームの送信方式：** Alpine.js の `@submit.prevent` + `fetch` + JSON 送信（通常の form submit ではない）

**コピー機能：**
- URLパラメータ `copy_from_id={tx_id}` 指定時、指定取引のデータをフォームに初期値として反映
- フォーム上部に「コピー元データを基に入力」の案内を表示（`is_copy=True`）

**パターン適用機能：**
- URLパラメータ `pattern_id={id}` 指定時、該当パターンをフォームに自動適用（`init_pattern` として JSON で埋め込まれる）
- 「パターンから入力」ボタン（⚡）からモーダルでパターンを選択して適用することも可能
- パターン適用後、取引保存時に次回支払日をトーストで表示する（月次：翌月同日、年次：次回支払月）
- `/transactions/new?pattern_id=X` 経由で開いたフォームは、送信ペイロードに `pattern_id` を含めて保存する（`transactions.pattern_id` に記録される）。パターンを使わない自由入力の場合 `pattern_id` は送信しない（`NULL` のまま）

**一括登録機能：**
- フリーワード検索結果から複数取引をチェックボックスで選択し、日付・金額を調整して一括登録できる
- 「グループから一括入力」ボタン（🗂）からパターングループを選択して、グループ内パターンを一括登録できる
- 資金移動専用グループの場合は `POST /api/v1/transactions/transfer` を使用
- 通常グループの場合は `POST /api/v1/transactions` を逐次呼び出し

**デフォルト日付：** `today_jst()` で取得した当日日付

### 取引編集（`/transactions/{tx_id}/edit`）

- フォームは新規入力と同じテンプレートを使用（`mode="edit"` で分岐）
- 取引が存在しない場合は HTTP 404 を返す
- 保存後は `return_url` パラメータ（取得元の一覧フィルター条件）へリダイレクト

**`TransactionUpdate` の更新対象フィールド：**
`date`, `category_id`, `account_id`, `income_amount`, `expense_amount`, `memo`, `group_id`
（`is_transfer`, `transfer_detail` は更新不可）

### 資金移動取引の作成（`POST /api/v1/transactions/transfer`）

- 1リクエストで**出金・入金の2件**のトランザクションを同時に作成する
- **カテゴリの自動生成：** `upsert_transfer_category` 関数で以下のパスのカテゴリを取得または作成する
  - 出金側：`【資金移動】- {to_account.code}へ -`
  - 入金側：`【資金移動】- {from_account.code}から -`
- 両カテゴリの親は `【資金移動】`（`is_transfer=True`）で、存在しない場合は自動作成
- 作成された両カテゴリの `is_transfer=True`
- `TransferOut` レスポンスは `expense_tx`（出金）と `income_tx`（入金）の2件を返す
- リクエストボディに任意項目 `pattern_id` を指定した場合、作成される出金・入金の**両方**の取引に同じ `pattern_id` が設定される（資金移動専用パターンを適用した場合）

**`TransferCreate` リクエストボディ：**

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `date` | Date | 必須 | 取引日 |
| `from_account_id` | int | 必須 | 送金元口座ID |
| `to_account_id` | int | 必須 | 送金先口座ID |
| `amount` | int | 必須 | 移動金額（円） |
| `memo` | str | 任意 | メモ |
| `group_id` | int | 任意 | グループID |
| `pattern_id` | int | 任意 | 紐付けるパターンID（出金・入金の両方の取引に同じ値が設定される） |

フォームでは送金元と送金先に同一口座を選択するとアラートを表示して送信を阻止する。

### 取引削除（`DELETE /api/v1/transactions/{tx_id}`）

- 取引が存在しない場合は HTTP 404 を返す
- 特に削除制約なし（関連レコードへの参照制約なし）
- フロントエンドからは confirm ダイアログで確認後に `fetch` で削除し、成功後に画面をリロード

---

## 実装上の注意点

- **カテゴリ検索はサブクエリを使うこと：** `get_transactions` では `joinedload` による JOIN が既に発生しているため、カテゴリで絞り込む場合は重複 JOIN を避けるためサブクエリを使用する（`crud/transaction.py` 参照）
- **JST タイムゾーン：** 取引一覧の当月デフォルト表示・取引入力フォームのデフォルト日付は `today_jst()` で当日を取得する（`date.today()` は使用しない）
- **Jinja2 テンプレートへの JSON 埋め込み：** テンプレートに Alpine.js バインディングが含まれるため、`x-data` 属性はシングルクォートを使用すること（例：`x-data='patternRegModal({{ data | tojson }})'`）
- **`<script>` タグへの JSON 埋め込み：** `form.html` の `_ACCOUNTS_LIST` 等は `<script>` 内で `{{ accounts_data | tojson }}` で埋め込んでいるが、date/datetime オブジェクトは `tojson` でシリアライズできないため、テンプレートに渡す前に `str()` または `.isoformat()` で変換すること
- **パターンの date 除去：** `new_transaction_page` では `get_pattern` の返値から `datetime`/`date` 型のフィールドを除去してから `init_pattern` として埋め込む（`form.html` の `tojson` シリアライズのため）
- **`init_date` のバリデーション：** URLパラメータ `date` で日付を渡す場合、ISO 8601 形式以外の文字列は `date.fromisoformat()` で検証し、不正値は `None` に置き換える（JSインジェクション対策）
- **チェックボックスのデフォルト値と `f` フラグ：** HTML の `<input type="checkbox">` は未チェック時に値を送信しないため、Query パラメータのデフォルト値を単純に `True` にすると「初回アクセス」と「明示的にチェックを外した送信」を区別できなくなる。`is_transfer` は `year`/`month` と同じく `f`（フォーム送信フラグ）で両者を区別して解決する（詳細は上記「『資金移動を含む』チェックボックスのデフォルト値」参照）。同様のチェックボックス系フィルターを追加する際はこのパターンを踏襲すること

---

## 動作確認チェックリスト

- [ ] 取引一覧：初回アクセス時（`f` パラメータなし）で当月が自動選択されること
- [ ] 取引一覧：初回アクセス時（`f` パラメータなし）で「資金移動を含む」チェックボックスがオン（資金移動を含む表示）になっていること
- [ ] 取引一覧：フィルターフォーム送信時（`f=1`）に「資金移動を含む」チェックを外して絞り込むと、資金移動が除外されること
- [ ] 取引一覧：年・月・カテゴリ・アカウント・グループ・メモ検索の各フィルターが正しく機能すること
- [ ] 取引一覧：「資金移動を含む」チェックオンで資金移動取引も表示されること
- [ ] 取引一覧：`ids` 指定時は `is_transfer` によるフィルタリングを行わず、指定された ID の取引がそのまま表示されること（レポート画面からのドリルダウンで実際に資金移動が表示されないのは、ドリルダウン元の集計が資金移動を除外した ID のみを渡しているためであり、月次集計との整合はこの経路で担保される）
- [ ] 取引一覧：各列のヘッダークリックでソートが切り替わり、同列クリックで昇順・降順が反転すること
- [ ] 取引一覧：ページネーションが50件単位で機能すること
- [ ] 取引一覧：削除ボタンで confirm 後に取引が削除されること
- [ ] 取引一覧：Excel出力ボタンで現在のフィルター条件が引き継がれること
- [ ] 取引入力：親カテゴリ選択後に子カテゴリが動的にロードされること
- [ ] 取引入力：カテゴリ選択後にそのカテゴリの直近10件が表示されること
- [ ] 取引入力：「↑ 使う」ボタンで過去取引の内容（カテゴリ・金額・メモ等）がフォームに転記されること
- [ ] 取引入力：フリーワード検索でメモ・カテゴリを横断検索できること
- [ ] 取引入力：一括登録で複数取引を選択して日付・金額を変更してまとめて登録できること
- [ ] 取引入力：「パターンから入力」でパターンをフォームに適用できること
- [ ] 取引入力：パターン適用後に取引保存で次回支払日がトーストで表示されること
- [ ] 取引入力：グループから一括入力で通常パターンが一括登録できること
- [ ] 取引入力：`pattern_id` クエリパラメータ経由で入力したフォームを送信すると `transactions.pattern_id` に値が保存されること
- [ ] 取引入力：パターンを使わない自由入力で送信すると `transactions.pattern_id` が `NULL` のままであること
- [ ] 資金移動：`【資金移動】` 親カテゴリ選択時に送金元・送金先・金額フォームに切り替わること
- [ ] 資金移動：送信後に出金・入金の2件が作成されること
- [ ] 資金移動：送金元・送金先カテゴリが `【資金移動】- {code}へ -` / `- {code}から -` 形式で自動生成されること
- [ ] 資金移動：送金元と送金先に同じ口座を選択するとアラートが表示されること
- [ ] 資金移動：`pattern_id` を指定して送信すると、出金・入金の両方の取引に同じ `pattern_id` が設定されること
- [ ] パターン削除後も、紐付いていた取引の `pattern_id` が `NULL` になるだけで取引自体は削除されないこと（SET NULL）
- [ ] 取引編集：既存取引の内容が初期値として表示されること
- [ ] 取引編集：保存後に元の一覧（return_url）へリダイレクトされること
- [ ] コピー機能：`copy_from_id` パラメータでコピー元のデータがフォームに反映されること
