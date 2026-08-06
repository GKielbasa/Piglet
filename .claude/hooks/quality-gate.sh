#!/usr/bin/env bash
# Stop hook: blocks the agent from ending its turn while CLAUDE.md section 12
# gates are red.
#
# PostToolUse (python-quality.sh) checks one file at a time, right after an edit.
# That catches mechanical faults early but says nothing about the change as a
# whole: a rename can leave another module broken, a new test can fail.
# This hook closes that gap — it runs the full suite the moment the agent tries
# to say "done".
#
# It only fires when Python actually changed: python-quality.sh drops a marker
# on every .py edit, and this hook consumes it. Pure conversation turns pass
# through untouched.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PROJECT="$ROOT/piglet"
MARKER="$ROOT/.claude/.quality-pending"

payload=$(cat)

# Re-entry guard: if the agent is already responding to this hook, do not stack
# another block on top of it.
if [ "$(printf '%s' "$payload" | jq -r '.stop_hook_active // false')" = "true" ]; then
    exit 0
fi

[ -f "$MARKER" ] || exit 0
cd "$PROJECT" || exit 0

failures=""

run_gate() {
    local label="$1"
    shift
    local out
    out=$(uv run "$@" 2>&1)
    local code=$?

    # pytest exits 5 when it collects nothing. Until plan step 2 lands the first
    # test that is the expected state, not a failure.
    if [ "$label" = "pytest" ] && [ "$code" -eq 5 ]; then
        return 0
    fi

    if [ "$code" -ne 0 ]; then
        failures+="--- $label (exit $code) ---
$out

"
    fi
}

run_gate "ruff format" ruff format --check .
run_gate "ruff check" ruff check .
run_gate "mypy --strict" mypy
run_gate "basedpyright (strict)" basedpyright --project "$ROOT"
run_gate "pytest" pytest -q

if [ -n "$failures" ]; then
    printf '%s\n' \
        "CLAUDE.md section 12: not all gates are green. Do not report this task as done." \
        "Fix the failures below, then finish." "" "$failures" >&2
    exit 2
fi

rm -f "$MARKER"
exit 0
