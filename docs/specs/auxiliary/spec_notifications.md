# 仕様：C-7 通知（定期支払いの当日・未記録を Slack に通知）

> **状態**: 実装済み（[ADR-0007](../../adr/0007-pattern-payment-notification-via-slack.md) の「進め方」の 3 番目）。
> 方針・代替案・確認済みの論点は ADR-0007 に記録されている。本書は ADR の決定を**実装できる粒度**に落とした仕様で、ADR と食い違う場合は ADR を正とする。

## 概要

定期取引パターンのうち「今日が支払日で未記録」と「支払日を過ぎて未記録」のものを、1 日 1 回、Slack の Incoming Webhook に投稿する機能。画面を開かない日でも記録漏れに気づけるようにすることが目的。

- 判定ロジックは既存の `get_due_and_unrecorded_patterns` をそのまま使い、通知側で再実装しない（ダッシュボードと通知の結果を一致させる）
- **外部への送信のみ**。受信するエンドポイント・画面・API・DB テーブルは追加しない
- 判定と送信は 1 回実行して終了する CLI に閉じ、定期実行は専用の `scheduler` コンテナが CLI を呼ぶ形で行う
- 通知先は Slack のみ（`Notifier` 抽象は用意するが、実装は `SlackNotifier` だけ）

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | なし | 追加しない |
| API | なし | 追加しない（ADR-0007 決定 2。[ADR-0006](../../adr/0006-no-authentication-for-personal-local-use.md) の前提を変えないため） |
| CLI | `python -m app.notify.run daily` | 判定して送る（1 回実行して終了） |
| CLI | `python -m app.notify.run daily --dry-run` | 送らずに本文を標準出力へ出す |
| CLI | `python -m app.notify.run test` | 疎通確認用のテストメッセージを送る |
| 常駐 | `python -m app.notify.scheduler` | 毎日 `NOTIFY_TIME`（JST）に `daily` を実行し続ける |

ルートを追加しないため、`tests/integration/routers/test_pages_smoke.py`（全ページルートの HTTP 200 検証）には影響しない。

---

## 対象ファイル

### 新規

- `backend/app/notify/__init__.py` — パッケージ
- `backend/app/notify/base.py` — `NotificationMessage`、`Notifier` 抽象、`NotificationError`
- `backend/app/notify/slack.py` — `SlackNotifier`（`httpx`、リトライ、URL を出さないエラー処理）
- `backend/app/notify/messages.py` — `build_daily_message` / `build_test_message`（純粋関数）
- `backend/app/notify/run.py` — CLI（`daily` / `daily --dry-run` / `test`）
- `backend/app/notify/scheduler.py` — 次の `NOTIFY_TIME` を待って `run daily` を呼ぶループ
- `backend/tests/test_notify_messages.py`
- `backend/tests/test_notify_slack.py`
- `backend/tests/test_notify_run.py`
- `backend/tests/test_notify_scheduler.py`（ADR-0007 の見込みにはないが、時刻判定を検証するため追加する）

### 変更

- `backend/app/config.py` — `slack_webhook_url` / `notify_time` / `notify_show_amount` を追加
- `docker-compose.yml` — `scheduler` サービスの追加、環境変数の受け渡し
- `.env.example` — 新規 3 項目
- `backend/requirements.txt` — `httpx` の行にコメントを添えるのみ（バージョン・依存は変えない）
- 関連ドキュメント（`CLAUDE.md` / `DESIGN.md` / `README.md`）— 実装 PR で更新する

### 既存のまま使うもの（変更しない）

- `backend/app/crud/pattern.py` — `get_due_and_unrecorded_patterns(db, today)`
- `backend/app/jst.py` — `today_jst` / `now_jst`
- `backend/app/database.py` — `SessionLocal`

---

## データモデル

**新規テーブル・カラム・マイグレーションはない**（送信履歴も持たない。ADR-0007 決定 8）。

通知の材料は、`get_due_and_unrecorded_patterns` が返す次の 2 つのリスト（要素は `dict`）である。

| 戻り値 | 内容 |
|---|---|
| `due` | 今日が支払日で、対象期間が未記録のアクティブパターン |
| `unrecorded` | 対象期間の支払日を過ぎても未記録のアクティブパターン（猶予なし） |

本文で使う `dict` のキー:

