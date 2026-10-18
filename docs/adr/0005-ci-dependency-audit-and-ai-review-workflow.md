# ADR-0005: CIへの依存脆弱性スキャン導入とAIコードレビュー運用ルール化

## ステータス

採用・実装済み（Accepted / Implemented）— 2026-10-12（ブランチ `chore/ci-audit-and-portfolio-cleanup`）。実装結果は末尾の「実装結果」を参照

---

## コンテキスト

### 背景

[docs/plan_skill-improvement-roadmap.md](../plan_skill-improvement-roadmap.md) は、ITスキル・AIスキル向上のための改修案を5つ挙げ、優先順位付きロードマップとしてまとめている。その **Step 1（最優先）** が「改修案5: AIコードレビューのCI組み込み＋依存脆弱性スキャン」であり、理由は「既存フレームワーク（[docs/plan_ai-spec-driven-development.md](../plan_ai-spec-driven-development.md)）の続きなので着手障壁が最も低く、以降の改修のレビュー品質も底上げされる」ためとされている。

`plan_ai-spec-driven-development.md` はすでに **Phase 2（レビュー自動化）** として以下を予告している。

- `/code-review` スキルを仕様書レビューに活用
- ブランチ命名規約を CLAUDE.md に追記
- 本文書内で定義済みの PR テンプレートを `.github/pull_request_template.md` に正式移行

しかし現状、`.github/workflows/test.yml` は pytest の実行のみで、依存パッケージの脆弱性スキャンは組み込まれていない。また `.github/pull_request_template.md` は存在せず（`find .github -type f` で `workflows/test.yml` のみ確認済み）、PR テンプレートは文書内の記載に留まっている。

### 現状の CI 構成

```yaml
# .github/workflows/test.yml（抜粋）
- name: Install dependencies
  working-directory: backend
  run: pip install -r requirements.txt
- name: Run tests with coverage
  working-directory: backend
  run: pytest --tb=short
```

### 実測: 既存依存関係の脆弱性状況

本 ADR 作成にあたり、`backend/requirements.txt` に対して実際に `pip-audit` を実行し、導入時点でどの程度の既存脆弱性が検出されるかを確認した。

```
$ pip-audit -r backend/requirements.txt
Found 19 known vulnerabilities in 4 packages
Name             Version ID              Fix Versions
---------------- ------- --------------- ------------
python-multipart 0.0.20  PYSEC-2026-1852 0.0.22
python-multipart 0.0.20  PYSEC-2026-3038 0.0.26
python-multipart 0.0.20  PYSEC-2026-3037 0.0.30
python-multipart 0.0.20  PYSEC-2026-3036 0.0.30
python-multipart 0.0.20  PYSEC-2026-3040 0.0.31
python-multipart 0.0.20  PYSEC-2026-3039 0.0.27
jinja2           3.1.4   PYSEC-2026-1471 3.1.6
jinja2           3.1.4   PYSEC-2026-1475 3.1.5
jinja2           3.1.4   PYSEC-2026-1472 3.1.5
pytest           8.3.4   PYSEC-2026-1845 9.0.3
starlette        0.41.3  PYSEC-2026-161  1.0.1
starlette        0.41.3  PYSEC-2026-248  1.3.0
starlette        0.41.3  PYSEC-2026-249  1.3.1
starlette        0.41.3  PYSEC-2026-1942 0.49.1
starlette        0.41.3  PYSEC-2026-1941 0.47.2
starlette        0.41.3  PYSEC-2026-2281 1.1.0
starlette        0.41.3  PYSEC-2026-2280 1.1.0
```

`jinja2`・`python-multipart`・`pytest` は `requirements.txt` に直接ピン留めされており、パッチ済みバージョンへの更新で解消できる（`jinja2>=3.1.6`、`python-multipart>=0.0.31`、`pytest>=9.0.3`）。一方 `starlette` は `requirements.txt` に直接の記載がなく、`fastapi==0.115.5` の間接依存（`fastapi 0.115.5` は `starlette>=0.40.0,<0.42.0` を要求）であるため、`starlette` 単体のバージョンアップでは解消できず、`fastapi` 側の対応バージョン確認が必要になる。

この実測結果は、ロードマップの改修案5にあった **確認事項2「pip-audit で検出された既存の脆弱性への対応方針（即修正 or 別issue化）」** に対して、仮定ではなく実データに基づいて判断するための根拠となる。

### 課題

