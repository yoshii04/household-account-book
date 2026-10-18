# 仕様：月次集計レポート

## 概要

指定した年月の取引を費目（カテゴリ）別に集計し、収入合計・支出合計・差引を一覧表示する機能。資金移動を除外した通常取引のみを対象とし、親カテゴリをクリックすることで子カテゴリの内訳を展開できる。支出上位10費目の横棒グラフも併せて表示する。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/reports/monthly` | 費目別月次集計（サマリーカード・テーブル・棒グラフ） |
| API | `GET /api/v1/reports/monthly` | 指定年月の費目別集計データを返す |

---

## 対象ファイル

- `backend/app/routers/reports.py` — APIルーター（`/monthly` エンドポイント）
- `backend/app/services/report_service.py` — `get_monthly_summary` 関数（集計ロジック）
- `backend/app/routers/pages.py` — ページルーター（`/reports/monthly` ルート）
- `backend/app/templates/reports/monthly.html` — 月次集計テンプレート
- `backend/app/models/transaction.py` — Transaction ORMモデル
- `backend/app/models/category.py` — Category ORMモデル

---

## データモデル

### transactions テーブル（集計対象フィールド）

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | 取引ID |
| `date` | Date | NOT NULL, index | 取引日 |
| `category_id` | Integer | FK(categories.id), NOT NULL, index | カテゴリID（常に**子カテゴリ**のIDが格納される） |
| `income_amount` | Integer | NOT NULL, default=0 | 入金額（円）。出金取引では 0 |
| `expense_amount` | Integer | NOT NULL, default=0 | 出金額（円）。入金取引では 0 |
| `is_transfer` | Boolean | NOT NULL, default=False, index | 資金移動フラグ。月次集計では除外する |

### categories テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| `id` | Integer | PK, autoincrement | カテゴリID |
| `code` | String(50) | NOT NULL | カテゴリコード |
| `name` | String(100) | NOT NULL | カテゴリ名（表示用） |
| `parent_id` | Integer | FK(categories.id), nullable | 親カテゴリID。`NULL` のとき親カテゴリ（最上位） |
| `full_path` | String(200) | NOT NULL, UNIQUE | 階層パス（例: `B10_食費/外食`）。ソートキーとして使用 |
| `is_transfer` | Boolean | NOT NULL, default=False | 資金移動カテゴリフラグ |

---

## 機能仕様

### API: `GET /api/v1/reports/monthly`

**クエリパラメータ：**

| パラメータ | 型 | 必須 | 制約 | 説明 |
|---|---|---|---|---|
| `year` | int | 必須 | — | 集計年 |
| `month` | int | 必須 | 1〜12 | 集計月 |

**集計クエリ：**

- `transactions` と `categories` を `category_id = Category.id` で JOIN する
- `Transaction.date` の年・月が指定値と一致する行のみ対象（`extract` を使用）
- `Transaction.is_transfer = False` の行のみ対象（資金移動は除外）
- `Category.id`、`full_path`、`parent_id`、`code`、`name` でグループ化し、`SUM(income_amount)` / `SUM(expense_amount)` を算出
- `full_path` 昇順でソート

**親子構造の組み立て：**

取引は常に**子カテゴリ**（`parent_id IS NOT NULL`）に紐づく。集計クエリの結果だけでは親カテゴリの名称・コードが得られないため、以下の手順で親子構造を組み立てる。

1. 集計結果を `parent_id IS NULL`（親カテゴリ）と `parent_id IS NOT NULL`（子カテゴリ）に分類する
2. 子カテゴリが参照する `parent_id` のうち、集計結果に含まれていない（その月に直接取引がない）親カテゴリを DB から補完取得する（`Category.id.in_(missing_parent_ids)` クエリ）
3. 補完した親カテゴリは `total_income = 0`、`total_expense = 0` で初期化する
4. 各子カテゴリを対応する親の `children` リストに追加し、子の金額を親の合計に加算する
5. 親が見つからない場合は、その子カテゴリ自身を親として `parent_map` に登録する
6. 全親カテゴリを `full_path` 昇順でソートする

**収入・支出の分類：**

- `income_categories`：`total_income > 0` のカテゴリ（収入が1円でもあれば収入カテゴリ）
- `expense_categories`：`total_income == 0` のカテゴリ（収入が0円のカテゴリはすべて支出カテゴリ）

**レスポンス構造：**

```json
{
  "year": 2025,
  "month": 6,
  "total_income": 350000,
  "total_expense": 180000,
  "categories": [ /* income_categories + expense_categories を full_path 順に結合したリスト */ ],
  "income_categories": [
    {
      "cat_id": 10,
      "full_path": "A10_給与",
      "code": "A10",
      "name": "給与",
      "total_income": 350000,
      "total_expense": 0,
      "children": [
        {
          "cat_id": 11,
          "full_path": "A10_給与/本給",
          "code": "本給",
          "name": "本給",
          "total_income": 300000,
          "total_expense": 0
        }
      ]
    }
  ],
  "expense_categories": [
    {
      "cat_id": 20,
      "full_path": "B10_食費",
      "code": "B10",
      "name": "食費",
      "total_income": 0,
      "total_expense": 45000,
      "children": [ /* ... */ ]
    }
  ]
}
```

- `total_income` / `total_expense` はすべての `is_transfer=False` 行の合計（`income_categories` と `expense_categories` の合算）
- 子カテゴリのエントリには `children` キーを含まない
- 親カテゴリの `total_income` / `total_expense` は子の合計を含む（自身に取引がなくても子の合計が加算される）

### 画面: `/reports/monthly`

**年月の初期値：**

- クエリパラメータ `year` / `month` が指定されていない場合、`today_jst()` で取得した当日の年月をデフォルトとして使用する

**ページ構成：**

1. **年月選択フォーム（GET）：** `year`（number input）と `month`（select）を選択して「表示」ボタンで再取得する
2. **サマリーカード（3枚）：**
   - 収入合計カード：`¥{total_income:,}`
   - 支出合計カード：`¥{total_expense:,}`
   - 差引カード：`¥{total_income - total_expense:,}`。差引が 0 以上のとき `positive`、負のとき `negative` CSS クラスを付与する
3. **費目別テーブル：** 収入セクション（背景 `#f0f8f0`）→ 支出セクション（背景 `#fff0f0`）の順に表示する
4. **棒グラフ（Chart.js）：** 支出カテゴリのみ対象。詳細は「グラフ仕様」を参照