| キー | 用途 |
|---|---|
| `name` | パターン名 |
| `typical_amount` | 金額（`None` または 0 のときは金額を載せない。ダッシュボードの `if p.typical_amount` と同じ扱い） |
| `next_payment_date` | 「支払日」。未記録のパターンでは**対象期間内の支払日**が入る（過ぎた支払日のまま据え置かれ、先送りされない） |
| `is_income` | 収入パターンの判別 |

`category_full_path` / `account_code` / `memo_template` 等のキーは**本文に使わない**（ADR-0007 決定 4）。`due` と `unrecorded` は同じパターンを含まない（`due` は支払日 = 今日、`unrecorded` は支払日 < 今日で判定されるため）。

---

## 機能仕様

### 設定（環境変数）

`backend/app/config.py` の `Settings` に追加する。

| 環境変数 | `Settings` の項目 | 型 | 既定 | 内容 |
|---|---|---|---|---|
| `SLACK_WEBHOOK_URL` | `slack_webhook_url` | `str` | `""` | 前後の空白は取り除いて使う。**空なら通知機能は無効** |
| `NOTIFY_TIME` | `notify_time` | `str` | `"22:30"` | 毎日の実行時刻（JST、24 時間表記 `HH:MM`）。`scheduler` だけが使う |
| `NOTIFY_SHOW_AMOUNT` | `notify_show_amount` | `str` | `"true"` | 本文に金額を含めるか。`true` / `false`（大文字小文字を区別しない） |

- **`notify_time` と `notify_show_amount` は `str` で受け、検証は通知側（`notify_time` は `scheduler` の起動時、`notify_show_amount` は `run daily`）で行う。** `Settings` は backend も読み込むため、`time` や `bool` の型で検証すると、不正な値で Web アプリまで起動しなくなる（通知の設定ミスが画面に波及しない、という ADR-0007 決定 7 の方針を守る）
- **`NOTIFY_SHOW_AMOUNT` が `true` / `false` 以外（空、`flase`、`1` 等）なら、`daily` は送信せずにエラーログ「NOTIFY_SHOW_AMOUNT が不正です」を出して終了コード 1**（`--dry-run` も同じ）。金額を隠したいのに誤記で金額が外部に出る、という事故を避けるため、不正値を既定（`true`）に読み替えない（fail-closed）
- `SLACK_WEBHOOK_URL` が空でない場合、**送信前に次をすべて満たすことを検証する**（`urllib.parse.urlsplit` で解析）。満たさなければ設定ミスとして扱い、送信せずにエラーログを出して終了コード 1（`daily` / `test` とも）。ログに**入力された URL は出さない**（「形式が不正」とだけ出す）
  - スキーム が `https`
  - ホスト名が `hooks.slack.com`（Incoming Webhook の URL は常にこのホスト）
  - パスが `/services/` で始まる
  - ユーザー情報（`user:pass@`）とポート指定を含まない

  これにより、`.env` の誤記や改ざんで、本文（パターン名・金額）が Slack 以外のホストへ送られることを防ぐ
- `.env.example` は次のとおりとする。**URL の値は空にし、形式の例はコメントにも書かない**（GitHub のシークレットスキャンが Slack Webhook の URL 形式を検出するため、ダミーの URL でもコミットできなくなる場合がある）

  ```
  # 定期支払いの通知（Slack Incoming Webhook）。空なら通知機能は無効
  SLACK_WEBHOOK_URL=
  # 毎日の実行時刻（JST, HH:MM）
  NOTIFY_TIME=22:30
  # 本文に金額を含めるか（true / false）
  NOTIFY_SHOW_AMOUNT=true
  ```

### 通知の内容・頻度

| 項目 | 仕様 |
|---|---|
| 頻度 | 1 日 1 回、1 メッセージ。既定は JST 22:30 |
| 基準日 | `today_jst()`。`date.today()` は使わない |
| 送らない条件 | `due` と `unrecorded` が**両方とも 0 件**なら何も送らない |
| 宛先 | `SLACK_WEBHOOK_URL` の 1 本のみ |
| 並び順 | `get_due_and_unrecorded_patterns` が返す順（`sort_order`, `id`）のまま。通知側で並べ替えない |

### 本文の組み立て（`build_daily_message`）

シグネチャ: `build_daily_message(due, unrecorded, show_amount, today) -> NotificationMessage | None`

> ADR-0007 の見込みのシグネチャに `today` を加える。見出しに日付を載せるため。

`NotificationMessage` は `text: str` を持つ（dataclass）。0 件のときは `None` を返す。

#### 書式

