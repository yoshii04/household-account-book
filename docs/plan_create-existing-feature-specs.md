# 計画：既存機能の仕様書作成

## 概要

AI仕様駆動開発フレームワーク（`docs/plan_ai-spec-driven-development.md`）を既存機能に適用するため、
現在実装済みの全機能について機能仕様書を作成する。
これにより、今後の機能追加・修正をAIに依頼する際の精度と再現性を高める。

---

## docs ディレクトリ構造の整備

仕様書を機能分類ごとに3階層で管理するため、以下のディレクトリ構造を作成する。
これは仕様書作成に先行して実施する。

```
docs/
└── specs/                          # 仕様書ルート
    ├── index.md                    # 機能一覧索引（後述）
    ├── core/                       # コア機能（グループA）
    │   ├── spec_transactions.md
    │   ├── spec_import.md
    │   ├── spec_categories.md
    │   └── spec_accounts.md
    ├── reports/                    # レポート機能（グループB）
    │   ├── spec_dashboard.md
    │   ├── spec_report-monthly.md
    │   ├── spec_report-comparison.md
    │   ├── spec_report-matrix.md
    │   ├── spec_report-annual.md
    │   ├── spec_report-yearly-trend.md
    │   ├── spec_report-account-annual.md
    │   ├── spec_report-account-classification.md
    │   └── spec_report-account-balance.md
    └── auxiliary/                  # 補助機能（グループC）
        ├── spec_patterns.md
        ├── spec_export.md
        ├── spec_pdf-export.md
        ├── spec_loans.md
        ├── spec_backup.md
        └── spec_groups.md
```

### 作成手順

1. `docs/specs/` ディレクトリを作成する
2. `docs/specs/core/`、`docs/specs/reports/`、`docs/specs/auxiliary/` を作成する
3. `docs/specs/index.md` を作成する（内容は次節を参照）

---

## 機能一覧索引の作成

`docs/specs/index.md` として機能一覧索引を作成し、全仕様書へのリンクを一覧できる形にする。
これにより、特定機能の仕様書をすぐに参照できるようにする。

### index.md のフォーマット

```markdown
# 機能仕様書 索引

## コア機能

| No | 機能名 | 仕様書 | 優先度 |
|----|--------|--------|--------|
| A-1 | 取引管理 | [spec_transactions.md](core/spec_transactions.md) | 高 |
| A-2 | インポート | [spec_import.md](core/spec_import.md) | 高 |
| A-3 | カテゴリ管理 | [spec_categories.md](core/spec_categories.md) | 高 |
| A-4 | 口座管理 | [spec_accounts.md](core/spec_accounts.md) | 高 |

## レポート機能

| No | 機能名 | 仕様書 | 優先度 |
|----|--------|--------|--------|
| B-1 | ダッシュボード | [spec_dashboard.md](reports/spec_dashboard.md) | 高 |
| B-2 | 月次集計レポート | [spec_report-monthly.md](reports/spec_report-monthly.md) | 高 |
| B-3 | 前年同月比レポート | [spec_report-comparison.md](reports/spec_report-comparison.md) | 中 |
| B-4 | カテゴリ×グループ マトリックス | [spec_report-matrix.md](reports/spec_report-matrix.md) | 中 |
| B-5 | 年次集計レポート | [spec_report-annual.md](reports/spec_report-annual.md) | 中 |
| B-6 | 年度別トレンドレポート | [spec_report-yearly-trend.md](reports/spec_report-yearly-trend.md) | 中 |
| B-7 | 口座別年次集計 | [spec_report-account-annual.md](reports/spec_report-account-annual.md) | 中 |
| B-8 | 口座分類別年次集計 | [spec_report-account-classification.md](reports/spec_report-account-classification.md) | 中 |
| B-9 | 口座残高レポート | [spec_report-account-balance.md](reports/spec_report-account-balance.md) | 中 |

## 補助機能

| No | 機能名 | 仕様書 | 優先度 |
|----|--------|--------|--------|
| C-1 | 定期取引パターン管理 | [spec_patterns.md](auxiliary/spec_patterns.md) | 中 |
| C-2 | エクスポート | [spec_export.md](auxiliary/spec_export.md) | 低 |
| C-3 | PDF出力 | [spec_pdf-export.md](auxiliary/spec_pdf-export.md) | 低 |
| C-4 | ローン返済シミュレーション | [spec_loans.md](auxiliary/spec_loans.md) | 低 |
| C-5 | バックアップ・リストア | [spec_backup.md](auxiliary/spec_backup.md) | 低 |
| C-6 | グループ管理 | [spec_groups.md](auxiliary/spec_groups.md) | 低 |
```