1. 依存パッケージの脆弱性が機械的に検知されておらず、`requirements.txt` のバージョンが安全かどうかは目視でしか確認できない
2. `docs/plan_ai-spec-driven-development.md` の Phase 2（レビュー自動化）が予告のまま未着手で、PR テンプレートも正式なファイルとして存在しない
3. ロードマップの改修案5には **確認事項1「AIコードレビューをCI上で自動実行するか、それとも人間が `/code-review` を手動起動する運用ルール化に留めるか」** という未決事項が残っている

---

## 決定

### 1. `pip-audit` を CI に追加し、ブロッキングとする

`.github/workflows/test.yml` の `pytest` 実行ステップの前に `pip-audit` ステップを追加し、脆弱性が検出された場合は CI を失敗させる（ロードマップの実装方針どおり）。

```yaml
- name: Install dependencies
  working-directory: backend
  run: pip install -r requirements.txt

- name: Audit dependencies for known vulnerabilities
  working-directory: backend
  run: |
    pip install pip-audit
    pip-audit -r requirements.txt

- name: Run tests with coverage
  working-directory: backend
  run: pytest --tb=short
```

非ブロッキング（warning-only）での導入は代替案として検討したが不採用とした（理由は後述）。

### 2. 導入時点で検出された既存脆弱性は、実装 PR 内で可能な限り解消する

上記の実測結果を踏まえ、以下の方針で対応する。

| パッケージ | 対応 |
|---|---|
| `jinja2` | `3.1.4` → `3.1.6` 以上にバージョン更新（直接ピン留め、解消可能） |
| `python-multipart` | `0.0.20` → `0.0.31` 以上にバージョン更新（直接ピン留め、解消可能） |
| `pytest` | `8.3.4` → `9.0.3` 以上にバージョン更新（直接ピン留め、解消可能。メジャーバージョンアップのため実装 PR でテストスイート全体が問題なく動作することを確認する） |
| `starlette` | `fastapi` の間接依存のため単体更新不可。実装 PR 着手時に `fastapi` の対応バージョンを確認し、`fastapi` ごと更新できるか検証する。既存 API の破壊的変更がなければ更新、影響が大きい場合は `pip-audit --ignore-vuln <ID>` で一時的に許可し、追跡用 issue を作成した上で本 ADR のスコープ外として別対応とする |

これにより CI 導入時点から「脆弱性ゼロ」の状態でブロッキングを開始でき、改修案1（静的解析導入）で採用されている「まず解消してからブロッキングにする」という段階導入の考え方と整合する。

### 3. AIコードレビューの CI 自動実行は見送り、人間による手動起動を運用ルールとして明文化する

ロードマップの確認事項1に対する決定として、**CI 上での AI コードレビュー自動実行は今回は見送る**。

理由:
- Claude Code を CI（GitHub Actions）上で自動実行するには、`ANTHROPIC_API_KEY` 等の認証情報を Secrets に登録し、API 利用コストを管理する仕組みが必要になるが、現時点でこのリポジトリにその基盤がない
- `plan_ai-spec-driven-development.md` の Phase 2 の記載も「`/code-review` スキルを**仕様書レビューに活用**」であり、人間が起動する運用を前提とした書き方になっている（CI ジョブとしての自動実行は明記されていない）
- 個人開発規模のリポジトリでは、PR ごとに自動実行するコスト・実行時間増加に対して得られる効果が見合わない

代わりに、**「PR 作成前に人間が `/code-review` を手動起動する」運用ルールを明文化**する。具体的には CLAUDE.md に運用ルールを追記し、後述の PR テンプレートに実行有無を確認するチェック項目を追加する。CI 上での自動化は、認証・コスト管理の基盤が整った段階で改めて別 ADR として検討する（本 ADR の未決事項として残す）。

### 4. `.github/pull_request_template.md` を新規作成し、PR テンプレートを正式移行する

`docs/plan_ai-spec-driven-development.md` の「PRテンプレート」セクションで既に定義されている内容をベースに、`.github/pull_request_template.md` として正式移行する。加えて、決定3の運用ルールに対応する「`/code-review` 実行済み」のチェック項目を追加する。

```markdown
## 概要
<1〜3行で変更内容>

## 仕様書
docs/plan_<feature-name>.md

## 完了条件チェック
- [ ] <完了条件1>
- [ ] <完了条件2>

## レビュー
- [ ] `/code-review` を実行し、指摘事項に対応済み

## テスト方法
<動作確認手順>
```

### 5. `docs/plan_ai-spec-driven-development.md` の Phase 2 セクションを更新する

Phase 2 に記載されている項目のうち、本 ADR に基づく実装で完了する項目（PR テンプレート移行）と、決定3により CI 自動実行を見送った旨（手動運用ルール化に留めた理由）を追記し、予告のままだった記載を実態に合わせる。

---

## 検討した代替案