```
【家計簿】{YYYY-MM-DD} の支払いリマインド

■ 今日が支払日（まだ未記録 {n}件）
• {名前} — {金額}円

■ 支払日を過ぎて未記録（{n}件）
• {名前} — {金額}円（支払日: {MM/DD}）
```

- 見出し行 → 空行 → セクションの順。セクション間は空行 1 行
- **件数が 0 のセクションは見出しごと省略する**（片方だけ 1 件以上のときは、その 1 セクションだけの本文になる）
- 金額は桁区切りカンマ（`80,000円`）。名前と金額の区切りは ` — `（半角スペース + EM ダッシュ + 半角スペース）
- 支払日は `next_payment_date` を `MM/DD`（ゼロ埋め。`11/01`）で表示する。「今日が支払日」のセクションには支払日を載せない（常に今日のため）
- 末尾に改行は付けない

#### 例（ADR-0007 と同じ）

```
【家計簿】2026-11-03 の支払いリマインド

■ 今日が支払日（まだ未記録 1件）
• 家賃 — 80,000円

■ 支払日を過ぎて未記録（2件）
• 通信費 — 5,500円（支払日: 11/01）
• 保険料 — 12,000円（支払日: 10/25）
```

#### 金額・収入・エスケープの扱い

| ケース | 表示 |
|---|---|
| `show_amount=False` | 金額を載せない。「今日が支払日」は `• 家賃`、「未記録」は `• 通信費（支払日: 11/01）` |
| `typical_amount` が `None` / 0 | 金額を載せない（` — ` ごと省略）。例: `• 家賃`、`• 通信費（支払日: 11/01）` |
| `is_income=True`（給与など） | 名前の直後に `（収入）` を付ける。例: `• 給与（収入） — 300,000円`。金額の符号（`+` / `-`）は付けない |
| 名前に `&` `<` `>` を含む | Slack の仕様に従い `&amp;` `&lt;` `&gt;` に置換する（この順で。`&` を先に置換する）。パターン名以外の固定文言には適用不要 |
| 名前に改行・連続する空白を含む | 1 つの半角スペースにまとめる（名前の途中の改行で、箇条書きや見出しの行を偽装されないようにする） |
| 名前が空白だけ | `（名称なし）` と表示する |

> `（収入）` の表示は ADR-0007 で明示されていない。収入パターン（給与など）も判定の対象に含まれるため、「支払い」と取り違えないための最小限の目印として仕様で定めた。

### テストメッセージ（`build_test_message`）

シグネチャ: `build_test_message(now) -> NotificationMessage`

```
【家計簿】テスト通知です（{YYYY-MM-DD HH:MM} JST）
```

`now` は `now_jst()` を渡す。件数・パターン名・金額など、DB の内容は一切含めない。

### 送信（`SlackNotifier`）

#### 抽象

```python
class NotificationError(Exception):
    """送信失敗。メッセージに URL を含めない。"""
    status_code: int | None   # HTTP ステータス。通信できなかった場合は None
    error_type: str           # 原因となった例外の型名（例: "ConnectTimeout"）

class Notifier(ABC):
    def send(self, message: NotificationMessage) -> None: ...  # 失敗時は NotificationError
```

#### 送信リクエスト

- `POST {SLACK_WEBHOOK_URL}`、`Content-Type: application/json`、本文は `{"text": message.text}`
- タイムアウトは **10 秒**（接続・読み取りとも）。リダイレクトは追従しない（`httpx` の既定のまま）
- **HTTP 2xx を成功**とする（Slack は成功時に 200 と本文 `ok` を返す）

#### リトライ（ADR-0007 決定 7）

| 結果 | 扱い |
|---|---|
| 通信エラー（接続断・タイムアウト等、`httpx.TransportError`） | リトライする |
| HTTP 5xx / 429 | リトライする |
| 上記以外の HTTP 4xx、3xx | リトライしない（URL 失効など、再送しても直らないため） |
| 上記以外の例外（`httpx.InvalidURL` 等） | リトライしない。`Exception` を捕捉し、`status_code=None`・型名のみを持つ `NotificationError` に変換する（`httpx` の例外メッセージには URL が含まれうるため、未捕捉のまま呼び出し側へ漏らさない。`KeyboardInterrupt` / `SystemExit` は捕捉しない） |

