# Architecture

> Written in English, as CLAUDE.md section 0 requires of everything on disk. This file
> replaces an earlier Polish draft that described a layout which was never built.

## Organising principle

`piglet` is a **library of primitives** with an agent growing on top of it — not an agent
with functions bolted on. The order matters: the S01 tasks are pipelines, not agents. The
agent loop with a tool registry arrives when a task demands one, not in advance.

**What deterministic code can decide, it decides.** The model is asked only what code cannot
answer, and the shrinking happens before the call rather than after it: filter, then classify;
deduplicate identical inputs; compute what is derivable. A model call is the only step in a
pipeline that can be wrong without failing, so every record kept away from it is a record that
cannot be misclassified. Reasoning in [`adr/0006-own-chat-client.md`](adr/0006-own-chat-client.md),
decision 4.

The decisions behind the current shape are in [`adr/0002-resilient-http-client.md`](adr/0002-resilient-http-client.md)
and [`adr/0004-failure-class-and-service-profile.md`](adr/0004-failure-class-and-service-profile.md), which refines it;
the ones behind the project as a whole in [`adr/0001-fundamenty-projektu.md`](adr/0001-fundamenty-projektu.md).

## Layers

For the plain-language version of this — what to expect on opening each directory, and what may
never be in it — see [`LAYOUT.md`](LAYOUT.md). This file stays the authority on module names,
what exists, and why.

```
app/          composition root, configuration, CLI      -> knows adapters and domain
application/  task modules and the platform client      -> knows llm/ and adapters
llm/          capabilities built on a model             -> knows domain
adapters/     httpx, filesystem, structlog, providers   -> knows domain
domain/       values, decisions, Protocols              -> knows nothing else
```

Dependencies point one way only: `domain/` imports nothing from the layers above it, and
nothing in it performs I/O.

One edge crosses back: `app/cli.py` imports `application/tasks.py`, because an entry point has
to be able to reach a task. It stays generic — the CLI takes a task's name as an argument and
never mentions one, so `app/` still does not know which course this is.

An adapter may stand on another adapter: `adapters/llm/` takes the `ResilientHTTPClient` from
`adapters/http/` instead of opening a socket of its own. The one-way rule governs the three
layers, not siblings within one.

**The universality boundary.** `domain/`, `adapters/` and `app/` may not know the course
exists — no `ag3nts`, no platform vocabulary, nothing named after a task. A `PostToolUse`
hook greps every write to those directories and rejects the edit if it finds any. Course
knowledge lives in `application/`, which the hook leaves alone — it is the one layer allowed
to name a platform, a task and a taxonomy.

## What exists today

| Module | Role |
|---|---|
| `errors.py` | `PigletError` and its descendants: transport, HTTP status, retries exhausted, refused as unsafe to repeat, and — under `ModelError` — a provider's own failure, a truncated answer, a violated schema, plus the two a prompt file can raise |
| `domain/http/request.py` | `HTTPRequest`, `HTTPMethod` — an immutable request, validated on construction |
| `domain/http/response.py` | `HTTPResponse` — status, headers, raw bytes, case-insensitive header lookup |
| `domain/http/retry_policy.py` | `RetryPolicy` — retry or not, how long to wait, and why we stopped. Pure: no I/O, no sleeping |
| `domain/http/service_profile.py` | `ServiceProfile`, `FailureClass` — what a failure means *here*. The one file rewritten per integration |
| `domain/http/cache_key.py` | `compute_cache_key` — request identity, credentials deliberately excluded |
| `domain/ports.py` | `ChatModel`, `HTTPTransport`, `ResponseCache`, `Sleeper` — structural contracts |
| `domain/llm/chat.py` | `ChatRequest`, `ChatCompletion`, `ChatMessage`, `ResponseSchema`, `TokenUsage`, `Role`, `FinishReason` — one exchange with a model, as values |
| `domain/llm/prompt.py` | `Prompt`, `parse_prompt` — a prompt file split into header and instruction. Pure |
| `domain/age.py` | `birth_years_for_age_range` — an age range at a given year, as birth years |
| `adapters/http/httpx_transport.py` | the wire; httpx exceptions stop here, become `TransportError` and are classified |
| `adapters/http/resilient_client.py` | retries, cache lookup, one log entry per attempt |
| `adapters/cache/filesystem_cache.py` | one JSON document per key, body base64, TTL, damaged file = miss |
| `adapters/logging/setup.py` | structlog to JSONL, `run_id` in context, known secrets scrubbed |
| `adapters/llm/openrouter_chat.py` | Chat Completions over the resilient client: enforced schemas, one `llm_call_finished` entry per call |
| `adapters/llm/recording_chat.py` | a `ChatModel` wrapping a `ChatModel`: writes every exchange to disk, for any provider |
| `adapters/prompts/markdown_prompt_library.py` | prompts as markdown files, re-read on every load |
| `llm/json_schema.py` | `to_strict_json_schema` — a pydantic model in the dialect strict mode accepts |
| `llm/structured.py` | `complete_as` — ask for a shape, validate what comes back into it |
| `llm/classification.py` | `classify_in_batches` — batching, bounded concurrency, deduplication, one verdict per record |
| `application/platform_client.py` | the course platform: download a task's input, submit its answer |
| `application/people.py` | S01E01: filter deterministically, classify what is left, submit |
| `application/tasks.py` | `run_task` — where a task's objects are assembled |
| `app/config.py` | `Settings` — environment then `.env` then defaults; secrets as `SecretStr` |
| `app/container.py` | the composition root: every object wired by hand |
| `app/cli.py` | `version`, `config`, `http get`, `llm ask`, `task run` |

## Seams — modules that will come

They are not created as empty packages. A directory begins with its first line of code.
What follows is intent, so today's decisions do not block tomorrow's.

| Module | When | What it will do | What it will lean on |
|---|---|---|---|
| `tools/` | S01E02 | tool registry, JSON schemas, argument validation | `llm/` (function calling) |
| `rag/` | S02E02 | indexing, embeddings, hybrid search | `llm/`, cache |
| `agent/` | S02E05 | the loop: call, tools, result, repeat; step budget | `tools/`, `llm/` |
| `memory/` | S02E03 / S04E04 | long-term memory, markdown knowledge base | `rag/` |
| `eval/` | S03E01 | test sets, metrics, replaying runs | the JSONL logs, which is why they exist now |
| `api/` | S03E03 or a UI | FastAPI routes calling the same functions the CLI calls | `app/container.py` |
| `sandbox/` | S05 | isolated execution of code and tools | everything |

## Data on disk

Everything the program writes lives under `data/`, outside the repository:

- `data/cache/` — cached responses, one JSON document per request identity
- `data/logs/` — JSONL, one file per day, one object per line: what each call cost
- `data/runs/<run_id>/` — one JSON document per model call: what each call contained. The log
  cannot answer why a model chose what it did, and an exchange cannot be reconstructed after
  the fact, which is why both are written from the first run. `PIGLET_RECORD_EXCHANGES=false`
  switches it off where the prompts carry data that must not be kept.

## Testing rigour, deliberately asymmetric

Unit tests are mandatory for the tooling layer — `domain/`, `adapters/`, `app/` — and are
written as assertions accepted by the author **before** the implementation exists.

Task modules get none. They are non-deterministic; the flag verifies them, and from S03E01
the logs and offline evaluation do. Reasoning in ADR 0001, decisions 5 and 6.

Beyond the tests, a step is closed by a run: the definition of done names a command and the
output that counts as proof. Green gates say the code is coherent, not that it does what
was agreed.
