# 仕様：B-7 口座別年次集計

## 概要

口座ごとの累計残高を年単位・月単位・日単位の3層でドリルダウン表示する機能。各時点における「初回取引（または start_date）から対象期間末時点までの累計残高（initial_balance + adjustment_amount を含む）」を縦軸（種別／口座）×横軸（年/月/日）のクロス表形式で確認できる。資金移動を含む全取引を対象として残高を算出するため、純粋な口座残高の推移把握に使用する。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面（第1層） | `/reports/account-annual` | 口座別年次累計残高（年範囲指定） |
| 画面（第2層） | `/reports/account-annual/monthly` | 口座別月次累計残高（指定年の1〜12月） |
| 画面（第3層） | `/reports/account-annual/monthly/daily` | 口座別日次累計残高（指定年月の1日〜月末日） |
| API（第1層） | `GET /api/v1/reports/account-annual` | 年次累計残高 JSON |
| API（第2層） | `GET /api/v1/reports/account-monthly` | 月次累計残高 JSON |
| API（第3層） | `GET /api/v1/reports/account-monthly-daily` | 日次累計残高 JSON |

---

## 対象ファイル

- `backend/app/routers/reports.py` — APIルーター（`/account-annual`、`/account-monthly`、`/account-monthly-daily` エンドポイント）
- `backend/app/routers/pages.py` — 画面ルーター（`/reports/account-annual`、`/monthly`、`/monthly/daily`）
- `backend/app/services/report_service.py` — `get_account_annual_report`、`get_account_annual_monthly_report`、`get_account_monthly_daily_report` 関数
- `backend/app/models/account_type.py` — 口座タイプマスタ（種別ラベル・表示順の参照元）
- `backend/app/templates/reports/account_annual.html` — 年次画面テンプレート
- `backend/app/templates/reports/account_annual_monthly.html` — 月次画面テンプレート
- `backend/app/templates/reports/account_annual_monthly_daily.html` — 日次画面テンプレート

---

## データモデル

### accounts（口座）

| フィールド | 型 | 説明 |
|---|---|---|
| `id` | Integer PK | 口座ID |
| `code` | String | 口座コード（表示順ソート用） |
| `name` | String | 口座名 |
| `account_type` | String | 口座タイプコード（`cash` / `bank` / `card` / `e-money` / `other`） |
| `is_active` | Boolean | 有効フラグ（True のもののみ集計対象） |
| `sort_order` | Integer | 表示順 |
| `start_date` | Date | 残高計算の起算日（設定時はこれ以降の取引のみ集計） |
| `initial_balance` | Integer | 起算日時点の初期残高 |
| `adjustment_amount` | Integer | 残高調整額 |

### account_types（口座タイプマスタ）

| フィールド | 型 | 説明 |
|---|---|---|
| `code` | String | タイプコード（accounts.account_type と対応） |
| `label` | String | 表示ラベル |
| `sort_order` | Integer | 種別グループの表示順 |

### transactions（取引明細）

| フィールド | 型 | 説明 |
|---|---|---|
| `account_id` | Integer FK | 口座ID |
| `date` | Date | 取引日 |
| `income_amount` | Integer | 入金額 |
| `expense_amount` | Integer | 出金額 |
| `is_transfer` | Boolean | 資金移動フラグ |

---

## 機能仕様

### 3層ドリルダウン構造

- **第1層（年次）**：`/reports/account-annual` — `start_year`〜`end_year` の範囲で各年末時点の累計残高を表示。年のリンクをクリックすると第2層へ遷移。
- **第2層（月次）**：`/reports/account-annual/monthly?year=YYYY` — 指定年の1〜12月について各月末時点の累計残高を表示。月のリンクをクリックすると第3層へ遷移。
- **第3層（日次）**：`/reports/account-annual/monthly/daily?year=YYYY&month=M` — 指定年月の1日〜月末日について各日末時点の累計残高を表示。

### 累計残高の計算方法

