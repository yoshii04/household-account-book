# 仕様：B-9 口座残高レポート

## 概要

指定日付時点の口座別残高を一覧表示する機能。`initial_balance`・`adjustment_amount` に加え、起算日（`start_date`）以降・指定日以前の取引差額を積み上げることで各口座の実残高を算出する。口座タイプ別の種別明細と、分類（`classification`）別の小計を並べて提供することで、資産全体の状況を把握できる。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/reports/account-balance` | 口座別金額集計（アカウント別金額集計）画面 |
| API | `GET /api/v1/reports/account-balance` | 口座残高レポート JSON |

---

## 対象ファイル

- `backend/app/routers/reports.py` — API ルーター（`/api/v1/reports/account-balance`）
- `backend/app/routers/pages.py` — ページルーター（`/reports/account-balance`）
- `backend/app/services/report_service.py` — 集計ロジック（`get_account_balance_report`、行 1322〜）
- `backend/app/models/account.py` — `Account` ORM モデル
- `backend/app/models/account_type.py` — `AccountType` ORM モデル
- `backend/app/templates/reports/account_balance.html` — Jinja2 テンプレート

---

## データモデル

### accounts

| フィールド | 型 | 説明 |
|---|---|---|
| `id` | Integer (PK) | |
| `code` | String(50), UNIQUE | 口座コード（並び順の基準） |
| `name` | String(100) | 口座名 |
| `account_type` | String(20) | タイプコード（`cash` / `bank` / `card` / `e-money` / `other`） |
| `sort_order` | Integer | （本レポートでは使用せず `code` 順） |
| `is_active` | Boolean | `False` の口座は集計対象外 |
| `start_date` | Date, nullable | 残高計算の起算日。NULL の場合は全期間が対象 |
| `initial_balance` | Integer, nullable | 起算日時点の初期残高 |
| `adjustment_amount` | Integer, nullable | 残高調整額 |
| `classification` | String(100), nullable | 口座分類（例: `個人`、`共通`） |

### account_types

| フィールド | 型 | 説明 |
|---|---|---|
| `id` | Integer (PK) | |
| `code` | String(50), UNIQUE | タイプコード |
| `label` | String(100) | 画面表示ラベル |
| `sort_order` | Integer | グループ表示順 |

### transactions（集計に使用するフィールド）

| フィールド | 型 | 説明 |
|---|---|---|
| `account_id` | Integer (FK) | 対象口座 |
| `date` | Date | 取引日 |
| `income_amount` | Integer | 入金額 |
| `expense_amount` | Integer | 出金額 |
| `is_transfer` | Boolean | 資金移動フラグ（本レポートでは除外しない） |

---

## 機能仕様

### クエリパラメータ

| パラメータ | 型 | デフォルト（画面） | デフォルト（API） | 説明 |
|---|---|---|---|---|
| `as_of_date` | date, optional | `today_jst()`（今日） | `_last_day_of_prev_month()`（JST 前月末日） | 集計基準日 |
| `show_zero` | bool | `False` | 非対応（常に `False`） | 差引残高が 0 円の口座を表示するか |

- 画面と API でデフォルト日付が異なる。画面はデフォルト「今日」、API はデフォルト「前月末日（JST）」。
- `_last_day_of_prev_month()` の実装: `today_jst().replace(day=1) - timedelta(days=1)`
- `show_zero` は画面クエリパラメータとしてのみ公開されている。API にはパラメータなし。

### 対象口座のフィルタリング

- `Account.is_active == True` の口座のみ集計対象とする。
- 口座の取得順は `Account.code` の昇順。

### 残高計算ロジック

口座ごとに以下の手順で残高を算出する。

1. `Transaction.account_id == acc.id` かつ `Transaction.date <= as_of_date` の取引を対象とする。
2. `acc.start_date` が設定されている場合は、さらに `Transaction.date >= acc.start_date` を追加する（起算日より前の取引を除外）。
3. 対象取引の `income_amount` 合計を `total_income`、`expense_amount` 合計を `total_expense` として取得する（`COALESCE` で NULL を 0 に変換）。
4. 以下の式で残高を計算する:

   ```
   balance = initial_balance + adjustment_amount + total_income - total_expense
   ```

   （`initial_balance` / `adjustment_amount` が NULL の場合は 0 として扱う）

- `is_transfer` フラグによる除外は行わない。資金移動取引も残高計算に含める。

### 表示対象の絞り込み

以下の条件を両方満たす口座は常に非表示（`show_zero` の設定に関わらず）:

```
total_income == 0 AND total_expense == 0 AND initial_balance == 0 AND adjustment_amount == 0
```

`show_zero == False`（デフォルト）のとき、`balance == 0` の口座も非表示とする。

### グループ化と表示構造

#### 種別別グループ（`grouped`）

- `account_types` テーブルを `sort_order` 昇順 → `code` 昇順で取得し、その順番でグループを並べる。
- `account_types` に存在しないタイプコードを持つ口座は、後方に追加される。
- 各グループは以下の小計を持つ:
  - `subtotal_initial`（初期残高の合計）
  - `subtotal_adjustment`（調整金額の合計）
  - `subtotal_income`（収入累計の合計）
  - `subtotal_expense`（支出累計の合計）
  - `subtotal_balance`（差引残高の合計）
- 画面では種別ラベルを `account_types.label` から参照して表示する（存在しない場合はコードをそのまま表示）。

#### 分類別集計（`classified_groups`）

- `classification` が設定されている口座を分類ごとに集計する。
- 分類名のアルファベット/文字コード昇順でソートされる。
- 各分類グループは種別別グループと同じ小計フィールドを持つ。
- 画面では、分類が設定されている口座が 1 件以上存在する場合のみ「分類別集計」テーブルを表示する。

#### 分類なしグループ（`unclassified`）

- `classification` が設定されていない口座を、種別グループ単位でまとめたリスト。
- 画面の分類別集計テーブルで「（分類なし）」行として表示する。

### API レスポンス構造

```json
{
  "as_of_date": "YYYY-MM-DD",
  "accounts": [
    {
      "account_id": 1,
      "code": "...",
      "name": "...",
      "account_type": "bank",
      "account_type_label": "銀行",
      "classification": "個人",
      "initial_balance": 100000,
      "adjustment_amount": 0,
      "total_income": 50000,
      "total_expense": 30000,
      "balance": 120000,
      "start_date": "2024-01-01"
    }
  ],
  "grouped": [...],
  "classified_groups": [...],
  "unclassified": [...],
  "grand_initial": 0,
  "grand_adjustment": 0,
  "grand_income": 0,
  "grand_expense": 0,
  "grand_balance": 0
}
```

- `start_date` は `isoformat()` 文字列（口座に `start_date` が未設定の場合は `null`）。

### 画面表示

- ページタイトル: 「アカウント別金額集計」
- サマリーカード: 収入合計 / 支出合計 / 差引残高（初期残高・調整金額含む）を表示。
- 集計日フォーム: 日付入力と「残高0円の口座も表示」チェックボックスを持ち、`GET` で再送信。
- 「残高0円の口座も表示」チェックボックス変更時に `onchange="this.form.submit()"` で即時再送信する。
- 種別別明細テーブルで種別列は `rowspan` でまとめて表示する。
- 口座に `start_date` が設定されている場合、口座名の隣に「（YYYY-MM-DD 以降）」を小文字で表示する。
- 分類タグは `background:#e8edf2` のバッジ形式で表示し、未設定の場合は「—」を表示する。
- 調整金額が 0 の場合は「—」を表示し、正の場合は「+¥...」形式で表示する。

