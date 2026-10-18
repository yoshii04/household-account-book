# 仕様：前年同月比レポート

## 概要

指定した年月の収支を前年同月と比較し、カテゴリ別の増減額・増減率を一覧表示する機能。ユーザーは年・月を選択するだけで、収入カテゴリ・支出カテゴリ別に当年と前年の金額、差異、増減率を確認でき、支出の大幅増減をハイライトで把握できる。各金額セルをクリックすると、その月・カテゴリの取引明細モーダルが開く。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/reports/comparison` | 前年同月比レポート（年・月選択フォーム、収入/支出カテゴリ別比較テーブル） |
| API | `GET /api/v1/reports/comparison` | 指定年月の前年同月比データを取得 |

---

## 対象ファイル

- `backend/app/routers/reports.py` — APIルーター（`GET /api/v1/reports/comparison` エンドポイント）
- `backend/app/routers/pages.py` — ページルーター（`/reports/comparison` ルート）
- `backend/app/services/report_service.py` — `get_comparison()` 関数（集計ロジック）
- `backend/app/templates/reports/comparison.html` — 前年同月比テンプレート（Alpine.js による親子展開・モーダル連携）

---

## データモデル

### 参照テーブル

#### transactions テーブル（主要フィールド）

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | Integer | 取引ID |
| `date` | Date | 取引日（年・月の抽出に使用） |
| `income_amount` | Integer | 入金額（収入取引のみ正値、支出取引は 0） |
| `expense_amount` | Integer | 出金額（支出取引のみ正値、収入取引は 0） |
| `category_id` | Integer | カテゴリID（子カテゴリのみ直接紐づく） |
| `is_transfer` | Boolean | 資金移動フラグ（集計から除外） |

#### categories テーブル（主要フィールド）

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | Integer | カテゴリID |
| `full_path` | String | `A30_通信費/インターネット` 形式の階層パス（ソートキーとしても利用） |
| `parent_id` | Integer / NULL | 親カテゴリのID（NULLは親カテゴリ自身） |
| `code` | String | カテゴリコード |
| `name` | String | カテゴリ名（表示用） |

---

## 機能仕様

### クエリパラメーター

| パラメーター | 型 | 必須 | 説明 |
|---|---|---|---|
| `year` | int | 必須（API）/ 省略可（画面） | 比較対象の当年。省略時は JST 当月の年 |
| `month` | int（1〜12） | 必須（API）/ 省略可（画面） | 比較対象の月。省略時は JST 当月の月 |

画面（`/reports/comparison`）でパラメーターが省略された場合、`_current_ym()`（`today_jst()` を使用）で当月の年・月をデフォルト値として設定する。

### 集計対象

- `Transaction.is_transfer=False` の取引のみ集計する（資金移動取引は除外）
- 集計期間: `extract("year", date).in_([year, year-1])` かつ `extract("month", date) == month` の取引

### 集計クエリ

1回のSQLクエリで当年・前年の両方を集計する。`case` 式を用いて年別に金額を振り分ける：
- `this_year_expense`: `year` 年の出金合計
- `last_year_expense`: `year-1` 年の出金合計
- `this_year_income`: `year` 年の入金合計
- `last_year_income`: `year-1` 年の入金合計

結果は `Category.full_path` の昇順でソートされる。

### カテゴリ親子構造の組み立て

取引は子カテゴリ（`parent_id IS NOT NULL`）にのみ紐づくため、集計後に親カテゴリを補完して親子構造を組み立てる：

1. 集計結果のうち `parent_id=None` の行を親カテゴリとして `parent_map` に登録する
2. 子カテゴリが参照する親のうち `parent_map` に未登録のもの（取引ゼロの親カテゴリ）を `db.query(Category).filter(Category.id.in_(missing_parent_ids))` で補完登録し、金額はすべて 0 で初期化する
3. 各子カテゴリを対応する親の `children` リストに追加し、親の `this_year_expense`・`last_year_expense`・`this_year_income`・`last_year_income` に子の値を加算する
4. 子の加算が完了した後に、親カテゴリの `diff_expense`・`ratio_expense`・`diff_income`・`ratio_income` を再計算する
5. 各親の `children` は `full_path` 昇順でソートする
6. 最終的な `all_categories` は `full_path` 昇順でソートする

### 収入カテゴリ / 支出カテゴリの分類

- **収入カテゴリ**: `this_year_income > 0` または `last_year_income > 0` のカテゴリ（当年・前年どちらかで収入があれば収入カテゴリ）
- **支出カテゴリ**: `this_year_income == 0` かつ `last_year_income == 0` のカテゴリ（当年・前年ともに収入ゼロ）

### 増減額・増減率の計算

各カテゴリ（親・子）について：

- `diff_expense` = `this_year_expense` - `last_year_expense`
- `ratio_expense` = `round((this_year_expense / last_year_expense - 1) * 100, 1)`（前年ゼロの場合は `None`）
- `diff_income` = `this_year_income` - `last_year_income`
- `ratio_income` = `round((this_year_income / last_year_income - 1) * 100, 1)`（前年ゼロの場合は `None`）

増減率が `None` の場合、テンプレートでは「—」（全角ダッシュ）として表示する。

### レスポンス構造

```json
{
  "year": 2025,
  "last_year": 2024,
  "month": 6,
  "income_categories": [
    {
      "cat_id": 1,
      "full_path": "A10_給与",
      "parent_id": null,
      "code": "A10",
      "name": "給与",
      "this_year_income": 300000,
      "last_year_income": 280000,
      "this_year_expense": 0,
      "last_year_expense": 0,
      "diff_income": 20000,
      "ratio_income": 7.1,
      "diff_expense": 0,
      "ratio_expense": null,
      "children": []
    }
  ],
  "expense_categories": [...],
  "total_this_income": 300000,
  "total_last_income": 280000,
  "total_this_expense": 200000,
  "total_last_expense": 210000,
  "total_this_balance": 100000,
  "total_last_balance": 70000,
  "diff_income": 20000,
  "diff_expense_total": -10000,
  "diff_balance": 30000
}
```

**合計フィールドの説明：**

| フィールド | 説明 |
|---|---|
| `total_this_income` | 当年の収入カテゴリ合計 |
| `total_last_income` | 前年の収入カテゴリ合計 |
| `total_this_expense` | 当年の支出カテゴリ合計 |
| `total_last_expense` | 前年の支出カテゴリ合計 |
| `total_this_balance` | 当年の収支（収入計 − 支出計） |
| `total_last_balance` | 前年の収支（収入計 − 支出計） |
| `diff_income` | 収入計の増減額 |
| `diff_expense_total` | 支出計の増減額 |
| `diff_balance` | 収支の増減額 |

### 画面表示仕様

#### 年月選択フォーム

- `year`（数値入力、2000〜2099）と `month`（セレクトボックス、1〜12）を選択して GET サブミットする

#### 比較テーブル

- 列構成: 「費目」「前年（`last_year` 年）」「当年（`year` 年）」「増減額」「増減率」
- 収入セクション（背景色 `#f0f8f0`）と支出セクション（背景色 `#fff0f0`）に分けて表示する
- 収入の増減額: 正値を緑（`amount-income`）、負値を赤（`amount-expense`）で表示
- 支出の増減額: 正値（増加）を赤（`amount-expense`）、負値（減少）を緑（`amount-income`）で表示
- 支出の親カテゴリ行: `diff_expense > 5000` の場合 `highlight-up`、`diff_expense < -5000` の場合 `highlight-down` クラスを付与してハイライト表示する
- 支出の子カテゴリ行にも同様のハイライトを適用する

