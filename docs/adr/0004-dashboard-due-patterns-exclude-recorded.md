# ADR-0004: ダッシュボード「今日の支払いパターン」バナーからの記録済みパターン除外

## ステータス

採用・実装済み（Accepted / Implemented）— 2026-08-22

---

## コンテキスト

### 現状の実装

ダッシュボード（`/`）の「今日の支払いパターン」バナーは `backend/app/routers/pages.py` の `dashboard()`（65–83行目）が `get_due_and_unrecorded_patterns(db, today)`（`backend/app/crud/pattern.py`）を呼び出して取得した `due_patterns` を `backend/app/templates/index.html`（7–30行目）で描画している。同じデータは `GET /api/v1/patterns/due`（`backend/app/routers/patterns.py` 33–36行目）経由でも取得でき、内部的には同じ `_filter_due()` を使う `get_due_patterns()` を呼んでいる。

[ADR-0001](0001-pattern-payment-status-tracking.md) で導入された `_build_recorded_lookup()` は、パターンごとに「対象期間（当月 or 対象月）に該当する取引が既に記録されているか」をハイブリッド判定（`pattern_id` 一致優先、`category_id`+`account_id`+`group_id` フォールバック）で計算し、`info["recorded"]` として保持している。ダッシュボードのもう一方のセクションである「今月未記録のパターン」を抽出する `_filter_unrecorded()`（`crud/pattern.py` 229–249行目）は、この `info["recorded"]` を見て**記録済みのパターンを除外**している。

```python
def _filter_unrecorded(patterns, today, recorded_lookup):
    result = []
    for p in patterns:
        tp = _target_period(p, today)
        if not tp:
            continue
        _start, _end, payment_date = tp
        if payment_date >= today:
            continue  # 支払日がまだ過ぎていない
        info = recorded_lookup.get(p.id, {"recorded": False, "transaction_id": None})
        if info["recorded"]:
            continue
        result.append(p)
    return result
```

一方、「今日が支払日」のパターンを抽出する `_filter_due()`（217–226行目）は支払日と頻度の一致だけを見ており、`recorded_lookup` を一切参照しない。

```python
def _filter_due(patterns: list[TransactionPattern], check_date: date) -> list[TransactionPattern]:
    """アクティブパターン群から「今日が支払日」のものだけを抽出する。"""
    return [
        p for p in patterns
        if p.payment_day_of_month == check_date.day
        and (
            p.frequency == "monthly"
            or (p.frequency == "annual" and p.payment_month_of_year == check_date.month)
        )
    ]
```

`get_due_patterns()` と `get_due_and_unrecorded_patterns()` はどちらも `_filter_due()` の結果に対して `recorded_lookup` を計算し `_to_dict()` に渡して `is_current_period_recorded` フィールドを埋めてはいるが、その値を**フィルタ条件として使っていない**ため、既に取引記録済みのパターンも `due_patterns` にそのまま残ってしまう。

### 課題

支払日当日に取引を記録した後もダッシュボードの「今日の支払いパターン」バナーに同じパターンが表示され続け、「入力する →」ボタンも消えない。ユーザーは既に対応済みの支払いかどうかをバナーの見た目だけでは判別できず、実質的に「支払い済みの情報が表示されている」状態になっている。

`is_current_period_recorded` という判定結果自体は既に計算されているにもかかわらず、`_filter_due()` 側だけがそれを使っていないという実装上の非対称性が原因であり、`_filter_unrecorded()` 側の既存ロジックと合わせれば追加の判定ロジックなしで解消できる。

### 要望

「今日の支払いパターン」バナー（および内部的に同じ関数を使う `GET /api/v1/patterns/due`）から、対象期間について既に記録済みのパターンを除外する。

---

## 決定

### 1. `_filter_due()` に `recorded_lookup` を渡し、記録済みパターンを除外する

`_filter_unrecorded()` と対称になるよう、`_filter_due()` のシグネチャに `recorded_lookup` を追加し、`info["recorded"]` が真のパターンをスキップする。

```python
def _filter_due(
    patterns: list[TransactionPattern], check_date: date, recorded_lookup: dict[int, dict]
) -> list[TransactionPattern]:
    """アクティブパターン群から「今日が支払日」かつ「対象期間が未記録」のものだけを抽出する。"""
    result = []
    for p in patterns:
        if p.payment_day_of_month != check_date.day:
            continue
        if not (
            p.frequency == "monthly"
            or (p.frequency == "annual" and p.payment_month_of_year == check_date.month)
        ):
            continue
        info = recorded_lookup.get(p.id, {"recorded": False, "transaction_id": None})
        if info["recorded"]:
            continue
        result.append(p)
    return result
```

判定ロジック自体（`_build_recorded_lookup()` のハイブリッド判定・対象期間の定義・`group_id` の非対称マッチング）は ADR-0001／ADR-0002 のまま変更しない。

### 2. `get_due_patterns()` の呼び出し順序を変更する

現状は `due = _filter_due(patterns, check_date)` を先に計算してから、その結果に対して `recorded_lookup` を構築している。`_filter_due()` が `recorded_lookup` を必要とするようになるため、`recorded_lookup` を先に（DB クエリで絞り込み済みの `patterns` に対して）構築してから `_filter_due()` に渡す順序に変更する。

```python
def get_due_patterns(db: Session, check_date: date) -> list[dict]:
    """今日が支払日かつ対象期間が未記録のアクティブパターンを返す。"""
    patterns = (
        _patterns_query(db)
        .filter(
            TransactionPattern.is_active.is_(True),
            TransactionPattern.payment_day_of_month == check_date.day,
        )
        .order_by(TransactionPattern.sort_order, TransactionPattern.id)
        .all()
    )
    recorded_lookup = _build_recorded_lookup(db, patterns, check_date)
    due = _filter_due(patterns, check_date, recorded_lookup)
    return [_to_dict(p, today=check_date, recorded_lookup=recorded_lookup) for p in due]
```

