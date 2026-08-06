#!/usr/bin/env bash
# PreToolUse hook: confines a subagent's writes to a single directory.
#
# Wired from a subagent's own frontmatter, so the rule binds only while that
# agent runs. It exists for one reason: an agent that can patch the code it is
# judging stops reporting and starts fixing, and the independence that made the
# review worth reading disappears with it. The reviewer and the assertion
# drafter produce a report; that is their whole output.
#
# Exit 2 sends stderr back to the agent as feedback, matching the other hooks in
# this directory.
#
# Usage (from an agent's frontmatter):
#   write-scope.sh <allowed-prefix-relative-to-repo-root> <role-name>
set -uo pipefail

allowed="${1:?allowed prefix required}"
role="${2:-This agent}"

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

file=$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
[ -z "$file" ] && exit 0

# Both absolute and repo-relative paths arrive here; normalise to repo-relative.
case "$file" in
    /*) rel="${file#"$ROOT"/}" ;;
    *) rel="$file" ;;
esac

case "$rel" in
    "$allowed"*) exit 0 ;;
esac

printf '%s\n' \
    "OUT OF SCOPE: $rel is not yours to write." \
    "" \
    "$role writes to $allowed and nowhere else. A finding is not a fix — if the" \
    "change belongs in the code, name the file and the line in your report and" \
    "let the author decide. Do not reach for Bash to do what this refused." >&2
exit 2