### 代替案A: `pip-audit` を非ブロッキング（warning-only）で導入する

- 長所: 既存の脆弱性が残っている状態でも CI が壊れず、導入のハードルが低い
- 短所: 「検出されても誰も見ない」形骸化のリスクが高い。脆弱性スキャンは放置コストが（Lint 指摘等と比べて）大きく、実測の結果すべて直接依存のバージョン更新で解消可能（`starlette` を除く）だったため、非ブロッキングにする理由が薄い
- → **不採用**。決定2のとおり実装 PR 内で解消し、初回からブロッキングで導入する。

### 代替案B: AIコードレビューを `claude-code-action` 等で CI 上に自動組み込みする

- 長所: レビュー自動化の完成度が高く、改修案5の名称（「AIコードレビューのCI組み込み」）に最も忠実
- 短所: `ANTHROPIC_API_KEY` の Secrets 登録・コスト管理・PR ごとの実行時間増加など運用負荷が大きい。個人開発規模のリポジトリでは投資対効果が低く、既存の Phase 2 記載（手動起動前提）とも整合しない
- → **不採用**（決定3）。将来、認証・コスト管理の基盤が整った段階で別 ADR として再検討する。

---

## 変更ファイル一覧（見込み）

| ファイル | 変更内容 |
|---|---|
| `.github/workflows/test.yml` | `pip-audit` ステップを `pytest` の前に追加（ブロッキング） |
| `backend/requirements.txt` | `jinja2`・`python-multipart`・`pytest` をパッチ済みバージョンに更新。`fastapi`（および間接依存の `starlette`）の更新可否を実装 PR 着手時に確認 |
| `.github/pull_request_template.md`（新規） | PR テンプレートを正式移行し、「`/code-review` 実行済み」チェック項目を追加 |
| `docs/plan_ai-spec-driven-development.md` | Phase 2 セクションを更新（PR テンプレート移行の完了、CI 自動レビュー見送りの理由を明記） |
| `CLAUDE.md` | 「PR 作成前に `/code-review` を手動実行する」運用ルールを追記 |

### 仕様書（本 ADR をもとに別途作成）

本 ADR の決定に基づき、`docs/plan_ci-dependency-audit-and-ai-review-workflow.md` として実装仕様書を作成し、`plan_ai-spec-driven-development.md` の開発フロー（仕様書レビュー→AI実装→実装レビュー→commit/PR）に従って実装する。

---

## 影響・注意点

- `pytest` は `8.3.4` → `9.0.3` 以上へのメジャーバージョンアップとなるため、既存テストスイート（14 ファイル）が変更なしで動作するか実装 PR で確認が必要。破壊的変更がある場合は追加の未決事項として扱う
- `fastapi==0.115.5` は `starlette>=0.40.0,<0.42.0` を要求しており、`starlette` のパッチ済みバージョン（`0.47.2` 以上、または `1.x` 系）を単体で導入することはできない。`fastapi` 自体のバージョンアップ（実測時点の最新版は `0.141.1`）が必要になり、これは他の依存（`pydantic`・`starlette` 経由のミドルウェア挙動等）への影響範囲が広いため、本 ADR のスコープでは「解消する」と決め切らず、実装 PR 着手時に別途検証する（→ 検証の結果、更新できた。「実装結果」を参照）
- `pip-audit` は PyPI の OSV データベースに問い合わせるため、CI 実行にはネットワークアクセスが必要（GitHub Actions ランナーは標準で外部アクセス可能なため問題ない）
- 他の依存（`sqlalchemy`・`psycopg2-binary` 等）についても将来的に新規の脆弱性が公表される可能性があるため、本来は PR トリガーだけでなく週次 cron 等の定期実行が望ましい。ただし本 ADR のスコープは「PR 作成時の CI ジョブへの組み込み」に限定し、定期実行の追加は別対応とする
- AI コードレビューの手動運用ルール化（決定3）は強制力を持たない（人間が実行を忘れる可能性がある）。PR テンプレートのチェック項目はあくまで自己申告であり、CI による強制ではない点に留意する

---

## 確認済みの論点

- ロードマップの確認事項2（既存脆弱性への対応方針）について、`pip-audit` を実際に実行し、`jinja2`・`python-multipart`・`pytest` は直接ピン留めのバージョン更新で解消可能、`starlette` は `fastapi` の間接依存のため単体では解消できないことを実測で確認した（詳細は「コンテキスト」参照）。この結果に基づき決定2の対応方針を定めた。

## 未決事項

