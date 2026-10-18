# ADR-0001: パターン管理 当月支払い状況チェック機能の追加

## ステータス

採用・実装済み（Accepted / Implemented）— 2026-08-15

---

## コンテキスト

### 現状の実装

定期取引パターン（`transaction_patterns`）は `payment_day_of_month` / `payment_month_of_year` を保持するが、実際の取引（`transactions`）とは一切紐付いていない。

`backend/app/crud/pattern.py` の `_calc_payment_dates()` は、**「今日の日付」と「支払日設定」だけ**を見て `last_payment_date` / `next_payment_date` を機械的に算出している。

```python
if p.frequency == "monthly":
    this_month = clamp_day_to_month(today.year, today.month, p.payment_day_of_month)
    if this_month <= today:
        last_pd = this_month           # ← 実際に記録したかどうかは見ていない
        ...
```

`transactions` テーブルにはパターンへの外部キーが存在しない（`backend/app/models/transaction.py`）。パターン一覧画面（`/patterns`）やダッシュボード（`/`）の「入力」ボタンは `/transactions/new?pattern_id=<id>` へ遷移してフォームにパターン内容を転記するだけで、送信時に `pattern_id` は保存されない（`backend/app/templates/transactions/form.html`）。

### 課題

支払日を過ぎると、実際にその月の支払いを取引として記録していなくても `last_payment_date` / `next_payment_date` が機械的に繰り上がる。そのため「今月分を記録し忘れているのに、あたかも記録済みであるかのように見える」状態が発生し、ユーザーは毎回 `/transactions` を検索して手動で記録有無を確認している。

### 要望

支払日情報と実際の取引を紐付け、**その期間分の支払いを取引に記録していないパターン**を一覧・ダッシュボードで判別できるようにする。

### 想定される入力経路

「当月分の支払いを記録する」方法はパターン経由の「入力」ボタン（`?pattern_id=X`）だけではない。`backend/app/routers/pages.py` の `/transactions/new` は `copy_from_id` によるコピー入力（`is_copy=True`）にも対応しており、パターン画面を経由せず**取引一覧から先月分の取引をコピーして日付だけ当月に書き換えて登録する**運用が実際に行われている。この経路では `pattern_id` はフォームに一切渡らない（`_INIT_PATTERN` が設定されるのは `pattern_id` クエリパラメータ経由のときのみ）。記録状況判定はこの経路も対象に含める必要がある（→ 決定2で対応）。

---

## 決定

### 1. `transactions.pattern_id` を追加し、パターン経由の入力を明示的にリンクする

- `transactions` テーブルに `pattern_id INTEGER NULL REFERENCES transaction_patterns(id) ON DELETE SET NULL` を追加する（マイグレーション `0014_add_pattern_id_to_transactions.py`）。
- `pattern_group_id`（`transaction_patterns` → `pattern_groups`）と同様に `SET NULL` とし、パターン削除時に取引は消さない。
- `/transactions/new?pattern_id=X` 経由で開いたフォームは、送信ペイロードに `pattern_id` を含めて保存する。
- 資金移動パターン（`to_account_id` あり）の場合、`POST /api/v1/transactions/transfer` が作成する出金・入金 2 件の取引の**両方**に同じ `pattern_id` を設定できるよう、リクエストボディに任意項目として `pattern_id` を追加する。
- パターンを使わない自由入力は従来どおり可能（`pattern_id` は必須にしない）。

### 2. 「当月（対象期間）記録済み」判定はハイブリッド方式にする

`pattern_id` は今後作成される取引にしか付かないため、判定は次の2段構えにする。

1. **優先**: 対象期間内に `pattern_id` が一致する取引が存在するか
2. **フォールバック**: `pattern_id` が NULL でも、`category_id` + `account_id`（資金移動パターンは `to_account_id` も含む）が一致する取引が対象期間内に存在するか

