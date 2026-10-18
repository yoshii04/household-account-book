# 仕様：年度別トレンドレポート（過去1年収支）

## 概要

指定した終了月を起点に、過去12ヶ月間のカテゴリ別収支を月単位で集計・表示する機能。縦軸にカテゴリ（収入・支出の親子階層）、横軸に月を並べたトレンドテーブルと、主要費目の折れ線グラフの2画面を提供する。資金移動を除いた通常取引のみを集計対象とする。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/reports/yearly-trend` | 過去1年収支テーブル |
| 画面 | `/reports/yearly-trend-chart` | 過去1年収支 主要費目グラフ |
| API | `GET /api/v1/reports/yearly-trend` | 過去12ヶ月カテゴリ別収支データ取得 |

---

## 対象ファイル

- `backend/app/routers/reports.py` — APIルーター（`/yearly-trend` エンドポイント）
- `backend/app/services/report_service.py` — 集計ロジック（`get_yearly_trend` 関数、行654付近）
- `backend/app/routers/pages.py` — ページルーター（`/reports/yearly-trend`、`/reports/yearly-trend-chart`）
- `backend/app/templates/reports/yearly_trend.html` — テーブル表示テンプレート
- `backend/app/templates/reports/yearly_trend_chart.html` — グラフ表示テンプレート

---

## データモデル

### 使用テーブル

| テーブル | 主要フィールド | 用途 |
|----------|--------------|------|
| `transactions` | `date`, `category_id`, `income_amount`, `expense_amount`, `is_transfer` | 集計元データ |
| `categories` | `id`, `full_path`, `parent_id`, `name` | カテゴリ名・親子関係の解決 |

### 集計キー

- `"YYYY-M"` 形式の文字列（例: `"2025-3"`）を月識別キーとして使用する
- ゼロ埋めなし（`"2025-03"` ではなく `"2025-3"`）

---

## 機能仕様

### 集計対象期間

- 集計期間は**暦年ベース**で、会計年度（4月始まり等）ではない
- 終了月（`end_year`/`end_month`）を含む**直近12ヶ月**を集計対象とする
  - 例: 終了月が2026年1月 → 2025年2月〜2026年1月の12ヶ月
- 開始日は12ヶ月前の月初日（1日）、終了日は `end_month` の月末日
- `year`, `month` パラメーターが未指定の場合は**前月**をデフォルトとする（`_prev_ym()` → `today_jst()` を使用）

### 集計対象トランザクション

- `Transaction.is_transfer IS FALSE` の取引のみ集計する（資金移動は除外）
- 期間は `start_date <= Transaction.date <= end_date` でフィルタリング

### カテゴリ集計ロジック

- `Category × 月` の組み合わせで `income_amount` と `expense_amount` を集計
- 取引は必ず**子カテゴリ**に紐づく（親カテゴリには直接紐づかない）
- 集計結果に現れた子カテゴリの親が集計結果に含まれない場合は、DBから親カテゴリを追加取得して補完する
- カテゴリの `is_income` 判定: 収入合計 (`income_amount`) > 0 であれば収入扱い、そうでなければ支出扱い（親カテゴリ・子カテゴリともに同様）
- 親カテゴリの `cells`（月別金額）は、収入・支出の判定結果に応じて `income_data` または `expense_data` の合算値をセットする

### レスポンス構造

`GET /api/v1/reports/yearly-trend` が返却するJSONの主要キー：

| キー | 型 | 説明 |
|------|----|------|
| `end_year` | int | 集計終了年 |
| `end_month` | int | 集計終了月 |
| `months` | list[dict] | 12ヶ月のリスト（古い順）。各要素は `{year, month, key}` |
| `year_spans` | list[dict] | ヘッダー用年スパン。各要素は `{year, count}` でcolspan計算に使用 |
| `income_categories` | list[dict] | 収入カテゴリ（親単位、`full_path` 昇順）。各要素は `{cat_id, full_path, name, is_income, cells, row_total, children}` |
| `expense_categories` | list[dict] | 支出カテゴリ（親単位、`full_path` 昇順） |
| `income_month_totals` | dict[str, int] | 月キー→収入合計 |
| `expense_month_totals` | dict[str, int] | 月キー→支出合計 |
| `balance_month_totals` | dict[str, int] | 月キー→収支（収入−支出） |
| `income_row_total` | int | 12ヶ月の収入合計 |
| `expense_row_total` | int | 12ヶ月の支出合計 |
| `balance_row_total` | int | 12ヶ月の収支合計（収入合計−支出合計） |

### テーブル画面（`/reports/yearly-trend`）

- 「カテゴリ」列と12ヶ月の月列、「年間計」列で構成
- 月列ヘッダーは2行構成：1行目に年スパン（colspan）、2行目に月番号
- 収入セクション → 支出セクション → 収支行の順で表示
- 親カテゴリ行をクリックすると子カテゴリ行を展開/折りたたみ（Alpine.js `x-show` / `open[cat_id]`）
- 金額セルをクリックすると詳細モーダルを表示（`$store.detailModal.show(...)`）
  - 引数は `{year, month, category_id, title}` または `{year, month, title}`（カテゴリ計行）
- 収支行の金額は正値に `+` プレフィックスを付与、正負で色クラスを切り替え（`amount-income` / `amount-expense`）
- 金額が0の場合はセルを空白表示（`—` は収支行のみ）

### グラフ画面（`/reports/yearly-trend-chart`）

- テーブル画面と同じ集計データ（`get_yearly_trend` の結果）を使用
- 収入 TOP5: `income_categories` を `row_total` 降順でソートした上位5件
- 支出 TOP5: `expense_categories` のうち `full_path` が `"B"` で始まるカテゴリを `row_total` 降順でソートした上位5件
  - Bカテゴリのみに絞る処理はページルーター（`pages.py`）で行う
- グラフはChart.jsの折れ線グラフ（`type: 'line'`）、横軸が月、縦軸が金額
- 収入・支出それぞれ独立したグラフを描画（同一ページに並列表示）
- 各カテゴリが1本の折れ線（`tension: 0.3`、塗りつぶしなし `fill: false`）
- グラフの下にカテゴリ×月のサマリーテーブルも表示
- `data.months` は `<script>` タグ内に `tojson` フィルタで埋め込む（HTML属性ではない）

---

## 実装上の注意点

- カテゴリ集計時に子カテゴリの親が集計結果に含まれない場合があるため、DBから補完するロジックが必要（`monthly_report` と同様のパターン）
- `today_jst()` を使用してデフォルトの前月を計算する（`date.today()` や `datetime.now()` は使わない）
- `year_spans` はテーブルヘッダーの `colspan` 計算のために、12ヶ月リストを年ごとにグルーピングした結果
- グラフ画面で `income_top5` / `expense_top5` を `<script>` 内に `tojson` フィルタで埋め込む際、HTML属性ではなくscriptタグ内なのでシングルクォート属性の制限は適用されない

---

## 動作確認チェックリスト

- [ ] `year`/`month` パラメーターを省略すると前月が集計終了月として使用される
- [ ] 集計対象が暦年ベースの直近12ヶ月であることを確認（終了月を含む）
- [ ] `is_transfer=True` の取引が集計結果に含まれないことを確認
- [ ] 親カテゴリ行クリックで子カテゴリ行が展開/折りたたみできる
- [ ] 月セルクリックで詳細モーダルが正しく開く（year, month, category_id が渡される）
- [ ] 収支行の金額が正の場合に `+` プレフィックスが付く
- [ ] テーブルヘッダーの年スパンが正しく `colspan` で表示される（12ヶ月が2年にまたがる場合）
- [ ] グラフ画面の支出TOP5が `full_path` が `"B"` 始まりのカテゴリのみから選出される
- [ ] データなし時に「対象期間のデータがありません。」が表示される
- [ ] グラフのツールチップに金額が `¥{金額}` 形式で表示される