1. ~~`fastapi` のバージョンアップ可否・互換性検証（`starlette` の脆弱性解消に伴う）は、実装 PR 着手時に別途確認する~~ → 解決済み（2026-10-12）。`fastapi==0.143.0` / `starlette==1.7.0` に更新した。「実装結果」を参照
2. AIコードレビューの CI 自動実行（`claude-code-action` 等）は本 ADR では見送ったが、認証・コスト管理の基盤が整った段階で別 ADR として再検討する

---

## 実装結果（2026-10-12）

| 項目 | 結果 |
|---|---|
| `pip-audit` | `.github/workflows/test.yml` にブロッキングで追加。`pip-audit -r backend/requirements.txt` は **19 件 → 0 件**（`No known vulnerabilities found`）。決定1では「`pytest` の前のステップ」としていたが、**テストとは別ジョブ `audit` にした**（コードレビューでの指摘。ステップ前置きだと、新しい脆弱性が公表された時点で無関係な PR のテスト結果が出なくなり、失敗原因も切り分けにくい） |
| `jinja2` / `python-multipart` / `pytest` | 決定どおり `3.1.6` / `0.0.32` / `9.1.1` に更新。`pytest-asyncio`（`1.4.0`）・`pytest-cov`（`7.1.0`）・`pytest-mock`（`3.16.0`）も `pytest` 9 系に合わせて更新 |
| `starlette`（未決事項1） | `fastapi` を `0.115.5` → `0.143.0` に更新し、`starlette==1.7.0` を `requirements.txt` に明示して解消した。`--ignore-vuln` による一時許可は不要だった |
| `fastapi` 更新の影響 | Starlette 1.x で `TemplateResponse(name, {"request": request, ...})` の旧シグネチャが使えなくなり、ページ系テスト 42 件が失敗した。`TemplateResponse(request, name, context)` に全 23 箇所を移行して 390 件すべて通過 |
| `.github/pull_request_template.md` | 新規作成（「`/code-review` 実行済み」を含む） |
| `CLAUDE.md` / `docs/plan_ai-spec-driven-development.md` | 手動 `/code-review` の運用ルールと Phase 2 の実態を反映 |

### ADR の想定から外れた点

- ADR は「`fastapi` 更新は影響範囲が広く、決め切れない」としていたが、既存テスト 390 件と実機の画面確認（全主要ページの HTTP 200）で、`TemplateResponse` の呼び出し形式の移行だけで済むことを確認できた。この確認を CI に残すため、全ページルートが HTTP 200 を返すことを検証するスモークテスト（`tests/integration/routers/test_pages_smoke.py`）を追加した
- 想定外の追加変更として、CI に PostgreSQL 16 のサービスコンテナを加えた（`TEST_DATABASE_URL` を指定すると同じテストを PostgreSQL で実行する）。SQLite と PostgreSQL の方言差を CI で検出するためで、本 ADR の決定ではなく別の改善項目として実施した。SQLite での実行も CI に残している

### コードレビューを受けた追加対応（2026-10-12）

PR のコードレビューで、CI に加えたテスト基盤について次の問題が指摘され、同じ PR 内で対応した。

| 指摘 | 対応 |
|---|---|
| PostgreSQL では、`create_all` を含む外側トランザクションが未コミットのまま残り、`IntegrityError` 後の `db.rollback()` がテーブルごと巻き戻す（SQLite でも先にコミットしたデータが消える） | `db_engine` で `create_all` 後に `conn.commit()` する。再現テスト（`test_pattern_groups_router.py`）を追加。修正前は PostgreSQL で `UndefinedTable` になることを確認した |
| `TEST_DATABASE_URL` に開発用 DB を指定すると、`drop_all` で実データが消える | アプリの `DATABASE_URL` と同じ DB、または DB 名に `test` を含まない場合は、テスト実行前に `pytest.UsageError` で拒否する |
| `TemplateResponse` の移行が、個別テストの無いルートでは自動検証されない | 全ページルートの HTTP 200 を確認するスモークテストを追加（旧シグネチャに戻すと失敗することを確認した） |
| `pip-audit` がテストと同一ジョブの前段にあり、新しい脆弱性の公表でテスト結果が出なくなる | 別ジョブ `audit` に分離した |

なお、レビューでは次の指摘も挙がった。

- `docker-compose.yml` のポートを `127.0.0.1` に限定する → 対応した（[ADR-0006](0006-no-authentication-for-personal-local-use.md) の決定3）
- PostgreSQL と SQLite のテストを matrix で並列化する → 見送り。実行時間の差が小さく、現状で困らないため
- テスト用ライブラリを `requirements-dev.txt` に分離する → 見送り。本番イメージにテスト用ライブラリが含まれる点は残るが、Dockerfile の変更を伴うため、必要になった時点で別途対応する

