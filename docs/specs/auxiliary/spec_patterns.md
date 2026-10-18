# 仕様：定期取引パターン管理

## 概要

毎月・毎年など定期的に発生する収支取引を「パターン」として登録・管理する機能。支払日が到来したパターンを一覧表示して登録漏れを防ぐほか、過去の取引履歴からパターン候補を自動分析し、新規登録の手間を省く。パターンは「パターングループ」で束ねて管理でき、資金移動専用グループにも対応する。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/patterns` | 定期取引パターン管理（一覧・作成・編集・削除） |
| API | `GET /api/v1/patterns` | パターン一覧（有効/全件切り替え可） |
| API | `GET /api/v1/patterns/analyze` | 履歴からパターン候補を分析 |
| API | `GET /api/v1/patterns/due` | 今日が支払日のパターン一覧 |
| API | `GET /api/v1/patterns/{id}` | パターン詳細 |
| API | `POST /api/v1/patterns` | パターン作成 |
| API | `PUT /api/v1/patterns/{id}` | パターン更新 |
| API | `DELETE /api/v1/patterns/{id}` | パターン削除 |
| API | `GET /api/v1/pattern-groups` | パターングループ一覧 |
| API | `GET /api/v1/pattern-groups/{id}` | パターングループ詳細 |
| API | `POST /api/v1/pattern-groups` | パターングループ作成 |
| API | `PUT /api/v1/pattern-groups/{id}` | パターングループ更新 |
| API | `DELETE /api/v1/pattern-groups/{id}` | パターングループ削除 |

※ 当月（対象期間）支払い状況チェック機能は既存エンドポイントのレスポンス拡張のみで実現しており、新規エンドポイントの追加はない。ただし `GET /api/v1/patterns/due` は同判定結果を用いて、対象期間について記録済みのパターンをレスポンスから除外するフィルター条件としても使用する。

---

## 対象ファイル

- `backend/app/routers/patterns.py` — パターン APIルーター
- `backend/app/routers/pattern_groups.py` — パターングループ APIルーター
- `backend/app/crud/pattern.py` — DBアクセス・ビジネスロジック（パターン）。対象期間の記録状況判定・`get_unrecorded_patterns()` を含む
- `backend/app/crud/pattern_group.py` — DBアクセス・ビジネスロジック（パターングループ）
- `backend/app/models/pattern.py` — ORMモデル（TransactionPattern）
- `backend/app/models/pattern_group.py` — ORMモデル（PatternGroup）
- `backend/app/models/transaction.py` — `Transaction.pattern_id` カラム・`pattern` リレーション（定義本体は [spec_transactions.md](../core/spec_transactions.md) 参照）
- `backend/app/schemas/pattern.py` — Pydanticスキーマ（パターン）。`is_current_period_recorded` / `current_period_transaction_id` を含む
- `backend/app/schemas/pattern_group.py` — Pydanticスキーマ（パターングループ）
- `backend/app/routers/pages.py` — ページルーター（`/patterns` ルート）
- `backend/app/templates/patterns/index.html` — パターン管理テンプレート（Alpine.js使用）。「未記録」バッジ表示を含む
- `frontend/static/css/style.css` — 「未記録」バッジ用スタイル

---

## データモデル

### transaction_patterns テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | パターンID |
| `name` | String(200) | NOT NULL | パターン名 |
| `frequency` | String | NOT NULL | 頻度（`monthly` / `annual` / `daily` / `other`） |
| `category_id` | Integer | FK(categories.id), NOT NULL | カテゴリ（子カテゴリを指す） |
| `account_id` | Integer | FK(accounts.id), NOT NULL | 支払元口座 |
| `to_account_id` | Integer | FK(accounts.id), nullable | 資金移動先口座（資金移動パターンのみ） |
| `group_id` | Integer | FK(groups.id), nullable | グループ |
| `pattern_group_id` | Integer | FK(pattern_groups.id), nullable, ondelete="SET NULL" | パターングループ |
| `typical_amount` | Integer | NOT NULL | 通常金額（円） |
| `is_income` | Boolean | NOT NULL, default=False | 収入フラグ（True=収入、False=支出） |
| `memo_template` | String | nullable | メモテンプレート |
| `payment_day_of_month` | Integer | nullable | 支払日（日）。`monthly` / `annual` で使用 |
| `payment_month_of_year` | Integer | nullable | 支払月（月）。`annual` の場合に使用 |
| `sort_order` | Integer | NOT NULL, default=0 | 表示順（昇順） |
| `is_active` | Boolean | NOT NULL, default=True | 有効フラグ |

**リレーション：** `category`（Category）、`account`（Account）、`to_account`（Account）、`group`（Group）、`pattern_group`（PatternGroup）

**補足：**
- `to_account_id` が設定されている場合は資金移動パターンとして扱われる
- `payment_day_of_month` が未設定の場合、`last_payment_date` / `next_payment_date` の計算は不可（None を返す）
- `annual` の場合は `payment_month_of_year` も必須
- `transactions.pattern_id`（`transaction_patterns.id` への任意 FK、`ondelete="SET NULL"`）でパターン経由の取引と紐付けられる。パターンを削除しても紐付いていた取引は削除されず `pattern_id` が `NULL` になる（詳細は [spec_transactions.md](../core/spec_transactions.md) 参照）

---

### pattern_groups テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | グループID |
| `name` | String | NOT NULL, UNIQUE | グループ名（重複不可） |
| `description` | String | nullable | 説明 |
| `sort_order` | Integer | NOT NULL, default=0 | 表示順（昇順） |
| `is_transfer_only` | Boolean | NOT NULL, default=False | 資金移動専用グループフラグ |

---

## 機能仕様

### パターン一覧（`GET /api/v1/patterns`）

- クエリパラメータ `include_inactive`（デフォルト `False`）で有効パターンのみ / 全件を切り替える
- `sort_order` 昇順でソートして返す
- レスポンスには各パターンに対して計算済みの `last_payment_date` / `next_payment_date` を含む
- レスポンスには対象期間の記録状況を示す `is_current_period_recorded`（bool、デフォルト `False`）と、記録済み取引の詳細リンク用 `current_period_transaction_id`（int、nullable）を含む（判定ロジックは後述「当月（対象期間）の記録状況判定」参照）
- 記録状況の判定は、一覧対象パターン群の `category_id` / `account_id` / `group_id` / `pattern_id` の集合に対しまとめて1クエリで対象期間の取引を取得して行い、N+1 クエリを発生させない

---

### 今日が支払日のパターン一覧（`GET /api/v1/patterns/due`）

- `today_jst()` で当日の日付（JST）を取得する
- 以下の条件をすべて満たすパターンを返す:
  - `is_active = True`
  - `payment_day_of_month == today.day`
  - `frequency == 'monthly'` の場合: 上記のみで対象
  - `frequency == 'annual'` の場合: さらに `payment_month_of_year == today.month` も一致する場合のみ対象
  - 対象期間について記録済み（`is_current_period_recorded == True`）のパターンは除外する（判定方式は後述「当月（対象期間）の記録状況判定」を参照）
- レスポンスには `GET /api/v1/patterns` と同様に `is_current_period_recorded` / `current_period_transaction_id` を含む（上記フィルターにより、残るパターンは全件 `is_current_period_recorded = false` になる）

---

### パターン候補の自動分析（`GET /api/v1/patterns/analyze`）

- 登録済み取引を `(category_id, account_id, group_id)` の組み合わせでグループ化する
- **6件以上**の取引が存在するグループのみを分析対象とする
- 取引日の平均発生間隔（日数）によって頻度を自動判定する:

| 平均間隔 | 最低件数 | 判定頻度 |
|---|---|---|
| 20〜45日 | — | `monthly` |
| 300〜400日 | — | `annual` |
| 0〜20日 | 5件以上 | `daily` |
| それ以外 | — | `other` |

- 最頻出のメモ文字列を `memo_template` の候補として提案する
- `typical_amount` は取引金額の平均値（収入と支出の多い方）を使用する
- 結果は `frequency` 順（`monthly` → `annual` → `daily` → `other`）、次いで `occurrence_count` 降順でソートする
- 既登録のパターンとの重複チェックは行わない（同じ組み合わせが候補に含まれる場合がある）

---

### 次回・前回支払日の計算（`last_payment_date` / `next_payment_date`）

- `payment_day_of_month` が未設定の場合は両方 `None` を返す
- 月末を超える日付は `clamp_day_to_month`（`utils/date_utils.py`）で月末に丸める
- **実績ベースの分岐：** 算出前に対象期間（後述）が「記録済み」か「未記録」かを判定し、結果によって次回支払日の扱いが変わる
  - **対象期間内が記録済み**（`is_current_period_recorded = True`）→ 記録があるため進めてよいと判断し、以下の従来ロジックどおり支払日ベースで算出する
  - **対象期間内が未記録**（`is_current_period_recorded = False`）→ `next_payment_date` は「対象期間内の支払日」のまま据え置く（先送りしない）。あわせてレスポンスの `is_current_period_recorded` は `false` を返す
  - **警告タイミングに猶予期間はない：** 対象期間の支払日を1日でも過ぎて未記録であれば、即座に「未記録」（`is_current_period_recorded = false`）として扱う

**`monthly` の場合（記録済みのときの算出ロジック）:**
- 当月の支払日（= `today.year/today.month/payment_day_of_month`、月末丸め）が今日以前 → `last=当月の支払日`、`next=翌月の支払日`
- 当月の支払日が今日より後 → `last=前月の支払日`、`next=当月の支払日`

**`annual` の場合（記録済みのときの算出ロジック）:**
- `payment_month_of_year` が必要（未設定の場合は `None`）
- 当年の支払日（= `today.year/payment_month_of_year/payment_day_of_month`、月末丸め）が今日以前 → `last=当年の支払日`、`next=翌年の支払日`
- 当年の支払日が今日より後 → `last=前年の支払日`、`next=当年の支払日`

---

### 当月（対象期間）の記録状況判定（`is_current_period_recorded`）

支払日を過ぎても実際に取引として記録していない場合に、パターン一覧・ダッシュボードで「未記録」であることを判別できるようにする機能。この判定結果は `GET /api/v1/patterns/due`（今日が支払日のパターン一覧）でも、対象期間について記録済みのパターンをレスポンスから除外するフィルター条件として使用する。

**対象期間の定義：**

| frequency | 対象期間 |
|---|---|
| `monthly` | 当月1日〜末日 |
| `annual` | 当年の `payment_month_of_year` の1日〜末日 |
| `daily` / `other` | 対象外（都度記録が前提のため、記録状況チェックの対象にしない） |

**判定方式（ハイブリッド）：**

`pattern_id` は今後作成される取引にしか付与されないため、以下の2段構えで判定する。

1. **優先：** 対象期間内に `transactions.pattern_id` が一致する取引が存在するか
2. **フォールバック：** `pattern_id` が `NULL` の取引でも、以下をすべて満たす取引が対象期間内に存在するか
   - `category_id` + `account_id`（資金移動パターンは `to_account_id` も含む）が一致する
   - **`group_id` の非対称一致：** パターンの `group_id` が設定されている場合のみ、取引側の `group_id` が同じ値であることを追加で要求する。パターンの `group_id` が `NULL`（グループ未指定）の場合は、取引側の `group_id` の値を問わない（取引側が `NULL` でも何らかのグループが設定されていても一致とみなす）

フォールバックにより、パターンを使わず手動入力した取引や、「先月分をコピーして当月分を作成する」運用（取引一覧からのコピー入力 `copy_from_id`）で作成した取引も、コピー元の `category_id` / `account_id` / `group_id` を引き継ぐため「記録済み」と判定できる（この運用専用の追加実装は不要）。

**`group_id` を非対称に扱う理由：** `category_id` + `account_id` を共有するが `group_id` が異なる複数パターンが存在する場合（例：同じカテゴリ・口座の支払いを人別グループ違いで別パターンとして登録しているケース）、一方のグループの記録がもう一方のパターンにも「記録済み」として誤って波及するのを防ぐための条件。逆に `group_id` を対称的な厳密一致（`NULL` 同士も一致とみなす）にすると、グループ未指定のパターンに対してグループタグ付きの取引が入力された場合に、従来「記録済み」だったものが新たに「未記録」に変わる回帰が生じるため、非対称マッチングを採用している。

**判定に含まれない・対応しない事項：**
- `pattern_id` が未設定の既存取引に対する遡及的なバックフィル処理は行わない
- 過去取引に後から `pattern_id` を紐付け直す編集 UI は提供しない

**`current_period_transaction_id`：**
- 判定で一致した取引（優先条件が一致すればそれを、なければフォールバックで一致した取引を）の ID を返す。詳細画面へのリンクに使用する
- 該当取引がない場合は `null`

---

### パターン一覧のフロントエンド表示（未記録バッジ）

- `patterns/index.html`：支払日情報セルに「未記録」バッジ（赤系）を表示する
- 表示条件：`is_current_period_recorded = false` かつ対象期間の支払日を過ぎている場合

---

### パターングループ管理

- グループ名（`name`）は UNIQUE 制約があり、重複登録はエラーになる
- グループを削除すると、所属するパターンの `pattern_group_id` は `NULL` に設定される（`ondelete="SET NULL"` によるカスケード）。パターン自体は削除されない
- `is_transfer_only = True` のグループは資金移動パターン専用として区別して表示できる

---

### パターンの作成・更新（`POST /api/v1/patterns`、`PUT /api/v1/patterns/{id}`）

- `is_income` フラグで収入 / 支出を区別する
- `to_account_id` を指定する場合は資金移動パターンとなり、対応するカテゴリは `【資金移動】` 系を使用することを推奨
- `is_active = False` に設定することでパターンを無効化できる（削除せずに一時停止）

---

### パターンの削除（`DELETE /api/v1/patterns/{id}`）

- パターンを物理削除する
- 関連する取引データには影響しない（取引の `category_id` 等はそのまま残る）。紐付いていた取引の `pattern_id` は `NULL` になる（`ondelete="SET NULL"`）が、取引自体は削除されない

---

## 実装上の注意点

- **日付処理:** `today_jst()` / `now_jst()`（`app/jst.py`）を必ず使用する。`date.today()` や `datetime.now()` はサーバーのタイムゾーンに依存するため使用禁止
- **月末丸め:** `payment_day_of_month` から実際の日付を算出する際は `utils/date_utils.py` の `clamp_day_to_month` を使用する（例: 31日指定で2月なら28日/29日に丸める）
- **Jinja2 + Alpine.js のJSON埋め込み:** `index.html` では Alpine.js の `x-data` バインディングに JSON を渡す場合、シングルクォート属性を使うこと
  ```html
  {# OK #}
  <div x-data='myComponent({{ data | tojson }})'>
  {# NG — JSON の " が属性を途中で切る #}
  <div x-data="myComponent({{ data | tojson }})">
  ```
- **カテゴリ検索:** パターン一覧にカテゴリフィルターを追加する場合は JOIN ではなくサブクエリを使用する（`joinedload` と重複 JOIN による SQLエラーを防ぐ）
- **`annual` パターンの `/due` 判定:** 月と日の両方が一致する場合のみ返す。`payment_month_of_year` が `None` の場合は `/due` の対象外とする
- **記録状況判定の N+1 回避:** `_to_dict()` の呼び出し元（`get_patterns`・`get_due_patterns` 等）で対象パターン群の `category_id` / `account_id` / `group_id` / `pattern_id` の集合に対しまとめて1クエリで対象期間の取引を取得する。パターンごとに個別クエリを発行しないこと
- **`/due` のフィルター順序:** `get_due_patterns` は「支払日一致」の絞り込み結果に対して記録状況を計算するのではなく、DB クエリで絞り込んだパターン群に対して先に `recorded_lookup` を構築してから、支払日一致 かつ 未記録の条件でフィルターする（`_filter_unrecorded` と対称な処理順序）
- **記録状況判定の対象期間:** `daily` / `other` 頻度のパターンは記録状況チェックの対象外（`is_current_period_recorded` は常に `False` のまま、または判定自体をスキップする）
- **フォールバックの `group_id` 非対称マッチング:** フォールバック判定に `group_id` を条件として加える際、パターンの `group_id` が `NULL` の場合に取引側の `group_id` まで条件に含めない（`IS NULL` を要求しない）こと。対称的な厳密一致にすると、グループ未指定パターンに対する既存の判定結果が変わる回帰を招く

---

## 動作確認チェックリスト

- [ ] `/patterns` 画面が正常に表示される
- [ ] パターンを新規作成できる（monthly / annual / daily / other の各頻度）
- [ ] パターンを編集できる（金額・支払日・カテゴリ・グループ等を変更）
- [ ] パターンを削除できる（削除後に一覧から消える）
- [ ] `is_active = False` にしたパターンがデフォルト一覧（`include_inactive=False`）に表示されない
- [ ] `include_inactive=True` にすると無効パターンも一覧に表示される
- [ ] `GET /api/v1/patterns/due` が今日の支払日に該当するパターンのみ返す
  - [ ] `monthly`: `payment_day_of_month == today.day` で一致
  - [ ] `annual`: `payment_day_of_month == today.day` かつ `payment_month_of_year == today.month` で一致
  - [ ] 対象期間について記録済み（`is_current_period_recorded = true`）のパターンはレスポンスに含まれないこと
  - [ ] 支払日当日に取引を記録すると、以降 `GET /api/v1/patterns/due` のレスポンスから当該パターンが消えること
- [ ] `GET /api/v1/patterns/analyze` がパターン候補を正しく返す
  - [ ] 6件未満のグループは候補に含まれない
  - [ ] 既登録の組み合わせは候補に含まれない
  - [ ] `frequency` 判定が正しく行われる（monthly / annual / daily / other）
- [ ] `last_payment_date` / `next_payment_date` が正しく計算される
  - [ ] `payment_day_of_month` 未設定の場合は `None` を返す
  - [ ] 月末（31日等）指定で短い月でも正しく月末に丸められる
  - [ ] `monthly`: 今日が支払日より後なら `last=当月`、`next=翌月`（対象期間が記録済みの場合）
  - [ ] `annual`: 当年支払日が今日より後なら `last=前年`、`next=当年`（対象期間が記録済みの場合）
- [ ] 当月（対象期間）の記録状況判定（`is_current_period_recorded`）
  - [ ] `pattern_id` を指定して取引を作成すると、対象期間内であれば `is_current_period_recorded = true` になる
  - [ ] `pattern_id` が `NULL` の取引でも、`category_id` + `account_id`（パターンに `group_id` が設定されている場合は `group_id` も含む）が一致すれば対象期間内で `is_current_period_recorded = true` になる（フォールバック）
  - [ ] 資金移動パターンでは `to_account_id` も一致条件に含まれる
  - [ ] パターンに `group_id` が設定されている場合、`category_id` + `account_id` が一致していても取引側の `group_id` が異なれば `is_current_period_recorded = false` のままになる（グループ違いパターン間の誤判定防止）
  - [ ] パターンの `group_id` が `NULL`（グループ未指定）の場合、取引側の `group_id` の値に関わらず `category_id` + `account_id` の一致のみで `is_current_period_recorded = true` になる（回帰防止の確認）
  - [ ] 対象期間内に該当取引がない場合、`is_current_period_recorded = false` かつ `current_period_transaction_id = null` になる
  - [ ] 支払日を1日でも過ぎて未記録の場合、猶予期間なく即座に `is_current_period_recorded = false` になる
  - [ ] 支払日を過ぎても未記録の場合、`next_payment_date` が対象期間内の支払日のまま据え置かれる（先送りされない）
  - [ ] `daily` / `other` 頻度のパターンは記録状況チェックの対象外である
  - [ ] `GET /api/v1/patterns` と `GET /api/v1/patterns/due` の両方のレスポンスに `is_current_period_recorded` / `current_period_transaction_id` が含まれる
  - [ ] `/patterns` 画面で未記録パターンに「未記録」バッジが表示される
- [ ] パターングループを作成できる
- [ ] パターングループを削除しても所属パターンは削除されず `pattern_group_id` が NULL になる
- [ ] パターングループ名の重複登録がエラーになる
- [ ] `is_transfer_only = True` のグループが正しく判別される
- [ ] `to_account_id` を設定した資金移動パターンが正常に作成・更新できる
