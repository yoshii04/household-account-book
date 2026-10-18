# 仕様：ダッシュボード

## 概要

アプリのトップ画面として当月の収支サマリーを一覧表示する機能。当月収入・当月支出・差引残高をカード形式で提示し、費目別支出の円グラフと直近5件の取引を同一画面に配置する。また、今日が支払日となっている定期取引パターンがあれば画面上部にバナーで通知するほか、支払日を過ぎても記録されていない定期取引パターンがあれば「今月未記録のパターン」セクションで警告する。今日の支払いパターン通知バナーは、対象期間について既に取引を記録済みのパターンを対象から除外する。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/` | ダッシュボード（当月収支カード・費目別円グラフ・直近取引・今日のパターン通知・今月未記録のパターン） |

ダッシュボードはページ専用ルートのみで、独立した JSON API エンドポイントは存在しない。集計処理はすべてサーバーサイドで実行されてテンプレートに渡される。

---

## 対象ファイル

- `backend/app/routers/pages.py` — ページルーター（`dashboard` 関数、`_current_ym` ヘルパー）
- `backend/app/services/report_service.py` — `get_monthly_summary` 関数
- `backend/app/crud/pattern.py` — `get_due_patterns` 関数、`get_unrecorded_patterns` 関数
- `backend/app/crud/transaction.py` — `get_transactions` 関数（直近取引取得）
- `backend/app/jst.py` — JST タイムゾーンユーティリティ（`today_jst`）
- `backend/app/templates/index.html` — ダッシュボードテンプレート

---

## データモデル

### transactions テーブル（集計対象）

| カラム | 型 | 説明 |
|--------|-----|------|
| `date` | Date | 取引日（当月フィルター対象） |
| `category_id` | Integer | カテゴリ ID（categories テーブルへの FK） |
| `income_amount` | Integer | 収入金額（収入取引は支出が 0） |
| `expense_amount` | Integer | 支出金額（支出取引は収入が 0） |
| `is_transfer` | Boolean | 資金移動フラグ。`True` のものは集計・直近取引から除外 |
| `memo` | String | メモ（直近取引テーブルに表示） |

### categories テーブル（集計補完）

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | Integer | カテゴリ ID |
| `full_path` | String | フルパス（例: `B10_食費/外食`）。ソートキーとして使用 |
| `parent_id` | Integer | 親カテゴリ ID（NULL = 親カテゴリ） |
| `code` | String | カテゴリコード |
| `name` | String | カテゴリ名（円グラフのラベルに使用） |

### transaction_patterns テーブル（今日のパターン通知）

| カラム | 型 | 説明 |
|--------|-----|------|
| `is_active` | Boolean | 有効フラグ。`False` のものは取得対象外 |
| `payment_day_of_month` | Integer | 毎月の支払日（今日の日付と照合） |
| `frequency` | String | 頻度（`monthly` または `annual`） |
| `payment_month_of_year` | Integer | 年 1 回の場合の支払月（annual パターンの月照合に使用） |
| `typical_amount` | Integer | 通常金額（バナーに表示） |
| `is_income` | Boolean | 収入フラグ（バナーの金額表示スタイルに使用） |
| `name` | String | パターン名（バナーに表示） |

対象期間の記録状況（`is_current_period_recorded`）もフィルター条件として内部的に参照する（バナー上には表示しない）。判定ロジックの詳細は [spec_patterns.md](../auxiliary/spec_patterns.md) の「当月（対象期間）の記録状況判定」を参照。

### transaction_patterns テーブル（今月未記録のパターン）

| カラム | 型 | 説明 |
|--------|-----|------|
| `is_current_period_recorded` | Boolean | 対象期間内の記録状況（`get_patterns`/`get_due_patterns` と共通の判定ロジック。詳細は [spec_patterns.md](../auxiliary/spec_patterns.md) の「当月（対象期間）の記録状況判定」参照） |
| `current_period_transaction_id` | Integer, nullable | 記録済み取引への詳細リンク用 |

---

## 機能仕様

### 表示期間の決定

- `_current_ym()` ヘルパー関数が `today_jst()` を呼び出して JST での今日の日付を取得し、その年・月を当月として使用する
- クエリパラメーターによる期間変更機能はなく、常に当月固定で表示する

### 当月収支サマリーカード

- `get_monthly_summary(db, year, month)` で当月の費目別集計を取得する
- 集計クエリは `Transaction.is_transfer.is_(False)` で資金移動を除外する
- 表示する集計値は以下の 3 つ:
  - **収入**（`summary.total_income`）: 当月の `income_amount` 合計
  - **支出**（`summary.total_expense`）: 当月の `expense_amount` 合計
  - **差引**（`summary.total_income - summary.total_expense`）: 収入 − 支出
- 差引カードは正値（≥ 0）のとき `.positive` クラス、負値のとき `.negative` クラスを付与してスタイルを変える

### 費目別支出 円グラフ

- Chart.js の doughnut（ドーナツ）グラフを使用する
- データソースは `summary.categories`（収入・支出カテゴリを合わせた全カテゴリ）
- ラベルは `cat.name`（カテゴリ名）、値は `cat.total_expense`（支出合計）
- `total_expense` が 0 のカテゴリ（収入カテゴリ）はデータとしては含まれるが、値 0 のため実質グラフには描画されない
- 凡例は下部（`legend: { position: 'bottom' }`）に表示する

### `get_monthly_summary` の集計ロジック

- `transactions` テーブルと `categories` テーブルを JOIN し、対象年月 + `is_transfer=False` でフィルタリングする
- 取引は子カテゴリ（`parent_id` が NOT NULL）にのみ紐づく。親カテゴリは取引を直接持たないため、子カテゴリが参照する親を `Category.id IN (...)` で DB から補完して親子構造を組み立てる
- 補完した親カテゴリの `total_income` / `total_expense` には配下の子カテゴリの合計値が加算される
- 最終的に `income_categories`（`total_income > 0` のカテゴリ）と `expense_categories`（`total_income == 0` のカテゴリ）に分類して返す

### 直近の取引

- `get_transactions(db, year=year, month=month, is_transfer=False, per_page=5)` で当月の非資金移動取引を最大 5 件取得する
- テーブル表示項目: 日付 / カテゴリ（`category_full_path`）/ メモ / 支出金額 / 収入金額
- テーブル下部の「すべて表示 →」リンクは `/transactions?year={year}&month={month}` に遷移する
- 取引が 0 件の場合は「データなし」行を表示する

### 今日のパターン通知バナー

- `get_due_patterns(db, today_jst())` で今日が支払日かつ対象期間が未記録のアクティブパターンを取得する
- 取得条件:
  - `is_active=True`
  - `payment_day_of_month == today.day`
  - `frequency == "monthly"` の場合は無条件で対象
  - `frequency == "annual"` の場合は `payment_month_of_year == today.month` のもののみ対象
  - 対象期間について既に記録済み（`is_current_period_recorded == True`）のパターンは除外する。判定方式（ハイブリッド：`pattern_id` 優先 + `category_id`/`account_id`/`group_id` フォールバック）は [spec_patterns.md](../auxiliary/spec_patterns.md) の「当月（対象期間）の記録状況判定」を参照
- `due_patterns` が空の場合はバナーを表示しない（`{% if due_patterns %}` で制御）。今日が支払日のパターンが記録済みのみだった場合も同様にバナー自体が表示されない
- バナーに表示する情報: パターン名 / カテゴリ(`category_full_path`) / 通常金額（`typical_amount`）/ 「入力する →」ボタン
- 「入力する →」ボタンは `/transactions/new?pattern_id={p.id}` に遷移する
- `typical_amount` が設定されている場合のみ金額を表示し、収入（`is_income=True`）は `+¥xxx` 形式、支出は `-¥xxx` 形式で表示する

### 今月未記録のパターン

- `get_unrecorded_patterns(db, today_jst())` で、対象期間の支払日を過ぎてもなお `is_current_period_recorded = false` のアクティブパターンを取得する
- 対象期間の定義・記録状況の判定方式（ハイブリッド：`pattern_id` 優先 + `category_id`/`account_id`/`group_id`（非対称マッチング）フォールバック）は [spec_patterns.md](../auxiliary/spec_patterns.md) の「当月（対象期間）の記録状況判定」を参照
- **猶予期間はない：** 対象期間の支払日を1日でも過ぎて未記録であれば即座に対象となる
- `daily` / `other` 頻度のパターンは対象外（都度記録が前提のため）
- 対象パターンが 0 件の場合はセクション自体を表示しない
- 各行に表示する情報：パターン名 / カテゴリ(`category_full_path`) / 通常金額（`typical_amount`）/ 「入力する →」ボタン
- 「入力する →」ボタンは `/transactions/new?pattern_id={p.id}` に遷移する（今日のパターン通知バナーと同じ遷移先）

---

## 実装上の注意点

- **JST タイムゾーン:** 当月の決定に `date.today()` や `datetime.now()` を使わず、必ず `today_jst()` を使うこと（`_current_ym()` 関数、`get_due_patterns`・`get_unrecorded_patterns` の引数参照）
- **記録状況判定のクエリ数:** `get_due_patterns` / `get_unrecorded_patterns` は対象パターン群の `category_id` / `account_id` / `group_id` / `pattern_id` に対しまとめて1クエリで対象期間の取引を取得し、パターンごとの個別クエリ（N+1）を発生させない
- **資金移動の除外:** 月次集計（`get_monthly_summary`）と直近取引（`get_transactions(..., is_transfer=False, ...)`）の両方で `is_transfer=False` フィルターを適用し、資金移動取引を集計から除外している
- **親カテゴリの DB 補完:** 子カテゴリが参照している親カテゴリに直接取引が紐づいていない場合でも、子を親に集約するため DB から親を補完する。カテゴリ JOIN でなくサブクエリを使うことで joinedload との重複 JOIN を避ける
- **Jinja2 テンプレートへの JSON 埋め込み:** ダッシュボードの `index.html` は `<script>` ブロック内でカテゴリ名と支出金額を直接 Jinja2 ループで展開している（`tojson` フィルターは使用していない）。将来的に Alpine.js バインディングに JSON を埋め込む場合はシングルクォート属性（`x-data='...'`）を使うこと
- **日付オブジェクトの文字列化:** テンプレートに `date` / `datetime` オブジェクトをそのまま `tojson` に渡すと TypeError になる。日付を JSON 属性として渡す場合は `.isoformat()` で文字列化すること

---

## 動作確認チェックリスト

- [ ] `/` にアクセスして当月の年月（JST 基準）がタイトルに表示されること
- [ ] 収入・支出・差引の各サマリーカードに当月の正しい集計値が表示されること
- [ ] 差引が正の場合にサマリーカードが `.positive` スタイルで表示され、負の場合に `.negative` スタイルで表示されること
- [ ] 費目別支出の円グラフに当月の支出カテゴリが描画されること（資金移動カテゴリが含まれないこと）
- [ ] 直近の取引テーブルに当月の非資金移動取引が最大 5 件表示されること
- [ ] 「すべて表示 →」リンクが `/transactions?year={year}&month={month}` に正しく遷移すること
- [ ] 当月に取引が 0 件の場合、直近取引テーブルに「データなし」が表示されること
- [ ] 今日が `payment_day_of_month` に一致するアクティブな monthly パターンが未記録の場合、バナーが表示されること
- [ ] 今日が `payment_day_of_month` かつ `payment_month_of_year` に一致するアクティブな annual パターンが未記録の場合、バナーが表示されること
- [ ] 今日が支払日のパターンがない場合、バナーが表示されないこと
- [ ] 今日が支払日のパターンでも、対象期間について記録済み（`is_current_period_recorded = true`）の場合はバナーに表示されないこと
- [ ] 今日が支払日のパターンが記録済みのパターンのみの場合、バナー自体が表示されないこと
- [ ] 支払日当日に取引を記録すると、以降 `/` を再読み込みした際に当該パターンがバナーから消えること
- [ ] バナーの「入力する →」ボタンが `/transactions/new?pattern_id={id}` に遷移し、パターン情報が初期入力されること
- [ ] 支払日を過ぎても未記録のアクティブパターンがある場合、「今月未記録のパターン」セクションに表示されること
- [ ] 対象期間内に記録済みのパターンが「今月未記録のパターン」セクションに含まれないこと
- [ ] 該当パターンが0件の場合、「今月未記録のパターン」セクションが表示されないこと
- [ ] `daily` / `other` 頻度のパターンが「今月未記録のパターン」に含まれないこと
- [ ] `annual` パターンで当年の対象期間の支払日を過ぎても未記録の場合に「今月未記録のパターン」に表示されること
- [ ] 「今月未記録のパターン」セクションの「入力する →」ボタンが `/transactions/new?pattern_id={id}` に遷移すること
- [ ] JST と UTC で日付が異なる深夜時間帯（例: UTC 15:00〜16:00 = JST 翌 0:00〜1:00）に JST 基準の当月が正しく反映されること
