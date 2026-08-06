# ADR 0002 — The resilient HTTP client: async, own retry, hexagon, typer

- **Date:** 2026-08-06
- **Status:** accepted
- **Supersedes:** nothing. Refines decision 3 of ADR 0001 (primitives first).

> Written in English because CLAUDE.md section 0 requires it of everything on disk.
> ADR 0001 predates that rule and stays as it is; a decision is not edited after the fact.

## Context

The first five lessons all need the same thing before they need anything else: fetch a
resource, send a payload, survive a transient failure, and leave a record. S01E05 states
it outright — the API "is deliberately overloaded and regularly returns 503", and the
task asks to "inspect the HTTP headers of every response" and to "log every call and
response". So the HTTP client is the first primitive, four lessons before the lesson that
justifies it.

Four decisions were open. Each of them is cheap now and expensive in S03.

## Decisions

### 1. Asynchronous from the first line

Every I/O signature is `async`, including the cache, whose implementation is blocking.

S01E02 asks for two calls per person over a list of people, and S01E04 crawls a document
tree. Both are the same shape: many independent requests, each mostly spent waiting. With
`asyncio.gather` the wall-clock cost is the slowest request; sequentially it is their sum.
Measured on three requests to a server delaying 1, 2 and 3 seconds: 3.62 s together,
against 6 s apart.

Doing this later would mean rewriting every signature and every test, because `async`
propagates up the call stack — it cannot be introduced at the bottom without touching
everything above.

Cost: `pytest-asyncio` in every test, and event-loop errors that read badly. The cache
does blocking file I/O inside an `async` method, which is a lie the size of one local
read; it becomes a real question only if the cache ever moves off disk.

### 2. Our own `RetryPolicy` instead of `tenacity`

`tenacity` is the obvious library and it was rejected.

The decision we need is not "retry three times with backoff" — it is "read what the server
said and defer to it": `Retry-After` as seconds or as an HTTP date, `X-RateLimit-Reset` as
either a unix timestamp or delta-seconds, and a fall back to exponential backoff when the
header is missing or unreadable. Expressing that inside `tenacity` means writing the same
logic in the shape of someone else's callbacks, and then owning both.

Written as a pure function of `(response, attempt, delay already spent)`, the policy has no
I/O at all: it never sleeps, never sends, and returns a verdict. That is what makes the
eleven assertions around it testable in milliseconds, including the ones about headers
nobody has seen yet — and it is why `hypothesis` can generate the attempt numbers instead
of us guessing which ones matter.

The educational goal is the tiebreaker: backoff with jitter is a thing to understand once,
not to import.

Cost: ours to maintain. No circuit breaker, no bulkhead — one service, rule of three.

**Assumption, still unconfirmed:** that the platform actually uses these header names.
S01E05 will show. Until then an unknown header degrades to backoff rather than raising, and
`vcrpy` will record what really arrives.

### 3. Hexagonal layering: `domain/`, `adapters/`, `app/`

The layout follows `05_04_api` from the course reference material, minus the DI container.

- `domain/` — values and decisions: request, response, retry policy, cache key, and the
  `Protocol`s the outside world must satisfy. No import of `httpx`, no import of anything
  that does I/O.
- `adapters/` — the world: `httpx`, the filesystem, `structlog`.
- `app/` — configuration and the composition root, where objects are wired by hand.

The point is not tidiness, it is the universality rule of CLAUDE.md section 6: these three
directories may not know the course exists. That boundary is now mechanical — a hook greps
every write to them for course vocabulary and rejects it. Course knowledge will live in
`application/` and in a platform adapter, neither of which exists yet.

Cost: three levels of nesting (`domain/http/retry_policy.py`) against the advice to keep
hierarchies flat, and more ceremony than a project this size would otherwise carry.
Accepted knowingly: flattening later is cheap, separating later is not.

### 4. `typer` for the command line

The logic never reads `sys.argv` and never calls `print`. `app/cli.py` reads arguments,
calls one function from the composition root and echoes the result; `_fetch` takes a
`Settings` and a URL and returns a response.

That keeps FastAPI cheap when it arrives: an HTTP route calls the same function the CLI
calls. `typer` earns its place by deriving the interface from type annotations, so the
signature stays the single source of truth — the same reason `pydantic` is at the process
boundary.

## Consequences

- Retry, cache and logging are decided once, in one place. A task module composes; it does
  not repeat this.
- Caching is opt-in per call (`should_cache`), not a rule about verbs: S01E05 wants a POST
  remembered, and "we cache GETs" would have been wrong on arrival.
- Every attempt leaves a JSONL entry with `run_id`, `status_code`, `attempt` and
  `duration_ms` — the dataset S03E01 needs, recorded from the first request rather than
  reconstructed later.
- Secrets are scrubbed by a logging processor, not by convention. Course addresses carry
  the key **in the path**, so "we do not log headers" would not have been enough.
- The total waiting ceiling outranks the server: when a server asks for 120 s and the
  budget is 60 s, the client stops instead of waiting. Bounded latency was judged worth
  more than eventual success; a caller who disagrees raises `max_total_delay_seconds`.