フォールバックを設けるのは、既存データやパターンを使わず手動入力した取引でも「実質同じ支払い」を取りこぼさないため。`pattern_id` 未設定の既存取引に対する遡及的なバックフィル処理は行わない（判定はフォールバックで担保できるため、マイグレーション時のバックフィルスクリプトは不要と判断）。過去取引に後から `pattern_id` を紐付け直す編集 UI も**提供しない**（ユーザー確認済み・対象外）。

**「先月分をコピーして当月分を作成する」運用への対応：** この経路（`copy_from_id` によるコピー入力）で作成された取引にも `pattern_id` は付かないが、コピー元の `category_id` / `account_id` をそのまま引き継ぐため、上記フォールバック判定（`category_id` + `account_id` 一致）でそのまま「記録済み」と判定できる。この経路専用の追加実装は不要。

**対象期間の定義：**

| frequency | 対象期間 |
|---|---|
| `monthly` | 当月1日〜末日 |
| `annual` | 当年の `payment_month_of_year` の1日〜末日 |
| `daily` / `other` | 対象外（都度記録が前提のため、記録状況チェックの対象にしない。ユーザー確認済み） |

### 3. `last_payment_date` / `next_payment_date` の算出を実績ベースに変更する

- 対象期間内に記録済み → 現状どおり支払日ベースで算出（記録があるので進めてよい）
- 対象期間内が**未記録** → `next_payment_date` は「対象期間内の支払日」のまま据え置く（先送りしない）。あわせて `is_current_period_recorded: false` を返す。
- **警告タイミングに猶予期間は設けない。** 対象期間の支払日を1日でも過ぎて未記録であれば即座に「未記録」として扱う（ユーザー確認済み）。

これにより「記録していないのに支払日を過ぎると次回・前回の表示がズレる」という当初の課題を解消する。

### 4. API 拡張（新規エンドポイントは追加しない）

既存の `PatternOut` に以下を追加し、`GET /api/v1/patterns` と `GET /api/v1/patterns/due` の両方に反映する。

```python
class PatternOut(PatternBase):
    ...
    is_current_period_recorded: bool = False
    current_period_transaction_id: Optional[int] = None  # 記録済み取引への詳細リンク用
```

`crud/pattern.py` 側は `_to_dict()` の呼び出し元（`get_patterns` 等）で、対象パターン群の `category_id` / `account_id` / `pattern_id` の集合に対し**まとめて1クエリ**で対象期間の取引を取得し、N+1 クエリを避ける（`joinedload` によるパターン取得とは別に、`Transaction` を `category_id/account_id` の `IN` 句 + 日付範囲でまとめて引く）。

### 5. フロントエンド

- `patterns/index.html`：支払日情報セルに「未記録」バッジ（赤系）を追加する。`is_current_period_recorded = false` かつ対象期間の支払日を過ぎているパターンを強調表示する。
- `index.html`（ダッシュボード）：現状の「今日の支払いパターン」バナー（`due_patterns`、支払日当日のみ）に加えて、**「今月未記録のパターン」**セクションを新設する。`crud/pattern.py` に `get_unrecorded_patterns(db, today)` を追加し、対象期間の支払日を過ぎてもなお `is_current_period_recorded = false` のアクティブパターンを返す。

---

## 検討した代替案

### 代替案A: `pattern_id` を追加せず、ヒューリスティック判定のみで実現する

`category_id` + `account_id` の一致だけで「記録済み」を判定する方式。

- 長所: マイグレーション不要、既存データにも即適用できる
- 短所: 同一カテゴリ・口座で月内に複数回取引がある場合（例: 食費で複数回買い物）に、どれが「定期パターン分」でどれが「通常の取引」か区別できず誤判定しやすい
- → **不採用**。ただし判定のフォールバックとしては採用する（決定2）。

### 代替案B: `pattern_id` を必須化し、パターン経由でない取引作成を禁止する