`_build_recorded_lookup()` の対象を `due`（絞り込み後）から `patterns`（DB クエリ済みでほぼ同サイズ）に変えるだけで、追加のクエリは発生しない。`get_due_and_unrecorded_patterns()`（285–308行目）は既に `recorded_lookup` を `_filter_due()` より前に全パターンに対して構築済みのため、`_filter_due(patterns, today, recorded_lookup)` の呼び出しに `recorded_lookup` を渡すだけでよい。

### 3. `GET /api/v1/patterns/due` は追加の変更不要

`patterns.py` の `due_patterns()` エンドポイントは `get_due_patterns()` を呼ぶだけなので、決定1・2の変更により自動的に記録済みパターンが除外される。API レスポンス構造（`PatternOut`）の変更は不要。

### 4. フロントエンド変更は不要

`index.html` は `{% if due_patterns %}` でバナー全体の表示可否を判定しているため、記録済みパターンだけが対象日だった場合はバナー自体が表示されなくなる（既存のテンプレートロジックのまま正しく動作する）。テンプレートの変更は不要。

---

## 検討した代替案

### 代替案A: テンプレート側で `is_current_period_recorded` を見てスキップ表示する

- 長所: バックエンドのロジック変更が不要
- 短所: バナー見出しの件数表示（`{{ due_patterns | length }}件`）に記録済みパターンが混入したまま件数がズレる。`GET /api/v1/patterns/due` の API レスポンスにも記録済みパターンが残り続け、API 単体で見ても「支払い予定」の意味と矛盾する
- → **不採用**。サーバー側でフィルタし、API・画面の両方で一貫させる。

### 代替案B: `_filter_due()` は変更せず、呼び出し元（`get_due_patterns()` / `get_due_and_unrecorded_patterns()`）でそれぞれ個別に `info["recorded"]` フィルタを追加する

- 長所: `_filter_due()` のシグネチャを変えずに済む
- 短所: 同じ除外ロジックが2箇所に重複し、`_filter_unrecorded()` との対称性も失われる。今後 `_filter_due()` を単独で使う箇所が増えた場合に記録済み除外を忘れるリスクがある
- → **不採用**。`_filter_unrecorded()` と同じ形で `_filter_due()` に一本化する。

---

## 変更ファイル一覧（見込み）

| ファイル | 変更内容 |
|---|---|
| `backend/app/crud/pattern.py` | `_filter_due()` に `recorded_lookup` 引数を追加し記録済み除外条件を実装。`get_due_patterns()` の呼び出し順序を変更（`recorded_lookup` を `_filter_due()` より先に構築）。`get_due_and_unrecorded_patterns()` の `_filter_due()` 呼び出しに `recorded_lookup` を渡す |
| `backend/tests/integration/routers/test_dashboard_router.py` | 「今日の支払いパターン」バナーに記録済みパターンが表示されないこと、記録済みパターンのみの場合はバナー自体が非表示になることを検証するテストを追加 |
| `backend/tests/integration/routers/test_patterns_router.py` | `GET /api/v1/patterns/due` が記録済みパターンを含まないことを検証するテストを追加（`test_due_patterns_includes_recorded_status_fields` は現状維持しつつ別途追加） |
| `backend/tests/test_pattern_crud.py` | `_filter_due()` / `get_due_patterns()` の単体テストに「支払日当日かつ記録済み」の除外ケースを追加 |

### 仕様書（別プルリクエストで対応）

以下の仕様書は本 ADR の変更内容の影響を受けるが、**本 ADR・本実装のプルリクエストでは修正しない**。仕様書自体の更新は別プルリクエストで行う。

| ファイル | 影響内容（別PRでの反映事項） |
|---|---|
| `docs/specs/reports/spec_dashboard.md` | 「今日の支払いパターン」バナーが対象期間の記録済みパターンを除外する旨を仕様に反映 |
| `docs/specs/auxiliary/spec_patterns.md` | `GET /api/v1/patterns/due` のレスポンスが記録済みパターンを含まないことを仕様に反映 |

---

## 影響・注意点

- 「今月未記録のパターン」セクション（`unrecorded_patterns` / `_filter_unrecorded()`）には変更を加えない。
- 判定ロジック本体（`_build_recorded_lookup()` のハイブリッド判定・対象期間定義・`group_id` 非対称マッチング）は ADR-0001／ADR-0002 のまま変更しない。今回の変更は「計算済みの判定結果をどこでフィルタに使うか」という抽出条件のみに閉じる。
- `_build_recorded_lookup()` の呼び出し回数・クエリ数は変わらない（`get_due_patterns()` 内で1回のまま）。対象を `due`（絞り込み後）から `patterns`（DB クエリ済み、ほぼ同サイズ）に変えるだけで N+1 は発生しない。
- `GET /api/v1/patterns/due` の利用箇所はダッシュボード（`get_due_and_unrecorded_patterns()` 経由）以外に確認されていない（`grep` 済み）。API レスポンスの件数が減る変更となるが、記録済みパターンを「支払い予定」として返すこと自体が今回のバグであるため、意図した挙動である。

---

## 確認済みの論点

なし。ADR-0001／ADR-0002 で確立済みの記録判定ロジック（`_build_recorded_lookup()`）をそのまま流用し、`_filter_unrecorded()` と対称な抽出条件を `_filter_due()` に追加するのみのため、新たな論点は生じない。

## 未決事項

なし。