#### 親子展開（Alpine.js）

- Alpine.js の `open` オブジェクト（`{ [cat_id]: boolean }`）で各親カテゴリの展開状態を管理する
- 子カテゴリがある親行はクリックで展開/折りたたみができる（`cursor: pointer`）
- 「親カテゴリのみ表示」ボタン（`parentsOnly` フラグ）で子カテゴリ行の表示/非表示を一括切り替えできる

#### 取引詳細モーダル連携

- 金額セルに `amt-clickable` クラスを付与し、クリックで `$store.detailModal.show({year, month, category_id, title})` を呼び出す
- 前年金額セルは `year-1`、当年金額セルは `year` をそれぞれ `year` パラメーターとして渡す
- ゼロ（非表示）の金額セルにはモーダル呼び出しイベントを付与しない

#### フッター合計行

- 「収入計」行（背景色 `#e8f4e8`）: 前年収入合計・当年収入合計・増減額
- 「支出計」行（背景色 `#fce8e8`）: 前年支出合計・当年支出合計・増減額
- 「収支（収入 − 支出）」行（背景色 `#e8eaf6`、上部ボーダー `#9fa8da`）: 前年収支・当年収支・増減額（増減率列は空欄）

---

## 実装上の注意点

- **JST タイムゾーン**: デフォルト年月の取得には `today_jst()`（`app.jst` モジュール）を使用する。`date.today()` は使用しない
- **子カテゴリのみ取引に紐づく**: 取引は子カテゴリ（`parent_id IS NOT NULL`）にのみ紐づく。親カテゴリへの直接紐づきはないため、親カテゴリの金額は子カテゴリの合算で構成される。親が集計結果に現れない場合は DB から補完する
- **親の diff/ratio は子加算後に再計算**: 親カテゴリの `diff_expense`・`ratio_expense`・`diff_income`・`ratio_income` は、子カテゴリの金額を親に加算した後に再計算する（`_make_item()` 初回呼び出し時の値は最終値ではない）
- **前年ゼロ時の増減率は `None`**: `last_year_expense` または `last_year_income` がゼロの場合、対応する `ratio_*` は `None` とする。テンプレートでは `{% if cat.ratio_expense is not none %}` で判定し「—」を表示する
- **Alpine.js のシングルクォート属性**: テンプレートの `x-data` 属性はシングルクォートを使用する（`<div x-data="{ open: {}, parentsOnly: false }">`。本テンプレートでは JSON 埋め込みがないためダブルクォートで問題ないが、JSON を埋め込む場合はシングルクォートに変更すること）

