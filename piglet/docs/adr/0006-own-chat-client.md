# ADR 0006 — Our own chat client over the resilient HTTP client

- **Date:** 2026-08-11
- **Status:** accepted
- **Supersedes:** nothing. Corrects the LLM row of `CLAUDE.md` section 11, which named the
  `openai` SDK before this decision existed.

## Context

Everything below the model layer is finished: retry, backoff, failure classes, an injectable
`ServiceProfile`, a filesystem cache and one JSONL entry per HTTP attempt. Above it there is
nothing. `openai` is not a dependency and `PIGLET_OPENROUTER_API_KEY` sits in `Settings` unread.

Three statements already in the repository cannot all hold once a model call exists:

1. `CLAUDE.md` section 11 names the **`openai` SDK** pointed at OpenRouter.
2. The same section forbids **"an LLM or HTTP call that bypasses the tooling layer (cache and
   logs must see it)"**.
3. ADR 0001 decision 2 rejects libraries that hide the mechanics the course teaches, and notes
   that the course's own reference examples call the API with a bare `fetch`.

The SDK carries its own transport and its own retry loop. Used as intended it satisfies (1) and
breaks (2): no attempt of ours would appear in `data/logs/`, which is the dataset ADR 0001
decision 4 created two seasons early precisely so that S03E01 would have something to read.

Two facts from OpenRouter's documentation, checked while planning, shape the rest of this ADR:

- **A failure can arrive as HTTP 200.** *"the returned HTTP response status will be 200 OK and any
  error occurred while the LLM is producing the output will be emitted in the response body"*,
  shaped `{"error": {"code", "message"}}`.
- **`usage` is returned on every response and carries `cost`.** The request field
  `usage: {include: true}` is documented as deprecated and without effect.

Its documented status codes — 400/401/402/403 permanent, 408/500/502/503/504 transient, 429 with
`Retry-After` — match the defaults of `ServiceProfile` exactly, so no profile is written for it.

## Decisions

### 1. We write the chat client ourselves, over `ResilientHTTPClient`

Chat Completions is one POST with a JSON body. The adapter builds that body from domain values,
sends it through the client we already have, and validates what comes back into pydantic DTOs.

Rejected: **the SDK as intended** — breaks (2) above. Rejected: **the SDK with a bridging
`httpx` transport delegating to `ResilientHTTPClient`** — it satisfies (2), but the bridge has to
convert `httpx.Request` to `HTTPRequest` and back, disable the SDK's retries so two policies do not
multiply, and would still need our own log entry for model, tokens and cost, because the SDK's
transport sees a URL and a status and nothing else. The remaining benefit was typed request and
response objects, which is the part we most want to write by hand: the author's understanding is
the deliverable (section 0), and translating an API into types is where that understanding forms.

The cost is real and accepted: every capability the SDK ships — streaming, multimodal content
parts, tool-call schemas — arrives here as our code, when a task needs it and not before.

### 2. Three places, and an adapter is allowed to stand on another adapter

`domain/llm/` holds values and the `ChatModel` port. `adapters/llm/` holds the wire.
`llm/` holds capabilities built on the port — the enforced schema, the batched classifier — and
never imports the adapter, so a second provider is a new adapter and nothing else.

The port stays one method wide: `complete(ChatRequest) -> ChatCompletion`. Generics live above it,
in `complete_as[T]`, which also converts a pydantic model into the strict JSON Schema dialect. A
`Protocol` with a generic method is awkward for both type checkers, and every future provider would
otherwise repeat the same validation.

`ARCHITECTURE.md` said dependencies point one way through three layers. It did not say whether an
adapter may depend on another adapter, and this one does: `adapters/llm/` takes a
`ResilientHTTPClient`. That is permitted, and no `HTTPClient` port is introduced to disguise it —
section 7 puts a `Protocol` at the second implementation, and the second HTTP client does not
exist. Its tests build a real client over a scripted transport, the pattern already established in
`tests/adapters/http/test_resilient_client.py`.

### 3. A 200 that carries a failure — nobody caches it, and only the adapter can see it

`ResilientHTTPClient` reads a 200 as success: it neither retries it nor asks the profile about it,
and it writes it to the cache. A mid-generation error from OpenRouter is therefore a poisoned entry
waiting to be replayed for the whole TTL.

So model calls are not cached, and `build_llm_http_client` builds a client with **no cache object
at all** rather than relying on every call site passing `should_cache=False`. Re-running a task
costs the model calls again; that is cents, and the alternative is a run that silently replays a
failure.

The adapter reads the body, and names what it finds: `ModelCallFailedError` for an error object,
`ModelAnswerTruncatedError` for `finish_reason: length`. It does not loop. One retry — for a
provider error only — belongs to `classify_in_batches`, which knows what losing a batch costs. A
truncated or schema-violating answer is not retried at all: at `temperature=0` the second attempt
buys the same failure at the same price, and both point at a fix (a larger token budget, a model
that honours schemas) rather than at bad luck.

### 4. What deterministic code can decide, it decides

The model is asked only what code cannot answer. Filter before classifying, never classify then
filter. Deduplicate identical inputs and reuse the verdict. Compute what is derivable — a birth
year from an age range — in code.

This is not an optimisation policy; it is where correctness comes from. A model call is the only
step in a pipeline that can be wrong without failing, so every record kept away from it is a record
that cannot be misclassified.

## Consequences

- **The JSONL gains a second event.** `llm_call_finished` carries the model asked for and the model
  that answered, the outcome, finish reason, token counts, cost and duration. Without it the log
  shows only that something POSTed to `/chat/completions`, because that URL never varies.
- **`ChatRequest` carries a field the wire never sees** — `prompt_name`, so the log can say which
  prompt produced a call. Metadata on a request value is a small price for a log that S03E01 can
  group by.
- **Changing provider is a new adapter and nothing above it moves.** ADR 0001 already named this as
  the test of whether the abstraction is right; this is where it becomes checkable.
- **The correction to `CLAUDE.md` is part of this decision, not a side effect.** A session that read
  the stack table alone would reach for the SDK and be right to.
- **Streaming is not bought.** When a task needs tokens as they arrive, it is our parser that has to
  grow one. Nothing in this decision makes that easier than it would have been.