- **試行は最大 3 回**。待ち時間は 1 回目の失敗後に 1 秒、2 回目の失敗後に 2 秒（計 3 秒）。`Retry-After` は参照しない
- 3 回とも失敗、またはリトライ対象外のエラーで `NotificationError` を送出する
- テストで実際に待たないよう、待機関数（既定 `time.sleep`）とトランスポート（既定 `None`）は `SlackNotifier` のコンストラクタで差し替え可能にする

  ```python
  SlackNotifier(webhook_url, *, transport=None, sleep=time.sleep)
  ```

#### URL を出さない（ADR-0007 決定 6）

Webhook URL は秘密情報として扱う。次をすべて満たすこと。

- `httpx` の例外（`HTTPStatusError` 等）はメッセージに URL を含むため、**送信処理で捕捉し、`NotificationError` に詰め替える。** `NotificationError` が保持・出力するのは**ステータスコードと例外の型名だけ**で、`str()` は `status=500 type=HTTPStatusError`（通信エラーは `status=- type=ConnectTimeout`）の形にする
- **`NotificationError` は `except` ブロックの外で送出する**（ステータスコードと型名を変数に控えてから `except` を抜ける）。`except` の中で送出すると、元の例外が `__context__` に残り、トレースバックに URL が出うるため。`raise ... from None` だけに頼らない
- ログには `logger.exception` や `exc_info=True` を使わない（同上）
- **`httpx` / `httpcore` のロガーを `WARNING` 以上に設定する。** `httpx` は INFO レベルで `HTTP Request: POST <URL> ...` を出力するため、既定のままだと URL がログに残る。**`slack.py` のモジュール読み込み時に設定する**（CLI・`scheduler`・テストのどこから `SlackNotifier` を使っても保護されるようにするため。エントリーポイントごとの設定に頼らない）
- `--dry-run` の出力や、例外・ログのいずれにも URL を含めない
- DB に保存しない

### CLI（`app.notify.run`）

`argparse` のサブコマンド（`daily` / `test`）で実装する。引数が不正な場合は `argparse` の既定どおり終了コード 2。

#### `daily`

```
Settings 読み込み
 ├─ NOTIFY_SHOW_AMOUNT が不正 → ログ「NOTIFY_SHOW_AMOUNT が不正です」、終了コード 1（DB に接続しない。--dry-run も同じ）
 ├─ --dry-run あり → [A]
 └─ なし
     ├─ SLACK_WEBHOOK_URL が空 → ログ「通知は無効です（SLACK_WEBHOOK_URL 未設定）」、終了コード 0（DB に接続しない）
     ├─ URL の検証に失敗（「設定」節）→ ログ「SLACK_WEBHOOK_URL の形式が不正です」、終了コード 1（DB に接続しない）
     └─ 検証に成功 → [B]

[A] dry-run: DB から取得 → 本文を組み立てる → 本文を標準出力へ出す（送信しない）
    0 件のときは「送信対象はありません」を標準出力へ出す。URL が空でも動く。終了コード 0
[B] DB から取得 → 本文を組み立てる
    ├─ None（0 件）→ ログ「送信対象なし」、終了コード 0
    └─ あり → SlackNotifier.send
        ├─ 成功 → ログ「通知を送信しました: due=N unrecorded=M」、終了コード 0
        └─ NotificationError → ログ（ステータスコードと型名のみ）、終了コード 1
```

- DB セッションは `SessionLocal()` で開き、必ず `finally` で閉じる
- 判定は `get_due_and_unrecorded_patterns(db, today_jst())` の 1 回の呼び出しのみ。通知側で判定条件を持たない
- DB 取得・本文の組み立て段階の想定外の例外（DB 接続失敗など）は、ログに型名と詳細を出して終了コード 1。詳細は、DB ドライバのメッセージ（`exc.orig`）の 1 行目を 200 文字までにする（SQLAlchemy の `str(exc)` は SQL 文とバインド値を含むため使わない）。`DATABASE_URL` はログに出さない。送信段階の例外は `SlackNotifier` が `NotificationError` に変換済みのため、ここには URL を含む例外は届かない
- テストしやすいよう、`main()` から次の関数を呼ぶ構造にする（`notifier` は `None` なら送信しない）

  ```python
  def run_daily(db, notifier, *, today, show_amount, dry_run=False, out=sys.stdout) -> int  # 終了コードを返す
  ```

#### `test`

- `build_test_message(now_jst())` を送る。DB には接続しない
- `SLACK_WEBHOOK_URL` が空 → 疎通確認の目的を果たせないため、ログ「SLACK_WEBHOOK_URL が未設定です」を出して**終了コード 1**（`daily` が 0 で終わるのとは異なる）
- URL の検証に失敗 → ログ「SLACK_WEBHOOK_URL の形式が不正です」を出して終了コード 1
- 成功 → 終了コード 0。`NotificationError` → ログを出して終了コード 1