- **基準値（base）** = `initial_balance`（NULL は 0 扱い）+ `adjustment_amount`（NULL は 0 扱い）
- **各期間末の累計残高** = base + その期間末時点までの全取引の純収支（`income_amount` - `expense_amount` の合計）

#### 年次（get_account_annual_report）

- 対象取引：`account_id` が一致、かつ `date <= date(end_year, 12, 31)`
- `start_date` が設定されている口座は `date >= start_date` の取引のみ
- 年別に `income_amount` - `expense_amount` を合計（`yearly_net`）
- 各表示年の累計残高 = base + 対象年以前の全 `yearly_net` の合計

#### 月次（get_account_annual_monthly_report）

- 対象取引：`account_id` が一致、かつ `date <= date(year, 12, 31)`
- `start_date` が設定されている口座は `date >= start_date` の取引のみ
- (年, 月)ごとに純収支を集計（`monthly_net`）
- 各表示月（1〜12）の累計残高 = base + `指定年より前の全月 + 指定年の対象月以前` の純収支合計

#### 日次（get_account_monthly_daily_report）

- **前月末残高の計算**：`date < date(year, month, 1)` の全取引をまとめて集計し、base + 合計で前月末残高（`balance_before_month`）を算出
- **日別純収支**：`date >= date(year, month, 1)` かつ `date <= date(year, month, 月末日)` の取引を日別に集計（`daily_net`）
- 各日の累計残高 = 前日の累計残高 + その日の純収支（前月末残高から日ごとに積算）

### 資金移動取引の扱い

- `is_transfer` によるフィルタリングは行わない。資金移動を含む全取引が集計対象となる。
- 口座残高として資金移動（例：銀行口座からクレジットカード引き落とし）も反映される。

### 表示対象口座の絞り込み

- `Account.is_active = True` の口座のみ対象
- `yearly_net`（または `monthly_net`、`daily_net`）が空で base も 0 の場合はその口座を結果から除外する

### 種別グループ化と表示順

- `AccountType` テーブルの `sort_order`、`code` でソートした順が種別グループの表示順となる
- `AccountType` に登録されていない `account_type` コードを持つ口座は、登録済み種別の後ろに追加表示される
- 種別グループが2つ以上ある場合に限り、種別小計行を表示する

### 各列のラベル

| 層 | 横軸ラベル | 右端列ラベル |
|---|---|---|
| 年次 | `YYYY年`（リンクあり） | `{end_year}年末残高` |
| 月次 | `M月`（リンクあり） | `12月末残高` |
| 日次 | `D日`（リンクなし） | `月末残高` |

### パラメーター仕様

#### 画面（pages.py）

| パラメーター | 層 | 必須 | 説明 |
|---|---|---|---|
| `start_year` | 年次 | 任意 | 開始年（省略時: DBの最古取引年） |
| `end_year` | 年次 | 任意 | 終了年（省略時: 当年） |
| `year` | 月次・日次 | 必須 | 対象年 |
| `month` | 日次 | 必須 | 対象月（1〜12） |
| `start_year`, `end_year` | 月次・日次 | 任意 | 年次画面に戻るリンク用として引き継ぐ |

- 年次画面で `start_year > end_year` の場合は自動的に入れ替える
- `start_year` の最小年はDBの最古取引年（`func.min(Transaction.date)` から算出）

#### API（reports.py）

| エンドポイント | パラメーター | 型 | 必須 |
|---|---|---|---|
| `GET /api/v1/reports/account-annual` | `start_year` | int | 必須 |
| `GET /api/v1/reports/account-annual` | `end_year` | int | 必須 |
| `GET /api/v1/reports/account-monthly` | `year` | int | 必須 |
| `GET /api/v1/reports/account-monthly-daily` | `year` | int | 必須 |
| `GET /api/v1/reports/account-monthly-daily` | `month` | int | 必須 |

### APIレスポンス構造

#### 年次（/account-annual）

