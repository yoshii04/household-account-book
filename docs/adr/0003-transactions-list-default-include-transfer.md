# ADR-0003: 取引一覧のデフォルト表示で資金移動を含める

## ステータス

採用・実装済み（Accepted / Implemented）— 2026-08-16

---

## コンテキスト

### 現状の実装

取引一覧ページ（`GET /transactions`、`backend/app/routers/pages.py:89` の `transactions_page()`）は、フィルターフォームに「資金移動を含む」チェックボックス（`backend/app/templates/transactions/list.html:66-71`）を持つ。

```python
# backend/app/routers/pages.py:97, 119-121
is_transfer: Optional[bool] = Query(False),
...
# is_transfer=True → 資金移動を含む全件表示（フィルターなし）
# is_transfer=False → 資金移動を除外（デフォルト）
effective_is_transfer = None if is_transfer else False
```

`is_transfer` の Query デフォルトは `False` であり、初回アクセス時（フィルター未送信）はチェックボックスが**オフ**の状態で表示される。ユーザーはページを開くたびに毎回チェックを入れ直して「絞り込む」を押さないと資金移動取引を確認できない。

年・月については、同じ関数内に「初回アクセス時のみ当月をデフォルトにする」という区別ロジックが既に存在する。

```python
# backend/app/routers/pages.py:109-112
if not f and not ids_list:
    # 初回アクセス（フォーム未送信）は当月をデフォルトにする
    year = year or cur_year
    month = month or cur_month
```

`f` はフィルターフォームの `<input type="hidden" name="f" value="1">`（`list.html:20`）によって、「フォームが一度でも送信されたか」を示すフラグとして使われている。`is_transfer` にはこの区別が適用されておらず、単純な Query デフォルト値（`False`）のみで挙動が決まっている。

### 関連する類似実装との比較

| エンドポイント | `is_transfer` デフォルト | 備考 |
|---|---|---|
| `GET /transactions`（一覧ページ） | `False`（今回の変更対象） | `pages.py:97` |
| `GET /transactions/export/excel`（Excel出力） | `False` | `pages.py:181`。一覧ページの「Excel出力」ボタンから呼ばれるが、JS（`list.html:310-320`）がクリック時点のチェックボックスの実際の状態をそのままクエリに詰めて渡すため、ページ側のデフォルトが変わればボタンの挙動も自然に追従する。エンドポイント自体のデフォルトを変える必要はない |
| `GET /api/v1/transactions`（JSON API） | `False` | `routers/transactions.py:26`。一覧ページとは**別の実装**（`pages.py` はこの API を呼ばず `get_transactions()` を直接呼んでいる）。レポート画面のドリルダウンモーダル（`base.html:199-206`）がこの API を `is_transfer` 未指定で呼び出しており、レポート集計（資金移動除外）との整合を暗黙に前提にしている |
| `/export` 画面（Actual.TXT形式エクスポート） | `True` | `pages.py:370`。こちらは元々デフォルトで資金移動を含む設計になっている |

### 要望

取引一覧ページの初回表示で「資金移動を含む」チェックボックスをデフォルトでオンにする。

### 対象外の確認

- **`GET /api/v1/transactions`（JSON API）のデフォルトは対象外。** レポート画面のドリルダウンモーダルがこの API を直接呼んでおり、資金移動を除外した集計と一致させることを前提にしている。ここのデフォルトを変えるとドリルダウン結果が月次集計と食い違う回帰を生む。
- **`GET /transactions/export/excel` のデフォルトも対象外。** ボタン押下時に現在のチェックボックス状態をそのまま渡す実装のため、一覧ページ側の初期表示を変えるだけで自然に一致する。エンドポイント自体の変更は不要。
- **`/export`（Actual.TXT エクスポート画面）・ダッシュボードの直近取引表示は対象外。** 前者は既にデフォルト `True`、後者（`pages.py:69` の `recent_items`）は `is_transfer=False` 固定でチェックボックス自体が存在しない別機能。

---

## 決定

### 1. 一覧ページの `is_transfer` を「初回アクセス時のみ」デフォルト True にする

`is_transfer` の Query デフォルトを `None`（未指定）に変更し、既存の `f`（フォーム送信フラグ）による初回アクセス判定に相乗りする形で解決する。

```python
# backend/app/routers/pages.py
def transactions_page(
    ...
    is_transfer: Optional[bool] = Query(None),
    ...
):
    ...
    if not f and not ids_list:
        # 初回アクセス（フォーム未送信）は当月・資金移動含むをデフォルトにする
        year = year or cur_year
        month = month or cur_month
        if is_transfer is None:
            is_transfer = True
    elif is_transfer is None:
        # フォーム送信済み（f=1）または ids 指定時にチェックボックスが
        # 未チェック（=パラメータ未送信）なら、明示的に除外する
        is_transfer = False

    effective_is_transfer = None if is_transfer else False
```