#### 終了コード

| コード | 意味 |
|---|---|
| 0 | 成功、対象 0 件、機能無効（`daily` で URL が空）、`--dry-run` |
| 1 | 送信失敗、設定ミス（URL の検証失敗、`NOTIFY_SHOW_AMOUNT` の不正値、`test` で URL が空）、想定外の例外 |
| 2 | 引数の誤り（`argparse`） |

#### ログ

- 標準ライブラリの `logging`。ロガー名は `app.notify.*`（`-m` で実行すると `__name__` が `__main__` になるため固定する）で、INFO にするのはこの名前空間だけ（root のレベルは変えない）。出力先は標準エラー、書式は `%(asctime)s %(levelname)s %(name)s %(message)s`（`docker compose logs` で読める形）
- 失敗時のログの例: `Slack への通知に失敗しました: status=500 type=HTTPStatusError attempts=3`／通信エラーは `status=- type=ConnectTimeout attempts=3`

### スケジューラ（`app.notify.scheduler`）

`NOTIFY_TIME`（JST）に 1 日 1 回 `daily` を実行し続ける、薄い常駐プロセス。**標準ライブラリのみ**で実装し、cron 系・APScheduler 等の依存は追加しない（ADR-0007 決定 3）。

#### 起動時

1. `NOTIFY_TIME` を `HH:MM`（`00:00`〜`23:59`、ASCII の半角数字のみ）として検証する。不正なら、ログを出して**終了コード 2 で終了**する（`restart` ポリシーにより再起動を繰り返すが、`docker compose logs scheduler` で原因が分かる）
2. 起動した時刻が、今日の `NOTIFY_TIME` を**すでに過ぎている場合は、今日の分は実行済みとして扱う**（追い送信しない。ADR-0007 決定 8・確認済み論点 7）。まだ過ぎていなければ、今日の `NOTIFY_TIME` に実行する
3. 起動ログに実行時刻と次回実行予定を出す（Webhook URL は出さない）

#### ループ

```
実行済みの日付 = 起動時の判定結果（上記 2）

繰り返し:
    now = now_jst()
    target = 今日の NOTIFY_TIME（JST）
    if now >= target かつ 今日は実行済みでない:
        実行済みの日付 = 今日
        if now - target <= 許容遅延: daily を実行
        else: ログ「実行時刻を大きく過ぎたため、今日は送信しない」
    30 秒待つ
```

| 項目 | 仕様 |
|---|---|
| 時刻の判定 | **壁時計（`now_jst()`）で判定する。** コンテナの `TZ` には依存しない。1 回の `time.sleep` で次の実行時刻まで待たず、30 秒ごとに起き直す（ホストのスリープ中は VM の単調時計が進まない場合があり、1 回の長い `sleep` では復帰後に実行時刻がずれうるため） |
| 判定の関数 | 時刻の判定は純粋関数に切り出す: `decide(now, notify_time, last_handled_date, tolerance) -> "run" \| "skip" \| "wait"`。ループ本体は `decide` の結果に従うだけにし、テストで実際に待たずに検証できるようにする |
| 許容遅延 | **10 分**（定数）。スリープ復帰などで実行時刻を過ぎて起きた場合、10 分以内なら実行し、それを超えたら今日は送らない（ADR-0007 の「実行が欠けたら翌日に回収」と同じ扱い） |
| 二重実行の防止 | 実行済みの日付をメモリに持ち、同じ日に 2 回起動しない（ファイル・DB には保存しない） |
| `daily` の呼び出し | **別プロセス**で実行する: `subprocess.run([sys.executable, "-m", "app.notify.run", "daily"], timeout=120)`。実行のたびに新しい DB 接続を作るため、長時間アイドルで切れた接続や DB の再起動の影響を受けない。標準出力・標準エラーは親から継承し、`docker compose logs` にそのまま出る |
| 停止 | コンテナでは PID 1 になり、ハンドラがないと SIGTERM が無視されて `docker compose stop` / `up -d` が 10 秒待たされる。`__main__` 実行時に SIGTERM で終了コード 0 の `SystemExit` を送出するハンドラを入れる（`daily` の実行中に停止した場合は、その実行を中断してよい） |
| 失敗時 | `daily` の終了コードが 0 以外、またはタイムアウトでも、**プロセスは落とさず**、終了コード（タイムアウトはその旨）をログに残して次回を待つ（ADR-0007 決定 7）。ループの 1 反復で想定外の例外が出ても同様に、例外の型名だけをログに残して続ける（メッセージは出さない） |

