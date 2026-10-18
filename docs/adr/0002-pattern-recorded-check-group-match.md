# ADR-0002: パターン記録判定へのグループ一致条件の追加

## ステータス

採用・実装済み（Accepted / Implemented）— 2026-08-16

---

## コンテキスト

### 現状の実装（ADR-0001 で実装済み・`main` にマージ済み）

[ADR-0001](0001-pattern-payment-status-tracking.md) により、以下がすでに実装・リリース済みである。

- `transactions.pattern_id` によるパターン⇔取引の紐付け（決定1）
- 「対象期間（当月 or 当年の対象月）に記録済みか」のハイブリッド判定
  - 優先: `transactions.pattern_id` が一致する取引の有無
  - フォールバック: `pattern_id` が `NULL` でも `category_id` + `account_id` が一致する取引の有無
  （`backend/app/crud/pattern.py` の `_build_recorded_lookup()`）
- 判定は「対象期間内に記録があるか」のみを見ており、支払日ちょうどの日付一致や金額一致は要求しない
  → **支払日が数日前後する／金額が毎月同じでない、という制約はこの時点ですでに満たされている**
- `is_current_period_recorded` / `current_period_transaction_id` を `PatternOut` に追加し、`/patterns`・ダッシュボードの両方で参照
- `patterns/index.html` の一覧表に **グループ・アカウント・カテゴリ（`category_full_path` に親/子を含む）を列として表示**し、未記録かつ支払日超過のパターンに「未記録」バッジを表示済み（`isUnrecordedAndPastDue()`）

つまり、今回の改修要望のうち以下は ADR-0001 の実装で**すでに満たされている**。

| 要望 | 対応状況 |
|---|---|
| 当月分の支払いを取引に記録してあるかをチェックする機能 | 実装済み（`is_current_period_recorded`） |
| グループ・アカウント・親カテゴリ・子カテゴリを一覧で確認できること | 実装済み（`patterns/index.html` の列表示） |
| 未記録の場合にわかるようにする | 実装済み（「未記録」バッジ） |
| 当月（対象期間）の記録有無で判定し、記録なしは未入力とみなす | 実装済み（対象期間ベース判定） |
| 支払日が数日前後する可能性への対応 | 実装済み（日付一致ではなく期間一致で判定） |
| 金額が毎月同じでない可能性への対応 | 実装済み（判定に金額を一切使用していない） |

### 残っているギャップ：フォールバック判定に `group_id` が含まれていない

`_build_recorded_lookup()` のフォールバック条件（`backend/app/crud/pattern.py:78-84`）は次の通りで、**`group_id` を判定条件に含めていない**。

```python
or_(
    Transaction.pattern_id == p.id,
    and_(
        Transaction.pattern_id.is_(None),
        Transaction.category_id == p.category_id,
        Transaction.account_id == p.account_id,
    ),
)
```

一方 `transaction_patterns` には `group_id`（`backend/app/models/pattern.py:21`）があり、`transactions` にも `group_id`（`backend/app/models/transaction.py:23`）がある。パターン一覧 UI は「グループ」列を表示しているにもかかわらず、記録判定はグループを見ていない。

**具体的な誤判定シナリオ：** 同一の `category_id` + `account_id` を共有するが `group_id` が異なる2つのパターンが存在する場合（例：同じカテゴリ・同じ口座の支払いを「20_太郎」グループのパターンと「10_必須(通常)」グループのパターンとしてそれぞれ登録しているケース）、一方のグループの支払いだけを取引に記録すると、`pattern_id` が付かない手動入力やコピー入力では **category_id + account_id が一致してしまうため、もう一方のグループのパターンも「記録済み」と誤判定される**。これは「グループ、アカウント、親カテゴリ、子カテゴリで支払いが記録されているかを確認してほしい」という要望に対する未対応部分である。

### 対象外の確認

- **親カテゴリ／子カテゴリの別軸判定は不要。** `category_id` は子カテゴリを一意に指し、`full_path`（例: `A30_通信費/インターネット`）を通じて親カテゴリも一意に定まる。既存の `category_id` 一致判定で親子とも担保されており、追加の判定軸は不要。
- **`pattern_group_id`（パターングループ）は対象外。** 要望文の「グループ」は一覧の「グループ / PG」列のうち `group_id`（人別・目的別グループ）を指す。`pattern_group_id` は資金移動専用グループ等の分類目的であり、記録済み判定の識別軸とは無関係。

---

## 決定

### 1. フォールバック判定に `group_id` の一致条件を追加する（非対称マッチング）

`_build_recorded_lookup()` のフォールバック条件を、パターンに `group_id` が設定されている場合のみ取引側の `group_id` との一致を要求する形に変更する。

```python
and_(
    Transaction.pattern_id.is_(None),
    Transaction.category_id == p.category_id,
    Transaction.account_id == p.account_id,
    or_(
        p.group_id is None,
        Transaction.group_id == p.group_id,
    ) if p.group_id is not None else True,  # 実装イメージ。p.group_id が None のパターンは group 条件を課さない
)
```

