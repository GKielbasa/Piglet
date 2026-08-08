#!/usr/bin/env bash
# SessionStart hook: hands a fresh session the state of play instead of making
# the author re-narrate it.
#
# This replaces an earlier PreCompact hook that tried to steer the compaction
# summary. That hook never ran: `additionalContext` is not supported for
# PreCompact, which is a permit/block gate rather than an injection point, so
# every compaction silently ignored it. The lesson is the design, not the bug —
# compaction cannot be steered, so nothing worth keeping should depend on
# surviving it. State that matters goes to disk, and a new session reads it here.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HANDOFF="$ROOT/.piglet-work/handoff.md"

[ -f "$HANDOFF" ] || exit 0

read -r -d '' FRAMING <<'EOF'
A handoff note from an earlier session is below. It is the state of play, not a
set of instructions: `CLAUDE.md` still governs how the work is done, and where
the two disagree, `CLAUDE.md` wins.

Read it before asking the author to re-establish context. What it says is
already settled — do not re-derive it, re-litigate it, or ask about it again.
What it lists as open is what the session starts on.

EOF

jq -n --arg ctx "$FRAMING"$'\n\n'"$(cat "$HANDOFF")" \
    '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