---

## 実装上の注意点

- **JST タイムゾーン**: デフォルト日付の算出に `today_jst()` を使用すること（`date.today()` 不可）。
- **テンプレートへの日付渡し**: `target_date.isoformat()` で文字列に変換してからテンプレートに渡す（`date` オブジェクトをそのまま `tojson` に渡すと `TypeError` になるため）。
- **資金移動取引の扱い**: 他の集計レポート（月次集計など）とは異なり、本レポートでは `is_transfer` フラグによる除外を行わない。資金移動取引も残高計算に含める。
- **`show_zero` パラメータ**: 画面のみ対応。API エンドポイントには `show_zero` パラメータが存在せず、常に `False` 相当で動作する。

---

## 動作確認チェックリスト

- [ ] `as_of_date` 未指定時、画面は今日、API は前月末日がデフォルトになる
- [ ] `start_date` が設定された口座で、起算日より前の取引が残高計算に含まれない
- [ ] `start_date` が未設定の口座では全期間の取引が集計される
- [ ] `balance = initial_balance + adjustment_amount + total_income - total_expense` で正しく計算される
- [ ] 取引も残高もない口座（全フィールドが 0）は `show_zero` に関わらず非表示になる
- [ ] 差引残高が 0 の口座は `show_zero=False`（デフォルト）では非表示、`show_zero=true` では表示される
- [ ] 種別グループが `account_types.sort_order` → `code` 順で表示される
- [ ] 分類が設定された口座が存在する場合のみ「分類別集計」セクションが表示される
- [ ] 分類別集計が分類名の文字コード昇順で表示される
- [ ] 分類なしの口座が「（分類なし）」行として正しく集計される
- [ ] 資金移動取引が残高計算に含まれる（除外されない）
- [ ] `is_active=False` の口座が集計対象に含まれない
- [ ] 「残高0円の口座も表示」チェックボックス変更時にフォームが即時送信される
- [ ] サマリーカード・種別別明細・分類別集計の合計が一致している
