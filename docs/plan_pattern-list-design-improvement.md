# 対応計画：パターン管理一覧のデザイン改善

## 概要

パターン管理画面（`/patterns`）の一覧が列数（12列）が多く見にくいため、
情報の優先度に応じた視覚的階層を設けてコンパクトかつ読みやすい一覧にリデザインする。

---

## 現状の問題点

| 問題 | 詳細 |
|------|------|
| 列が多すぎる（12列） | 「グループ」「パターングループ」「支払日」「最終支払日」「次回支払日」が並列で視認性が低い |
| 視覚的重みが均一 | パターン名・金額・次回支払日などの重要列が埋もれる |
| カテゴリ full_path が長い | `A30_通信費/インターネット` のような長文で列幅を消費 |
| 操作ボタンが幅を使う | 「入力」「編集」「削除」3ボタンが横並びで列幅を圧迫 |
| 状態（有効/無効）が専用列 | 無効行は既にopacityで視覚化されており専用列が冗長 |

---

## 改善方針

### 1. 2段組みセルで列数を削減（12列 → 7列）

各行を2行レイアウトにすることで、関連情報をまとめて1列に収める。

**改善後の列構成:**

| # | 列名 | 内容（1行目 / 2行目） |
|---|------|-----------------------|
| 1 | パターン | パターン名（太字） / カテゴリ（small、muted） |
| 2 | グループ / PG | グループコード / パターングループバッジ |
| 3 | アカウント | 送金元アカウント / →送金先（資金移動時のみ） |
| 4 | 金額 | ±¥金額（右寄せ、色分け） / 収支区分ラベル |
| 5 | 支払日情報 | 支払日設定（毎月〇日など） / 次回支払日（近い場合は橙色強調） |
| 6 | 状態 | 有効/無効バッジ（列として維持、「無効も表示」チェック時に表示） |
| 7 | 操作 | アイコンボタン3つ（「入力」「編集」「削除」） |

**削除・統合する列:**
- 「支払日」「最終支払日」「次回支払日」の3列 → 「支払日情報」1列に統合
- 「グループ」「パターングループ」の2列 → 1列に統合
- 「メモテンプレート」列を削除（パターン名2行目またはツールチップへ）

### 2. 操作ボタンのアイコン化

テキストボタン（入力・編集・削除）をアイコン付きコンパクトボタンに変更し、列幅を削減する。

```
[✏ 編集]  [🗑 削除]  → ホバーでラベル表示（title属性）
[→ 入力]  ← 「入力」ボタンは視認性のためラベル維持
```

### 3. 頻度グループヘッダーにサマリーを追加

各頻度セクション（月次・年次・日次・その他）のヘッダー行に件数と月次合計金額を表示する。

```
月次（8件）  支出合計: ¥52,800
```

### 4. メモテンプレートのインライン折りたたみ表示

メモは列として表示せず、パターン名の下（2行目）にアイコン付きで表示。
長い場合は省略して、ホバー or クリックで全文表示。

```
[パターン名（太字）]
[📝 スーパー〇〇] [カテゴリ]  ← 2行目
```

### 5. 次回支払日の視認性強化

現在の「橙色 + bold」に加え、7日以内の場合はセル背景色（薄橙）でハイライトする。

---

## ビフォー / アフター イメージ

### 現状（12列）
```
パターン名 | カテゴリ | アカウント | グループ | PG | 金額 | 支払日 | 最終支払日 | 次回支払日 | メモ | 状態 | 操作
```
→ 横スクロールが発生しやすく、重要情報が埋もれる

### 改善後（7列）
```
パターン（名前+カテゴリ） | グループ/PG | アカウント | 金額 | 支払日情報 | 状態 | 操作
```
→ 1画面に収まり、重要列（名前・金額・次回支払日）が見やすくなる

---

## 変更ファイル一覧

### 1. `backend/app/templates/patterns/index.html`（主要変更）

**テーブルヘッダー変更**

```html
<!-- 変更前（12列） -->
<th>パターン名</th>
<th>カテゴリ</th>
<th>アカウント</th>
<th>グループ</th>
<th>パターングループ</th>
<th class="text-right">金額</th>
<th>支払日</th>
<th>最終支払日</th>
<th>次回支払日</th>
<th>メモテンプレート</th>
<th>状態</th>
<th>操作</th>

<!-- 変更後（7列） -->
<th>パターン</th>
<th>グループ / PG</th>
<th>アカウント</th>
<th class="text-right">金額</th>
<th>支払日</th>
<th>状態</th>
<th>操作</th>
```

**パターン列（2段組み）**

```html
<td>
  <div class="pattern-name" x-text="p.name"></div>
  <div class="pattern-sub">
    <template x-if="p.memo_template">
      <span class="pattern-memo" x-text="'📝 ' + p.memo_template"></span>
    </template>
    <span class="pattern-category" x-text="p.category_full_path"></span>
  </div>
</td>
```

**グループ / PG列（統合）**

