# 仕様：B-5 年次集計レポート

## 概要

指定した年範囲のカテゴリ別収支を年単位で集計し、一覧表形式で表示する。
縦軸に収入・支出の親カテゴリ（子カテゴリを展開可能）、横軸に各年を配置したクロス集計表で、複数年の収支推移を把握できる。
グラフ画面では収入・支出の主要カテゴリ（各 TOP5）を棒グラフで視覚的に比較できる。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/reports/annual` | 年次集計表（カテゴリ × 年のクロス集計） |
| 画面 | `/reports/annual-chart` | 収入・支出 TOP5 の年別棒グラフ |
| API | `GET /api/v1/reports/annual` | 年次集計データを JSON で返す |

---

## 対象ファイル

- `backend/app/routers/reports.py` — API ルーター（`/api/v1/reports/annual`）
- `backend/app/services/report_service.py` — 集計ロジック（`get_annual_report` 関数）
- `backend/app/routers/pages.py` — 画面ルーター（`/reports/annual`、`/reports/annual-chart`）
- `backend/app/templates/reports/annual.html` — 年次集計表テンプレート
- `backend/app/templates/reports/annual_chart.html` — グラフテンプレート

---

## データモデル

### 使用テーブル

| テーブル | 主要フィールド | 用途 |
|----------|---------------|------|
| `transactions` | `date`, `category_id`, `income_amount`, `expense_amount`, `is_transfer` | 集計元データ |
| `categories` | `id`, `full_path`, `name`, `parent_id` | カテゴリ情報・親子関係の解決 |

### 集計キー

- `Category.id`、`Category.full_path`、`Category.parent_id`、`Category.name`
- `extract("year", Transaction.date)` — 年単位の集計キー

---

## 機能仕様

### パラメーター

| パラメーター | 型 | 必須 | デフォルト値 | 制約 |
|---|---|---|---|---|
| `start_year` | int | 画面: 省略可、API: 必須 | DB 内の `is_transfer=False` 取引の最古年 | — |
| `end_year` | int | 画面: 省略可、API: 必須 | `today_jst().year`（当年） | — |

- `start_year > end_year` の場合、画面ルーターが自動的に swap する（逆転防止）
- API エンドポイント（`GET /api/v1/reports/annual`）では両パラメーターとも `Query(...)` で必須

### 集計対象

- `Transaction.is_transfer.is_(False)` の取引のみを対象とする（資金移動を除外）
- 集計期間は `start_year` 年 1 月 1 日〜`end_year` 年 12 月 31 日

### 集計ロジック（`get_annual_report`）

1. **DB クエリ**: `categories` と `transactions` を JOIN し、カテゴリ × 年で `income_amount`・`expense_amount` の合計を取得
2. **子カテゴリの分類**: クエリ結果の各カテゴリについて、`parent_id` が `None` のものを親、`None` でないものを子として分類する
3. **親マップ初期化**: 結果セットに含まれる親カテゴリのエントリを作成し、直接取引がある場合はその金額を初期値として設定する
4. **親の DB 補完**: 子カテゴリの `parent_id` が親マップに存在しない場合（子カテゴリのみに取引が紐づき、親カテゴリ自体には取引がない場合）、DB から `Category` を取得してマップに追加する
5. **子の集約**: 子カテゴリを親マップに紐づけ、子の金額を親の集計値にも加算する
6. **収入／支出の判定**: カテゴリごとに `total_income` の合計が 0 より大きければ収入、それ以外は支出とみなす
7. **`cells` フィールド**: 収入カテゴリは `income_data[cat_id]`（年→金額のdict）、支出カテゴリは `expense_data[cat_id]` を `cells` として持つ
8. **子行のソート**: 各親の `children` は `full_path` の昇順でソートされる
9. **全カテゴリのソート**: 収入カテゴリ・支出カテゴリともに `full_path` 昇順でソートされる

### レスポンス構造（`get_annual_report` の戻り値）

```json
{
  "start_year": 2022,
  "end_year": 2024,
  "years": [2022, 2023, 2024],
  "income_categories": [
    {
      "cat_id": 1,
      "full_path": "A10_給与",
      "name": "給与",
      "is_income": true,
      "cells": {"2022": 3600000, "2023": 3800000},
      "row_total": 7400000,
      "children": [...]
    }
  ],
  "expense_categories": [...],
  "income_year_totals": {"2022": 3600000, "2023": 3800000},
  "expense_year_totals": {"2022": 2400000, "2023": 2500000},
  "balance_year_totals": {"2022": 1200000, "2023": 1300000},
  "income_grand_total": 7400000,
  "expense_grand_total": 4900000,
  "balance_grand_total": 2500000
}
```

- `cells` のキーは年を文字列にしたもの（例: `"2023"`）
- 取引がない年のキーは `cells` に含まれない（0ではなくキー欠落）

### 年次集計表画面（`/reports/annual`）

- フォームで `start_year`／`end_year` を入力して再表示
- テーブル構成:
  - 列: カテゴリ名 | 各年 | 合計
  - 行: 収入セクション / 収入計 / 支出セクション / 支出計 / 収支行
- **収入セクション**: `income_categories` を親行で一覧表示。子カテゴリがある場合、Alpine.js の `open[cat_id]` フラグで展開・折りたたみ
- **支出セクション**: `expense_categories` を同様に表示
- **収支行**: `balance_year_totals`（収入計 − 支出計）を各年に表示。プラスは収入色、マイナスは支出色
- **金額クリック**: 金額セルをクリックすると `$store.detailModal.show(...)` を呼び出し、取引詳細モーダルを表示（`year` と `category_id` を渡す）
- 0円の場合は金額を表示せず、クリックも無効（`amt-clickable` クラスなし）

### グラフ画面（`/reports/annual-chart`）

- 画面ルーターで `get_annual_report` を呼び出したあと、以下の系列を選択してテンプレートに渡す:
  - `income_top5`: `income_categories` を `row_total` 降順でソートした先頭 5 件
  - `expense_top5`: `expense_categories` のうち `full_path` が `"B"` で始まるものを `row_total` 降順でソートした先頭 5 件
- Chart.js（`type: 'bar'`）で X 軸=年・Y 軸=金額の grouped bar chart を描画
- 収入・支出それぞれ独立したキャンバス（`#incomeChart`、`#expenseChart`）
- `cells[String(year)]` の値をデータとして使用し、値がない年は 0 として扱う
- データが 0 件の場合はグラフを描画せず「対象期間のデータがありません」を表示