**なぜ Query デフォルトを単純に `True` にしないか：** HTML の `<input type="checkbox">` は**チェックを外すとブラウザがそのフィールド自体を送信しない**。そのため「初回アクセス（`is_transfer` 未送信）」と「フォームを送信したがチェックを外した（`is_transfer` 未送信）」は、パラメータの有無だけでは区別できない。単純に Query デフォルトを `True` にすると、ユーザーが明示的にチェックを外して「資金移動を除外する」絞り込みをしても、その操作が無視されて常に資金移動が含まれてしまう回帰が生じる。

`f` フラグは既に year/month で「初回アクセスか、フォーム送信済みか」を区別するために使われており、同じ判定軸を `is_transfer` にも適用することで、既存パターンを踏襲しつつ回帰を避ける。

### 2. `GET /api/v1/transactions`（JSON API）・`GET /transactions/export/excel` のデフォルトは変更しない

「対象外の確認」節の理由により、`routers/transactions.py` の `is_transfer` デフォルト（`False`）、および `pages.py` の `transactions_export_excel()` の `is_transfer` デフォルト（`False`）はそのまま維持する。

### 3. テンプレート（`list.html`）の変更は不要

チェックボックスの `checked` 属性は既に `{% if filter.is_transfer %}checked{% endif %}`（`list.html:68`）で `filter.is_transfer` の解決済みの値を参照している。決定1により `pages.py` 側で解決される値が変わるだけで、テンプレート側は変更なしで正しく反映される。

---

## 検討した代替案

### 代替案A: `Query(True)` に単純変更する

- 短所: 決定1の説明の通り、チェックを外す操作と初回アクセスが区別できなくなり、ユーザーが明示的に資金移動を除外して絞り込む操作ができなくなる回帰が生じる
- → **不採用**

### 代替案B: hidden field トリック（`<input type="hidden" name="is_transfer" value="false">` を checkbox の直前に置き、同名で送信させる）

- 長所: バックエンドのロジック変更が不要になる可能性がある
- 短所: 同名パラメータが複数送信された場合にどちらの値を採用するかは FastAPI/Starlette のクエリパース実装に依存し、挙動を保証しづらい。また、初回アクセス時にはこのフィールド自体が存在しない（GET で `/transactions` を直接開いた場合はフォーム自体が送信されていない）ため、結局「初回アクセス」を判定する仕組みが別途必要になり、`f` ベースの既存パターンと二重管理になる
- → **不採用**

### 代替案C: JSON API（`GET /api/v1/transactions`）のデフォルトも `True` に変更する

- 短所: レポートのドリルダウンモーダル（`base.html`）が資金移動除外を前提に呼び出しており、月次集計と食い違う件数が表示される回帰が生じる。他に本 API を利用する未知のクライアントがいた場合も予告なしの破壊的変更になる
- → **不採用**

---

## 変更ファイル一覧（見込み）

| ファイル | 変更内容 |
|---|---|
| `backend/app/routers/pages.py` | `transactions_page()` の `is_transfer` パラメータのデフォルトを `None` に変更し、`f`（フォーム送信フラグ）に基づく初回アクセス判定に `is_transfer` のデフォルト解決を追加（決定1） |
| `backend/tests/integration/routers/test_transactions_router.py` | 初回アクセス時（`f` 未送信）に資金移動が含まれること、フォーム送信時（`f=1`）にチェックを外すと除外されることを検証するテストケースを追加 |

### 仕様書（別プルリクエストで対応）

以下の仕様書は本 ADR の変更内容の影響を受けるが、**本 ADR・本実装のプルリクエストでは修正しない**。仕様書自体の更新は別プルリクエストで行う。

| ファイル | 影響内容（別PRでの反映事項） |
|---|---|
| `docs/specs/core/spec_transactions.md` | L76-77「取引一覧（`/transactions`）」の初回アクセス時デフォルト説明に、`is_transfer` も当月と同様に初回アクセス時のみ `True`（資金移動を含む）がデフォルトになる旨を追記。L89 のフィルター条件表の `is_transfer` の説明を「ページの初回アクセス時は True（含む）、フォーム送信時にチェックを外すと False（除外）。JSON API（`GET /api/v1/transactions`）単体のデフォルトは従来通り False」に更新。L236 の動作確認チェックリストにも初回アクセス時のデフォルト表示に関する項目を追加 |

---

## 影響・注意点

- `GET /api/v1/transactions`（JSON API）・`GET /transactions/export/excel` のデフォルトは変更しないため、これらを直接叩く外部クライアントやスクリプトへの影響はない。
- レポート画面からのドリルダウン（`showSelectedInList()` / `showAllInList()`、`base.html:178,183`）は共に `f=1` を付けて `/transactions` に遷移する実装であるため、決定1の分岐では「フォーム送信済み」扱いとなり、`is_transfer` 未指定時は従来通り `False`（除外）になる。レポート集計との整合性は維持される。
- 「リセット」リンク（`list.html:73`、`href="/transactions"`）はパラメータなしで遷移するため初回アクセス扱いとなり、リセット後も資金移動を含む表示に戻る。これは「デフォルトはオン」という要望と整合する挙動として意図的な仕様とする。
- 既存データへの変更・マイグレーションは不要。表示ロジックのみの変更。

---

## 確認済みの論点

なし（初版）。

## 未決事項

なし。
