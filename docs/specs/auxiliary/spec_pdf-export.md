# 仕様：PDF出力（月次レポート一括ダウンロード）

## 概要

指定した年月の全レポート（費目別月次集計・前年同月比・カテゴリ×グループ マトリックス・口座別残高）を1つの A4 PDF ファイルにまとめてダウンロードする機能。年月未指定時は前月末時点のレポートを自動生成し、グラフ（横棒・円グラフ）を含む多ページ構成の PDF をブラウザへ直接ストリーミング返却する。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| API / ダウンロード | `GET /reports/export-pdf` | PDFを生成してダウンロード（テンプレートなし・StreamingResponse） |

---

## 対象ファイル

- `backend/app/routers/pages.py` — `export_pdf` ルート（`GET /reports/export-pdf`）
- `backend/app/services/pdf_service.py` — PDF生成ロジック（`generate_monthly_report_pdf`）
- `backend/app/services/report_service.py` — `get_monthly_summary` / `get_comparison` / `get_matrix_report` / `get_account_balance_report`
- `backend/app/jst.py` — `today_jst()`（作成日・前月計算に使用）

---

## データモデル

PDF生成では以下のサービス関数を通じて既存テーブルを参照する。PDF固有のテーブルは存在しない。

### 参照テーブル

| テーブル | 用途 |
|----------|------|
| `transactions` | 月次集計・前年同月比・マトリックスの集計対象 |
| `categories` | カテゴリ名・階層構造の取得（親カテゴリのみ PDF に表示） |
| `accounts` | 口座残高レポートの残高計算 |
| `account_types` | 口座種別ラベルの取得 |
| `groups` | マトリックスの列グループ |

### 主要フィールド（集計条件）

- `transactions.is_transfer = False` — 月次集計・比較から資金移動を除外
- `categories.parent_id IS NULL` — 親カテゴリのみ PDF に集計・表示（子カテゴリの合計を親に加算）
- `accounts.start_date` / `accounts.initial_balance` / `accounts.adjustment_amount` — 残高計算の起点

---

## 機能仕様

### エンドポイント: `GET /reports/export-pdf`

**クエリパラメータ：**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `year` | int | 任意 | 対象年。未指定時は前月の年を使用 |
| `month` | int | 任意 | 対象月（1〜12）。未指定時は前月を使用 |

- `year` と `month` のどちらか一方でも未指定の場合、両方を `_prev_ym()` で前月に設定する
- `_prev_ym()` は `today_jst()` を使って当日（JST）の前月年・前月を返す

**レスポンス：**

- `StreamingResponse` で PDF バイナリを返す
- `Content-Type: application/pdf`
- `Content-Disposition: attachment; filename*=UTF-8''{RFC5987エンコード済みファイル名}`
- ファイル名形式: `{year}{month:02d}{last_day:02d}時点収支レポート.pdf`（例: `20250531時点収支レポート.pdf`）
  - `last_day` は `calendar.monthrange(year, month)[1]` で当月末日を算出

**エラーハンドリング：**

- PDF生成中に例外が発生した場合、`logger.exception` でスタックトレースを記録し `HTTP 500`（`"PDF生成に失敗しました"`）を返す

---

### PDF 生成: `generate_monthly_report_pdf(db, year, month)`

`pdf_service.py` の `generate_monthly_report_pdf` 関数が呼び出されて PDF を生成し、`(pdf_bytes: bytes, filename: str)` のタプルを返す。

**ドキュメント設定：**

| 項目 | 値 |
|------|-----|
| 用紙サイズ | A4 |
| マージン（上下左右） | 各 15mm |
| フォント | `HeiseiKakuGo-W5`（reportlab の UnicodeCIDFont） |
| コンテンツ幅 | A4幅 − 30mm ≈ 510pt（`_PAGE_W`） |
| カラーパレット | 10色の HexColor（`#4472C4`, `#ED7D31`, `#A9D18E`, `#FF6384`, `#FFCE56`, `#4BC0C0`, `#9966FF`, `#FF9F40`, `#C9CBCF`, `#7BC8A4`） |

**数値フォーマット関数：**

| 関数 | 説明 |
|------|------|
| `_fmt(n)` | `¥{n:,}` 形式、0 の場合は `—` |
| `_pct(r)` | 増減率。`None` なら `—`、プラスは `+` 付き、小数点1桁 |
| `_diff(n)` | 差額。0 なら `—`、プラスは `+` 付き `¥{n:,}` 形式 |
| `_trunc(s, n=10)` | 文字列を最大 n 文字に切り詰め（末尾 `…`） |
| `_compact_val(v)` | グラフ軸ラベル用短縮表記（百万・万・千単位） |