---

## 動作確認チェックリスト

- [ ] `/reports/comparison` にアクセスして当月・前年同月の比較テーブルが表示されること
- [ ] 年・月セレクタを変更して「表示」ボタンを押すと、指定した年月のデータに切り替わること
- [ ] 収入セクションと支出セクションが分かれて表示されること
- [ ] 子カテゴリのある親カテゴリ行をクリックすると子行が展開・折りたたまれること
- [ ] 「親カテゴリのみ表示」ボタンで子行が一括非表示になり、再クリックで戻ること
- [ ] 支出で増減額が +5000 を超えるカテゴリ行に `highlight-up` スタイルが適用されること
- [ ] 支出で増減額が -5000 未満のカテゴリ行に `highlight-down` スタイルが適用されること
- [ ] 前年ゼロのカテゴリの増減率セルに「—」が表示されること
- [ ] 金額セルをクリックするとその年月・カテゴリの取引明細モーダルが開くこと
- [ ] 前年金額セルのモーダルは `year-1` 年のデータが表示されること
- [ ] `GET /api/v1/reports/comparison?year=2025&month=6` がJSONを返すこと
- [ ] 資金移動（`is_transfer=True`）の取引が集計に含まれないこと
- [ ] 収入計・支出計・収支行がそれぞれ正しい合計値を表示すること
- [ ] 収入の増減額・支出の増減額の色分け（収入増=緑、支出増=赤など）が正しいこと
