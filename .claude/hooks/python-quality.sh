#!/usr/bin/env bash
# PostToolUse hook: runs the CLAUDE.md quality gates on a single edited file.
#
# Two classes of check:
#   1. ruff + mypy  — mechanical, ~70% of the style guide (see pyproject.toml)
#   2. grep         — project rules no linter knows about:
#                     section 9 banned identifiers, section 6 universality test
#
# Exit 2 sends stderr back to the agent as feedback, so a violation is corrected
# in the same turn instead of surviving until the final gate run.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PROJECT="$ROOT/piglet"

file=$(jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0

case "$file" in
    *.py) ;;
    *) exit 0 ;;
esac
[ -f "$file" ] || exit 0
case "$file" in
    "$PROJECT"/*) ;;
    *) exit 0 ;;
esac

cd "$PROJECT" || exit 0
rel="${file#"$PROJECT"/}"
problems=""

# Tell the Stop hook that Python changed, so it runs the full suite before the
# agent is allowed to finish. Consumed by quality-gate.sh.
touch "$ROOT/.claude/.quality-pending"

# --- 1. Mechanical gates -----------------------------------------------------

uv run ruff format -q "$file" 2>/dev/null

if ! fix_out=$(uv run ruff check --fix "$file" 2>&1); then
    problems+="--- ruff ---
$fix_out

"
fi

if ! mypy_out=$(uv run mypy "$file" 2>&1); then
    problems+="--- mypy --strict ---
$mypy_out

"
fi

# Second type checker, run here so the agent never hands back code that lights up in
# the author's editor. Its config lives at the repo root, not in piglet/, because the
# editor workspace is the repo: hence the explicit --project.
if ! pyright_out=$(uv run basedpyright --project "$ROOT" "$file" 2>&1); then
    problems+="--- basedpyright (strict) ---
$pyright_out

"
fi

# --- 2. Section 9: banned identifiers ----------------------------------------
# Word-anchored so `process_batch` and `metadata` do not trigger; only an
# identifier that *is* the banned word counts.

BANNED='data|info|manager|helper|helpers|util|utils|handler|process|tmp|result2'

if hits=$(grep -nE "\b(def|class)[[:space:]]+(${BANNED})\b|^[[:space:]]*(${BANNED})[[:space:]]*[:=][^=]" "$file"); then
    problems+="--- CLAUDE.md section 9: banned name ---
These words carry no meaning. Rename to say what the thing is and why.
$hits

"
fi

case "$(basename "$file")" in
    utils.py|helpers.py|handlers.py|misc.py|common.py)
        problems+="--- CLAUDE.md section 9: banned module name ---
$rel is a bucket, not a module. Name it after what lives in it.

"
        ;;
esac

# --- 3. Section 6: universality test -----------------------------------------
# domain/, adapters/ and app/ must not know the course exists. Only
# application/ and a future Hub adapter are allowed to.

case "$rel" in
    src/piglet/domain/*|src/piglet/adapters/*|src/piglet/app/*)
        # Anchored on a non-letter so compounds leak-check too (`hub_client`,
        # `HubResponse`, `fetch_from_hub`) while `github` stays clean.
        if leak=$(grep -niE '(^|[^a-z])(ag3nts|powerplant|ai_?devs|hub|flg|flag|people)' "$file"); then
            problems+="--- CLAUDE.md section 6: universality test ---
$rel belongs to the generic layer, but names the course domain.
Tools do not know AI_devs exists.
$leak

"
        fi
        ;;
esac

# --- 4. Section 5: test integrity ---------------------------------------------
# Section 5 protects the specification while it is being written: assertions are
# accepted by the author before any implementation exists. Nothing protected it
# afterwards. These two checks do — they are the cheapest moment to catch a test
# quietly bent to fit the code it was supposed to judge.

case "$rel" in
    tests/*)
        if skips=$(grep -nE '@pytest\.mark\.(skip|xfail)|pytest\.skip\(' "$file"); then
            problems+="--- CLAUDE.md section 5: a test that cannot fail ---
A skipped or expected-to-fail test asserts nothing while still counting as green.
If this is deliberate, it is the author's call and belongs in the conversation,
not in a file. Remove it, or leave the test failing and say why.
$skips

"
        fi

        # Counted on the file as it now stands rather than on the diff: the trick
        # this catches is a test that ends up vacuous, however it got there.
        if grep -qE '^[[:space:]]*(async[[:space:]]+)?def test_' "$file" \
            && ! grep -qE '^[[:space:]]*assert\b|pytest\.raises' "$file"; then
            problems+="--- CLAUDE.md section 5: test without an assertion ---
$rel defines tests but asserts nothing. A test that cannot fail passes forever
and proves nothing — it is worse than an absent test, because the gates now
lean on it. Assert the behaviour, or delete the test and report the gap.

"
        fi
        ;;
esac

# --- Report ------------------------------------------------------------------

if [ -n "$problems" ]; then
    printf '%s\n' "Quality gate failed for $rel:" "" "$problems" >&2
    exit 2
fi

exit 0