---

### ページ構成

#### ページ 0: カバーページ

- タイトル（H1）: `家計簿レポート  {year}年{month}月`
- 作成日と対象期間末: `作成日: {today_jst():%Y年%m月%d日}　　対象期間末: {as_of_date:%Y年%m月%d日}`
  - `as_of_date` は `date(year, month, last_day)`（当月末日）
- 水平罫線（`HRFlowable`、カラー `#4472C4`）
- 収録レポート一覧（テキスト）:
  1. 費目別月次集計（親カテゴリ）＋ グラフ
  2. 前年同月比（親カテゴリ）＋ グラフ
  3. カテゴリ×グループ マトリックス（親カテゴリ）
  4. アカウント別残高 ＋ グラフ

#### ページ 1: 費目別月次集計（`_build_monthly`）

データソース: `get_monthly_summary(db, year, month)`

1. **サマリー表**（3列均等幅）:
   - ヘッダー行: 収入合計 / 支出合計 / 差引
   - データ行: 各金額（フォントサイズ 11pt）
   - 差引の文字色: プラスは `#1a7741`（緑）、マイナスは `#c0392b`（赤）

2. **費目別テーブル**（親カテゴリのみ）:
   - 列: 費目 / 収入 / 支出
   - 列幅比: 52% / 24% / 24%
   - 収入・支出の区切り行（`── 収入 ──` / `── 支出 ──`）は背景色 `#E8ECEF`
   - ゼロの場合は `—` 表示
   - ヘッダー行は `repeatRows=1`（改ページ時にも繰り返す）

3. **支出カテゴリ Top10 横棒グラフ**（`_make_hbar_chart`）:
   - `expense_categories` の `total_expense > 0` を降順ソートし先頭 10 件
   - グラフ内では昇順（小さい値が上）に反転して表示
   - 棒の色: `_PALETTE[0]`（`#4472C4`）
   - グラフ高さ: `max(150.0, len(labels) * 22.0 + 30.0)` pt

4. **収入カテゴリ構成 円グラフ**（`_make_pie_chart`）:
   - `income_categories` の `total_income > 0` を降順ソート
   - ラベル形式: `{カテゴリ名}\n{割合:.1f}%`
   - 右側にテキスト凡例（カラーボックス + `カテゴリ名 ¥金額`）
   - グラフ高さ: 180pt

#### ページ 2: 前年同月比（`_build_comparison`）

データソース: `get_comparison(db, year, month)`

1. **サマリー表**（4列）:
   - ヘッダー: 空白 / `{year}年` / `{last_year}年` / 差額
   - 行: 収入計 / 支出計 / 差引

2. **費目別テーブル**（親カテゴリのみ）:
   - 列: 費目 / 今年 / 前年 / 差額 / 増減率
   - 列幅比: 35% / 16% / 16% / 17% / 16%
   - 収入カテゴリは `this_year_income > 0` を基準に収入列・差額列を選択
   - 収入・支出の区切り行あり（背景色 `#E8ECEF`）

3. **支出 前年同月比 Top8 グループ横棒グラフ**（`_make_comparison_hbar`）:
   - `expense_categories` の `this_year_expense > 0 OR last_year_expense > 0` を対象に今年の支出降順ソートし先頭 8 件
   - 2系列: 今年（`_PALETTE[0]`）と前年（`_PALETTE[2]`）
   - 右端に凡例（今年・前年の年数ラベル）
   - グラフ高さ: `max(160.0, len(labels) * 28.0 + 30.0)` pt

#### ページ 3: カテゴリ×グループ マトリックス（`_build_matrix`）

データソース: `get_matrix_report(db, year, month)`

- **列構成**: 費目 / グループ名（可変数） / `(未分類)`（`has_no_group=True` の場合） / 合計
- **列幅**: 費目列 35%、残りを列数で均等配分
- **フォントサイズ**: グループ数に応じて動的に縮小（`max(6, 8 - max(0, n_extra - 4))` pt）
- 収入・支出の区切り行あり（背景色 `#E8ECEF`）
- 末行に「支出合計」行（背景色 `#D6E4F7`）
- ゼロの場合は `—` 表示

#### ページ 4: アカウント別残高（`_build_account_balance`）

データソース: `get_account_balance_report(db, as_of_date)`

1. **残高テーブル**:
   - 列: 種別/アカウント / 初期残高 / 調整 / 入金計 / 出金計 / 残高
   - 列幅比: 30% / 14% / 12% / 14% / 14% / 16%
   - 口座種別ヘッダー行（`【種別名】`）: 背景色 `#E8ECEF`
   - 小計行（`種別名 小計`）: 背景色 `#EBF2FA`
   - 合計行: 背景色 `#D6E4F7`

