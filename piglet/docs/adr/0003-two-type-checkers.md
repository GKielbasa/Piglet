# ADR 0003 — Two type checkers, and which one wins

- **Date:** 2026-08-06
- **Status:** accepted
- **Supersedes:** nothing. Extends the Types row of CLAUDE.md section 11.

## Context

The project declares `mypy --strict` as its type contract, and the gates enforce it. The
author's editor runs **basedpyright**, which is a different checker with different rules.

That mismatch cost real time. With no configuration, the editor reported **79 errors and
512 warnings** on a tree that the gates called green — because the editor's workspace is
the repository root while the project, its `.venv` and its sources live one level down in
`piglet/`. The checker could not find the installed dependencies (51 × `reportMissingImports`,
which cascades into hundreds of "type is unknown") nor the source root
(28 × `reportImplicitRelativeImport`).

Pointing it at the venv and the source root left **1 error and 63 warnings**. So roughly
92% of what the author saw was configuration, not code — but the remaining findings were
real, and there was no mechanism to keep them from coming back. Every session ended in the
same conversation: the gates are green, the editor is red, which one is right.

## Decisions

### 1. Both checkers run, and both run in the gates

`basedpyright` is a pinned dev dependency, not an editor plugin the project knows nothing
about. The `PostToolUse` hook runs it after every `.py` write and the `Stop` hook runs it
before a turn may end.

This is the decision that actually ends the recurrence. A checker that only lives in the
editor reports its findings *after* the coding agent has finished — so the author becomes
the error channel. Running it in the same hook as mypy means code that lights up in the
editor cannot leave the turn in the first place.

Its configuration is `pyrightconfig.json` at the **repository root**, not inside `piglet/`.
That is deliberate and it is the one config file that must live outside the project
directory: the editor opens the repository, so this is where it looks. Every invocation
therefore passes `--project` explicitly.

### 2. `strict`, not `recommended` and not `all`

basedpyright's modes are not a straight line from lax to severe. Measured on this tree:

| Mode | Errors | Warnings |
|---|---|---|
| `basic`, `standard` | 0 | 0 |
| **`strict`** | **2** | 0 |
| `recommended` | 1 | 63 |
| `all` | 64 | 0 |

`recommended` is `strict` plus basedpyright's own rules as warnings; `all` is the same set
as errors. Those extra rules are the reason for choosing `strict`:

- `reportUnannotatedClassAttribute` (17 hits) wants `self.directory: Path = directory`,
  where mypy infers the type from the parameter.
- `reportUnusedCallResult` (18 hits) flags every ignored return value — `mkdir()`,
  `write_text()`, `bind_contextvars()`.
- `reportAny` (19 hits) flags `Any`-typed expressions, almost all of them the `json.loads`
  result inside the filesystem cache.

The first two are style opinions that contradict sections 7 and 9 of CLAUDE.md. Adopting
them would change a documented style, not improve type safety. `strict` keeps the second
checker doing what a type checker is for.

`reportAny` is the one worth revisiting, but on its own merits rather than a linter's: the
cached document crosses a process boundary, so section 8 argues it should be a pydantic
model instead of a `dict`. Once it is, the rule becomes free to switch on and it will keep
the boundary from rotting. Until then, switching it on would only produce 19 warnings about
a decision nobody has taken.

### 3. mypy is the contract; basedpyright bends

When they disagree:

1. The finding is fixed in the code. Both checkers' ignore comments are a last resort and
   carry a WHY.
2. If the disagreement is real and mypy is right, the rule is turned off in
   `pyrightconfig.json` with a reason — in one place, never as scattered inline ignores.
3. The resulting convention is written into CLAUDE.md, and **the code does not comment it**.
   A rule repeated at every occurrence is noise the author has to delete by hand.

The whole delta under `strict` came to two occurrences of one rule:
`field(default_factory=dict)` gives a checker `dict[Unknown, Unknown]`, because a bare
`dict` erases its parameters. mypy trusts the declared annotation and never looks at the
factory. Spelling it `field(default_factory=dict[str, str])` satisfies both and changes
nothing at runtime — `dict[str, str]` is callable and returns `{}`.

## Consequences

- Five gates instead of four. basedpyright analyses the tree in about one second, so the
  cost is negligible next to mypy and pytest.
- The editor and the gates run the **same pinned version**, so a checker upgrade arrives
  through `uv.lock` and a review, not as a surprise mid-session. For this to hold, the
  editor extension must be told to use the project environment rather than its bundled
  copy (`basedpyright.importStrategy: "fromEnvironment"` in VS Code).
- Two dataclass fields are spelled with explicit factory type parameters. That is the
  entire code delta. A single `# type: ignore[...]` keeps serving both checkers, because
  pyright honours those comments in `strict` — `recommended` is where it stops doing so.
- Replacing mypy with basedpyright entirely — one checker, one truth, and faster — remains
  a live option. It is not taken now because mypy is what section 11 declares, what the
  hooks enforce, and the more conservative of the two. That change would be its own ADR.
