# 対応計画：取引一覧 編集ボタン押下時の Internal Server Error 修正

## 調査結果

### 症状
取引一覧画面の「編集」ボタンを押下すると HTTP 500 Internal Server Error が発生する。

### エラーログ（実機確認）

```
File "app/templates/transactions/form.html", line 560, in block 'scripts'
    date: {{ (initial_date if initial_date else (today if is_copy else (tx.date if tx else today))) | tojson }},
TypeError: Object of type date is not JSON serializable
```

---

## 根本原因

### 原因：`tx.date`（Python `date` 型）を Jinja2 の `tojson` フィルタに渡している

#### 処理の流れ

1. `GET /transactions/{tx_id}/edit` → `edit_transaction_page()`（`routers/pages.py:290`）
2. `get_transaction(db, tx_id)` → `_to_out_dict()` （`crud/transaction.py:21`）
   - `"date": tx.date` — Python の `datetime.date` オブジェクトをそのまま dict に格納
3. この dict をテンプレートコンテキスト `tx` として渡す
4. `transactions/form.html:560` で次の式を評価：
   ```jinja2
   date: {{ (initial_date if initial_date else (today if is_copy else (tx.date if tx else today))) | tojson }},
   ```
5. **編集モードの評価結果**：
   - `initial_date` → テンプレートコンテキストに未渡し → Jinja2 `Undefined`（falsy）→ スキップ
   - `is_copy` → `False` → スキップ
   - `tx.date` → Python `datetime.date` オブジェクト → **`tojson` が処理できず `TypeError`**
6. FastAPI が例外をキャッチして 500 を返す

#### なぜ新規入力・コピーでは問題が起きないか

| モード | `initial_date` | `is_copy` | 評価される値 | 型 |
|--------|---------------|-----------|-------------|-----|
| 新規 | `None` (falsy) | `False` | `today`（Python 文字列） | `str` ✅ |
| コピー | `None` (falsy) | `True` | `today`（Python 文字列） | `str` ✅ |
| **編集** | **未渡し**（falsy） | `False` | **`tx.date`** | **`date` ❌** |

`today = today_jst().isoformat()` は `str` 型なので `tojson` で問題なく処理される。
コピーモードでは `is_copy=True` のため `today`（文字列）が使われ、`tx.date` には到達しない。

---

## 副次的な問題（追加修正推奨）

### 問題2：`tx` が `None` の場合に 404 を返さない

`edit_transaction_page()` は `get_transaction(db, tx_id)` が `None`（存在しない ID）を返した場合でも、エラーを返さずに空の編集フォームを表示してしまう。

```python
# 現状：tx が None でも TemplateResponse を返す
tx = get_transaction(db, tx_id)
# ... tx が None かどうかのチェックなし
return templates.TemplateResponse("transactions/form.html", {..., "tx": tx, ...})
```

---

## 修正方針

### 修正1（主要）：`initial_date` として ISO 文字列を渡す

**対象ファイル**: `backend/app/routers/pages.py`（`edit_transaction_page`、290行付近）

テンプレートコンテキストに `initial_date`（ISO 文字列）を追加する。
これにより、テンプレート内で `initial_date` が truthy になり、`tx.date` の評価に到達しなくなる。

```python
# 修正前
return templates.TemplateResponse(
    "transactions/form.html",
    {
        "request": request,
        "mode": "edit",
        "parent_categories": parent_categories,
        "accounts": accounts,
        "accounts_data": accounts_data,
        "groups": groups,
        "today": today_jst().isoformat(),
        "tx": tx,
        "return_url": return_url or "",
        "is_copy": False,
    },
)

# 修正後
return templates.TemplateResponse(
    "transactions/form.html",
    {
        "request": request,
        "mode": "edit",
        "parent_categories": parent_categories,
        "accounts": accounts,
        "accounts_data": accounts_data,
        "groups": groups,
        "today": today_jst().isoformat(),
        "tx": tx,
        "return_url": return_url or "",
        "is_copy": False,
        "initial_date": tx["date"].isoformat() if tx and tx.get("date") else None,  # 追加
    },
)
```

#### この方針を選んだ理由

- `new_transaction_page` に既存の `initial_date` パラメータと同じ仕組みで統一できる
- `_to_out_dict()` の戻り値（`date` 型）を変更しない
  - API エンドポイント（`GET /api/v1/transactions/{tx_id}`）の `TransactionOut` スキーマは `date: Date` 型のまま維持できる
- テンプレート側のロジックを変更しない（副作用なし）

### 修正2（副次）：存在しない取引 ID に対して 404 を返す

**対象ファイル**: `backend/app/routers/pages.py`（`edit_transaction_page`）

```python
# 修正前
tx = get_transaction(db, tx_id)
parent_categories = ...

# 修正後
tx = get_transaction(db, tx_id)
if not tx:
    raise HTTPException(status_code=404, detail="取引が見つかりません")
parent_categories = ...
```

---

## 修正スコープ

| ファイル | 変更内容 |
|----------|---------|
| `backend/app/routers/pages.py` | `edit_transaction_page` に `initial_date` を追加、404 ハンドリングを追加 |

テンプレート、CRUD、スキーマへの変更は不要。

---

## 動作確認手順

1. `docker compose restart backend`
2. 取引一覧（`/transactions`）で任意の取引の「編集」ボタンを押下
3. 500 エラーが解消され、編集フォームが表示されること
4. 表示された日付フィールドに正しい日付（元の取引の日付）が初期値としてセットされていること
5. 内容を変更して「保存」ボタンを押下し、取引が正常に更新されること
6. 存在しない ID（例：`/transactions/99999/edit`）にアクセスして 404 が返ること（修正2の確認）
