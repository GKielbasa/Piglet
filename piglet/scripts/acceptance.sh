#!/usr/bin/env bash
# Acceptance checks — one section per plan step.
#
# Unit tests prove that code does what its author wrote down. These checks run
# the real thing and inspect what an outsider can observe: exit codes, files on
# disk, log contents, stdout. That is the part a test cannot bend to match the
# implementation.
#
# Every check prints its ASSUMPTION and the EVIDENCE that settles it. A step is
# closed by this output, never by the words "it works".
#
# Usage:  ./scripts/acceptance.sh        (run from the piglet directory)
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

PROBE="src/piglet/_probe.py"
passed=0
failed=0

cleanup() { rm -f "$PROBE"; }
trap cleanup EXIT

section() {
    printf '\n\033[1m== %s ==\033[0m\n' "$1"
}

report() {
    local ok="$1" assumption="$2" evidence="$3"
    if [ "$ok" = "yes" ]; then
        passed=$((passed + 1))
        printf '  \033[32mOK  \033[0m %s\n' "$assumption"
    else
        failed=$((failed + 1))
        printf '  \033[31mFAIL\033[0m %s\n' "$assumption"
        printf '       evidence: %s\n' "$evidence"
    fi
}

# Command must succeed.
assert_ok() {
    local assumption="$1"
    shift
    local out
    if out=$("$@" 2>&1); then
        report yes "$assumption" ""
    else
        report no "$assumption" "$(printf '%s' "$out" | head -3 | tr '\n' ' ')"
    fi
}

# Command output must contain a string.
assert_contains() {
    local assumption="$1" needle="$2"
    shift 2
    local out
    out=$("$@" 2>&1)
    if printf '%s' "$out" | grep -qF "$needle"; then
        report yes "$assumption" ""
    else
        report no "$assumption" "expected '$needle', got: $(printf '%s' "$out" | head -2 | tr '\n' ' ')"
    fi
}

# A snippet written to the source tree must trip a specific ruff rule.
# Proves the configuration enforces what CLAUDE.md claims, rather than merely
# listing the rule in `select`.
assert_ruff_rejects() {
    local rule="$1" assumption="$2" snippet="$3"
    printf '%s' "$snippet" > "$PROBE"
    local out
    out=$(uv run ruff check --no-cache --select "$rule" "$PROBE" 2>&1)
    rm -f "$PROBE"
    if printf '%s' "$out" | grep -q "$rule"; then
        report yes "$assumption" ""
    else
        report no "$assumption" "rule $rule did not fire"
    fi
}

# ---------------------------------------------------------------------------
section "Step 1 — foundation and quality configuration"
# ---------------------------------------------------------------------------

assert_ok "the package imports" \
    uv run python -c "import piglet"

assert_contains "the interpreter is pinned to 3.12" "3.12" \
    cat .python-version

assert_ok "the lock file exists and the environment matches it" \
    uv sync --locked --quiet

assert_ruff_rejects UP046 \
    "CLAUDE.md 8: PEP 695 generics, not TypeVar/Generic" \
    'from typing import Generic, TypeVar

T = TypeVar("T")


class Box(Generic[T]):
    """Doc."""
'

assert_ruff_rejects PLR0913 \
    "CLAUDE.md 7: a constructor past 6 arguments is rejected" \
    'def f(a: int, b: int, c: int, d: int, e: int, f: int, g: int) -> None:
    """Doc."""
'

assert_ruff_rejects TID252 \
    "CLAUDE.md 9: relative imports are rejected" \
    '"""Doc."""

from .sibling import thing

__all__ = ["thing"]
'

assert_ruff_rejects BLE001 \
    'CLAUDE.md 11: bare except Exception is rejected' \
    '"""Doc."""


def f() -> None:
    """Doc."""
    try:
        pass
    except Exception:
        pass
'

assert_ruff_rejects T201 \
    'CLAUDE.md 11: print() in logic is rejected' \
    '"""Doc."""


def f() -> None:
    """Doc."""
    print("x")
'

# mypy cannot read from stdin, so the probe lands in the tree for one run.
# Output is captured before grepping: under `pipefail` a `cmd | grep -q` pipeline
# reports mypy's non-zero exit, not whether the pattern matched.
printf '"""Doc."""\n\n\ndef f(x):\n    return x\n' > "$PROBE"
mypy_out=$(uv run mypy "$PROBE" 2>&1)
rm -f "$PROBE"
if printf '%s' "$mypy_out" | grep -q "no-untyped-def"; then
    report yes "CLAUDE.md 8: mypy --strict rejects an unannotated function" ""
else
    report no "CLAUDE.md 8: mypy --strict rejects an unannotated function" \
        "$(printf '%s' "$mypy_out" | head -2 | tr '\n' ' ')"
fi

section "Step 1 — the tree itself is green"

assert_ok "ruff format is clean"  uv run ruff format --check .
assert_ok "ruff check is clean"   uv run ruff check .
assert_ok "mypy --strict is clean" uv run mypy

# ---------------------------------------------------------------------------
# Step 2 and beyond: a section lands here together with the step it verifies.
# ---------------------------------------------------------------------------

printf '\n\033[1m== Summary ==\033[0m\n'
printf '  passed: %s\n  failed: %s\n\n' "$passed" "$failed"
[ "$failed" -eq 0 ]
