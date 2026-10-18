#!/usr/bin/env bash
# 実名・実在の取引先名など、リポジトリに含めたくない語が追跡ファイルに無いことを確認する。
#
# 語そのものをリポジトリに置くと、それ自体が漏えいになる。そのため語の一覧は
# 環境変数 FORBIDDEN_TERMS（改行区切り）で受け取る。CI では同名の Secret から渡す。
# 一致したファイル名だけを表示し、一致した行（語を含む）は表示しない。
#
#   FORBIDDEN_TERMS=$'語1\n語2' scripts/check_forbidden_terms.sh
set -euo pipefail

if [ -z "${FORBIDDEN_TERMS:-}" ]; then
  echo "FORBIDDEN_TERMS が未設定のため、禁止語の検査をスキップします" >&2
  exit 0
fi

# 空行を除いた語の一覧（一致は固定文字列として扱う）
patterns="$(printf '%s\n' "$FORBIDDEN_TERMS" | sed '/^[[:space:]]*$/d')"

hits="$(git grep -l -I -F -f <(printf '%s\n' "$patterns") -- . ':!scripts/check_forbidden_terms.sh' || true)"

if [ -n "$hits" ]; then
  echo "禁止語を含むファイルがあります（語は表示しません）:" >&2
  echo "$hits" >&2
  exit 1
fi

echo "禁止語は見つかりませんでした（$(printf '%s\n' "$patterns" | wc -l | tr -d ' ') 語を検査）"