### Docker Compose（`scheduler` サービス）

`docker-compose.yml` に追加する。backend と同じイメージで、コマンドだけが違う。

```yaml
  scheduler:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+psycopg2://household_user:${DB_PASSWORD}@db:5432/household_db
      SLACK_WEBHOOK_URL: ${SLACK_WEBHOOK_URL:-}
      NOTIFY_TIME: ${NOTIFY_TIME:-22:30}
      NOTIFY_SHOW_AMOUNT: ${NOTIFY_SHOW_AMOUNT-true}
    volumes:
      - ./backend:/app:ro
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    command: python -m app.notify.scheduler
```

- `ports` は持たない（外部に何も公開しない）。`--reload` を使わないため二重起動しない
- **`scheduler` には必要な環境変数だけを渡す。** `SECRET_KEY` / `DEBUG` は通知機能が使わない（`Settings` に既定値がある）ため渡さない。ソースは読み取り専用（`:ro`）でマウントする（`scheduler` はファイルを書かない。`__pycache__` を書けなくても動作に影響しない）
- `backend` にも同じ 3 つの環境変数を渡す（`Settings` が読むため。値には既定を付け、**未設定でも `docker compose up` が失敗しない**ようにする）。書式は `SLACK_WEBHOOK_URL` / `NOTIFY_TIME` が `${VAR:-既定}`（未設定と空のどちらも既定になる）、**`NOTIFY_SHOW_AMOUNT` だけ `${VAR-既定}`**（未設定のときだけ既定になる）。`NOTIFY_SHOW_AMOUNT=` と空で書いた場合に `true` へ読み替えず、不正値として扱う（fail-closed）ため
- `restart: unless-stopped` を付ける。Docker の再起動やプロセス異常終了のあとに自動で復帰させるため（`backend` には付いていないが、通知は放置される常駐プロセスなので必要）
- `volumes` は `./backend:/app` のみ（`data` / `static` は不要）。`scheduler` のコード変更の反映は `docker compose restart scheduler`
- ホストの cron / launchd から `docker compose exec backend python -m app.notify.run daily` を呼ぶ使い方も、同じ CLI で可能（`scheduler` コンテナを増やしたくない場合の代替）

### 依存

`backend/requirements.txt` の `httpx==0.28.1` を、`SlackNotifier` からも使う。**新しい依存は追加しない。** 行には次の旨のコメントを添える（`requirements.txt` は 1 ファイルで本番イメージにも入るため）。

```
httpx==0.28.1  # テスト（TestClient）と通知（Slack 送信）で使用
```

---

## 実装上の注意点

