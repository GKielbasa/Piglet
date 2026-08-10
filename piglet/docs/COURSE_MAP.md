# Course map: AI_devs 4 → `piglet` modules

A living document. After each lesson, fill in the module and the status.

**Module names come from [`ARCHITECTURE.md`](ARCHITECTURE.md)**, which is the authority. A name
here that does not appear there is a name nobody has built. `✓` after a module means it exists on
disk today; the Status column is about the *lesson*, not the module.

Status: `—` not started · `WIP` in progress · `✓` done

## Season 1 — foundations

| Lesson | Technical capabilities | Module | Task | Status |
|---|---|---|---|---|
| S01E01 | structured outputs / JSON Schema, choosing a model, organising instructions in code, few/many-shot | `llm/`, `application/`, `adapters/http/` ✓ | **people** — CSV → filter → tag classification → `/verify` | — |
| S01E02 | function calling, tool schemas, validation and guardrails, workflow vs agent, query transformation, dynamic tool lists, prompt injection | `tools/`, `agent/` | **findhim** — orchestrating `/api/location` and `/api/accesslevel`, matching geography to the site | — |
| S01E03 | threat modeling, least privilege, dry run + HITL, audit trail, secrets management | `app/config.py` ✓, `adapters/logging/` ✓, `application/` (dry run) | ⚠️ **no lesson file in `_teoria/`** — a video transcript only | — |
| S01E04 | vision, PDF, audio, video, generating and editing images | `llm/` (multimodal), `adapters/http/` ✓ | **sendit** — crawl the markdown documentation, vision over its images, a rigid declaration template | — |
| S01E05 | explicit and implicit limits, rate limits, retry on 503, running against production | `adapters/http/` ✓ (retry, backoff), `adapters/cache/` ✓ | **railway** — a self-documenting API, activating route X-01 under hard limits | — |

## Season 2 — context and agents

| Lesson | Technical capabilities | Module | Status |
|---|---|---|---|
| S02E01 | dynamic system instruction, state outside the context window, context masking, planning and tracking progress | `agent/` (context) | — |
| S02E02 | indexing, vector stores, semantic search, retrieval, RAG | `rag/` | — |
| S02E03 | a knowledge base as a tool, categorisation, resource maps, graphs, long forms | `rag/`, `memory/` | — |
| S02E04 | concurrency, global context, dividing tools between agents, a manager | `agent/` (multi) | — |
| S02E05 | designing an agent: instruction, scope of responsibility, tool set, assigned knowledge | `agent/` | — |

## Season 3 — observability and limits

| Lesson | Technical capabilities | Module | Status |
|---|---|---|---|
| S03E01 | tracing, replaying state, prompt versioning, metrics, evaluation | `eval/`, reading what `adapters/logging/` ✓ already writes | — |
| S03E02 | controlling task difficulty, mitigating prompt injection, hallucinations | `agent/` (guards) | — |
| S03E03 | feedback from the environment, the space between tool calls, HITL | `agent/`, `api/` | — |
| S03E04 | test data sets, model ensembles, self-optimising schemas | `eval/`, `llm/` (registry) | — |
| S03E05 | steering reasoning, flexible presentation, generative UI | `llm/`, `api/` | — |

## Season 4 — deployment and collaboration

| Lesson | Technical capabilities | Module | Status |
|---|---|---|---|
| S04E01 | deployment, synchronous and asynchronous collaboration, mapping processes | — | — |
| S04E02 | a chat interface, personalisation, meta-prompts | `api/`, `agent/` | — |
| S04E03 | background work, managing events and messaging | `api/` (background); no module decided yet | — |
| S04E04 | a knowledge base of your own in markdown, long-term memory vs a knowledge base | `memory/` | — |
| S04E05 | in-house solutions, privacy, reading SQLite, an orders API | `tools/` (sqlite) | — |

## Season 5 — production

| Lesson | Technical capabilities | Module | Status |
|---|---|---|---|
| S05E01 | chatbot and agent architecture, provider integrations | `llm/` (registry), `api/` | — |
| S05E02 | user interface, tools for agents, search engines and vector stores | `tools/`, `rag/` | — |
| S05E03 | model migrations and API changes, steering an agent's evolution | `llm/` (registry), and an ADR | — |
| S05E04 | production experience | everything | — |
| S05E05 | an assistant of your own — configuration, tools, collaboration, growth | everything | — |

## What this implies for the architecture

The primitives that recur across S01E01–E05 are the ones built first. Three of the five exist:

1. `adapters/http/` ✓ — retry, backoff, deferring to `Retry-After` (forced by S01E05)
2. `adapters/cache/` ✓ — re-running a task must cost zero requests
3. `adapters/logging/` ✓ — JSONL per call; the foundation for S03E01, which is why it exists from
   S01E01 rather than from season 3. **One known debt to settle when S03E01 turns the log into an
   evaluation dataset:** `http_attempt_finished` is emitted in two different shapes —
   `ResilientHTTPClient._record_attempt` binds its fields progressively, `_recall` hand-rolls a
   second version with a different field set for a cache hit. One event name, two schemas, so every
   consumer has to handle both. Cheap to unify now, awkward once something reads it.
4. `llm/` — completions, enforced response schemas, vision, tool calling
5. `application/` — the task modules and the platform client: fetching input, `/verify`, extracting
   the answer token

`app/config.py` ✓ keeps secrets out of the code and out of every module above.

**Why there is no `hub/` and no `tasks/`.** Both appeared in the first draft of this map, written
before the layers were settled. They are one thing, and it is `application/` — the only layer
permitted to know that this course exists (`CLAUDE.md` section 6, and the `PostToolUse` hook that
greps for course vocabulary in `domain/`, `adapters/` and `app/`). Splitting the platform client
from the task modules is a decision for the day there is a second thing to talk to, not for a map.
