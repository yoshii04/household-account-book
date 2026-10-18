# 仕様：C-4 ローン返済シミュレーション

## 概要

借入条件（借入額・年利・返済回数・返済方式など）を入力すると返済スケジュールをプレビューし、確認後に全返済回の取引を DB へ一括作成する機能。元本は資金移動として、利息は通常支出として記録することで、ローン口座残高の正確な追跡を可能にする。繰上返済（期間短縮型・返済額軽減型）にも対応し、土日祝対応の返済日調整もサポートする。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/loans/new` | ローン返済シミュレーション画面（Alpine.js使用） |
| API | `POST /api/v1/loans/preview` | 返済スケジュールのプレビュー（計算のみ、DB変更なし） |
| API | `POST /api/v1/loans/create` | 返済スケジュールに基づいて取引を一括作成 |

---

## 対象ファイル

- `backend/app/routers/loans.py` — `/api/v1/loans/preview` および `/api/v1/loans/create` のルーター
- `backend/app/services/loan_service.py` — 返済スケジュール計算ロジック（元利均等・元金均等・固定額払い・繰上返済）
- `backend/app/schemas/loan.py` — `LoanInput`・`RepaymentItem`・`LoanPreviewResponse` スキーマ
- `backend/app/routers/pages.py` — `/loans/new` ページルート（口座リスト・利息カテゴリを渡す）
- `backend/app/templates/loans/form.html` — ローンシミュレーション画面テンプレート（Alpine.js）
- `backend/app/utils/date_utils.py` — `clamp_day_to_month`（月末日丸め）

---

## データモデル

### 使用テーブル

#### transactions（取引明細）
- `date`: 返済日（土日調整・月末丸め済みの日付）
- `income_amount` / `expense_amount`: 元本取引は資金移動の出金・入金として2件作成
- `category_id`: 利息取引は `A10_ローン/` 配下の子カテゴリ、元本は自動生成カテゴリ
- `account_id`: 元本の出金は返済口座、入金はローン口座
- `is_transfer`: 元本取引は `True`、利息取引は `False`
- `memo`: `{memo_prefix} 第{n}回（元本）` / `{memo_prefix} 第{n}回（利息）` / `{memo_prefix} 繰り上げ返済（元本）`
- `group_id`: オプションで指定されたグループID

#### accounts（口座・カード）
- ローン口座（`loan_account_id`）と返済口座（`repayment_account_id`）の2口座を使用
- 口座の `code` フィールドは資金移動カテゴリの自動生成に使用される

#### categories（カテゴリ階層）
- 利息カテゴリ: `A10_ローン/` 配下の子カテゴリ（`A10_ローン/%` で検索、なければ `A10_ローン%`）
- 元本の資金移動カテゴリ: `upsert_transfer_category` により自動生成・再利用
  - 出金側: `【資金移動】- {loan_account.code}へ -`
  - 入金側: `【資金移動】- {repayment_account.code}から -`

---

## 機能仕様

### 入力パラメータ（LoanInput）

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `loan_account_id` | int | 必須 | ローン口座ID |
| `repayment_account_id` | int | 必須 | 返済口座ID |
| `interest_category_id` | int | 条件付き必須 | 利息カテゴリID（`create_interest_transactions=True` のとき必須） |
| `borrow_date` | date | 必須 | 借入日 |
| `borrow_amount` | float | 必須（gt=0） | 借入額 |
| `annual_rate` | float | 必須（ge=0） | 年利（%単位） |
| `num_payments` | int | 必須（gt=0） | 返済回数 |
| `repayment_day` | int | 必須（1〜31） | 毎月の返済日 |
| `first_payment_date` | date | 必須 | 初回返済日 |
| `repayment_method` | str | 必須 | 返済方式（下記参照） |
| `holiday_handling` | str | 必須 | 土日処理方式（下記参照） |
| `create_interest_transactions` | bool | 必須 | 利息を別取引として記録するか |
| `group_id` | int | オプション | グループID |
| `memo_prefix` | str | オプション | メモプレフィックス（デフォルト: `"ローン返済"`） |
| `early_repayments` | list | オプション | 繰上返済リスト（`date`, `amount` のペア） |
| `early_repayment_type` | str | オプション | 繰上返済タイプ（下記参照） |
| `first_payment_amount` | float | オプション | 初回返済額を明示指定 |
| `last_payment_amount` | float | オプション | 最終回返済額を明示指定 |
| `regular_payment_amount` | float | 条件付き必須 | 固定額払い時の通常返済額（`fixed_payment` 方式のとき必須） |

### 返済方式（repayment_method）

- `equal_installment`（元利均等返済）
  - 毎回の支払額 = `残高 × 月利 × (1+月利)^n / ((1+月利)^n - 1)`
  - 月利 = 年利 / 100 / 12
  - 端数は切り捨て。最終回は残高全額を充当
- `equal_principal`（元金均等返済）
  - 毎回の元金 = 借入額 / 返済回数（最終回は残余残高）
  - 利息 = 残高 × 月利
  - 支払額 = 元金 + 利息
- `fixed_payment`（固定額払い）
  - 毎回 `regular_payment_amount` を支払い
  - 残高が支払額を下回った場合（`remaining <= regular_payment_amount - interest`）は最終回として残高全額を返済
  - `regular_payment_amount` の指定が必須

### 土日処理（holiday_handling）

- `next`: 返済日が土曜・日曜の場合、翌月曜日に調整
- `prev`: 返済日が土曜・日曜の場合、直前の金曜日に調整
- `none`: 調整なし（指定の日付のまま）

### 返済日の月末丸め（clamp_day_to_month）

- `repayment_day` が対象月の末日を超える場合（例: 31日指定で2月）は月末日に丸める
- `calendar.monthrange(year, month)[1]` で月末日を取得して丸め処理

### 繰上返済（early_repayments）

- 繰上返済は `pending_early` リストに保持し、該当返済日以前の繰上返済をスケジュールに挿入
- 繰上返済タイプ（`early_repayment_type`）:
  - `shorten`（期間短縮型）: 繰上返済後も毎月の支払額は変更なし。返済回数が減少する
  - `reduce`（返済額軽減型）: 繰上返済後に残回数で毎月の支払額を再計算（月利を考慮）
- 繰上返済は `is_early_repayment=True` でスケジュールに挿入される
- 繰上返済回の元本取引のメモは `{memo_prefix} 繰り上げ返済（元本）`

### 初回・最終回の明示指定

- `first_payment_amount`: 初回返済額を明示指定（端数調整等に使用）
- `last_payment_amount`: 最終回返済額を明示指定（最終残高の調整等に使用）
- 指定がない場合は計算式に基づいて算出

### プレビューAPI（POST /api/v1/loans/preview）

- DB への書き込みは一切行わない（計算のみ）
- レスポンス（`LoanPreviewResponse`）:
  - `schedule`: `RepaymentItem` のリスト
    - `payment_number`: 返済回番号
    - `payment_date`: 返済日（調整済み）
    - `payment_amount`: 支払総額
    - `principal_amount`: 元本部分
    - `interest_amount`: 利息部分
    - `remaining_balance`: 支払後の残高
    - `is_early_repayment`: 繰上返済かどうか
  - `total_payment`: 総支払額（繰上返済を含む）
  - `total_principal`: 総元本（借入額と一致するはず）
  - `total_interest`: 総利息（繰上返済回を除く通常返済回のみ集計）

### 一括作成API（POST /api/v1/loans/create）

- プレビューと同じ `LoanInput` を受け取り、計算後にそのまま DB へ取引を一括登録
- **重複登録ガード**: 第1回の `{memo_prefix} 第1回（元本）` が同じ口座・日付で既に存在する場合は `409 Conflict` を返す
- 元本取引（資金移動として2件作成）:
  - 返済口座からの出金: `is_transfer=True`, `expense_amount=元本額`
  - ローン口座への入金: `is_transfer=True`, `income_amount=元本額`
  - カテゴリは `upsert_transfer_category` で `【資金移動】- {loan_account.code}へ -` / `【資金移動】- {repayment_account.code}から -` を自動生成・再利用
  - メモ: `{memo_prefix} 第{n}回（元本）`
- 利息取引（`create_interest_transactions=True` の場合のみ）:
  - 通常の支出取引として1件作成
  - `is_transfer=False`, `expense_amount=利息額`
  - カテゴリ: `interest_category_id` で指定された利息カテゴリ
  - メモ: `{memo_prefix} 第{n}回（利息）`
- 繰上返済回:
  - 元本取引（資金移動2件）のみ作成
  - メモ: `{memo_prefix} 繰り上げ返済（元本）`

### 画面（/loans/new）のデータ構成

- テンプレートに渡すデータ:
  - アクティブな口座リスト（`is_active=True`、`code` 昇順）
  - 利息カテゴリリスト: `A10_ローン/%` に一致する子カテゴリ（存在しない場合は `A10_ローン%` でフォールバック）
- Alpine.js を使用してフォーム操作・プレビュー結果の表示を行う

---

## 実装上の注意点

- **日付処理**: `date.today()` や `datetime.now()` は使用禁止。必ず `app.jst` の `today_jst()` / `now_jst()` を使用すること（CLAUDE.md 参照）
- **Alpine.js テンプレートのシングルクォート属性**: `form.html` で Alpine.js の `x-data` に JSON を埋め込む場合は必ずシングルクォート属性を使用すること。ダブルクォートでは JSON 内の `"` が属性区切りと衝突する
  ```html
  {# OK #}
  <div x-data='myComponent({{ data | tojson }})'>
  {# NG #}
  <div x-data="myComponent({{ data | tojson }})">
  ```
