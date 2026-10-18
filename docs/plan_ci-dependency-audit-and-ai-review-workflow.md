# 計画：CI依存脆弱性スキャン導入とAIコードレビュー運用ルール化

## 概要

`.github/workflows/test.yml` に `pip-audit` を追加し、依存パッケージの既知脆弱性を機械的に検知・ブロッキングする。
あわせて、導入時点で検出された既存脆弱性を実装 PR 内で解消し、`.github/pull_request_template.md` を正式ファイルとして新規作成する。
AIコードレビューは CI 上での自動実行を見送り、「PR 作成前に人間が `/code-review` を手動起動する」運用ルールとして CLAUDE.md に明文化する。
本仕様書は [ADR-0005](adr/0005-ci-dependency-audit-and-ai-review-workflow.md) の決定に基づく実装仕様書であり、
[docs/plan_ai-spec-driven-development.md](plan_ai-spec-driven-development.md) の開発フローに従って実装する。

---

## 現状の問題点

| 問題 | 詳細 |
|------|------|
| 依存脆弱性が機械的に検知されていない | `.github/workflows/test.yml` は pytest の実行のみで、脆弱性スキャンが組み込まれていない |
| 実測で既存脆弱性が存在することを確認済み | `pip-audit -r backend/requirements.txt` で 4 パッケージ・19 件の既知脆弱性を検出（`jinja2`, `python-multipart`, `pytest`, `starlette`） |
| PR テンプレートが正式ファイルとして存在しない | `docs/plan_ai-spec-driven-development.md` 内で定義済みだが `.github/pull_request_template.md` は未作成（Phase 2 が予告のまま未着手） |

---

## 要件

### CI 依存脆弱性スキャン

- `.github/workflows/test.yml` に `pip-audit` を追加すること。当初は `pip install -r requirements.txt` の後・`pytest` 実行の前のステップとしていたが、実装では**テストとは別ジョブ（`audit`）**とした（新しい脆弱性が公表されてもテスト結果が出るようにし、失敗原因を切り分けやすくするため。[ADR-0005](adr/0005-ci-dependency-audit-and-ai-review-workflow.md) の「実装結果」を参照）
- `pip-audit` で既知脆弱性が検出された場合、CI ジョブを失敗させること（非ブロッキングにはしない）
- 導入時点で機械的に解消可能な既存脆弱性はすべて解消し、「脆弱性ゼロ」の状態でブロッキング運用を開始できること

### 既存依存パッケージの脆弱性解消

- `jinja2` を `3.1.6` 以上に更新すること
- `python-multipart` を `0.0.31` 以上に更新すること
- `pytest` を `9.0.3` 以上に更新すること（メジャーバージョンアップのため、既存テストスイート全ファイルが変更なしで通過することを確認すること）
- `starlette`（`fastapi` の間接依存）は、`fastapi` の対応バージョンを確認し、破壊的変更がなければ `fastapi` ごと更新すること。影響が大きく本仕様書のスコープで解消しきれない場合は `pip-audit --ignore-vuln <ID>` で一時的に許可し、追跡用 issue を作成した上で別対応とすること

### PR テンプレートの正式移行

- `.github/pull_request_template.md` を新規作成すること
- `docs/plan_ai-spec-driven-development.md` 内ですでに定義されているテンプレート内容をベースにすること
- 「`/code-review` を実行し、指摘事項に対応済み」のチェック項目を追加すること

### AIコードレビュー運用ルールの明文化

- CI（GitHub Actions）上での AI コードレビュー自動実行は今回のスコープでは行わないこと
- CLAUDE.md に「PR 作成前に `/code-review` を手動起動する」運用ルールを追記すること

### 計画書（Phase 2）の実態反映

- `docs/plan_ai-spec-driven-development.md` の Phase 2 セクションを更新し、以下を反映すること
  - PR テンプレートの `.github/pull_request_template.md` への正式移行が完了したこと
  - AI コードレビューの CI 自動実行は見送り、手動運用ルール化に留めた理由

---

## 実装方針

### 対象ファイルと変更内容