---

## 実装上の注意点

- **子カテゴリのみが取引に紐づく**: CLAUDE.md の方針通り、取引には子カテゴリのみが紐づく。親カテゴリに直接取引が紐づくことはない。集計後、子の `parent_id` をもとに親を DB から補完して親子構造を組み立てる
- **JST タイムゾーン**: `end_year` のデフォルト値は `today_jst().year` を使う（`date.today()` は使わない）
- **デフォルト `start_year` の算出**: `db.query(func.min(extract("year", Transaction.date))).filter(Transaction.is_transfer.is_(False)).scalar()` で取得する
- **Jinja2 テンプレートへの JSON 埋め込み**: `<script>` タグ内では `{{ data.years | tojson }}` をそのまま使う。Alpine.js バインディングが必要な場合はシングルクォート属性を用いる

---

## 動作確認チェックリスト

- [ ] `start_year`／`end_year` 未指定でアクセスすると、DB 最古年〜当年が自動設定される
- [ ] `start_year > end_year` でアクセスすると swap されて正常表示される
- [ ] 収入カテゴリ・支出カテゴリがそれぞれ `full_path` 昇順で表示される
- [ ] 親カテゴリ行をクリックすると子カテゴリ行が展開・折りたたみされる
- [ ] 子カテゴリがない親行には展開アイコン（▶/▼）が表示されない
- [ ] 金額セルをクリックすると取引詳細モーダルが開く
- [ ] 0円のセルはクリック不可で金額も表示されない
- [ ] 収支行がプラスのとき収入色、マイナスのとき支出色で表示される
- [ ] 資金移動（`is_transfer=True`）の取引が集計に含まれない
- [ ] グラフ画面で収入 TOP5 が `row_total` 降順の先頭 5 件になっている
- [ ] グラフ画面の支出 TOP5 が `full_path` が `"B"` 始まりのカテゴリのみから選ばれている
- [ ] データがない場合に「対象期間のデータがありません」が表示される