```json
{
  "start_year": 2020,
  "end_year": 2024,
  "years": [2020, 2021, ...],
  "accounts": [
    {
      "account_id": 1,
      "code": "bank_001",
      "name": "銀行口座A",
      "account_type": "bank",
      "start_date": "2020-01-01",
      "cells": {"2020": 100000, "2021": 150000, ...},
      "row_total": 150000
    }
  ],
  "grouped": [
    {
      "type": "bank",
      "type_label": "銀行",
      "accounts": [...],
      "subtotal_cells": {"2020": 100000, ...},
      "subtotal_total": 150000
    }
  ],
  "year_totals": {"2020": 200000, ...},
  "grand_total": 300000
}
```

#### 月次（/account-monthly）

- `years` の代わりに `year`（int）と `months`（[1..12]）
- `year_totals` の代わりに `month_totals`（キー: "1"〜"12"）
- `row_total` は 12月末の累計残高

#### 日次（/account-monthly-daily）

- `year`、`month`、`days`（[1..月末日]）、`days_in_month`
- `day_totals`（キー: "1"〜月末日の文字列）
- `row_total` は月末日の累計残高

### 金額の表示形式（テンプレート）

- 残高がプラスの場合：`+¥{:,}` 形式（例: `+¥150,000`）
- 残高がマイナスの場合：`¥{:,}` 形式（例: `¥-50,000`）、CSSクラス `amount-expense` 付与
- 残高が 0 の場合：セルは空白表示
- 残高がプラスの場合：CSSクラス `amount-income` 付与
- 種別小計行の 0 は `—` 表示

### start_date の表示

- 口座に `start_date` が設定されている場合、口座名の横に `（YYYY-MM-DD 以降）` を小文字で表示

---

## 実装上の注意点

- JST タイムゾーン：当年の取得に `today_jst().year` を使用（`date.today()` は使用しない）
- `start_date` が設定されている口座では、`start_date` より前の取引は集計から除外される。ただし `initial_balance` と `adjustment_amount` は無条件に加算される
- 日次レポートでは前月末残高（`balance_before_month`）を先に計算し、そこから日ごとに加算する方式を採用している
- `has_data` 判定（日次）：当月の取引がなくても前月以前に取引がある場合は表示対象に含める
- `AccountType` に登録されていないタイプコードの口座は `type_label` がコード値のまま表示される

---

## 動作確認チェックリスト

- [ ] `/reports/account-annual` にアクセスしてクエリパラメーターなしで表示できる（start_year=DBの最古年、end_year=当年が使われる）
- [ ] `start_year` > `end_year` を指定したとき自動で入れ替わる
- [ ] 年次画面の年リンクをクリックすると `/reports/account-annual/monthly?year=YYYY` に遷移する
- [ ] 月次画面の月リンクをクリックすると `/reports/account-annual/monthly/daily?year=YYYY&month=M` に遷移する
- [ ] 日次・月次画面の「← 月別に戻る」「← 年別に戻る」リンクが正しいパラメーター付きで遷移する
- [ ] `start_date` が設定された口座で、起算日より前の取引が集計から除外されることを確認する
- [ ] `initial_balance` と `adjustment_amount` が残高に加算されることを確認する
- [ ] 資金移動取引（`is_transfer=True`）も残高計算に含まれることを確認する
- [ ] 取引も残高もない口座（base=0 かつ取引なし）が表示されないことを確認する
- [ ] 種別グループが1つしかない場合に小計行が表示されないことを確認する
- [ ] 種別グループが2つ以上の場合に小計行が表示されることを確認する
- [ ] `AccountType` の `sort_order` 順に種別グループが並ぶことを確認する
- [ ] 年次 API `GET /api/v1/reports/account-annual?start_year=2020&end_year=2024` が正常なJSONを返す
- [ ] 月次 API `GET /api/v1/reports/account-monthly?year=2024` が正常なJSONを返す
- [ ] 日次 API `GET /api/v1/reports/account-monthly-daily?year=2024&month=3` が正常なJSONを返す