**費目テーブルの動作（Alpine.js）：**

- テーブル全体を `x-data="{ open: {} }"` で囲み、`open` オブジェクトでカテゴリIDごとの展開状態を管理する
- **親行（`parent-row`）：** クリックで `open[cat_id]` をトグルする。子カテゴリが存在する場合のみ `cursor: pointer` を設定する
- **トグルアイコン：** `x-text="open[cat_id] ? '▼' : '{% if cat.children %}▶{% endif %}'"` で展開状態に応じて切り替える。子がない場合はアイコン非表示
- **子行（`child-row`）：** `x-show="open[cat_id]"` / `x-cloak` を使い、初期状態で非表示とする。左余白 `2em` でインデント表示する
- **金額セルのクリック（`amt-clickable`）：** 金額が 0 でない場合に `amt-clickable` クラスを付与し、`@click.stop` で取引詳細モーダルを開く
  - モーダルは `$store.detailModal.show({year, month, category_id, title})` で呼び出す
  - `title` は `"<カテゴリ名> <year>年<month>月"` の形式
  - `@click.stop` で親行のトグルイベントへの伝播を防ぐ

### グラフ仕様

- **Chart.js** の棒グラフ（`type: 'bar'`、`indexAxis: 'y'` で横棒）
- **対象：** `expense_categories` のうち `total_expense > 0` のカテゴリのみ
- **上位10件：** `total_expense` 降順でソートし、先頭10件を表示
- **凡例：** 非表示（`legend: { display: false }`）
- **色：** 10色のプリセット配列からインデックス順に割り当て（`['#FF6384','#36A2EB','#FFCE56','#4BC0C0','#9966FF','#FF9F40','#C9CBCF','#7BC8A4','#E8A838','#B5A8D7']`）
- グラフのデータは `<script>` ブロックに Jinja2 でサーバーサイドレンダリングされる（Alpine.js 不使用）

