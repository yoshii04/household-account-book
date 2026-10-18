# 仕様：C-5 バックアップ・リストア

## 概要

PostgreSQL データベースの内容をダンプファイルとしてダウンロードし、以前のダンプファイルからデータを復元する機能。
`pg_dump` / `psql` コマンドをサーバーサイドで実行することで、全テーブルを対象にしたバックアップ・リストアを実現する。
リストアは `--single-transaction` オプションにより、エラー発生時でも安全にロールバックされる。

---

## 対象画面・エンドポイント

| 種別 | パス | 説明 |
|------|------|------|
| 画面 | `/backup` | バックアップ・リストア画面（HTML） |
| API | `POST /api/v1/backup/dump` | DB ダンプを生成してダウンロード |
| API | `POST /api/v1/backup/restore` | アップロードした SQL ファイルを DB へ復元 |

---

## 対象ファイル

- `backend/app/routers/backup.py` — ルーター（`/backup` 画面 + `/api/v1/backup/*` API）
- `backend/app/services/backup_service.py` — `pg_dump` / `psql` 実行ロジック（`create_dump_to_tempfile` / `restore_from_file`）
- `backend/app/templates/backup/index.html` — バックアップ・リストア画面テンプレート

---

## データモデル

バックアップ・リストアはデータベース全体を対象とするため、特定のテーブルは持たない。
`pg_dump` が生成する SQL ファイルにはすべてのテーブル・データが含まれる。

---

## 機能仕様

### バックアップ（POST /api/v1/backup/dump）

- `backup_service.create_dump_to_tempfile()` を呼び出して一時ファイルにダンプを生成する
- `settings.database_url` を `urlparse` でパースし、`-h`・`-p`・`-U`・`-d` の DB 接続情報を取得する
- パスワードは `PGPASSWORD` 環境変数経由で `pg_dump` に渡す（コマンドライン引数には含めない）
- 一時ファイルのパスは `tempfile.gettempdir()` + `uuid.uuid4().hex` で衝突しないユニークな値を生成する
- `pg_dump` オプション:
  - `--clean` — DROP 文を含めて既存オブジェクトをクリーンアップ
  - `--if-exists` — DROP 時に対象が存在しない場合でもエラーにしない
  - `-f <tmp_path>` — 一時ファイルへ出力
  - タイムアウト: **120 秒**
- ダンプ成功後、`FileResponse` でクライアントへファイルを送信する
- `background_tasks.add_task(os.unlink, tmp_path)` により、レスポンス送信後に一時ファイルを自動削除する
- ダウンロードファイル名: `backup_{YYYYMMDD_HHMMSS}.sql`（例: `backup_20240101_123456.sql`）
  - タイムスタンプは `now_jst().strftime("%Y%m%d_%H%M%S")` で生成する
  - Content-Type: `application/octet-stream`
- `pg_dump` の終了コードが 0 以外の場合は、一時ファイルを削除してから `RuntimeError` を raise する
  - エラーメッセージは `result.stderr.strip()` を使用し、空の場合はデフォルトメッセージを返す

### リストア（POST /api/v1/backup/restore）

- リクエストは `UploadFile = File(...)` のマルチパートアップロードで受け取る
- バリデーション: ファイル名が `.sql` で終わっていない場合は HTTP 400 を返す
- アップロードされたファイルの内容を `tempfile.gettempdir()` + `uuid.uuid4().hex` のパスに一時ファイルとして書き込む
- `backup_service.restore_from_file(tmp_path)` を呼び出して `psql` を実行する
- `psql` オプション:
  - `--single-transaction` — 全操作を単一トランザクションで実行し、エラー発生時はロールバックする
  - `-f <filepath>` — 復元するダンプファイルを指定
  - タイムアウト: **300 秒**
- 一時ファイルは `finally` ブロックで削除する（成功・失敗に関わらず必ず削除）
- `psql` の終了コードが 0 以外の場合は `RuntimeError` を raise し、HTTP 500 を返す
- 成功時のレスポンス: `{"message": "復元が完了しました"}`

---

## 実装上の注意点

- **JST タイムゾーン**: バックアップファイル名のタイムスタンプ生成には `date.today()` や `datetime.now()` を使わず、`jst.py` の `now_jst()` を使うこと。
  ```python
  from app.jst import now_jst
  filename = f"backup_{now_jst().strftime('%Y%m%d_%H%M%S')}.sql"
  ```
- **リストアのアトミック性**: `psql` は `--single-transaction` オプションで実行されるため、SQL ファイルの途中でエラーが発生した場合はすべての変更がロールバックされる。ただし `pg_dump --clean` で生成した SQL には DROP 文が含まれるため、リストア中はデータが一時的に失われる可能性がある点に注意する。
- **パスワードの扱い**: DB パスワードはコマンドライン引数ではなく `PGPASSWORD` 環境変数で渡すこと（プロセスリストへの露出を防ぐため）。
- **一時ファイルの命名**: 同時リクエストでファイルが衝突しないよう、`uuid.uuid4().hex` でユニークなパスを生成すること。
- **バックアップは画面経由でのみ提供**: `GET` ではなく `POST` エンドポイントとして定義されており、`pg_dump` 自体がサーバー内でファイルを生成してから `FileResponse` で返す。`UploadFile` は使用しない。

---

## 動作確認チェックリスト

- [ ] `/backup` 画面が正常に表示される
- [ ] 「バックアップをダウンロード」ボタン押下で `backup_YYYYMMDD_HHMMSS.sql` がダウンロードされる
- [ ] ダウンロードされたファイル名のタイムスタンプが JST 時刻で正しい
- [ ] ダウンロードした SQL ファイルの内容に全テーブルのデータが含まれている
- [ ] `.sql` 以外のファイルをリストアしようとすると HTTP 400 が返る
- [ ] 有効な `.sql` ファイルをアップロードすると `{"message": "復元が完了しました"}` が返る
- [ ] リストア後、DB の内容がバックアップ時点に戻っていることを確認できる
- [ ] 不正な SQL ファイル（構文エラー等）をリストアした場合に HTTP 500 が返り、DB はロールバックされている
- [ ] サーバー上に一時ファイルが残留していない（バックアップ・リストアともに削除されている）
- [ ] `pg_dump` のタイムアウト（120 秒）・`psql` のタイムアウト（300 秒）が設定されている