- 長所: 紐付け精度は最も高くなる
- 短所: 既存の自由入力フローを破壊する。要望は「記録していない内容をわかるようにしたい」であり、入力方法を強制する要望ではない
- → **不採用**。`pattern_id` は任意（nullable）のままとする。

### 代替案C: 取引とは連動しない「支払済みチェック」を別テーブルで持つ（手動チェックボックス方式）

- 長所: 実装が単純
- 短所: 結局「毎回手動でチェックする」という現状の課題を形を変えて残すだけで、「取引に記録していない内容を自動的にわかるようにしたい」という要望の本質を満たさない
- → **不採用**。

---

## 変更ファイル一覧（見込み）

| ファイル | 変更内容 |
|---|---|
| `backend/alembic/versions/0014_add_pattern_id_to_transactions.py`（新規） | `transactions.pattern_id` 追加 |
| `backend/app/models/transaction.py` | `pattern_id` カラム・リレーション追加 |
| `backend/app/schemas/transaction.py` | `pattern_id` を作成/更新/レスポンススキーマに追加 |
| `backend/app/schemas/pattern.py` | `PatternOut` に `is_current_period_recorded` / `current_period_transaction_id` 追加 |
| `backend/app/crud/pattern.py` | 記録状況の一括判定ロジック、`_calc_payment_dates()` の実績ベース化、`get_unrecorded_patterns()` 追加 |
| `backend/app/crud/transaction.py` | 取引作成・資金移動作成時に `pattern_id` を保存 |
| `backend/app/routers/pages.py` | ダッシュボードに未記録パターン一覧を渡す |
| `backend/app/templates/transactions/form.html` | 送信ペイロードに `pattern_id` を含める |
| `backend/app/templates/patterns/index.html` | 「未記録」バッジ表示 |
| `backend/app/templates/index.html` | 「今月未記録のパターン」セクション追加 |
| `frontend/static/css/style.css` | 未記録バッジ用スタイル追加 |

### 仕様書（別プルリクエストで対応）

以下の仕様書は本 ADR の変更内容の影響を受けるが、**本 ADR・本実装のプルリクエストでは修正しない**。仕様書自体の更新は別プルリクエストで行う。

| ファイル | 影響内容（別PRでの反映事項） |
|---|---|
| `docs/specs/auxiliary/spec_patterns.md` | `pattern_id` 紐付け、記録状況判定ロジック（ハイブリッド方式・対象期間）、`last_payment_date` / `next_payment_date` の実績ベース化、`PatternOut` の追加フィールドを仕様に反映 |
| `docs/specs/reports/spec_dashboard.md` | ダッシュボードの「今月未記録のパターン」セクションを仕様に反映 |

---

## 影響・注意点

- `CLAUDE.md` の規約に従う：日付処理は必ず `jst.py`（`today_jst()`）を使用する。カテゴリでの絞り込みは `joinedload` との重複 JOIN を避けるためサブクエリを使う。
- 資金移動パターンは `category_id` が動的生成される「`【資金移動】/A→B`」カテゴリを指すため、フォールバック判定（`category_id` 一致）はそのまま機能する。
- `pattern_id` を `SET NULL` にするため、パターンを削除しても過去の取引記録・金額集計には影響しない（既存の `pattern_group_id` の設計方針を踏襲）。
- レスポンス増加分（`is_current_period_recorded` 等）は一覧取得のクエリ数を増やさない設計とし、`get_patterns` のパフォーマンスを劣化させない。

---

## 確認済みの論点

初版レビュー時に未決だった以下 3 点は、ユーザー確認により決定済み。

| 論点 | 決定 |
|---|---|
| 「未記録」警告のタイミング | 猶予期間なし。支払日を1日でも過ぎたら即警告（決定3） |
| 過去取引への `pattern_id` 遡及紐付け | 対応しない。紐付け直し編集 UI も提供しない（決定2） |
| `daily` / `other` 頻度パターンの記録状況チェック対象 | 対象外のまま（決定2 対象期間の定義） |

## 未決事項

なし。