---

## 実装上の注意点

- **JST タイムゾーン：** デフォルトの年月取得に `date.today()` や `datetime.now()` は使わず、`from app.jst import today_jst` の `today_jst()` を使うこと
- **親カテゴリの DB 補完：** 集計クエリは取引が存在するカテゴリしか返さない。子カテゴリが参照する親カテゴリに直接取引がない場合は `Category.id.in_(missing_parent_ids)` で別途 DB から補完する。この補完を省略すると、子カテゴリが親にひも付かず孤立する
- **`amt-clickable` のイベント伝播：** 金額セルの `@click.stop` は必須。省略すると金額クリック時に親行のトグルも同時に発生する
- **`total_income` による収入・支出の分類：** 収入カテゴリの判定条件は「`total_income > 0`」であり、支出額の有無は関係しない。収入が1円でもあれば `income_categories` に分類される
- **カテゴリ検索に JOIN を使わないこと：** 取引一覧などで `joinedload` と JOIN が重複するとSQLエラーになる。カテゴリ絞り込みが必要な場合はサブクエリを使用すること（本機能の集計クエリは直接 JOIN を使っているが、`get_transactions` などと組み合わせる場合は注意）
- **Jinja2 テンプレートへの Alpine.js バインディング：** `x-data` 属性にオブジェクトを渡す場合はシングルクォート属性を使うこと（`x-data='myComponent({{ data | tojson }})'`）。本機能のテーブルは `x-data="{ open: {} }"` のみのため現状問題ないが、JSON を埋め込む拡張時は注意すること
- **グラフデータのサーバーサイドレンダリング：** `<script>` ブロック内への Jinja2 埋め込みは `tojson` のみで問題ない（HTML エスケープ不要）

---

## 動作確認チェックリスト

- [ ] `/reports/monthly` にアクセスして当月（JST）のデータがデフォルト表示されること
- [ ] 年・月を変更して「表示」ボタンを押すと指定年月のデータに切り替わること
- [ ] 収入合計・支出合計・差引のサマリーカードが正しい金額を表示すること
- [ ] 差引がプラスのとき `positive`、マイナスのとき `negative` の CSS クラスが付くこと
- [ ] テーブルに「── 収入 ──」と「── 支出 ──」のセクション区切りが表示されること
- [ ] 収入カテゴリが上部、支出カテゴリが下部に表示されること
- [ ] 子カテゴリを持つ親行をクリックすると ▶ → ▼ に切り替わり、子行が展開されること
- [ ] 再クリックで子行が折りたたまれること
- [ ] 子カテゴリを持たない親行はアイコン非表示、クリックしても何も起きないこと
- [ ] 子カテゴリ行が親カテゴリ名より 2em インデントされて表示されること
- [ ] 金額セル（非ゼロ）をクリックすると取引詳細モーダルが開き、タイトルに「カテゴリ名 年月」が表示されること
- [ ] 金額セルのクリックで親行の展開・折りたたみが誤って発動しないこと
- [ ] 支出カテゴリの棒グラフが表示され、支出額降順の上位10費目が横棒で表示されること
- [ ] 取引が存在しない月では「データなし」と表示されること
- [ ] 親カテゴリ自身に取引がなく子カテゴリのみに取引がある場合、親の合計に子の金額が正しく加算されること