### 作成・運用ルール

- 仕様書を新規追加する際は必ず `index.md` にも行を追加する
- 索引は機能グループ単位（コア・レポート・補助）で分類する
- 仕様書が未作成の行も先に索引に追加しておき、作成後にリンクを有効にする

---

## 目的

- 既存機能の設計意図・制約・ビジネスルールをドキュメント化する
- 将来の機能変更時に、AIへの指示精度を高める基盤を整備する
- 機能ごとに「何が正しい動作か」を明文化し、レビュー・動作確認の基準とする

---

## 仕様書作成の方針

### 仕様書の位置づけ

- 各機能の仕様書は `docs/specs/<category>/spec_<feature-name>.md` として作成する（3階層構造）
- `plan_*.md`（計画書）とは別ファイルとし、実装済みの確定仕様を記録する
- 既存機能向けの専用テンプレートを使う（`plan_ai-spec-driven-development.md` のテンプレートとは別物）

### 既存機能仕様書のテンプレート

`plan_ai-spec-driven-development.md` のテンプレートは「新機能を計画する」ためのもので、
「現状の問題点」「確認事項（未決事項）」「要件」「実装方針」など変更指向のセクションを持つ。
既存機能の仕様書には以下の専用テンプレートを使うこと。

```markdown
# 仕様：<機能名>

## 概要

<機能の目的とユーザーストーリーを2〜3文で>

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/path` | <概要> |
| API | `GET /api/v1/...` | <概要> |

---

## 対象ファイル

- `backend/app/routers/xxx.py` — APIルーター
- `backend/app/services/xxx.py` — ビジネスロジック
- `backend/app/crud/xxx.py` — DBアクセス
- `backend/app/models/xxx.py` — ORMモデル
- `backend/app/schemas/xxx.py` — Pydanticスキーマ
- `backend/app/templates/xxx/` — Jinja2テンプレート

---

## データモデル

<使用するテーブル・主要フィールド・制約を記載>

---

## 機能仕様

### <機能サブセクション1>

- <ビジネスルール・動作仕様を箇条書き>

### <機能サブセクション2>

...

---

## 実装上の注意点

- <CLAUDE.md の関連ルール>（例：Jinja2テンプレートに Alpine.js バインディングが含まれる場合は
  シングルクォート属性 `x-data='{{ data | tojson }}'` を使うこと）
- <日付処理が含まれる場合は `today_jst()` / `now_jst()` を使うこと>
- <既存コードとの整合性に関する注意>

---

## 動作確認チェックリスト