- **JST**: 基準日は必ず `today_jst()`、テストメッセージの時刻は `now_jst()`。`date.today()` / `datetime.now()` は使わない（CLAUDE.md の規約）
- **判定を再実装しない**: 通知側は `get_due_and_unrecorded_patterns` の結果を並べ替えず、そのまま本文にする。ダッシュボードと通知の件数がずれたら、通知側の実装が誤り
- **外部への送信のみ**: 新しいルート・`ports`・Webhook 受信は追加しない。追加が必要になったら ADR-0006 の再検討に該当するため、先に ADR を更新する
- **本文に載せる項目を増やさない**: パターン名・支払日・金額・収入の目印だけ。口座名・カテゴリ階層・メモを載せる変更は ADR-0007 の更新が先
- **送信履歴を作らない**: 手動で `run daily` を打てば再送される（許容）。重複防止が必要になる機能（月次レポート等）の段階で別 ADR とする
- **Slack の `& < >` のエスケープ**: パターン名（利用者が自由に入力する文字列）にだけ適用する。固定文言の `<` 等は存在しない。エスケープにより `<!channel>` などのメンションやリンクの記法は成立しない。`*` `_` `~` `` ` `` は装飾として解釈されうるが、表示が崩れるだけで実害はないため、エスケープしない
- **ログに URL・`DATABASE_URL` を出さない**。`httpx` ロガーの抑制を忘れると、INFO ログに URL が残る
- **`.env` の変更後は `scheduler` を再作成する**: `docker compose up -d scheduler`（`docker compose restart` はコンテナの環境変数を作り直さないため、`.env` の変更が反映されない）。なお、実行時刻を過ぎてから再作成すると、その日は送信されない（起動時の規則）

### 既知の制約（既存の判定ロジックに由来する。本機能では変更しない）

通知はダッシュボードと同じ判定結果を使うため、次の挙動もダッシュボードと一致する。変えるなら判定ロジック側の別 ADR とする。

| 制約 | 内容 |
|---|---|
| 月末の丸め | 支払日が 29〜31 日のパターンは、その月に該当日がないと支払日が月末に丸められる。「今日が支払日」は `payment_day_of_month` と今日の**日の完全一致**で判定するため、丸められた月末日には出ない。さらに「未記録」は「支払日 < 今日」で判定するため、その月は月末日を過ぎると月が替わり対象期間も替わる。結果として、**該当日がない月の分は通知に出ない**場合がある |
| 月替わりで対象期間が替わる | 「未記録」は**今月（年次パターンは支払月）だけ**を対象にする。月が替わると、前月の未記録は通知にも出なくなる（月初に前月分を回収するには、月内に気づく必要がある） |
| 対象外の頻度 | `daily` / `other`、および `payment_day_of_month` 未設定のパターンは判定されない |
| 無効パターン | `is_active=False` のパターンは対象外 |

---

## テスト方針

[test_policy.md](../../test_policy.md) に従い、外部通信は行わず、SQLite in-memory で実行する（`pytest` のみで動く。PostgreSQL・実 Slack は不要）。

### `backend/tests/test_notify_messages.py`（単体。純粋関数）

- `due` のみ / `unrecorded` のみ / 両方の本文が書式どおり（ADR-0007 の例と一致）
- 両方 0 件で `None`
- 件数 0 のセクションが省略される
- `show_amount=False` で金額が載らない（支払日は載る）
- `typical_amount` が `None` / 0 のとき金額が省略される
- 金額が桁区切りになる、支払日が `MM/DD` にゼロ埋めされる
- `is_income=True` で `（収入）` が付く
- 名前の `& < >` がエスケープされる（`&` の二重置換が起きない）
- 口座名・カテゴリ・メモが本文に含まれない（`category_full_path` 等に目印の文字列を入れて検証）
- `build_test_message` が DB の内容を含まない

### `backend/tests/test_notify_slack.py`（単体。`httpx.MockTransport`）

- 200 で成功し、リクエストが `{"text": ...}` の JSON である
- 500 → 500 → 200 で成功する（試行 3 回、待機は 1 秒・2 秒。`sleep` を差し替えて検証）
- 3 回とも 500 で `NotificationError`（`status_code=500`）
- 429 がリトライされる
- 通信エラー（`httpx.ConnectError` / `TimeoutException`）がリトライされ、3 回失敗で `NotificationError`（`status_code=None`、型名を保持）
- 400 / 404 はリトライせず 1 回で `NotificationError`
- `httpx.InvalidURL` など `TransportError` 以外の例外もリトライせず `NotificationError`（`status_code=None`）に変換される。元の例外のメッセージが `NotificationError` に引き継がれない
- **`NotificationError` の `str()`・ログ（`caplog`、レベル DEBUG で取得）・トレースバック（`__context__` を含む）のいずれにも URL が含まれない**（成功・失敗の両方）
- `slack.py` を読み込んだだけで、`httpx` / `httpcore` ロガーのレベルが `WARNING` 以上になっている
- URL の検証: `http://`、別ホスト（`https://example.com/services/...`）、`/services/` 以外のパス、ユーザー情報・ポート付き、空文字を拒否し、正しい形式を受理する。拒否時のエラーに入力値が含まれない

### `backend/tests/test_notify_run.py`（結合。`run_daily` を DB 付きで通す）

- 今日が支払日で未記録のパターン → 送信が 1 回呼ばれ、本文にそのパターン名が入る
- 支払日を過ぎて未記録のパターン → 本文の「支払日を過ぎて未記録」に入る
- 記録済みのパターンは本文に入らない（取引を登録して検証）
- `is_active=False` のパターンは入らない
- 対象 0 件 → 送信されず、終了コード 0
- `--dry-run` → 送信されず、本文が出力され、`SLACK_WEBHOOK_URL` が空でも動く
- Webhook 未設定の `daily` → DB に触れず、送信されず、終了コード 0
- 送信失敗（`NotificationError`）→ 終了コード 1
- `SLACK_WEBHOOK_URL` の検証失敗（別ホスト・`http://`）→ DB に触れず、送信されず、終了コード 1
- `NOTIFY_SHOW_AMOUNT` が不正（空・`flase`・`1`）→ 送信されず、終了コード 1（`--dry-run` も同じ）。`true` / `TRUE` / `false` は受理される
- `test` コマンド → テストメッセージが 1 回送られ、DB に触れない。URL が空なら終了コード 1
- ダッシュボード（`get_due_and_unrecorded_patterns`）と同じ件数・同じ順序で本文になる

