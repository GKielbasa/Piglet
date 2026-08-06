#!/usr/bin/env bash
# PreCompact hook: tells the compactor what must survive.
#
# Compaction is lossy and silent, and it lands on exactly the sessions that cost
# the most to rebuild. The default summary prompt has no way to know that an
# assertion the author accepted is a contract rather than chatter, or that the
# output of a definition-of-done run is evidence that cannot be paraphrased.
# This says so.
set -uo pipefail

read -r -d '' PRIORITIES <<'EOF'
Additional priorities for this summary, specific to the piglet project. Where
they conflict with length, drop conversational filler, repeated tool output and
intermediate reasoning first.

A. ACCEPTED ASSERTIONS ARE VERBATIM. Any test name or condition the author has
   accepted (CLAUDE.md section 5) is the specification. Preserve it word for
   word. A paraphrased assertion is a changed requirement, and nobody will
   notice it changed.

B. EVIDENCE OF RUNS, NOT CLAIMS ABOUT THEM. The definition of done for each step
   and whether it was actually executed, with the output that was pasted back
   (CLAUDE.md section 12). "The gates were green" is not a substitute for the
   run that showed it.

C. WHICH GATES ARE RED, and the exact failure text — ruff, mypy, basedpyright,
   pytest. A summary saying "some type errors" has destroyed what it summarised.

D. DECISIONS AND THEIR REASONS. Anything settled this session that belongs in an
   ADR, anything the author explicitly rejected or corrected, and the assumption
   each decision rests on. A correction from the author is a requirement, not a
   remark.

E. EXACT PATHS, in two tiers: files this session changed, and files merely read
   or mentioned. Keep the first tier exactly.

F. OPEN QUESTIONS awaiting the author, and anything promised but not yet
   delivered.
EOF

jq -n --arg ctx "$PRIORITIES" \
    '{hookSpecificOutput: {hookEventName: "PreCompact", additionalContext: $ctx}}'
