# 対応計画：パターン管理情報の充実および取引入力の簡便化

## 概要

パターン一覧に「最終支払日」「次回支払日」を計算して表示し、次回支払日順でソートする。
各行に取引入力ボタンを追加し、ワンクリックで取引登録できるようにする。

---

## 要件

### 最終支払日

| 頻度 | ロジック |
|------|----------|
| 月次 | 今月の支払日 ≤ today → 今月の支払日を表示。今月の支払日 > today → 前月の支払日を表示 |
| 年次 | 今年の支払日 ≤ today → 今年の支払日を表示。今年の支払日 > today → 前年の支払日を表示 |

### 次回支払日

| 頻度 | ロジック |
|------|----------|
| 月次 | 今月の支払日 ≥ today → 今月の支払日を表示。今月の支払日 < today → 翌月の支払日を表示 |
| 年次 | 今年の支払日 ≥ today → 今年の支払日を表示。今年の支払日 < today → 翌年の支払日を表示 |

### ソート順

次回支払日の昇順で表示する（`next_payment_date` が null のものは末尾）。

### 取引入力

パターン行に「入力」ボタンを追加し、`/transactions/new?pattern_id=<id>` へ遷移する。

---

## 実装方針

### DBスキーマ変更

なし（既存フィールドから計算するのみ）。マイグレーション不要。

---

## 変更ファイル一覧

### 1. `backend/app/crud/pattern.py`

**追加する関数・変更**

```python
import calendar

def _payment_date_for_month(year: int, month: int, day: int) -> date:
    """支払日が月末を超える場合（例: 31日→2月）は月末にクランプして返す。"""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _calc_payment_dates(
    p: TransactionPattern, today: date
) -> tuple[date | None, date | None]:
    """
    (last_payment_date, next_payment_date) を返す。
    payment_day_of_month 未設定、または daily/other 頻度の場合は (None, None)。
    """
    if not p.payment_day_of_month:
        return None, None

    if p.frequency == "monthly":
        this_month = _payment_date_for_month(today.year, today.month, p.payment_day_of_month)
        if this_month <= today:
            last_pd = this_month
            next_y, next_m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            next_pd = _payment_date_for_month(next_y, next_m, p.payment_day_of_month)
        else:
            prev_y, prev_m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
            last_pd = _payment_date_for_month(prev_y, prev_m, p.payment_day_of_month)
            next_pd = this_month
        return last_pd, next_pd

    elif p.frequency == "annual" and p.payment_month_of_year:
        this_year = _payment_date_for_month(today.year, p.payment_month_of_year, p.payment_day_of_month)
        if this_year <= today:
            last_pd = this_year
            next_pd = _payment_date_for_month(today.year + 1, p.payment_month_of_year, p.payment_day_of_month)
        else:
            last_pd = _payment_date_for_month(today.year - 1, p.payment_month_of_year, p.payment_day_of_month)
            next_pd = this_year
        return last_pd, next_pd

    return None, None
```

**`_to_dict()` の変更**

```python
def _to_dict(p: TransactionPattern, today: date | None = None) -> dict:
    if today is None:
        today = today_jst()
    last_pd, next_pd = _calc_payment_dates(p, today)
    return {
        # ... 既存フィールド ...
        "last_payment_date": last_pd,
        "next_payment_date": next_pd,
    }
```

`today` は省略可能とし、未指定時は `today_jst()` を内部で呼ぶ。
既存の呼び出し箇所（`get_patterns`, `get_pattern`, `create_pattern`, `update_pattern`, `get_due_patterns`）の変更は不要。

---

### 2. `backend/app/schemas/pattern.py`

`PatternOut` に2フィールドを追加する。

```python
from datetime import date, datetime  # date を追加

class PatternOut(PatternBase):
    # ... 既存フィールド ...
    last_payment_date: Optional[date] = None
    next_payment_date: Optional[date] = None
```

---

### 3. `backend/app/templates/patterns/index.html`

#### テーブルヘッダー

「支払日」列の後に「最終支払日」「次回支払日」を追加。「操作」列に「入力」を追加。

```
パターン名 | カテゴリ | アカウント | グループ | PGrp | 金額 | 支払日 | 最終支払日 | 次回支払日 | メモ | 状態 | 操作
```

#### 最終支払日セル

```html
<td class="text-sm">
  <template x-if="p.last_payment_date">
    <span x-text="p.last_payment_date"></span>
  </template>
  <template x-if="!p.last_payment_date">
    <span style="color:#bbb;">—</span>
  </template>
</td>
```

#### 次回支払日セル

```html
<td class="text-sm">
  <template x-if="p.next_payment_date">
    <span :style="isNearDue(p.next_payment_date) ? 'color:#c05621;font-weight:600;' : ''"
          x-text="p.next_payment_date"></span>
  </template>
  <template x-if="!p.next_payment_date">
    <span style="color:#bbb;">—</span>
  </template>
</td>
```

#### 取引入力ボタン

操作列の「編集」「削除」に加えて追加する。

```html
<button class="btn-sm btn-primary"
        @click="$event.preventDefault(); window.location.href='/transactions/new?pattern_id=' + p.id">
  入力
</button>
```

#### ソート変更 (`getByFreq()`)

```javascript
getByFreq(freq) {
  return this.patterns
    .filter(p => p.frequency === freq)
    .sort((a, b) => {
      const na = a.next_payment_date;
      const nb = b.next_payment_date;
      if (!na && !nb) return 0;
      if (!na) return 1;   // null は末尾
      if (!nb) return -1;
      return na.localeCompare(nb);  // ISO 日付文字列の辞書順 = 日付昇順
    });
},
```

#### `isNearDue()` ヘルパー追加

```javascript
isNearDue(dateStr) {
  if (!dateStr) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(dateStr);
  const diffDays = (d - today) / (1000 * 60 * 60 * 24);
  return diffDays >= 0 && diffDays <= 7;
},
```

---

## 確認事項（未決）

1. **次回支払日のハイライト閾値**: 「7日以内」でよいか
2. **ソート粒度**: グループでまとめつつその中で次回支払日順にするか、全体を純粋に次回支払日順にするか