- [ ] <確認項目1>
- [ ] <確認項目2>
```

### 作成時の注意点

- 「現状の実装を記録する」のが目的のため、問題点があっても仕様書には現状を記載する
  （改善は別の `plan_*.md` で計画する）
- 複数画面を持つ機能は1ファイルにまとめる（例：年次集計とそのグラフ画面）
- APIのみの機能（カテゴリ管理、グループ管理）も対象とする

---

## 機能一覧と仕様書作成計画

### 優先度の考え方

| 優先度 | 基準 |
|--------|------|
| 高 | 変更頻度が高い・複雑なビジネスロジックを持つ・他機能の基盤となる |
| 中 | 安定しているが重要・中程度の複雑さ |
| 低 | 補助機能・変更頻度が低い |

---

### グループA：コア機能（優先度：高）

これらは最も頻繁に変更され、他機能に影響を与える中核機能。最初に仕様書を整備する。

| No | 機能名 | 仕様書ファイル | 対象画面 | 対象APIルーター | 優先度 |
|----|--------|--------------|---------|--------------|--------|
| A-1 | 取引管理 | `docs/specs/core/spec_transactions.md` | `/transactions`<br>`/transactions/new`<br>`/transactions/{id}/edit` | `transactions.py` | 高 |
| A-2 | インポート | `docs/specs/core/spec_import.md` | `/import` | `import_router.py` | 高 |
| A-3 | カテゴリ管理 | `docs/specs/core/spec_categories.md` | （画面なし） | `categories.py` | 高 |
| A-4 | 口座管理 | `docs/specs/core/spec_accounts.md` | `/accounts` | `accounts.py` | 高 |

---

### グループB：レポート機能（優先度：高〜中）

集計ロジックが複雑なため、仕様書で計算ルールを明確にしておく。

| No | 機能名 | 仕様書ファイル | 対象画面 | 対象APIルーター | 優先度 |
|----|--------|--------------|---------|--------------|--------|
| B-1 | ダッシュボード | `docs/specs/reports/spec_dashboard.md` | `/` | `pages.py`（`report_service.py` を直接呼び出し） | 高 |
| B-2 | 月次集計レポート | `docs/specs/reports/spec_report-monthly.md` | `/reports/monthly` | `reports.py` | 高 |
| B-3 | 前年同月比レポート | `docs/specs/reports/spec_report-comparison.md` | `/reports/comparison` | `reports.py` | 中 |
| B-4 | カテゴリ×グループ マトリックス | `docs/specs/reports/spec_report-matrix.md` | `/reports/matrix` | `reports.py` | 中 |
| B-5 | 年次集計レポート | `docs/specs/reports/spec_report-annual.md` | `/reports/annual`<br>`/reports/annual-chart` | `reports.py` | 中 |
| B-6 | 年度別トレンドレポート | `docs/specs/reports/spec_report-yearly-trend.md` | `/reports/yearly-trend`<br>`/reports/yearly-trend-chart` | `reports.py` | 中 |
| B-7 | 口座別年次集計 | `docs/specs/reports/spec_report-account-annual.md` | `/reports/account-annual`<br>`/reports/account-annual/monthly`<br>`/reports/account-annual/monthly/daily` | `reports.py` | 中 |
| B-8 | 口座分類別年次集計 | `docs/specs/reports/spec_report-account-classification.md` | `/reports/account-classification-annual`<br>`/reports/account-classification-annual-chart` | `reports.py` | 中 |
| B-9 | 口座残高レポート | `docs/specs/reports/spec_report-account-balance.md` | `/reports/account-balance` | `reports.py` | 中 |

---

### グループC：補助機能（優先度：低〜中）

変更頻度は低いが、ビジネスロジックが独立しているため仕様書があると安心。

| No | 機能名 | 仕様書ファイル | 対象画面 | 対象APIルーター | 優先度 |
|----|--------|--------------|---------|--------------|--------|
| C-1 | 定期取引パターン管理 | `docs/specs/auxiliary/spec_patterns.md` | `/patterns` | `patterns.py`<br>`pattern_groups.py` | 中 |
| C-2 | エクスポート | `docs/specs/auxiliary/spec_export.md` | `/export`<br>`/transactions/export/excel`<br>`/transactions/export/actual_txt` | `pages.py`（出力エンドポイント） | 低 |
| C-3 | PDF出力 | `docs/specs/auxiliary/spec_pdf-export.md` | `/reports/export-pdf` | `pages.py` | 低 |
| C-4 | ローン返済シミュレーション | `docs/specs/auxiliary/spec_loans.md` | `/loans/new` | `loans.py` | 低 |
| C-5 | バックアップ・リストア | `docs/specs/auxiliary/spec_backup.md` | `/backup` | `backup.py` | 低 |
| C-6 | グループ管理 | `docs/specs/auxiliary/spec_groups.md` | （画面なし） | `groups.py` | 低 |

---

## 作成順序（推奨）

以下の順で作成することを推奨する。
依存関係（カテゴリ・口座が他機能の前提）を考慮した順序とする。

```
第1フェーズ（コア基盤）
  1. A-3 カテゴリ管理    ← 取引・レポートの基盤
  2. A-4 口座管理        ← 残高・レポートの基盤
  3. A-2 インポート      ← データ投入の起点
  4. A-1 取引管理        ← 最も変更頻度が高いコア機能

