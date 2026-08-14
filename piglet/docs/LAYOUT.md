# Layout — what lives where, and what may never live there

> **One sentence:** every directory answers exactly one question, and the fastest way to know
> where code belongs is to ask which of those questions it answers.

This is the map you read when you open a directory and want to know what belongs in it.
[`ARCHITECTURE.md`](ARCHITECTURE.md) stays the authority on module names, the inventory of what
exists, and the decisions behind it; this file does not repeat that table.

## The four questions

| Directory | The question it answers |
|---|---|
| `src/piglet/domain/` | What do these things **mean**? |
| `src/piglet/adapters/` | How do we **touch the world**? |
| `src/piglet/llm/` | What can we **do with a model**? |
| `src/piglet/application/` | What does **the course** want? |
| `src/piglet/app/` | How is it **assembled and started**? |

---

## `domain/` — meanings and decisions

Values and rules. Understanding this directory needs no network, no disk and no clock — and
neither does the code.

**Expect:** immutable values compared by value (`HTTPRequest`, `ChatMessage`), pure decisions
(`RetryPolicy` answers "retry, and how long first?"; `ServiceProfile` answers "what does 429 mean
*here*?"), pure functions (`parse_prompt`, `birth_years_for_age_range`), and the structural
contracts the domain puts to the world in `ports.py`.

**Never here:** `httpx`, `open()`, a clock read directly, or anything that knows this course
exists.

## `adapters/` — the wire

One subdirectory per technology, each hidden behind a contract from `domain/ports.py`.

| Subdirectory | What it talks to |
|---|---|
| `http/` | httpx, and the client that keeps trying |
| `cache/` | the filesystem, one JSON document per request identity |
| `logging/` | structlog, one JSON object per line, secrets scrubbed |
| `llm/` | one model provider: builds the body, reads the answer, names the failures |
| `prompts/` | prompt files on disk |

**Expect:** classes with their dependencies injected through `__init__`, and translation in both
directions — their types in, ours out. An adapter may stand on another adapter: the model client
stands on the HTTP client rather than opening a socket of its own.

**Never here:** decisions (whether to retry belongs to `domain/`), and knowledge of the course.

## `llm/` — capabilities built on a model

Universal work built on the **contract**, not on a provider. This directory does not know
OpenRouter exists; it talks to `ChatModel`.

**Expect:** `json_schema.py` (a pydantic model in the dialect a provider enforces),
`structured.py` (ask for a shape, validate what comes back), `classification.py` (batching,
bounded concurrency, deduplication, one verdict per record).

**The membership test:** if it works for any model and any domain, it belongs here. Changing
provider must not touch a line in this directory.

## `application/` — the only layer that knows the course

Knows the platform's address, task names, the taxonomy, and the answer format.

**Expect:** `platform_client.py` (fetch a task's input, submit its answer), `people.py` (the task
module), `tasks.py` (where a task's objects are assembled by hand).

**The rule that keeps it honest:** a task module is **thin**. It fetches, filters
deterministically, composes calls to universal tools, and hands back the result. Substance that
is not about *this* task has landed in the wrong directory.

## `app/` — assembly and entry points

**Expect:** `config.py` (environment, then `.env`, then defaults), `container.py` (objects wired
by hand — no container, no autowiring), `cli.py` (read arguments, call one function, print).

**Never here:** logic. A branch in `cli.py` that decides something substantive is in the wrong
place — the same functions will be called by FastAPI later, and the CLI is only a shell.

`errors.py` sits one level above these directories: every exception the library raises, with
`PigletError` at the root.

---

## Outside the code

| Path | What it holds |
|---|---|
| `docs/` | how it is built and why. `ARCHITECTURE.md` (layers, modules), `COURSE_MAP.md` (lesson → module), `adr/` (one decision per file, superseded rather than edited) |
| `prompts/` | instructions as markdown files with a YAML header, re-read on every use, versioned in git |
| `data/` | the only thing the program writes: `cache/` (remembered responses), `logs/` (JSONL, one file per day — what each call **cost**) and `runs/<run_id>/` (one JSON per model call — what each call **contained**). Gitignored, and the raw material for the evaluation work of season 3 |

---

## Dependency direction

```
app/          assembles and starts        ──▶ everything below
application/  knows the course            ──▶ llm/, adapters/
llm/          capabilities                ──▶ domain/ (the contract, never an adapter)
adapters/     the outside world           ──▶ domain/
domain/       meanings and decisions      ──▶ nothing
```

Arrows point one way. `domain/` imports nothing from above and does not know the rest exists,
which is why its tests need neither network nor disk and finish in milliseconds.

Two edges cross back, and both are about **assembly** rather than about the domain:

- `app/cli.py` imports `application/tasks.py`, because an entry point has to reach a task. It stays
  generic — the CLI takes a task's name as an argument and never names one.
- `application/tasks.py` imports `app/config.py` and `app/container.py`, because it is itself a
  composition root: the one for the layer that knows the course. `app/container.py` may not know
  this platform exists, so the objects that do are assembled one level above it instead. The edge
  ends there — no task module imports `app/`, and nothing in `app/` imports a task module.

## The one rule a hook enforces

`domain/`, `adapters/` and `app/` may not know the course exists. A `PostToolUse` hook greps every
write to those directories for the course's vocabulary and rejects the edit if it finds any — it
once rejected a docstring for the phrase "read by people", because `people` is a task name.
`application/` is exempt, which is the whole reason that layer exists.
