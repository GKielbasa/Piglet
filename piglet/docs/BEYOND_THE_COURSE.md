# Beyond the course — what it would take to point this at real work

> **One sentence:** the other documents say what this project *is*; this one says what would have
> to change for it to do work outside the course, and what has already been learned the hard way.

Appended to at the end of a lesson, and only when the lesson moved the answer
(`CLAUDE.md` section 13, step 10).

**Not repeated here**, because it would drift out of date the moment either file changes:

- what exists and how the layers fit — [`ARCHITECTURE.md`](ARCHITECTURE.md)
- what belongs in which directory — [`LAYOUT.md`](LAYOUT.md)
- which lesson brings which module — [`COURSE_MAP.md`](COURSE_MAP.md), whose seams table is the
  answer to "what is still missing"
- why a decision was made — [`adr/`](adr/)

---

## 1. Repointing it: what has to be touched

`application/` is the only directory that knows the course exists, and a `PostToolUse` hook keeps
it that way — so replacing it is most of the work. It is not all of it:

| Touch | Why |
|---|---|
| `application/` | delete, write your own: your data sources, your task modules |
| `app/cli.py` | commands are named after what you do; an entry point has to name something |
| `prompts/` | task-specific prompts are content, not code; the generic ones stay |
| `docs/COURSE_MAP.md` | goes |

One decision matures at that moment. `application/` currently holds both a client for a third
party and the task logic; `COURSE_MAP.md` records that splitting them waits for a second service
to talk to. Any real job has several, so that day arrives immediately: the clients become
adapters, and only the use cases stay in `application/`.

## 2. Pointing it at a different provider

Most local runtimes — Ollama, LM Studio, llama.cpp's server, vLLM — speak the OpenAI-compatible
`/v1/chat/completions` shape, which is what the existing adapter speaks. Two variables:

```
PIGLET_LLM_BASE_URL=http://localhost:11434/v1
PIGLET_LLM_MODEL=<whatever the server calls it>
```

**The one line that gets in the way:** `_build_body` sends `provider: {"require_parameters": true}`
whenever a schema is present — OpenRouter's own routing hint. Most servers ignore unknown fields;
a strict one returns 400. Make it a constructor flag rather than a second adapter when that day
comes: the protocol is shared, only the hint is not.

Where runtimes really differ is **enforced schemas**: `response_format` with `json_schema`,
`response_format` with plain `json_object`, a native `format` field taking a schema, GBNF grammars,
`guided_json`. The dialect `to_strict_json_schema` emits is OpenAI's; check the runtime's own
documentation before assuming it transfers.

A direct `api.anthropic.com` adapter is a bigger job than it looks: `system` is a top-level
parameter rather than a message, structured output is `output_config.format` rather than
`response_format`, the response is a list of content blocks rather than `choices[0]`, `usage`
carries no cost, and current models reject `temperature` outright — which the batched classifier
sets to 0.

## 3. Traps, recorded while fresh

Each of these cost time to find. None of them is visible from the code alone.

- **A 200 can carry a failure.** A provider reports a mid-generation error inside a successful
  response, so the HTTP layer cannot see it and the adapter has to read the body. This is also why
  model calls are not cached: a poisoned 200 would be served back for the whole TTL.
- **`default` in a JSON Schema is rejected** in strict mode — HTTP 400, classified as permanent,
  no retry. Measured, not assumed.
- **A parametrised pydantic generic is named `Batch[Verdict]`** — brackets, which the provider's
  schema-name pattern refuses.
- **A key in a URL path reaches the log**, because every attempt logs its URL. Hand it to
  `configure_logging(secrets=[...])` or it is on disk in clear text.
- **`data/runs/` holds prompts verbatim** and the log's redactor does not run there. Personal data
  in a prompt is personal data on disk: `PIGLET_RECORD_EXCHANGES=false` where that matters.
- **Timeouts are sized for a network, not a CPU.** A local model on a processor can outlast
  `llm_timeout_seconds=120` on a large batch and look like a broken client.
- **`POST` is not retried by default** (RFC 9110 §9.2.2). A completion has no side effect but cost,
  so the adapter passes `is_safe_to_repeat=True`; anything that changes state elsewhere must not.

## 4. First jobs worth pointing it at

**Recon triage — today, with no new module.** Thousands of live hosts out of subdomain enumeration
and HTTP probing. Status codes and ports are a comparison; titles and bodies are prose. Declare a
taxonomy, project each host to one string, call the batched classifier. What is missing is a reader
for your tool's output: a pydantic model and a comprehension.

**A risk map of your own routes — today.** Route, handler name and a slice of the body, classified
along axes like "takes user input", "touches payments", "queries the database", "calls out". It
does not replace a review; it says where to start one.

**Scoring an AI red-team campaign — the scoring half works today**, the attack runs need `tools/`
and `agent/`. Outcomes into a closed set, with the quote that decided each one, gives attack
success rate per technique and per version: a number, and a trend across two runs.

The method behind all three, stripped of this project, is in
`_knowledgeBase/agents/skills/taxonomyClassification.md`.

---

## Log — what each lesson moved

| Lesson | What changed above |
|---|---|
| S01E01 | First entry. Sections 2 and 3 are entirely from this lesson: the provider notes and all seven traps. The classification capability is complete and provider-independent, which is what makes the three first jobs in section 4 possible at all. |