| ファイル | 変更種別 | 概要 |
|---------|---------|------|
| `.github/workflows/test.yml` | 変更 | `pip-audit` を別ジョブ `audit` として追加（ブロッキング） |
| `backend/requirements.txt` | 変更 | `jinja2`・`python-multipart`・`pytest` をパッチ済みバージョンに更新。`fastapi` を `0.143.0`、`starlette` を `1.7.0` に更新（2026-10-12 実施） |
| `.github/pull_request_template.md`（新規） | 追加 | PR テンプレートを正式移行し、「`/code-review` 実行済み」チェック項目を追加 |
| `docs/plan_ai-spec-driven-development.md` | 変更 | Phase 2 セクションを更新（PR テンプレート移行の完了、CI 自動レビュー見送りの理由を明記） |
| `CLAUDE.md` | 変更 | 「PR 作成前に `/code-review` を手動実行する」運用ルールを追記 |

### コード例

`.github/workflows/test.yml`（抜粋・追加ジョブ）:

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Audit dependencies for known vulnerabilities
        run: |
          pip install pip-audit
          pip-audit -r backend/requirements.txt
```

`.github/pull_request_template.md`（新規）:

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

---

## 実装上の注意点

- `pytest` は `8.3.4` → `9.0.3` 以上へのメジャーバージョンアップとなるため、既存テストスイート（14 ファイル）が変更なしで動作するか実装時に確認すること。破壊的変更がある場合は追加の未決事項として扱う
- `fastapi==0.115.5` は `starlette>=0.40.0,<0.42.0` を要求しており、`starlette` のパッチ済みバージョンを単体で導入することはできない。そのため `fastapi` ごと更新する必要があった。**2026-10-12 に `fastapi==0.143.0` / `starlette==1.7.0` へ更新し、`pip-audit` は 0 件になった**（`--ignore-vuln` は不要）。更新に伴い、Starlette 1.x で廃止された `TemplateResponse(name, {"request": ...})` の旧シグネチャを `TemplateResponse(request, name, context)` に移行している。詳細は ADR-0005「実装結果」を参照
- `pip-audit` は PyPI の OSV データベースに問い合わせるため CI 実行にはネットワークアクセスが必要（GitHub Actions ランナーは標準で外部アクセス可能なため問題ない）
- `sqlalchemy`・`psycopg2-binary` 等、他の依存についても将来的に新規の脆弱性が公表される可能性があるが、本仕様書のスコープは「PR 作成時の CI ジョブへの組み込み」に限定し、週次 cron 等の定期実行の追加は別対応とすること
- AI コードレビューの手動運用ルール化は強制力を持たない（人間が実行を忘れる可能性がある）。PR テンプレートのチェック項目はあくまで自己申告であり、CI による強制ではない点に留意すること
- CLAUDE.md の関連ルールを参照すること

---

## 確認事項（未決事項）

1. ~~`fastapi` のバージョンアップ可否・互換性検証~~ → 2026-10-12 解決済み。`fastapi==0.143.0` / `starlette==1.7.0` に更新（`TemplateResponse` の呼び出し形式を移行）。詳細は ADR-0005「実装結果」を参照
2. AIコードレビューの CI 自動実行（`claude-code-action` 等）は本仕様書のスコープでは見送るが、認証・コスト管理の基盤が整った段階で別 ADR として再検討する

---

## 完了条件

- [x] `.github/workflows/test.yml` に `pip-audit` が CI ジョブ（`audit`）として追加され、脆弱性検出時に CI が失敗すること
- [x] `backend/requirements.txt` で `jinja2>=3.1.6`・`python-multipart>=0.0.31`・`pytest>=9.0.3` に更新され、`pip-audit` で検出される既存脆弱性が（`starlette` を含め）解消され、0 件であること
- [x] `.github/pull_request_template.md` が新規作成され、「`/code-review` 実行済み」チェック項目を含むこと
- [x] CLAUDE.md に「PR 作成前に `/code-review` を手動実行する」運用ルールが追記されていること
- [x] `docs/plan_ai-spec-driven-development.md` の Phase 2 セクションが実態（PR テンプレート移行の完了、CI 自動レビュー見送りの理由）を反映して更新されていること
- [x] 既存テストスイート（pytest）が `pytest` のバージョンアップ後もすべて通過すること
- [x] 既存機能への影響がないこと