```html
<td>
  <div x-text="p.group_code || '—'" class="text-sm"></div>
  <div x-show="p.pattern_group_name">
    <span class="badge-pg" x-text="p.pattern_group_name"></span>
  </div>
</td>
```

**支払日情報列（統合）**

```html
<td class="text-sm">
  <!-- 支払日設定 -->
  <template x-if="p.payment_day_of_month">
    <div>
      <template x-if="p.frequency === 'monthly'">
        <span class="text-muted" x-text="'毎月' + p.payment_day_of_month + '日'"></span>
      </template>
      <template x-if="p.frequency === 'annual' && p.payment_month_of_year">
        <span class="text-muted" x-text="'毎年' + p.payment_month_of_year + '月' + p.payment_day_of_month + '日'"></span>
      </template>
    </div>
  </template>
  <!-- 次回支払日 -->
  <template x-if="p.next_payment_date">
    <div :class="isNearDue(p.next_payment_date) ? 'near-due' : ''">
      <span x-text="'次回: ' + p.next_payment_date"></span>
    </div>
  </template>
  <template x-if="!p.payment_day_of_month">
    <span style="color:#bbb;">—</span>
  </template>
</td>
```

**操作列（コンパクト化）**

```html
<td>
  <div class="action-group">
    <button class="btn-sm btn-primary"
            title="取引を入力する"
            @click="window.location.href='/transactions/new?pattern_id=' + p.id + (p.next_payment_date ? '&date=' + p.next_payment_date : '')">
      入力
    </button>
    <button class="btn-sm btn-edit"
            title="パターンを編集する"
            @click="openEditModal(p)">✏</button>
    <button class="btn-sm btn-delete"
            title="パターンを削除する"
            @click="deletePattern(p.id)">🗑</button>
  </div>
</td>
```

**頻度グループヘッダー（サマリー追加）**

```html
<h3 style="margin-bottom:0.5rem;">
  <span x-text="freq.label + '（' + getByFreq(freq.key).length + '件）'"></span>
  <span class="freq-summary" x-text="getFreqSummary(freq.key)"></span>
</h3>
```

JavaScript側に `getFreqSummary()` ヘルパーを追加：

```javascript
getFreqSummary(freq) {
  const patterns = this.getByFreq(freq).filter(p => p.is_active);
  if (patterns.length === 0) return '';
  const total = patterns.reduce((sum, p) => {
    return sum + (p.is_income ? 0 : (p.typical_amount || 0));
  }, 0);
  return total > 0 ? '  支出合計: ¥' + total.toLocaleString() : '';
},
```

---

### 2. `frontend/static/css/style.css`（スタイル追加）

パターン管理用の新規CSSクラスを「パターン管理」セクションに追加する。

```css
/* パターン一覧：2段組みセル */
.pattern-name {
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}
.pattern-sub {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  margin-top: 2px;
  flex-wrap: wrap;
}
.pattern-category {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
}
.pattern-memo {
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 140px;
}

/* パターングループバッジ */
.badge-pg {
  display: inline-block;
  padding: 1px 6px;
  font-size: 11px;
  background: #e8f5e9;
  color: #2e7d32;
  border: 1px solid #a5d6a7;
  border-radius: 3px;
  white-space: nowrap;
}

/* 次回支払日：近い場合のハイライト */
.near-due {
  color: #c05621;
  font-weight: 600;
  background: #fff7ed;
  border-radius: 3px;
  padding: 1px 4px;
  display: inline-block;
}

/* 頻度グループサマリー */
.freq-summary {
  font-size: 12px;
  font-weight: normal;
  color: #dc2626;
  margin-left: 0.75rem;
}

/* 操作ボタングループ */
.action-group {
  display: flex;
  gap: 4px;
  align-items: center;
  flex-wrap: nowrap;
}
```

---

## 実装上の注意点

- `data-table` クラスは他画面でも使用されているため変更しない。
  パターン一覧テーブルには別途 `pattern-list-table` クラスを付与してスタイルを分離する。
- 頻度グループの `data-table` 変更時は既存の行スタイル（`.row-inactive`）を引き継ぐこと。
- `pattern_group_name` は既存の API レスポンスに含まれているため、バックエンド変更は不要。
- メモテンプレートをパターン名と同列に移動しても、既存のモーダル内フォームは変更不要。

---

## 確認事項

1. **最終支払日の扱い**: 改善後の一覧から「最終支払日」列は削除する方針だが、必要であれば支払日情報セルの2行目に追加可能。
2. **パターン名の最大幅**: `max-width: 200px` でよいか（パターン名の平均的な長さによる）。
3. **メモ表示位置**: パターン名2行目でなく、ツールチップ（`title` 属性）への移動でも対応可能。

---

## 作業スコープ（バックエンド変更なし）

本対応はフロントエンド（HTML テンプレート・CSS）のみの変更で完結する。
API レスポンスのフィールドは現状のまま利用するため、バックエンド（Python）の変更は不要。