### `backend/tests/test_notify_scheduler.py`（単体。`decide` と起動時の判定）

`decide` を純粋関数として、次を検証する（実際に 30 秒待たない）。`subprocess.run` は差し替える。

- 起動時に今日の `NOTIFY_TIME` を過ぎていれば、今日は実行しない（追い送信なし）
- 起動時にまだ過ぎていなければ、`NOTIFY_TIME` に 1 回だけ実行する
- 同じ日に 2 回実行しない
- 許容遅延（10 分）以内の遅れは実行し、超えたら実行しない
- `NOTIFY_TIME` の不正値（`25:00`、`2230`、空）を検出する
- `daily` が失敗（終了コード 1・タイムアウト）してもループが続く

---

## 動作確認チェックリスト

### 設定

- [ ] `.env` に `SLACK_WEBHOOK_URL` を書かなくても `docker compose up -d` が成功する（`backend`・`scheduler` とも起動する）
- [ ] `.env.example` に Webhook の実 URL・URL 形式の文字列が書かれていない
- [ ] `NOTIFY_TIME=25:00` でも backend は起動し、`scheduler` だけがエラーを出して終了する
- [ ] `NOTIFY_SHOW_AMOUNT=false` で本文から金額が消える
- [ ] `NOTIFY_SHOW_AMOUNT=flase`（誤記）でも backend は起動し、`run daily` は送信せずに終了コード 1 になる
- [ ] `SLACK_WEBHOOK_URL=https://example.com/services/x` を指定すると、`run daily` / `run test` は送信せずに終了コード 1 になる（ログに入力した URL が出ない）

### CLI

- [ ] `run daily --dry-run` が本文を標準出力へ出し、Slack には何も送られない
- [ ] `run test` で Slack の指定チャンネルにテストメッセージが届く
- [ ] `run daily` で、本文が ADR-0007 の例と同じ形で Slack に届く
- [ ] 対象が 0 件の日は `run daily` が何も送らず、終了コード 0 で終わる
- [ ] `SLACK_WEBHOOK_URL` が空のとき `run daily` は何もせず終了コード 0、`run test` は終了コード 1
- [ ] 存在しないパスの Webhook URL（`https://hooks.slack.com/services/` 配下で、失効を想定した値）で `run daily` が終了コード 1 になり、リトライせずにエラーログが 1 件出る
- [ ] ネットワークを切った状態で `run daily` が 3 回試行したあと終了コード 1 になる

### 内容

- [ ] 「今日が支払日」の本文に、記録済みのパターンが含まれない
- [ ] 「支払日を過ぎて未記録」が、記録するまで毎日届く。記録した翌日から消える
- [ ] ダッシュボードの「今日の支払いパターン」「今月未記録のパターン」と、通知の件数が一致する
- [ ] 口座名・カテゴリ階層・メモが本文に含まれない

### 秘密情報

- [ ] `docker compose logs scheduler`・`run daily` の出力のどこにも Webhook URL が出ていない（正常時・失敗時とも）
- [ ] DB のダンプ（`/backup`）に Webhook URL が含まれない

### スケジューラ

- [ ] `docker compose ps` で `scheduler` が起動し、`ports` が公開されていない
- [ ] `docker compose exec scheduler env` に `SECRET_KEY` / `DEBUG` が渡っていない。`/app` が読み取り専用でマウントされている
- [ ] 起動ログに実行時刻と次回実行予定が出る
- [ ] `NOTIFY_TIME` を数分先にして起動すると、その時刻に 1 回だけ送信される
- [ ] 実行時刻を過ぎてから `scheduler` を起動すると、その日は送信されない（翌日の実行時刻に送られる）
- [ ] 送信に失敗してもコンテナが落ちず、翌日も実行される
- [ ] Docker を再起動したあと、`scheduler` が自動で復帰する

### 影響範囲

- [ ] `pytest` が通り、`test_pages_smoke.py` の結果が変わらない
- [ ] `pip-audit -r requirements.txt` の結果が変わらない（新規依存なし）
- [ ] 画面・API・DB スキーマ（Alembic）に変更がない
