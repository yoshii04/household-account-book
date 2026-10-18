# 家計簿アプリ

家計簿ソフトのエクスポート（`Actual.TXT`）を取り込み、費目別・口座別に集計して見るための、個人用の Web アプリです。Docker Compose（PostgreSQL + FastAPI）で動作します。

[![Test](https://github.com/yoshii04/household-account-book/actions/workflows/test.yml/badge.svg)](https://github.com/yoshii04/household-account-book/actions/workflows/test.yml)

> 業務外の個人開発 3 本の一つです。**この README は、仕様駆動の進め方（ADR → 仕様書 → 実装 → レビュー）の実例**として読めます。3 本を並べた紹介と、設計判断・AI の使い方は [baseball-stats-app の docs/portfolio](https://github.com/yoshii04/baseball-stats-app/tree/main/docs/portfolio) にあります。

## 解決したいこと

- 取引データが家計簿ソフトの中にしかなく、**費目×口座×グループ（人別・目的別）での集計や前年同月比**が見づらい
- 毎月決まって発生する支払い（家賃・通信費・給与など）を**記録し忘れていないか**を、画面で確認したい
- ローン返済の見通しや、前月末のレポートを、同じ画面から出したい

## 画面

> スクリーンショットは合成データ（架空の口座・取引）です。

| ダッシュボード | 月次集計 |
|---|---|
| ![ダッシュボード](docs/images/dashboard.png) | ![月次集計](docs/images/report-monthly.png) |
| **取引一覧** | **定期取引パターン管理** |
| ![取引一覧](docs/images/transactions.png) | ![パターン管理](docs/images/patterns.png) |

## 機能

| 区分 | 内容 |
|---|---|
| データ取込 | `Actual.TXT`（UTF-16LE・タブ区切り）の取り込み。カテゴリ階層・口座・グループは自動登録。資金移動の対向取引を自動生成 |
| 取引管理 | 入力（親カテゴリ選択 → 直近10件を表示 → ワンクリックで転記）、検索、編集、削除、コピー |
| 定期取引パターン | 毎月・毎年の支払いをパターン化。ダッシュボードで「今日の支払い」と「未記録」を表示 |
| レポート | 月次集計、前年同月比、カテゴリ×グループのマトリックス、年次・年度別トレンド、口座別・口座分類別の集計、口座残高 |
| 出力 | Excel / `Actual.TXT` エクスポート、前月末レポートの PDF |
| ローン | 元利均等返済のシミュレーションと、返済取引の一括登録 |
| バックアップ | `pg_dump` によるダンプのダウンロードと、SQL ファイルからの復元 |

機能ごとの詳細は[機能仕様書の索引](docs/specs/index.md)を参照してください。

## アーキテクチャ

```mermaid
flowchart LR
    Browser["ブラウザ<br/>Jinja2 / Alpine.js / Chart.js"]

    subgraph Backend["backend コンテナ（FastAPI）"]
        Routers["routers<br/>API + ページ"]
        Services["services<br/>集計・取込・ローン・PDF・バックアップ"]
        Crud["crud<br/>取引・パターン"]
        Models["models<br/>SQLAlchemy 2.0"]
        Routers --> Services
        Routers --> Crud
        Services --> Models
        Crud --> Models
    end

    DB[("db コンテナ<br/>PostgreSQL 16")]
    Alembic["Alembic<br/>マイグレーション"]

    Browser -- "HTTP :8080" --> Routers
    Models --> DB
    Services -- "pg_dump / psql" --> DB
    Alembic --> DB
```

| レイヤー | 技術 |
|---|---|
| Backend | Python 3.12 / FastAPI / SQLAlchemy 2.0 / Alembic / Pydantic 2 |
| Database | PostgreSQL 16 |
| Frontend | Jinja2 テンプレート（サーバーサイドレンダリング）/ Alpine.js / Chart.js（CDN） |
| 出力 | openpyxl（Excel）/ reportlab（PDF） |
| インフラ | Docker Compose |
| テスト・CI | pytest / GitHub Actions（`pip-audit`、PostgreSQL 16 でのテスト） |

詳細は[設計書（DESIGN.md）](DESIGN.md)を参照してください。

## 起動手順

### 1. 環境変数の設定

```bash
cp .env.example .env
# .env を編集して DB_PASSWORD を設定する
```

### 2. 起動とマイグレーション

```bash
docker compose up -d
docker compose exec backend alembic upgrade head
```

### 3. アクセス

| 用途 | URL |
|---|---|
| アプリ | http://localhost:8080 |
| API ドキュメント（Swagger UI） | http://localhost:8080/docs |
| DB（ホスト側） | `localhost:5439`（ユーザー `household_user`、DB `household_db`） |

> ホスト側のポート（8080 / 5439）は、他のアプリとの競合を避けるため一般的な値からずらしています。どちらも `127.0.0.1` にのみ公開しているため、同じネットワーク上の他の端末（スマートフォンなど）からはアクセスできません。

### 4. データの取り込み

1. http://localhost:8080/import を開く
2. `Actual.TXT` をアップロードする
3. 取り込み結果とスキップされた行を確認する

`Actual.TXT` と `data/*.csv` は実データのため `.gitignore` の対象です。リポジトリにはコミットしないでください。

## 開発

```bash
docker compose logs -f backend            # ログ確認
docker compose exec backend bash          # コンテナに入る

# マイグレーションの追加
docker compose exec backend alembic revision --autogenerate -m "説明"
docker compose exec backend alembic upgrade head
```

### テスト

```bash
cd backend
pip install -r requirements.txt
pytest                                    # 既定は SQLite in-memory（PostgreSQL 不要）

# PostgreSQL で実行する（CI と同じ。専用の DB を用意すること。テーブルを作成・削除します）
TEST_DATABASE_URL=postgresql://test:test@localhost:5432/test pytest

pip install pip-audit && pip-audit -r requirements.txt   # 依存の脆弱性検査（CI と同じ）
```

テストは単体テストと、`TestClient` を使った API・画面の結合テストで構成されます。方針は[テスト方針](docs/test_policy.md)にまとめています。

### 開発の進め方

変更は **ADR（なぜ変えるか）→ 仕様書（何を変えるか）→ 実装 → `/code-review`** の順で進めています。判断の経緯は ADR で追えます。

## ドキュメント

| 文書 | 内容 |
|---|---|
| [機能仕様書の索引](docs/specs/index.md) | 画面・API ごとの仕様（コア機能 / レポート / 補助機能） |
| [DESIGN.md](DESIGN.md) | システム構成、各層の設計、データフロー、API 一覧 |
| [CLAUDE.md](CLAUDE.md) | データモデル、主要 API、実装上の注意点（開発者・AI 向け） |
| [テスト方針](docs/test_policy.md) | テストの種類と書き方の方針 |
| [AI 仕様駆動開発の計画書](docs/plan_ai-spec-driven-development.md) | ADR・仕様書・実装・レビューの開発フロー |
| [設計判断と AI の使い方](https://github.com/yoshii04/baseball-stats-app/blob/main/docs/portfolio/design-decisions-and-ai.md) | AI と人の役割分担と進め方（3 本共通） |

### ADR（設計判断の記録）

| ADR | 内容 | 状態 |
|---|---|---|
| [0001](docs/adr/0001-pattern-payment-status-tracking.md) | パターン管理に当月の支払い状況チェックを追加する | 実装済み |
| [0002](docs/adr/0002-pattern-recorded-check-group-match.md) | 記録済み判定にグループ一致の条件を加える | 実装済み |
| [0003](docs/adr/0003-transactions-list-default-include-transfer.md) | 取引一覧の既定表示に資金移動を含める | 実装済み |
| [0004](docs/adr/0004-dashboard-due-patterns-exclude-recorded.md) | ダッシュボードの支払いバナーから記録済みを除く | 実装済み |
| [0005](docs/adr/0005-ci-dependency-audit-and-ai-review-workflow.md) | CI に依存脆弱性スキャンを入れ、AI レビューを手動運用にする | 実装済み |
| [0006](docs/adr/0006-no-authentication-for-personal-local-use.md) | 認証を導入せず、個人利用・ローカル稼働を前提とする | 採用 |

## 注意事項

- **認証機能はありません。** 個人利用・ローカル稼働を前提にしています（[ADR-0006](docs/adr/0006-no-authentication-for-personal-local-use.md)）。`docker-compose.yml` はポートを `127.0.0.1` に限定しているため、アクセスできるのは起動したマシンだけです。この制限を外す（`ports` からアドレス指定を取り除く）と、同じネットワーク上の誰でもアプリと DB に到達でき、バックアップの復元機能は、到達できる人に DB への任意の SQL 実行を許します
- インターネットや共有ネットワークに公開する場合は、先に ADR-0006 の「認証を導入する場合の変更点」を確認してください

## ディレクトリ構造

```
household-account-book/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/            # DB マイグレーション
│   ├── tests/              # 単体・結合テスト
│   └── app/
│       ├── main.py
│       ├── models/         # SQLAlchemy モデル
│       ├── schemas/        # Pydantic スキーマ
│       ├── crud/           # DB 操作
│       ├── services/       # ビジネスロジック
│       ├── routers/        # API ルーター + ページルーター
│       └── templates/      # Jinja2 HTML テンプレート
├── frontend/static/css/    # スタイルシート
├── db/init.sql             # DB 初期設定
├── data/                   # インポートファイル置き場（実データはコミットしない）
├── docs/
│   ├── adr/                # 設計判断の記録
│   ├── specs/              # 機能仕様書
│   └── images/             # README 用スクリーンショット
└── .github/                # CI ワークフロー、PR テンプレート
```

## ライセンス

ポートフォリオとして**閲覧のみ**を目的に公開しています。利用・複製・改変・再配布は許諾していません。詳細は [LICENSE](LICENSE) を参照してください。
