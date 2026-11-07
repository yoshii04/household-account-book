# ADR-0007: 定期支払いの当日・未記録を Slack に通知する（外部への送信のみ）

## ステータス

採用（Accepted）— 2026-11-03（ブランチ `docs/adr-0007-pattern-payment-notification`）。提案時点の未決事項 6 件と追加の確認事項 1 件は確認済み（末尾の「確認済みの論点」を参照）。実装は仕様書の作成後に行う

---

## コンテキスト

### 課題

このアプリの目的の一つは、毎月決まって発生する支払い（家賃・通信費・給与など）を**記録し忘れていないかを確認すること**である（[README](../../README.md) の「解決したいこと」）。現状、その確認は**ダッシュボード（`/`）を開いたときにだけ**行える。

- 「今日の支払いパターン」バナーと「今月未記録のパターン」は、`backend/app/routers/pages.py` の `dashboard()` が `get_due_and_unrecorded_patterns(db, today)`（`backend/app/crud/pattern.py`）を呼んで描画している
- 判定ロジックは [ADR-0001](0001-pattern-payment-status-tracking.md)・[ADR-0002](0002-pattern-recorded-check-group-match.md)・[ADR-0004](0004-dashboard-due-patterns-exclude-recorded.md) で整備済みで、「今日が支払日で未記録」と「支払日を過ぎて未記録」を正しく返す
- しかし**画面を開かない日は、記録漏れに気づけない**。判定ロジックの精度は十分でも、利用者に届く手段が画面しかない

### 検討の経緯

通知機能の全体像は、検討資料 `20261103_notification-feature-proposals.md`（リポジトリ外の個人メモ）で 5 案を比較した。

| 案 | 内容 |
|---|---|
| **1** | **支払いリマインド＆記録漏れアラート（最小構成）** ← 本 ADR の対象 |
| 2 | マルチチャネル通知基盤＋設定画面 |
| 3 | 月次レポートのメール配信（PDF 添付） |
| 4 | 家計アラート（予算超過・残高低下・乖離） |
| 5 | 双方向 Bot（通知から記録・照会） |

案 1 は、既存の判定ロジックをそのまま通知の材料にでき、新規テーブルも新規依存も要らず、アプリの目的（記録漏れ防止）に最も直結する。案 3・4・5 や LINE・メールへの対応は、案 1 で作る土台（Notifier 抽象・CLI・スケジューラ）の上に積めるため、本 ADR の範囲外とする。

### 前提となる制約

| 制約 | 内容 |
|---|---|
| [ADR-0006](0006-no-authentication-for-personal-local-use.md) | 認証なし・ローカル稼働。ポートは `127.0.0.1` のみに公開。インターネットから到達できないことを前提にしている。**外部からの受信（Webhook 等）は前提を崩す**（再検討トリガー）が、**外部への送信は影響しない** |
| 定期実行の仕組みがない | `backend/app/main.py` にスケジューラ・バックグラウンドタスクはない |
| 起動コマンドが `--reload` | `docker-compose.yml` の backend は `uvicorn ... --reload`。アプリ内にスケジューラを置くと、リロードのたびに二重起動しうる |
| 依存の追加コスト | CI の `audit` ジョブ（`pip-audit`）がブロッキング（[ADR-0005](0005-ci-dependency-audit-and-ai-review-workflow.md)）。依存を増やすたびに脆弱性検査の対象が増える |
| `httpx` は導入済み | `backend/requirements.txt` に `httpx==0.28.1` があり、Docker イメージにも入っている（テストの並びに書かれているが、`requirements.txt` は 1 ファイルのため本番イメージにも入る。通知でも使うことを確認済みで、決定 9 で扱いを明記する） |

---

## 決定

### 1. 通知先は Slack Incoming Webhook とし、まず 1 つだけ実装する

「今日が支払日」と「支払日を過ぎて未記録」のパターンを、Slack の Incoming Webhook に投稿する。