2. **口座種別残高構成 円グラフ**（`_make_pie_chart`）:
   - 各種別の `subtotal_balance != 0` を対象
   - マイナス残高の場合はラベルに `(負債)` を付加し絶対値でグラフ表示
   - グラフ高さ: 190pt

---

### 共通テーブルスタイル（`_base_table_style`）

| スタイル要素 | 値 |
|---|---|
| フォント | `HeiseiKakuGo-W5` 8pt |
| ヘッダー背景色 | `#4472C4`（青）、文字色は白 |
| 罫線 | 0.3pt、`#CCCCCC` |
| 偶数行背景色 | 白 / `#F7F7F7` の交互 |
| 数値列の整列 | 右揃え（第2列以降） |
| 費目列の整列 | 左揃え |
| セルパディング | 上下 3pt、左右 4pt |

---

## 実装上の注意点

- **JST タイムゾーン**: `today_jst()` を使って作成日・前月計算を行う。`date.today()` や `datetime.now()` は使用しないこと（`_prev_ym()` も `today_jst()` ベース）
- **テンプレートファイルは不使用**: PDF は `pdf_service.py` が直接 `SimpleDocTemplate` を構築して `StreamingResponse` で返す。Jinja2 の注意点（シングルクォート属性・`tojson` など）は本機能に適用されない
- **フォント登録**: `pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))` はモジュール読み込み時に実行される。アプリ起動時に reportlab が正しくインストールされていること
- **親カテゴリのみの集計**: PDF 内の全テーブルは親カテゴリ（`parent_id IS NULL`）のみを表示する。子カテゴリの金額は親に合算済みの値を使用する（`report_service.py` の集計ロジックに依存）
- **当月末日の計算**: `calendar.monthrange(year, month)[1]` で末日を取得する。`date(year, month, last_day)` が口座残高レポートの `as_of_date` に使われる
- **RFC 5987 ファイル名エンコード**: 日本語ファイル名を `urllib.parse.quote` で UTF-8 パーセントエンコードし、`filename*=UTF-8''{encoded}` 形式で `Content-Disposition` ヘッダーに設定する
- **グラフ描画ライブラリ**: reportlab の `HorizontalBarChart`・`Pie`・`Drawing` を使用する。Chart.js は使用しない（PDF は静的バイナリのため）
- **マトリックスのフォントサイズ動的調整**: グループ数が多い場合に列幅が狭くなるため、`max(6, 8 - max(0, n_extra - 4))` でフォントサイズを自動縮小する

---

## 動作確認チェックリスト

- [ ] `GET /reports/export-pdf` にアクセスすると PDF ファイルのダウンロードが開始されること
- [ ] `year`・`month` を省略した場合、前月（JST基準）のレポートが生成されること
- [ ] `year=2025&month=3` のようにクエリパラメータを指定すると指定月のレポートが生成されること
- [ ] ダウンロードされたファイル名が `{year}{month:02d}{last_day:02d}時点収支レポート.pdf` 形式であること（例: `20250331時点収支レポート.pdf`）
- [ ] PDF を開いた際にカバーページ（1ページ目）が表示され、タイトル・作成日・収録レポート一覧が確認できること
- [ ] 2ページ目に費目別月次集計のサマリー表・費目テーブル・棒グラフ・円グラフが表示されること
- [ ] 差引がプラスのとき金額が緑色、マイナスのとき赤色で表示されること
- [ ] 費目テーブルに収入・支出の区切り行（`── 収入 ──` / `── 支出 ──`）が表示されること
- [ ] 支出 Top10 横棒グラフが支出額降順（グラフ内は昇順）で表示されること
- [ ] 収入カテゴリ構成の円グラフにカテゴリ名と割合（%）が表示されること
- [ ] 3ページ目に前年同月比のサマリー表・費目テーブル・グループ横棒グラフが表示されること
- [ ] 比較グラフに今年・前年の凡例が表示されること
- [ ] 4ページ目にカテゴリ×グループ マトリックス表が表示されること
- [ ] 5ページ目に口座別残高テーブル・口座種別残高円グラフが表示されること
- [ ] マイナス残高の口座種別の凡例ラベルに `(負債)` が付いていること
- [ ] 日本語フォント（`HeiseiKakuGo-W5`）が正しく適用されており、文字化けがないこと
- [ ] PDF生成でサーバーエラーが発生した場合、HTTP 500 が返却されブラウザにエラーが表示されること
