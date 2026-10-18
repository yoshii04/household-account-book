# PDF サービス レビュー指摘修正計画

PDF サービスのコードレビューで発見された問題点と修正方針をまとめる。

---

## 🔴 必須対応（バグ・論理誤り）

### 1. `_make_pie_chart` のデッドコード削除・インポート整理

**ファイル**: `backend/app/services/pdf_service.py`  
**行**: L272–278

**問題**
```python
rect = Drawing(12, 10)          # 作成するが d には追加されない → dead code
from reportlab.graphics.shapes import Rect as GRect  # 関数内インポート
r = GRect(0, 0, 10, 8)
r.fillColor = _PALETTE[i % len(_PALETTE)]
r.strokeColor = colors.white
rect.add(r)                     # d ではなく rect に追加 → 描画されない
d.add(r.__class__(leg_x, ...))  # 別インスタンスを直接追加しているので上3行が全て無駄
```

`rect`・`r` を作って `rect.add(r)` しているが、最終的に `d` に追加しているのは
`r.__class__(...)` で生成した別オブジェクトのみ。前半の4行は描画に一切寄与しない。

**修正方針**
- `Rect` を L9 のファイル先頭インポートに追加する
- デッドコード4行（`rect =` / 関数内 `import` / `r =` / `rect.add`）を削除する
- `d.add(r.__class__(...))` を `d.add(Rect(...))` に書き換える

---

### 2. マイナス残高の口座が円グラフから除外される

**ファイル**: `backend/app/services/pdf_service.py`  
**行**: L556–557

**問題**
```python
pie_labels = [grp["type_label"] for grp in data["grouped"] if grp["subtotal_balance"] > 0]
pie_values = [grp["subtotal_balance"] for grp in data["grouped"] if grp["subtotal_balance"] > 0]
```

クレジットカードなど残高がマイナスになる口座種別が `> 0` の条件で除外される。
テーブルには表示されているのにグラフに出ないため、ユーザーが混乱する可能性がある。

**修正方針**
- フィルター条件を `!= 0` に変更し、全口座種別を対象とする
- マイナス残高は絶対値で円グラフの面積を算出する
- 凡例ラベルに `(負債)` サフィックスを付けてマイナスと視覚的に区別する

---

## 🟡 改善推奨（コード品質）

### 3. `from urllib.parse import quote` を関数内から先頭に移動

**ファイル**: `backend/app/routers/pages.py`  
**行**: L504

**問題**
```python
def export_pdf(...):
    ...
    from urllib.parse import quote  # ← 関数内インポート
```

標準ライブラリのインポートを関数内に書く必要はない。
リクエストのたびに `sys.modules` を参照するコストが微量だが発生する。

**修正方針**
- ファイル先頭のインポートブロックに `from urllib.parse import quote` を追加する
- 関数内の同行を削除する

---

### 4. 変数展開のない f-string を通常文字列に変更

**ファイル**: `backend/app/services/pdf_service.py`  
**行**: L428

**問題**
```python
story.append(_p(f"【支出 前年同月比 Top8】"))  # f"..." だが {} がない
```

`f` プレフィックスがあると Python は文字列をコンパイル時にテンプレートとして扱う。
変数展開が不要なリテラルには `f` を付けない。

**修正方針**
- `f"【支出 前年同月比 Top8】"` → `"【支出 前年同月比 Top8】"` に変更する

---

### 5. `export_pdf` エンドポイントにエラーハンドリングを追加

**ファイル**: `backend/app/routers/pages.py`  
**行**: `export_pdf` 関数全体

**問題**
PDF 生成中に例外が発生した場合（DB 接続断・データ不整合・reportlab 内部エラーなど）、
FastAPI のデフォルト 500 ハンドラがそのままスタックトレースを返す。
エラーの原因がログに残らず、クライアントへのメッセージも不親切。

**修正方針**
```python
import logging
logger = logging.getLogger(__name__)

try:
    pdf_bytes, filename = generate_monthly_report_pdf(db, year, month)
except Exception as e:
    logger.exception("PDF生成中にエラーが発生しました year=%s month=%s", year, month)
    raise HTTPException(status_code=500, detail="PDF生成に失敗しました")
```

---

## 修正優先順位まとめ

| # | 優先度 | ファイル | 内容 |
|---|--------|---------|------|
| 1 | 🔴 必須 | `pdf_service.py` L272–278 | デッドコード削除・`Rect` インポート整理 |
| 2 | 🔴 必須 | `pdf_service.py` L556–557 | マイナス残高を円グラフに含める |
| 3 | 🟡 推奨 | `pages.py` L504 | `quote` インポートをファイル先頭へ移動 |
| 4 | 🟡 推奨 | `pdf_service.py` L428 | 不要な `f` プレフィックス削除 |
| 5 | 🟡 推奨 | `pages.py` `export_pdf` | 例外を `HTTPException(500)` に変換してログ出力 |