- Webhook URL は 1 本で足り、Slack アプリのインストール権限・LINE の友だち登録・メールの送信元認証が要らない
- LINE は [Messaging API の無料枠が月 200 通](https://developers.line.biz/ja/docs/messaging-api/pricing/)（LINE Notify は 2025-03-31 に終了済み）で、初期設定も重い。メールは即時性が低い。いずれも**案 3・4 の段階で別 ADR として判断する**
- 通知先を増やせるよう、送信部分は `Notifier` 抽象（後述）に分けるが、**実装するのは `SlackNotifier` のみ**

### 2. 通知は「外部への送信のみ」とし、受信するエンドポイントを設けない

- 通知のために **新しい `ports` の公開、新しいルート（API・ページ）、Webhook 受信は追加しない**
- したがって [ADR-0006](0006-no-authentication-for-personal-local-use.md) の前提（ローカル稼働・認証なし）は変わらず、同 ADR の再検討トリガーにも該当しない
- 双方向の操作（通知から記録する等。案 5）は、公開 URL が要る LINE では行わない。Slack の Socket Mode で行う場合も、別 ADR とする

### 3. 判定・送信は CLI として作り、定期実行は専用の `scheduler` コンテナで行う

```
python -m app.notify.run daily            # 判定して送る（1回実行して終了）
python -m app.notify.run daily --dry-run  # 送らずに本文を標準出力へ出す
python -m app.notify.run test             # 疎通確認用のテストメッセージを送る
python -m app.notify.scheduler            # 毎日 NOTIFY_TIME に daily を実行し続ける
```

- **判定ロジックは 1 回実行して終わる CLI（`run`）に閉じる。** スケジューラはそれを呼ぶだけの薄い層にする。これにより、実行場所をアプリ内・専用コンテナ・ホストの cron のどれにも載せ替えられる
- 既定は `docker-compose.yml` に **`scheduler` サービスを追加**する。backend と同じイメージ（`build: ./backend`）で、コマンドだけが違う。`ports` は持たない。`--reload` を使わないため二重起動しない
- `scheduler` の実装は標準ライブラリのみ（`datetime` / `time.sleep` で「次の `NOTIFY_TIME`（JST）まで待って `daily` を呼ぶ」ループ）。**cron 系・APScheduler 等の新規依存は追加しない**
- ホストの cron や launchd から `docker compose exec backend python -m app.notify.run daily` を呼ぶ使い方も、同じ CLI で可能（コンテナを増やしたくない場合の代替）

### 4. 通知の内容・頻度・粒度

| 項目 | 決定 |
|---|---|
| 頻度 | **1 日 1 回、1 メッセージ**。既定は **JST 22:30**（`NOTIFY_TIME`）。その日の記録を済ませたあとの「最終確認」として夜に送る |
| 内容 | 2 つのセクションを 1 通にまとめる: 「今日が支払日（で未記録）」と「支払日を過ぎて未記録」。[ADR-0004](0004-dashboard-due-patterns-exclude-recorded.md) のとおり、前者も**記録済みのパターンは含まれない**ため、夜に届く内容は「今日の支払いなのにまだ記録していないもの」になる |
| 送らない条件 | **両方とも 0 件なら何も送らない**（ノイズ防止） |
| データ源 | `get_due_and_unrecorded_patterns(db, today_jst())` をそのまま使う。通知側で判定を再実装しない（ダッシュボードと通知の結果がずれないようにする） |
| 日付 | 基準日は `today_jst()`。`date.today()` は使わない（CLAUDE.md の規約） |
| 本文に載せる情報 | パターン名・支払日・金額（`typical_amount`）。**口座名・カテゴリ階層・メモは載せない** |
| 金額の表示 | **含める**（確認済み）。環境変数 `NOTIFY_SHOW_AMOUNT`（既定 `true`）で、`false` にすればパターン名と支払日のみにできる |
| 宛先 | **Slack の Webhook 1 本（宛先 1 つ）のみ**。複数宛先・宛先管理は扱わない（案 2 の範囲）。個人専用のワークスペースを使う |

本文の例:

```
【家計簿】2026-11-03 の支払いリマインド

■ 今日が支払日（まだ未記録 1件）
• 家賃 — 80,000円

■ 支払日を過ぎて未記録（2件）
• 通信費 — 5,500円（支払日: 11/01）
• 保険料 — 12,000円（支払日: 10/25）
```

「支払日を過ぎて未記録」は、記録するまで**毎日**送られる。これは意図した挙動で、一度見落としても翌日の通知で回収できる（後述の「実行が欠けた場合」の根拠でもある）。

### 5. 設定は `.env`（環境変数）のみとし、DB・画面は追加しない

| 環境変数 | 既定 | 内容 |
|---|---|---|
| `SLACK_WEBHOOK_URL` | 空 | **空なら通知機能は無効**（`daily` は何もせず正常終了する） |
| `NOTIFY_TIME` | `22:30` | 毎日の実行時刻（JST）。`scheduler` が使う |
| `NOTIFY_SHOW_AMOUNT` | `true` | 本文に金額を含めるか |

- `backend/app/config.py` の `Settings` に項目を追加する。`.env.example` には**ダミー値のみ**を書く
- `docker-compose.yml` の `backend` と `scheduler` に環境変数を渡す（`${SLACK_WEBHOOK_URL:-}` の形にして、未設定でも起動できるようにする）
- 通知先・時刻を画面から変える機能、ルール・履歴のテーブルは作らない（案 2 の範囲）

### 6. Webhook URL は秘密情報として扱う

Incoming Webhook の URL は、知っていれば誰でもそのチャンネルに投稿できる**秘密情報**である。

- `.env` にのみ置き、リポジトリにはコミットしない（`.env` は `.gitignore` 対象）
- **ログ・例外メッセージに URL を出さない。** `httpx` の例外（`HTTPStatusError` 等）はメッセージに URL を含むため、送信処理で捕捉し、**ステータスコードと例外の型名だけ**を記録する
- DB には保存しない（保存すると `pg_dump` のバックアップファイルに混ざる）

### 7. 失敗時の扱い

| 場面 | 扱い |
|---|---|
| 送信失敗（ネットワーク断・HTTP 5xx・429） | タイムアウト 10 秒、最大 3 回試行（指数的に待つ）。それでも失敗したらエラーをログに残す |
| 送信失敗（HTTP 4xx。URL 失効など） | リトライしない。エラーをログに残す |
| `run` の終了コード | 成功・対象 0 件・機能無効は 0、送信失敗は 1 |
| `scheduler` | `run` が失敗してもプロセスは落とさず、次回の実行時刻を待つ |
| アプリ本体 | 通知はアプリ（backend）と別プロセスで動くため、通知の失敗が画面・API に影響しない |

### 8. 重複送信の防止は行わない（ログテーブルを作らない）

`notification_logs` のような送信履歴は**作らない**。

- 実行は 1 日 1 回で、`scheduler` は「次の実行時刻まで待つ」方式のため、通常は二重に送らない
- 手動で `run daily` を打てば再送される。これは許容する（確認用途で使うため）
- 「未記録」は毎日再通知される設計なので、**実行が欠けても（例: Mac のスリープ中に時刻を過ぎた）翌日以降に自己回復する**。「今日が支払日」の通知だけは欠けうるが、その日の分も翌日の「未記録」に現れる
- `scheduler` は**追い送信（起動時に、今日の分が未送信なら送る処理）を持たない**。22:30 を過ぎてから起動した日は、翌日の 22:30 まで送らない（確認済み。論点 7）
- 送信履歴や冪等キーが必要になるのは、月次レポート（案 3。月 1 回しか送れない）や随時アラート（案 4）の段階であり、その時点で追加する

### 9. `httpx` は既存の依存をそのまま本番コードでも使う

- `backend/requirements.txt` の `httpx==0.28.1` を、`SlackNotifier` からも使う。**新しい依存は追加しない**（Dependabot による更新の対象は従来どおり）
- `requirements.txt` は 1 ファイルで、本番イメージにも入る。誤解を避けるため、実装時に `httpx` の行へ「テスト（TestClient）と通知（Slack 送信）で使用」という旨のコメントを添える
- 本番用とテスト用の requirements ファイル分割は、本 ADR の範囲外とする

---

## 検討した代替案

### 代替案A: アプリ内にスケジューラを置く（APScheduler 等を FastAPI の lifespan で起動）

- 長所: コンテナが増えない
- 短所: 現行の `uvicorn --reload` ではリロードのたびに二重起動し、通知が重複する。ワーカーを増やしても同様。新規依存（APScheduler）が増え、`pip-audit` の対象も増える
- → **見送り**

### 代替案B: ホストの cron / launchd のみで動かす

- 長所: 追加コンテナなし。最も単純
- 短所: 環境依存（macOS の launchd と Linux の cron で設定が異なる）。リポジトリで設定を再現・共有できない。Mac のスリープ中は動かない（コンテナでも Docker Desktop が止まれば同じ）
- → **既定としては見送り**。ただし CLI を共通にしているため、利用者の判断で代替として使える（決定 3）

### 代替案C: 最初から LINE またはメールにも対応する

- 短所: LINE は Messaging API のチャネル作成・友だち追加・userId 取得が必要で、無料枠は月 200 通。メールは SMTP の認証情報管理が要る。最初から 3 チャネルにすると実装・設定・テストの範囲が大きく、案 1 の「小さく始める」利点が消える
- → **見送り**。`Notifier` 抽象は切ってあるため、必要になった時点で `LineNotifier` / `EmailNotifier` を追加する（別 ADR）

### 代替案D: 案 2（通知基盤＋設定画面）を最初から作る

- 短所: 新規テーブル 3 つ・画面・API が必要で、個人用の 1 世帯アプリには過剰。通知を実際に使う前に設定機能を作ることになる
- → **見送り**。案 1 を使って通知の量・時刻・文面が固まってから、必要なら検討する

### 代替案E: Slack の Bot トークン（`chat.postMessage`）を使う

- 長所: チャンネルを呼び出しごとに指定でき、将来の双方向化（案 5）と同じ認証を使える
- 短所: Slack アプリの OAuth スコープ設定とトークン管理が要る。単に 1 チャンネルへ投稿するだけなら Webhook の方が単純
- → **見送り**。案 5 に進む場合に改めて判断する

### 代替案F: `notification_logs` で送信済みを管理する

- 長所: 二重送信を確実に防げる。送信履歴が残る
- 短所: テーブル追加と Alembic マイグレーションが必要。1 日 1 回・未記録は毎日再通知という設計では、得られる効果が小さい
- → **見送り**（決定 8）

---

## 変更ファイル一覧（見込み）

### 新規

| ファイル | 内容 |
|---|---|
| `backend/app/notify/__init__.py` | パッケージ |
| `backend/app/notify/base.py` | `NotificationMessage`、`Notifier` 抽象（`send(message) -> None`） |
| `backend/app/notify/slack.py` | `SlackNotifier`（`httpx`、リトライ、URL を出さないエラー処理） |
| `backend/app/notify/messages.py` | `build_daily_message(due, unrecorded, show_amount) -> NotificationMessage \| None`（純粋関数。Slack の `& < >` のエスケープを含む） |
| `backend/app/notify/run.py` | CLI（`daily` / `daily --dry-run` / `test`）。DB セッションの取得と判定の呼び出し |
| `backend/app/notify/scheduler.py` | 次の `NOTIFY_TIME`（JST）まで待って `run daily` を呼ぶループ |
| `backend/tests/test_notify_messages.py` | 文面・0 件なら送らない・金額の有無・エスケープ |
| `backend/tests/test_notify_slack.py` | `httpx.MockTransport` で成功・リトライ・4xx・URL 非出力を検証 |
| `backend/tests/test_notify_run.py` | SQLite の in-memory DB で `daily` を通しで検証（Webhook 未設定なら何もしない） |
| `docs/specs/auxiliary/spec_notifications.md` | 機能仕様書（本 ADR をもとに別途作成） |

### 変更

| ファイル | 内容 |
|---|---|
| `backend/app/config.py` | `slack_webhook_url` / `notify_time` / `notify_show_amount` を追加 |
| `docker-compose.yml` | `scheduler` サービス追加。`backend` / `scheduler` に環境変数を渡す |
| `.env.example` | 新規 3 項目（ダミー値） |
| `docs/specs/index.md` | 「C-7 通知」を補助機能に追加 |
| `CLAUDE.md` | ディレクトリ構造・環境変数・よく使うコマンドに通知を追記 |
| `DESIGN.md` | 通知の構成とデータフローを追記 |
| `README.md` | ADR 一覧に 0007 を追加。機能表に通知を追記 |

### 変更しないもの

- 既存の `crud/pattern.py` の判定ロジック（通知側はそのまま呼ぶだけ）
- DB スキーマ・Alembic マイグレーション
- `backend/requirements.txt` の依存の追加・バージョン変更（決定 9 のとおり `httpx` は既存の行をそのまま使い、コメントを添えるのみ）
- API・画面（ルートを追加しないため、全ページルートの HTTP 200 を見るスモークテストにも影響しない）
- [ADR-0006](0006-no-authentication-for-personal-local-use.md)（前提を変えない）

### 進め方

CLAUDE.md の運用（ADR → 仕様書 → 実装 → `/code-review`）に従い、次の順で別コミット・別 PR とする。

1. 本 ADR（`docs: ADR-0007 ...`）
2. 仕様書（`docs/specs/auxiliary/spec_notifications.md`）
3. 実装とテスト、関連ドキュメントの更新

---

## 影響・注意点

- **外部サービスにデータが出る。** パターン名と金額が Slack のサーバーに残る。Slack に投稿した内容は、投稿先ワークスペースの管理者の閲覧・保持設定の対象になり、後から削除しても保持・検索される場合がある。宛先は**個人専用のワークスペース（用意済み）**とし、家族や第三者を招待しないこと。金額が不要になったら `NOTIFY_SHOW_AMOUNT=false` にする
- **22:30 に Mac が起きていて Docker が動いていなければ、その日の通知は送られない。** これは許容する（確認済み）。取り戻すための再送（起動後の追い送信）や、常時稼働の環境への移行は行わない。欠けた分は翌日の同時刻に「未記録」として再通知される（決定 8）
- **口座名・カテゴリ・メモは載せない。** 取引の中身が外に出ないようにするための線引きで、載せる項目を増やすときは本 ADR を更新する
- **`scheduler` も `.env` のシークレットを持つ。** `backend` と同じ `.env` から渡すため、追加の管理対象はない
- **Slack のレート制限は問題にならない。** 1 日 1 通で、チャンネルあたり毎秒 1 件程度という制限（[Slack のレート制限](https://docs.slack.dev/apis/web-api/rate-limits)）には遠く及ばない
- **将来 `ports` を公開する場合（ADR-0006 の再検討）も、通知は影響を受けない。** 通知は送信のみのため、認証の導入有無と独立している
- **`SECRET_KEY` と `DEBUG` は引き続き動作に影響しない**（通知機能でも使わない）

---

## 確認済みの論点

提案時点の未決事項と、その後に出た確認事項は、2026-11-03 に次のとおり確認した。すべて解決済みで、残る確認事項はない。

| # | 論点 | 結論 | 反映箇所 |
|---|---|---|---|
| 1 | Slack の宛先（個人専用のワークスペースを用意できるか） | 個人用のワークスペースを用意済み | 決定 4（宛先）、影響・注意点 |
| 2 | 本文に金額を含めるか | 含める（`NOTIFY_SHOW_AMOUNT=true` を既定とする） | 決定 4、5 |
| 3 | 実行時刻 | **JST 22:30**（1 日 1 回のまま。朝・夕に分ける運用にはしない） | 決定 4、5、影響・注意点 |
| 4 | スケジューラの置き場所 | 専用コンテナ（`scheduler`） | 決定 3 |
| 5 | 家族への共有（宛先の数） | 宛先は 1 つのみ。宛先管理は作らない | 決定 4（宛先） |
| 6 | `httpx` を本番側の依存として扱ってよいか | 扱ってよい | 決定 9 |
| 7 | 22:30 に Mac・Docker が動いていない日の扱い | **その日は送られなくてよい。翌日に回収する**（追い送信はしない） | 決定 8、影響・注意点 |
