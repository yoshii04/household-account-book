# 仕様：B-8 口座分類別年次集計

## 概要

`accounts.classification` フィールドでグループ化した口座残高の年次推移を確認する機能。
ユーザーは「個人」「共通」などの分類単位で各年末時点の累計残高を把握できる。
テーブル表示とグラフ表示（積み上げ棒グラフ・折れ線グラフ）の 2 画面を提供する。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/reports/account-classification-annual` | 分類別年次残高テーブル |
| 画面 | `/reports/account-classification-annual-chart` | 分類別年次残高グラフ（積み上げ棒 + 折れ線） |
| API | `GET /api/v1/reports/account-classification-annual` | 集計データ JSON |

---

## 対象ファイル

- `backend/app/routers/reports.py` — API エンドポイント（`/api/v1/reports/account-classification-annual`）
- `backend/app/services/report_service.py` — 集計ロジック（`get_account_classification_annual_report`）
- `backend/app/routers/pages.py` — 画面ルーター（`/reports/account-classification-annual`、`/reports/account-classification-annual-chart`）
- `backend/app/templates/reports/account_classification_annual.html` — テーブル表示テンプレート
- `backend/app/templates/reports/account_classification_annual_chart.html` — グラフ表示テンプレート

---

## データモデル

### accounts（使用フィールド）

| フィールド | 型 | 説明 |
|---|---|---|
| `classification` | text \| NULL | 分類名（例: `個人`、`共通`）。NULL の場合は「分類なし」として集計 |
| `initial_balance` | int | 起算日時点の初期残高 |
| `adjustment_amount` | int | 残高調整額 |
| `start_date` | date \| NULL | 残高計算の起算日。NULL の場合はすべての取引が対象 |
| `is_active` | bool | 非アクティブ口座は集計から除外 |
| `sort_order` | int | 口座の並び順 |
| `code` | text | 口座コード（sort_order の次の並び基準） |

### transactions（使用フィールド）

| フィールド | 型 | 説明 |
|---|---|---|
| `account_id` | int | 集計対象口座の絞り込みに使用 |
| `date` | date | 集計年の絞り込みおよび各年末時点累計の計算に使用 |
| `income_amount` | int | 入金額 |
| `expense_amount` | int | 出金額 |

---

## 機能仕様

### パラメーター

| パラメーター | 必須 | 説明 |
|---|---|---|
| `start_year` | API: 必須 / 画面: 任意 | 集計開始年。省略時は DB 上の最古取引の年 |
| `end_year` | API: 必須 / 画面: 任意 | 集計終了年。省略時は現在年（JST） |

- 画面は `start_year > end_year` の場合に自動スワップして表示する。
- 画面用の現在年は `today_jst().year` で取得する。
- 画面用の DB 最古年は `func.min(extract("year", Transaction.date))` で取得する。

### 集計ロジック（`get_account_classification_annual_report`）

1. `is_active = True` の全口座を `sort_order`、`code` 順に取得する。
2. 各口座について、`start_date` から `end_year/12/31` 以前の取引を年別に集計する。
   - `start_date` が設定されている口座は、`start_date` 未満の取引を除外する。
   - `start_date` が NULL の口座は全取引が対象。
3. 各口座・各年の累計残高（`cumulative`）を次の式で算出する：

   ```
   cumulative = initial_balance + adjustment_amount
              + Σ (income_amount - expense_amount) の各年累計（start_year 以前の年を含む）
   ```

   - `base = initial_balance + adjustment_amount`
   - `cumulative(target_year) = base + Σ yearly_net[y] for y <= target_year`

4. 口座の `classification` をキーとして累計残高を合算する（分類なしは空文字 `""` として扱う）。
5. `base == 0` かつ取引が存在しない口座は集計をスキップする。

### 集計結果の構造

```json
{
  "start_year": 2020,
  "end_year": 2024,
  "years": [2020, 2021, 2022, 2023, 2024],
  "rows": [
    {
      "classification": "個人",
      "cells": {"2020": 500000, "2021": 800000, ...},
      "row_total": 1200000
    },
    {
      "classification": null,
      "cells": {"2020": 100000, ...},
      "row_total": 300000
    }
  ],
  "year_totals": {"2020": 600000, "2021": 1000000, ...},
  "grand_total": 1500000,
  "has_data": true
}
```

- `rows` は分類ありを名前順（昇順）で先に並べ、分類なし（`classification = null`）を末尾に配置する。
- `row_total` は `end_year` 末時点の残高（`cells[str(end_year)]`）。
- `grand_total` は `year_totals[str(end_year)]`。
- `has_data` はデータが存在する口座が 1 件以上あれば `true`。

### テーブル表示画面（`account_classification_annual.html`）

- 縦軸: 分類、横軸: 年（`start_year` ～ `end_year` の各年）。
- 各セルは「各年末時点の累計残高」。0 の場合は「—」を表示。
- 正の残高は `amount-income` クラス（`+¥` プレフィックス）、負の残高は `amount-expense` クラスで表示。
- `classification = null` の行は「（分類なし）」と表示する。
- 最終列に `end_year` 末残高（`row_total`）を表示する。
- 最終行に全分類の年別合計（`year_totals`）と `grand_total` を表示する。
- `has_data = false` の場合は「対象期間のデータがありません。」を表示する。
- 年範囲フォームから `start_year`・`end_year` を指定して再表示できる。`min` 属性は `db_min_year`。
- グラフ表示画面へのリンクに現在の `start_year`・`end_year` をクエリパラメーターとして引き継ぐ。

### グラフ表示画面（`account_classification_annual_chart.html`）

テーブルと同じ集計データを Chart.js で可視化する。グラフは 2 種類。

#### 積み上げ棒グラフ（`stackedChart`）

- 横軸: 年、縦軸: 累計残高。
- 系列: 各分類（`rows` の順序）。`classification = null` の系列ラベルは「（分類なし）」。
- 負残高（ローン等）は下方向にスタックされる。
- Y 軸の目盛りフォーマット: 億（`1e8`）・万（`1e4`）単位で省略表示。

#### 折れ線グラフ（`lineChart`）

- 横軸: 年、縦軸: 累計残高。
- 系列: 各分類（`rows` の順序）+ 全体合計（`year_totals`、ラベル「合計」）。
- 合計系列は黒（`#1e293b`）の破線（`borderDash: [5, 3]`）で表示。
- `fill: false`、`tension: 0.2`、`pointRadius: 4`。

