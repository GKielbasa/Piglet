# Architecture

> Written in English, as CLAUDE.md section 0 requires of everything on disk. This file
> replaces an earlier Polish draft that described a layout which was never built.

## Organising principle

`piglet` is a **library of primitives** with an agent growing on top of it — not an agent
with functions bolted on. The order matters: the S01 tasks are pipelines, not agents. The
agent loop with a tool registry arrives when a task demands one, not in advance.

The decisions behind the current shape are in [`adr/0002-resilient-http-client.md`](adr/0002-resilient-http-client.md)
and [`adr/0004-failure-class-and-service-profile.md`](adr/0004-failure-class-and-service-profile.md), which refines it;
the ones behind the project as a whole in [`adr/0001-fundamenty-projektu.md`](adr/0001-fundamenty-projektu.md).

## Layers

```
app/          composition root, configuration, CLI      -> knows adapters and domain
adapters/     httpx, filesystem, structlog              -> knows domain
domain/       values, decisions, Protocols              -> knows nothing else
```

Dependencies point one way only: `domain/` imports nothing from the layers above it, and
nothing in it performs I/O.

**The universality boundary.** `domain/`, `adapters/` and `app/` may not know the course
exists — no `ag3nts`, no platform vocabulary, nothing named after a task. A `PostToolUse`
hook greps every write to those directories and rejects the edit if it finds any. Course
knowledge will live in `application/` and in a platform adapter; neither exists yet, and
neither will be created before its first line of real code.

## What exists today

| Module | Role |
|---|---|
| `errors.py` | `PigletError` and its four descendants: transport, HTTP status, retries exhausted, refused as unsafe to repeat |
| `domain/http/request.py` | `HTTPRequest`, `HTTPMethod` — an immutable request, validated on construction |
| `domain/http/response.py` | `HTTPResponse` — status, headers, raw bytes, case-insensitive header lookup |
| `domain/http/retry_policy.py` | `RetryPolicy` — retry or not, how long to wait, and why we stopped. Pure: no I/O, no sleeping |
| `domain/http/service_profile.py` | `ServiceProfile`, `FailureClass` — what a failure means *here*. The one file rewritten per integration |
| `domain/http/cache_key.py` | `compute_cache_key` — request identity, credentials deliberately excluded |
| `domain/ports.py` | `HTTPTransport`, `ResponseCache`, `Sleeper` — structural contracts |
| `adapters/http/httpx_transport.py` | the wire; httpx exceptions stop here, become `TransportError` and are classified |
| `adapters/http/resilient_client.py` | retries, cache lookup, one log entry per attempt |
| `adapters/cache/filesystem_cache.py` | one JSON document per key, body base64, TTL, damaged file = miss |
| `adapters/logging/setup.py` | structlog to JSONL, `run_id` in context, known secrets scrubbed |
| `app/config.py` | `Settings` — environment then `.env` then defaults; secrets as `SecretStr` |
| `app/container.py` | the composition root: every object wired by hand |
| `app/cli.py` | `version`, `config`, `http get` |

There is no LLM client, no platform client and no task module yet. `piglet http get` is
the whole application.

## Seams — modules that will come

They are not created as empty packages. A directory begins with its first line of code.
What follows is intent, so today's decisions do not block tomorrow's.

| Module | When | What it will do | What it will lean on |
|---|---|---|---|
| `llm/` | S01E01 | completions, enforced response schemas, vision | `adapters/http` |
| `application/` | S01E01 | task modules and the platform client — the first code allowed to know the course | `llm/`, `adapters/` |
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
- `data/logs/` — JSONL, one file per day, one object per line

## Testing rigour, deliberately asymmetric

Unit tests are mandatory for the tooling layer — `domain/`, `adapters/`, `app/` — and are
written as assertions accepted by the author **before** the implementation exists.

Task modules get none. They are non-deterministic; the flag verifies them, and from S03E01
the logs and offline evaluation do. Reasoning in ADR 0001, decisions 5 and 6.

Beyond the tests, a step is closed by a run: the definition of done names a command and the
output that counts as proof. Green gates say the code is coherent, not that it does what
was agreed.