第2フェーズ（主要レポート）
  5. B-1 ダッシュボード
  6. B-2 月次集計レポート
  7. B-3 前年同月比レポート
  8. B-4 カテゴリ×グループ マトリックス

第3フェーズ（詳細レポート）
  9. B-5 年次集計レポート
 10. B-6 年度別トレンドレポート
 11. B-7 口座別年次集計
 12. B-8 口座分類別年次集計
 13. B-9 口座残高レポート

第4フェーズ（補助機能）
 14. C-1 定期取引パターン管理
 15. C-2 エクスポート
 16. C-3 PDF出力
 17. C-4 ローン返済シミュレーション
 18. C-5 バックアップ・リストア
 19. C-6 グループ管理
```

---

## 各機能の仕様書作成スコープ

### A-1 取引管理（`spec_transactions.md`）

**対象ファイル：**
- `backend/app/routers/transactions.py`
- `backend/app/crud/transaction.py`
- `backend/app/models/transaction.py`
- `backend/app/schemas/transaction.py`
- `backend/app/templates/transactions/`
- `backend/app/routers/pages.py`（取引関連ルート）

**記載すべき仕様：**
- 取引一覧のフィルター条件（日付・カテゴリ・金額・メモ等）
- ページング仕様
- フリーワード検索の対象フィールド
- カテゴリ別直近N件表示（`GET /api/v1/transactions/recent/by-category/{id}`）の用途（取引入力補助）
- 取引作成・編集フォームの入力項目・バリデーション
- 資金移動取引の特殊処理（2件同時作成・カテゴリ自動生成）
- 取引削除の制約
- カテゴリ検索はサブクエリを使う理由（CLAUDE.md参照）

---

### A-2 インポート（`spec_import.md`）

**対象ファイル：**
- `backend/app/routers/import_router.py`
- `backend/app/services/import_service.py`
- `backend/app/schemas/import_result.py`
- `backend/app/templates/import/`

**記載すべき仕様：**
- Actual.TXT のフォーマット（UTF-16LE、タブ区切り）
- カラム定義と取引への変換ルール
- カテゴリ階層の分割ルール（`/` で分割）
- 資金移動の判定条件（`【資金移動】` プレフィックス）
- 重複インポートの扱い（UNIQUE制約なし、許容）
- インポートログの記録内容
- エラー行の扱い（スキップ・ログ記録）

---

### A-3 カテゴリ管理（`spec_categories.md`）

**対象ファイル：**
- `backend/app/routers/categories.py`
- `backend/app/models/category.py`
- `backend/app/schemas/category.py`

**記載すべき仕様：**
- `full_path` の形式（`A30_通信費/インターネット`）
- 親子関係の表現方法（`parent_id`、`full_path`）
- `is_transfer` フラグの用途（集計除外条件）
- APIレスポンスの構造（子カテゴリ付きネスト形式）
- カテゴリのCRUD制約（インポートでのみ作成、UIからの直接編集不可等）

---

### A-4 口座管理（`spec_accounts.md`）

**対象ファイル：**
- `backend/app/routers/accounts.py`
- `backend/app/models/account.py`
- `backend/app/models/account_type.py`
- `backend/app/schemas/account.py`
- `backend/app/templates/accounts/`

**記載すべき仕様：**
- 口座タイプ（cash/bank/card/e-money/other）の定義
- `start_date`・`initial_balance`・`adjustment_amount` の残高計算への影響
- `classification` の用途（口座分類、任意文字列）
- 口座タイプのCRUD仕様（マスタ管理）
- 口座一括更新（`PUT /api/v1/accounts/bulk`）の動作

---

### B-1 ダッシュボード（`spec_dashboard.md`）

**対象ファイル：**
- `backend/app/routers/pages.py`（`/` ルート）
- `backend/app/services/report_service.py`（`get_monthly_summary` を直接呼び出し）
- `backend/app/templates/index.html`

**記載すべき仕様：**
- 表示する集計値（当月収入・当月支出・差引）
- 円グラフの集計対象（is_transfer=False の支出のみ等）
- 表示期間の決定ロジック（当月）
- JST タイムゾーン適用箇所（`today_jst()` で当月を決定すること）

---

### B-2 月次集計レポート（`spec_report-monthly.md`）

**対象ファイル：**
- `backend/app/routers/reports.py`（`/api/v1/reports/monthly`）
- `backend/app/services/report_service.py`
- `backend/app/routers/pages.py`（`/reports/monthly`）
- `backend/app/templates/reports/monthly.html`

**記載すべき仕様：**
- 集計対象（is_transfer=False の取引）
- 取引は必ず**子カテゴリ**に紐づく（親カテゴリは直接使われない）ため、
  集計後に親カテゴリを DB から補完して親子構造を組み立てる点
- 親カテゴリのクリックで子カテゴリを展開するUI仕様
- レスポンスのデータ構造

---

### B-3 前年同月比レポート（`spec_report-comparison.md`）

**対象ファイル：**
- `backend/app/routers/reports.py`（`/api/v1/reports/comparison`）
- `backend/app/services/report_service.py`
- `backend/app/routers/pages.py`（`/reports/comparison`）
- `backend/app/templates/reports/comparison.html`

**記載すべき仕様：**
- 比較対象期間の定義（当月 vs 前年同月）
- 集計対象（is_transfer=False の取引）
- レスポンス構造（カテゴリ・当月金額・前年金額・差異・増減率）
- 表示パラメーター（年・月の指定方法）

---

### B-4 カテゴリ×グループ マトリックス（`spec_report-matrix.md`）

**対象ファイル：**
- `backend/app/routers/reports.py`（`/api/v1/reports/matrix`）
- `backend/app/services/report_service.py`
- `backend/app/routers/pages.py`（`/reports/matrix`）
- `backend/app/templates/reports/matrix.html`

**記載すべき仕様：**
- 集計対象（is_transfer=False の取引）
- グループ軸（横）とカテゴリ軸（縦）の定義
- マトリックスセルの値（金額合計）
- 合計行・合計列の計算方法
- 表示パラメーター（年・月の指定方法）

---

### B-5 年次集計レポート（`spec_report-annual.md`）

**対象ファイル：**
- `backend/app/routers/reports.py`（`/api/v1/reports/annual`）
- `backend/app/services/report_service.py`
- `backend/app/routers/pages.py`（`/reports/annual`、`/reports/annual-chart`）
- `backend/app/templates/reports/annual.html`
- `backend/app/templates/reports/annual_chart.html`

**記載すべき仕様：**
- 年次集計の期間定義（暦年1月〜12月）
- 集計対象（is_transfer=False の取引）
- 親カテゴリ単位の集計（子カテゴリを親に集約）
- グラフ画面の系列定義（月別・カテゴリ別）
- 表示パラメーター（年の指定方法）

---

### B-6 年度別トレンドレポート（`spec_report-yearly-trend.md`）

**対象ファイル：**
- `backend/app/routers/reports.py`（`/api/v1/reports/yearly-trend`）
- `backend/app/services/report_service.py`
- `backend/app/routers/pages.py`（`/reports/yearly-trend`、`/reports/yearly-trend-chart`）
- `backend/app/templates/reports/yearly_trend.html`
- `backend/app/templates/reports/yearly_trend_chart.html`

**記載すべき仕様：**
- 年度の定義（暦年 or 会計年度の区別）
- 集計対象期間（何年分を表示するか）
- 集計対象（is_transfer=False の取引）
- グラフの系列定義（年度別・カテゴリ別）

---

### B-7 口座別年次集計（`spec_report-account-annual.md`）

**対象ファイル：**
- `backend/app/routers/reports.py`（`/api/v1/reports/account-annual`、`account-monthly`、`account-monthly-daily`）
- `backend/app/services/report_service.py`
- `backend/app/models/account_type.py`（表示ラベル・表示順の参照元）
- `backend/app/routers/pages.py`（`/reports/account-annual`、monthly、daily）
- `backend/app/templates/reports/account_annual.html`
- `backend/app/templates/reports/account_annual_monthly.html`
- `backend/app/templates/reports/account_annual_monthly_daily.html`

**記載すべき仕様：**
- 3層ドリルダウン構造（年単位 → 月単位 → 日単位）
- 各層で表示する集計値（入金合計・出金合計・差引残高）
- 資金移動取引の集計への含め方（is_transfer の扱い）
- 表示パラメーター（年・口座IDの指定方法）

---

### B-8 口座分類別年次集計（`spec_report-account-classification.md`）

**対象ファイル：**
- `backend/app/routers/reports.py`（`/api/v1/reports/account-classification-annual`）
- `backend/app/services/report_service.py`
- `backend/app/routers/pages.py`（`/reports/account-classification-annual`、chart）
- `backend/app/templates/reports/account_classification_annual.html`
- `backend/app/templates/reports/account_classification_annual_chart.html`

**記載すべき仕様：**
- 口座分類（`accounts.classification`）による集計グループの定義
- 集計値の定義（年次残高・月次推移等）
- グラフ画面の系列定義
- 表示パラメーター（年の指定方法）

---

### B-9 口座残高レポート（`spec_report-account-balance.md`）

**対象ファイル：**
- `backend/app/routers/reports.py`（`/api/v1/reports/account-balance`）
- `backend/app/services/report_service.py`
- `backend/app/models/account.py`
- `backend/app/models/account_type.py`（表示ラベル・表示順の参照元）
- `backend/app/routers/pages.py`（`/reports/account-balance`）
- `backend/app/templates/reports/account_balance.html`

**記載すべき仕様：**
- 残高計算ロジック（`initial_balance` + `adjustment_amount` + 期間純収支（収入合計 − 支出合計））
- `start_date` の扱い（起算日以前の取引を除外する）
- 資金移動取引の残高計算への含め方
- 口座タイプ別・分類別の表示グループ化（ラベル・順序は `account_types` テーブル参照）

---

### C-1 定期取引パターン管理（`spec_patterns.md`）

**対象ファイル：**
- `backend/app/routers/patterns.py`
- `backend/app/routers/pattern_groups.py`
- `backend/app/crud/pattern.py`
- `backend/app/crud/pattern_group.py`
- `backend/app/models/pattern.py`
- `backend/app/models/pattern_group.py`
- `backend/app/schemas/pattern.py`
- `backend/app/schemas/pattern_group.py`
- `backend/app/templates/patterns/`

**記載すべき仕様：**
- パターンの `frequency`（monthly/yearly）の動作の違い
- `payment_day_of_month`・`payment_month_of_year` の解釈
- `due` エンドポイントの判定ロジック（今月支払い予定の条件）
- パターン候補分析（`analyze`）のロジック
- パターングループとの関係（`SET NULL on delete`）
- `is_transfer_only` グループフラグの用途

---

### C-2 エクスポート（`spec_export.md`）

**対象ファイル：**
- `backend/app/routers/pages.py`（`/export`、`/transactions/export/excel`、`/transactions/export/actual_txt`）
- `backend/app/templates/export/`

**記載すべき仕様：**
- エクスポート種別（Excel・Actual.TXT）の違い
- Excelエクスポートのシート構成・列定義
- Actual.TXT出力フォーマット（UTF-16LE、タブ区切り）
- フィルター条件（取引一覧の絞り込み条件をエクスポートに引き継ぐか）

---

### C-3 PDF出力（`spec_pdf-export.md`）

**対象ファイル：**
- `backend/app/routers/pages.py`（`/reports/export-pdf`）
- `backend/app/services/pdf_service.py`

**記載すべき仕様：**
- 対象期間（前月末時点のレポート）
- PDFに含まれるグラフ・表の種類と順序
- 用紙サイズ・レイアウト（A4）
- ダウンロード動作（テンプレートなし・直接レスポンス）
- reportlab の使用箇所と制約

---

### C-4 ローン返済シミュレーション（`spec_loans.md`）

**対象ファイル：**
- `backend/app/routers/loans.py`（`/api/v1/loans/preview`、`/api/v1/loans/create`）
- `backend/app/services/loan_service.py`
- `backend/app/schemas/loan.py`
- `backend/app/routers/pages.py`（`/loans/new`）
- `backend/app/templates/loans/`
- `backend/app/utils/date_utils.py`（`clamp_day_to_month`）

**記載すべき仕様：**
- 元利均等返済の計算式とパラメーター（借入額・金利・返済期間）
- 繰上返済（`EarlyRepayment`）の挿入仕様
- 月末処理（`clamp_day_to_month`）の動作
- プレビューと一括作成の2ステップ仕様
- 一括作成時に生成される取引のカテゴリ・メモ形式

---

### C-5 バックアップ・リストア（`spec_backup.md`）

**対象ファイル：**
- `backend/app/routers/backup.py`（`/api/v1/backup/dump`、`/api/v1/backup/restore`）
- `backend/app/services/backup_service.py`
- `backend/app/routers/pages.py`（`/backup`）
- `backend/app/templates/backup/`

**記載すべき仕様：**
- pg_dump の出力形式とファイル命名規則
- リストア時の動作（既存データの上書き・DROP/RECREATE の有無）
- ファイル転送方式（マルチパートアップロード）
- エラー時の挙動（部分リストア後のロールバック等）

---

### C-6 グループ管理（`spec_groups.md`）

**対象ファイル：**
- `backend/app/routers/groups.py`（`/api/v1/groups`）
- `backend/app/models/group.py`
- `backend/app/schemas/group.py`

**記載すべき仕様：**
- グループの命名規則（例：`20_太郎`、`10_必須(通常)`）
- 数値プレフィックスの意味（表示順制御）
- 取引とグループの関係（取引に group_id が紐づく）
- APIのCRUD範囲（取得のみか、追加・編集・削除も可能か）

---

## 完了条件

### 計画書（本文書）の完了条件

- [x] 全19機能がリストアップされていること
- [x] 各機能の仕様書ファイル名が確定していること
- [x] 作成順序が依存関係を考慮していること
- [x] 各機能の「記載すべき仕様」が列挙されていること
- [x] docs ディレクトリの3階層構造が定義されていること
- [x] 機能一覧索引（`docs/specs/index.md`）のフォーマットが定義されていること

### 事前作業の完了条件

- [ ] `docs/specs/core/`、`docs/specs/reports/`、`docs/specs/auxiliary/` が作成されていること
- [ ] `docs/specs/index.md` が作成され、全19機能の行が記載されていること

### 仕様書作成の完了条件（各機能）

- [ ] `docs/specs/<category>/spec_<feature-name>.md` が存在すること
- [ ] 対象画面・エンドポイントが記載されていること
- [ ] データモデルと制約が記載されていること
- [ ] ビジネスルール（計算ロジック・制約）が記載されていること
- [ ] CLAUDE.md の関連ルールが参照されていること
- [ ] 動作確認チェックリストが記載されていること

---

## 参照

- `docs/plan_ai-spec-driven-development.md` — AI仕様駆動開発フレームワーク（仕様書テンプレート・品質基準）
- `CLAUDE.md` — プロジェクト固有のルール（カテゴリ検索・JST・Jinja2等）