#### カラーパレット

分類ごとに以下 15 色をインデックス順（`i % 15`）でサイクルして割り当てる：

```
'#3b82f6', '#22c55e', '#f59e0b', '#8b5cf6', '#06b6d4',
'#ef4444', '#f97316', '#84cc16', '#ec4899', '#14b8a6',
'#a78bfa', '#fb7185', '#34d399', '#fbbf24', '#60a5fa'
```

棒グラフの `backgroundColor` は色コードに `cc` を付加（透過度）、折れ線グラフの `backgroundColor` は `33` を付加（塗りつぶし領域用）。

グラフ画面にも同様の集計テーブルを同一ページ内に表示する（`has_data = false` 時はテーブル・グラフとも非表示）。

---

## 実装上の注意点

- 現在年の取得には `today_jst().year` を使用すること（`date.today()` は不可）。
- グラフ画面の `<script>` タグ内への JSON 埋め込みは `{{ data.rows | tojson }}`、`{{ data.years | tojson }}`、`{{ data.year_totals | tojson }}` で行う（`<script>` 内は HTML エスケープ不要）。
- `is_transfer` フラグによる資金移動の除外は本機能では行わない（全取引を対象に残高計算する）。
- `base（initial_balance + adjustment_amount）` が 0 かつ取引が存在しない口座は `has_any_data` フラグに影響しない（スキップされる）。

---

## 動作確認チェックリスト

- [ ] `start_year`・`end_year` 未指定でアクセスしたとき、DB 最古年〜現在年で表示されること
- [ ] `start_year > end_year` を指定したとき、自動スワップして正常に表示されること
- [ ] 分類が設定されている口座の残高が分類名ごとに正しく合算されること
- [ ] `classification = null` の口座が「（分類なし）」として末尾に表示されること
- [ ] `initial_balance`・`adjustment_amount` が累計残高に含まれること
- [ ] `start_date` を設定した口座で、`start_date` 未満の取引が除外されること
- [ ] 非アクティブ（`is_active = false`）の口座が集計に含まれないこと
- [ ] 正の残高は `+¥` プレフィックスで表示され、負の残高は別スタイルで表示されること
- [ ] 0 残高のセルが「—」で表示されること
- [ ] データなし時に「対象期間のデータがありません。」が表示されること
- [ ] グラフ画面で積み上げ棒グラフと折れ線グラフが両方表示されること
- [ ] 折れ線グラフの合計系列（黒破線）が表示されること
- [ ] テーブル↔グラフの切り替えリンクで年範囲パラメーターが引き継がれること
- [ ] 年範囲フォームの `min` 属性が DB 最古年になっていること