- **資金移動カテゴリの自動生成**: 元本取引は `crud/transaction.py` の `upsert_transfer_category` 関数を使用。ローンの場合は `【資金移動】/{from}→{to}` 形式ではなく `【資金移動】- {account.code}へ -` / `【資金移動】- {account.code}から -` 形式で生成される点に注意
- **利息取引の条件付き必須バリデーション**: `create_interest_transactions=True` なのに `interest_category_id` が未指定の場合は、ルーター側またはスキーマのバリデーターで 422 エラーを返すこと
- **端数処理**: 元利均等の支払額計算は切り捨て。端数は最終回に繰り入れる
- **繰上返済の順序**: `early_repayments` リストは日付昇順で処理されることを前提とする。`pending_early` から「返済日以前の繰上返済」を順に取り出してスケジュールに挿入する

---

## 動作確認チェックリスト

- [ ] `/loans/new` 画面が正常に表示される（口座リスト・利息カテゴリが表示される）
- [ ] 元利均等・元金均等・固定額払いそれぞれの方式でプレビューが計算される
- [ ] 年利0%のプレビューが正常に計算される（ゼロ除算にならない）
- [ ] 支払日が月末を超える月（例: 31日指定で2月）は月末日に丸められる
- [ ] `next` / `prev` の土日処理が正しく機能する（土日に当たる日付でテスト）
- [ ] 繰上返済（期間短縮型・返済額軽減型）を含むプレビューが正しく計算される
- [ ] プレビューの `total_principal` が `borrow_amount` と一致する
- [ ] `create_interest_transactions=False` の場合、プレビュー・作成ともに利息取引が含まれない
- [ ] `create_interest_transactions=True` で `interest_category_id` 未指定の場合、バリデーションエラーが返る
- [ ] 一括作成後、ローン口座・返済口座それぞれに正しい取引が登録されている
- [ ] 元本取引が `is_transfer=True`、利息取引が `is_transfer=False` になっている
- [ ] 同一条件で2回 `/api/v1/loans/create` を呼ぶと 409 Conflict が返る
- [ ] 繰上返済回の取引メモが `{memo_prefix} 繰り上げ返済（元本）` になっている
- [ ] `group_id` を指定した場合、作成された全取引に `group_id` が設定される
- [ ] `memo_prefix` を変更した場合、全取引のメモに反映される
