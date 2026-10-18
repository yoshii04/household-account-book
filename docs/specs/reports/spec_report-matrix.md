# 仕様：カテゴリ×グループ マトリックスレポート

## 概要

指定した年月の取引を「カテゴリ（縦軸）×グループ（横軸）」のマトリックス形式で集計し、誰がどの費目にいくら使ったかを一覧で把握する機能。収入・支出それぞれのセクションに分けて親・子カテゴリ階層を表示し、親行のクリックで子行を展開できる。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/reports/matrix` | カテゴリ×グループ マトリックス（年・月フォームで絞り込み） |
| API | `GET /api/v1/reports/matrix` | マトリックスデータを JSON で返す |

### API クエリパラメーター

| パラメーター | 型 | 必須 | 説明 |
|---|---|---|---|
| `year` | int | 必須 | 集計対象年 |
| `month` | int | 必須（1〜12） | 集計対象月 |

---

## 対象ファイル

- `backend/app/routers/reports.py` — API ルーター（`GET /api/v1/reports/matrix` エンドポイント）
- `backend/app/routers/pages.py` — ページルーター（`GET /reports/matrix` ルート）
- `backend/app/services/report_service.py` — `get_matrix_report` 関数（集計ロジック）
- `backend/app/models/group.py` — Group ORMモデル
- `backend/app/models/category.py` — Category ORMモデル（参照）
- `backend/app/models/transaction.py` — Transaction ORMモデル（参照）
- `backend/app/schemas/group.py` — `GroupOut` Pydantic スキーマ
- `backend/app/templates/reports/matrix.html` — マトリックス表示テンプレート

---

## データモデル

### 参照テーブル

#### transactions テーブル（集計元）

| カラム | 説明 |
|--------|------|
| `date` | 取引日（年・月でフィルタリング） |
| `is_transfer` | 資金移動フラグ。`False` の取引のみ集計対象 |
| `income_amount` | 入金額（収入カテゴリのセル値に使用） |
| `expense_amount` | 出金額（支出カテゴリのセル値に使用） |
| `category_id` | 紐づくカテゴリ ID（必ず子カテゴリ） |
| `group_id` | 紐づくグループ ID（NULL 可）。NULL の場合「グループなし」列に計上 |

#### categories テーブル

| カラム | 説明 |
|--------|------|
| `id` | カテゴリ ID |
| `full_path` | `A10_給与/基本給` のようなスラッシュ区切りの完全パス。ソートキーに使用 |
| `name` | カテゴリ表示名 |
| `parent_id` | 親カテゴリ ID（NULL = 親カテゴリ）。取引に紐づくのは子カテゴリのみ |

#### groups テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK | グループ ID |
| `code` | String(50) | NOT NULL, UNIQUE | グループコード（例: `10_必須(通常)`、`20_太郎`）。数値プレフィックスが表示順を制御 |
| `name` | String(100) | NOT NULL | グループ表示名 |
| `sort_order` | Integer | NOT NULL, default=0 | 表示順 |

---

## 機能仕様

### 集計対象

- `is_transfer=False` の取引のみ集計する（資金移動は除外）
- 指定した `year`・`month` に一致する取引日の取引に絞り込む

### グループ軸（横）の定義

- 対象月の取引に登録されているグループを `Group.code` 順でヘッダー列として並べる
- グループ ID が `NULL`（グループ未設定）の取引が1件でも存在する場合、`has_no_group=True` となり、最右列に「グループなし」列を追加する
- レスポンスの `groups` は `[{"id": ..., "code": ..., "name": ...}]` の形式

### カテゴリ軸（縦）の定義

- テーブルは**収入セクション**（上部）と**支出セクション**（下部）に分割される
- 収入/支出の判定: 親カテゴリの `income_amount` 合計が 1 円以上なら収入カテゴリ、それ以外は支出カテゴリ
- 各セクション内で `full_path` 昇順にソートされる
- 取引に直接紐づくのは子カテゴリのみ。子カテゴリの `parent_id` をもとに親カテゴリを取得し、親子構造を組み立てる
- 子カテゴリの親が集計結果に存在しない場合は DB から別途クエリして補完する

### マトリックスセルの値

- 各セル = カテゴリ ID × グループ ID の組み合わせに対応する金額合計
  - 収入カテゴリの行: `income_amount` の SUM
  - 支出カテゴリの行: `expense_amount` の SUM
- セルの金額が 0 円の場合、テンプレートで空白表示とする（`if amt` チェック）
- `cells` ディクショナリのキーはグループ ID（整数）または `None`（グループなし）

### 合計行・合計列の計算方法

| 集計値 | 計算方法 |
|--------|--------|
| 行合計（`row_total`）| 各カテゴリ行の全グループ（グループなし含む）金額の合計 |
| 収入計行（`income_col_totals`）| 収入セクションの各グループ列合計。キーはグループ ID |
| 支出計行（`expense_col_totals`）| 支出セクションの各グループ列合計。キーはグループ ID |
| 収入グランド総計（`income_grand_total`）| `income_col_totals` の全グループ合計 |
| 支出グランド総計（`expense_grand_total`）| `expense_col_totals` の全グループ合計 |

- 列合計は収入・支出セクション別に独立して計算される（収支の差引合計は表示しない）
- 親カテゴリの行合計・セル値は子カテゴリの集計を加算した後に確定する

### 表示パラメーター（年・月の指定方法）

- ページ（`/reports/matrix`）: クエリパラメーター `year`・`month` で年月を指定する。未指定時は `today_jst()` で取得した JST 当月をデフォルトにする
- API（`GET /api/v1/reports/matrix`）: `year`・`month` はどちらも必須パラメーター（`Query(...)`）

### 子カテゴリ展開（フロントエンド）

- 親カテゴリ行をクリックすると子カテゴリ行が展開/折り畳まれる（Alpine.js の `open[cat_id]` で状態管理）
- 子カテゴリ行はデフォルト非表示（`x-show="open[cat.cat_id]"` + `x-cloak`）
- 子カテゴリを持つ親行はポインターカーソル、子なし親行はデフォルトカーソルで表示する
- 展開状態は `x-data="{ open: {} }"` でページ内ローカルに管理する（ページリロードでリセット）

### 詳細モーダル

- 金額が入ったセル（`amt-clickable` クラス）をクリックすると `$store.detailModal.show(...)` を呼び出し、取引詳細モーダルを表示する
- `show()` に渡すパラメーター: `year`、`month`、`category_id`、`group_id`（グループなし列の場合は省略）、`title`

### API レスポンス構造

```json
{
  "year": 2026,
  "month": 6,
  "groups": [
    {"id": 1, "code": "10_必須(通常)", "name": "必須(通常)"}
  ],
  "has_no_group": false,
  "income_categories": [
    {
      "cat_id": 10,
      "full_path": "A10_給与",
      "name": "給与",
      "cells": {1: 200000},
      "row_total": 200000,
      "is_income": true,
      "children": [
        {
          "cat_id": 11,
          "full_path": "A10_給与/基本給",
          "name": "基本給",
          "cells": {1: 200000},
          "row_total": 200000,
          "is_income": true
        }
      ]
    }
  ],
  "expense_categories": [...],
  "income_col_totals": {1: 200000},
  "expense_col_totals": {1: 50000},
  "income_grand_total": 200000,
  "expense_grand_total": 50000
}
```

---

## 実装上の注意点

- **JST タイムゾーン:** デフォルト年月の決定には `today_jst()`（`app.jst` モジュール）を使用する。`date.today()` や `datetime.now()` は使わない
- **子カテゴリのみ取引に紐づく:** `get_matrix_report` では、DB から直接取得できるのは取引に紐づく子カテゴリのみ。子の `parent_id` をもとに親カテゴリを DB から補完クエリする処理が含まれる
- **収入/支出の判定:** 親カテゴリの収入合計（`_inc_cells` の合計）が 1 円でもあれば収入カテゴリとして分類する。子カテゴリの集計を親に加算した後に最終確定する
- **`cells` ディクショナリのキー型:** `cells` のキーはグループ ID（整数）または `None`（グループなし）。Jinja2 テンプレートでは `cat.cells.get(grp.id, 0)` および `cat.cells.get(none, 0)` でアクセスする
- **`x-data` 属性のクォート:** このテンプレートでは `x-data="{ open: {} }"` のように `tojson` を使わないリテラルオブジェクトのためダブルクォートを使用している。`tojson` フィルターの出力を `x-data` に埋め込む場合はシングルクォート属性にすること
- **`has_no_group` の列幅計算:** `colspan` の算出で `data.groups | length + (2 if data.has_no_group else 1) + 1` を使っている（カテゴリ列 1 + グループ列数 + グループなし列 0 or 1 + 合計列 1）

---

## 動作確認チェックリスト

- [ ] `/reports/matrix` にアクセスして当月のマトリックスが表示されること
- [ ] 年・月フォームを変更して「表示」ボタンを押すと指定月に切り替わること
- [ ] 収入セクションと支出セクションが分かれて表示されること
- [ ] グループ列のヘッダーにグループ名（`group.name`）が表示されること
- [ ] `group_id=NULL` の取引がある月では「グループなし」列が右端に表示されること
- [ ] `group_id=NULL` の取引がない月では「グループなし」列が表示されないこと
- [ ] 子カテゴリを持つ親行をクリックすると子行が展開されること
- [ ] 展開中の親行を再クリックすると子行が折り畳まれること
- [ ] 子カテゴリを持たない親行はデフォルトカーソルで表示されること
- [ ] 金額が入ったセルをクリックすると詳細モーダルが開くこと
- [ ] 詳細モーダルで絞り込まれた取引一覧が表示されること
- [ ] 「グループなし」列のセルをクリックするとモーダルが `group_id` なしで開くこと
- [ ] 行合計列（「合計」ヘッダー）が各親カテゴリの全グループ合計と一致すること
- [ ] 「収入計」行の各列が収入セクションの列合計と一致すること
- [ ] 「支出計」行の各列が支出セクションの列合計と一致すること
- [ ] ページ上部に収入合計・支出合計のサマリーが表示されること
- [ ] 対象月のデータが存在しない場合は「データがありません」メッセージが表示されること
- [ ] `GET /api/v1/reports/matrix?year=2026&month=6` が正常なJSONを返すこと
- [ ] `month` パラメーターに 1〜12 以外の値を渡すと 422 エラーになること