- `p.group_id` が設定されているパターン → 取引側の `group_id` も同じ値であることを要求する
- `p.group_id` が `NULL`（グループ未指定）のパターン → 従来通り取引側の `group_id` を問わない

`_build_recorded_lookup()` 内の索引化キーも `(category_id, account_id)` から `(category_id, account_id, group_id)` を考慮した形に変更し、N+1 を発生させない一括判定方針は維持する。

**非対称にする理由：** グループが同じか異なるかで誤判定が起きるのは「グループが指定された複数パターンが category_id + account_id を共有するケース」に限られる。グループ未指定のパターンにまで厳密一致（取引側も `group_id IS NULL` を要求）を課すと、グループ未指定のパターンに対して「たまたま group タグ付きで入力された取引」が既存は「記録済み」と判定されていたのに新たに「未記録」に変わるという**回帰**が生じうる。ADR-0001 のフォールバック設計思想（「取りこぼさないため」に緩めに倒す）を踏襲し、実害のあるケース（グループが異なるパターン間の誤マッチ）だけをピンポイントで解消する。

### 2. 対象期間・金額の判定ロジックは変更しない

ADR-0001 決定2・3（対象期間ベースの判定、金額を判定に使わない）はすでに「支払日が数日前後する」「金額が毎月同じでない」という制約を満たしている。今回のADRではこの部分に変更を加えない（現状維持であることを明記するに留める）。

### 3. API・フロントエンドの変更は不要

`is_current_period_recorded` / `current_period_transaction_id` のスキーマ、`patterns/index.html` のグループ・アカウント・カテゴリ列と「未記録」バッジはすでに存在する。今回の変更は `_build_recorded_lookup()` 内部のフォールバック述語のみで完結し、API レスポンス構造・テンプレートの変更は不要。

---

## 検討した代替案

### 代替案A: `group_id` も含めて対称的な完全一致にする（`NULL` 同士も一致とみなす）

- 長所: ロジックが単純で一貫性がある（`category_id` / `account_id` と同じ扱い）
- 短所: グループ未指定のパターンで、グループタグ付きの取引が入力された場合に新たに「未記録」と誤判定される回帰が生じる
- → **不採用**。決定1の非対称マッチングを採用する。

### 代替案B: `pattern_group_id` も判定条件に加える

- 短所: `pattern_group_id` は資金移動専用グループ等の分類目的であり、要望の「グループ」（人別・目的別の `group_id`）とは別軸。判定に加える理由がない
- → **不採用**

### 代替案C: 何もしない（`category_id` + `account_id` のみで十分とする）

- 短所: 同一カテゴリ・口座で複数グループのパターンが存在する場合の誤判定（今回の要望の核心）が解消されない
- → **不採用**

---

## 変更ファイル一覧（見込み）

| ファイル | 変更内容 |
|---|---|
| `backend/app/crud/pattern.py` | `_build_recorded_lookup()` のフォールバック条件に `group_id` の非対称一致を追加。候補取引の索引化キーを `(category_id, account_id, group_id)` を考慮した形に変更 |

### 仕様書（別プルリクエストで対応）

以下の仕様書は本 ADR の変更内容の影響を受けるが、**本 ADR・本実装のプルリクエストでは修正しない**。仕様書自体の更新は別プルリクエストで行う。

| ファイル | 影響内容（別PRでの反映事項） |
|---|---|
| `docs/specs/auxiliary/spec_patterns.md` | フォールバック判定の条件（`category_id` + `account_id` に加え、`group_id` が設定されたパターンは `group_id` の非対称一致も要求すること）を仕様に反映 |

---

## 影響・注意点

- 既存の `transactions` データへの変更・バックフィルは行わない（ADR-0001 の方針を踏襲）。今回の変更は判定ロジックのみに影響する。
- `group_id` が `NULL` のパターンは従来と同じ判定結果になるため、大多数の既存パターンの表示に影響はない。判定結果が変わるのは「`group_id` が設定された複数パターンが同一 `category_id` + `account_id` を共有している」場合のみ（誤判定の是正）。
- `CLAUDE.md` の規約に従う：`category_id` の絞り込みは既存どおり `joinedload` と重複しないサブクエリ／`IN` 句構成を維持し、今回の変更で JOIN 構成は変えない（Python 側のフォールバック述語追加のみ）。

---

## 確認済みの論点

初版レビュー時に未決だった以下の論点は、ユーザー確認により決定済み。

| 論点 | 決定 |
|---|---|
| フォールバックの `group_id` 一致を非対称（決定1）にするか、対称（代替案A）にするか | 非対称マッチングを採用（決定1）。`group_id` が設定されたパターンのみ取引側との一致を要求し、`group_id` 未指定のパターンは従来通り取引側の `group_id` を問わない |

## 未決事項

なし。
