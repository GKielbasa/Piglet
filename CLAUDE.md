# CLAUDE.md

Working rules for the `piglet` project. Binding on the coding agent (Claude Code).

**Everything written to disk is English** — code, names, comments, docstrings, error
messages, documentation, commit messages. No exceptions. Conversation with the author
may be in Polish; the repository never is. The only Polish in this tree is `_teoria/`,
which holds course transcripts as received.

---

## 0. Overriding context

The project is built alongside the AI_devs 4: Builders course, taken for the second time.

**The goal is not the flag.** The flag is a by-product. The goal is a universal toolkit
for an agent, and the author's understanding of how it works. Code the author cannot
explain is a failure — even if it runs and yields the flag.

The author is a PHP/Symfony developer who also knows Node, TypeScript and React, and
thinks in objects and DDD. When explaining Python, reach for those analogies — but do
not transcribe Symfony into Python (see section 6).

---

## 1. Think before writing code

Do not assume. Do not hide uncertainty. Name the trade-offs.

- State assumptions out loud. If unsure — ask.
- If several readings exist, present them. Do not pick one silently.
- If a simpler approach exists — say so. Push back when you have grounds.
- If something is unclear, stop and name what is unclear.

**Do not create project structure or modules nobody asked for.** An architecture
proposal is text to discuss, not files on disk.

## 2. Simplicity first

The least code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstraction for code used once. **Rule of three** — abstract on the third
  occurrence, not the first.
- No "flexibility" or "configurability" nobody requested.
- No error handling for impossible scenarios.
- If you wrote 200 lines where 50 suffice — write it again.

A directory and a module come into being with the first line of their own code, never
in advance. Future modules are described in `docs/ARCHITECTURE.md`, not created as
empty packages.

## 3. Surgical changes

Touch only what you must. Clean up after yourself and nobody else.

- Do not "improve" neighbouring code, comments or formatting.
- Do not refactor things that are not broken.
- Dead code you notice — report it, do not delete it.
- Do remove imports and variables that **your** change orphaned.

The test: every changed line must be derivable from the author's request.

## 4. Goal-driven execution

Define the success criterion, then loop until it is verified. For multi-step work,
present the plan as `step → definition of done` (section 5a).

## 5. Spec ownership

The risk when one agent writes both the code and the tests is *test inversion*: the test
starts confirming the behaviour of the code instead of the author's requirements.

So for the tooling layer (`tools/`, `core/`, `llm/`, `hub/` — whatever comes to exist):

1. First present **the assertions alone** — test names and conditions, no implementation.
2. Wait for the author to accept them.
3. Only then write the implementation.

This does not apply to course-task modules, and we write no unit tests for them: they are
non-deterministic, the flag verifies them, and from S03E01 onwards, evaluations do.

## 5a. Planning and plan mode

### When plan mode is mandatory

- a new module or a new directory,
- a change touching more than two files,
- an architectural decision,
- anything in the tooling layer.

A typo, a one-line fix or an obvious bug — no plan.

### Method: first principles, five steps in a fixed order

The order matters. Choosing a library at step one is the most common mistake — it bends
the problem to fit the tool instead of the other way round.

1. **Facts.** What do I know for certain? The task text, the data format, API limits.
   Quote the source; do not paraphrase from memory.
2. **Necessities.** Which operations *must* happen to turn those facts into the result?
   A technology-independent list — no library names at this stage.
3. **The core.** Which generic problem does this illustrate (section 6)? Skip this step
   and you get single-use code that dies when the input changes.
4. **Assumptions.** What am I taking for granted without certainty? Named explicitly and
   separately, so the author can refute them before code exists.
5. **Tools.** Only now: the simplest arrangement that delivers points 2–3.

### What a plan must contain

- the core of the task (step 3),
- the list of files to be created or changed,
- steps in `step → definition of done` form (see below),
- risks and uncertain areas,
- an explicit **"what I am deliberately not doing"** — scope left outside on purpose.

### Definition of done

A step is not planned until it says how it will be proven. "Assertions green" describes
a state; a definition of done names **the exact command** and **the output that counts
as proof**.

It is written **before** the implementation and accepted together with the assertions
(section 5). Written afterwards, it describes what was built instead of what was asked
for — test inversion moved up one level.

The form varies with the kind of work, and saying so honestly beats inventing a check:

| Kind of work | What proves it is done |
|---|---|
| pure logic | a run over a set of inputs, decisions printed, plus green tests |
| I/O adapter | a real write and read — the file on disk and its contents |
| configuration | the object printed: secrets masked, paths correct |
| observability | the log file exists, carries the required fields, grep for a secret is empty |
| types only (`Protocol`) | `mypy --strict` green — there is nothing to run |
| task module | real input → result → flag |
| documentation, ADR | **no run** — the author's review closes it, and the plan says so |

### What a plan does not contain

Code. A plan is a decision, not an implementation. A snippet is admissible only to
illustrate a signature or a contract awaiting approval — never as a finished function body.

### When an ADR is needed instead of a plan

When the decision is hard to reverse, or will be questioned a month from now. A plan
describes *how we do it now*; an ADR describes *why this way and not another* — and stays
permanently. ADRs are not edited; a stale decision is superseded by a newer ADR.

---

## 6. Universal tools — the overriding architectural rule

We build **tools for an agent**, not solutions to course tasks. A tool that stops working
when the input changes is worthless.

From every task we extract **the core** — the generic problem it illustrates — and
implement that. Example from S01E01: the task asks to find people from Grudziądz working
in transport. The core is not filtering people; it is *classifying records into a closed
taxonomy using a model, with an enforced response schema and batching*.

**Universality test:** if the name, signature or docstring of a tool contains anything
from the course domain — `ag3nts`, `people`, `flag`, `powerplant`, `hub` — it is not a
tool, it is a task. Tools do not know AI_devs exists.

The consequence: **a task module is thin.** It fetches data, composes calls to universal
tools, and hands back the result. All the substance lives in the tools.

---

## 7. Objects — when a class, when a function

We program with objects, but **Python-style objects**, not Java-style.

**A class** — when at least one holds:
- the object has state and a lifecycle (an HTTP client with a session, a cache, an API
  client holding a key),
- two implementations of the same contract exist, or certainly will,
- you want constructor-injected dependencies for testability.

**A function** — when it is a pure transformation: input → output, no state.
Computing a distance, parsing a row, assembling a prompt.

**Always:**
- **Composition over inheritance.** Inherit only to share implementation, never for the
  contract alone.
- **Constructor injection.** Dependencies arrive through `__init__`, not by importing a
  global singleton. There is no DI container — objects are assembled explicitly by a
  *composition root* at the application entry point.
- **Contracts via `Protocol`**, not `ABC`. `Protocol` is a structural interface, the
  equivalent of TypeScript's `interface`. Use `ABC` only when sharing implementation.
- A constructor with 7+ parameters means the class carries too much responsibility —
  split the class, do not abandon injection.
- Keep composition shallow, 2–3 levels. Deeper nesting is unreadable.

**Forbidden (Symfony habits that spoil Python):**
- A DI container with autowiring. We assemble objects by hand, explicitly.
- An interface for every class. A `Protocol` appears with the second implementation.
- Private fields with a getter and a setter. Attributes are public; `@property` only when
  the value is computed or validated.
- One class per file. A module groups related things.
- Entities and repositories without a database. There is nothing to represent.
- A class with a single `execute()` method. That is a function.

---

## 8. Types and contracts

Typing is complete, at the level of TypeScript with `strict: true`. `mypy --strict` is
our `tsc` and it must pass. Remember: annotations vanish at runtime, exactly like types in
TS — which is why validating external data is a separate layer (pydantic ≈ zod).

### The contract rule

> **No `dict[str, Any]` crosses a module boundary.** Everything entering the application
> from outside (HTTP, a file, a model response) and everything leaving it takes the form
> of a pydantic model. A `dict` lives inside a single function only, between
> deserialization and building the model.

### Choosing the construct

| Role | Construct | When |
|---|---|---|
| DTO — process boundary | `pydantic.BaseModel` | data from HTTP, files, model responses |
| Value Object — domain | `@dataclass(frozen=True, slots=True)` | immutable, equality by value |
| Contract | `Protocol` | when two implementations exist |
| Closed set of values | `Literal` / `StrEnum` | tags, levels, statuses |
| Distinguishable identifier | `NewType` | see below |

### When to create your own type

Three cases only. Outside them, leave `str` / `int`:

1. **Two `str` values are confusable at the call site** — `NewType("ApiKey", str)`.
2. **The value carries an invariant** — a VO validating in `__post_init__`.
3. **The set of values is closed** — `Literal` or `StrEnum`, never a loose `str`.

`Name = NewType("Name", str)` without one of these reasons is noise, not DDD.

### Generics

PEP 695 syntax (Python 3.12+), no imported `TypeVar`:

```python
class Cache[T]:
    def get(self, key: str) -> T | None: ...

async def classify[T: BaseModel](records: Sequence[str], schema: type[T]) -> list[T]: ...
```

Introduce a generic when the tool genuinely has to work for several types — not for
decoration.

---

## 9. Naming

**The overriding criterion:** a developer who knows nothing about AI agents or the AI_devs
course must understand everything after reading the code. A name carries domain meaning,
not implementation mechanics.

- PEP 8: `PascalCase` classes, `snake_case` functions and variables, `UPPER_SNAKE`
  constants, `_leading_underscore` private. Acronyms in class names stay upper:
  `HTTPClient`.
- Files and modules are descriptive, unabbreviated: `retry_policy.py`, not `rtr_pol.py`.
- A function is a verb (`fetch_document`), a class is a noun (`DocumentFetcher`).
- Booleans start with `is_` / `has_` / `should_`.
- **Forbidden in names:** `data`, `info`, `manager`, `helper`, `utils`, `handler`,
  `process`, `do_`, `tmp`, `result2`. They mean nothing.
- A name says **what** and **why**, not **how**. `deduplicate_by_checksum`, not
  `loop_and_compare`.
- Imports are always absolute, never relative.

---

## 10. Comments and docstrings

### Comments — WHY only

A comment explains **the reason**, never the content of the line. Code says *what* it
does; when it does not, the problem is a bad name, not a missing comment.

```python
# Bad — repeats the code
# increment the counter
counter += 1

# Good — explains a decision the reader cannot infer
# The Hub rate-limits per minute, so a fixed backoff would still hit the wall on retry.
# Jitter spreads concurrent workers across the window.
delay = base_delay * 2**attempt + random.uniform(0, 1)
```

A justified WHY comment covers: a workaround for someone else's bug, a non-obvious
algorithmic choice, a requirement of an external API, a deliberate trade-off.

### Docstrings — Google style

A docstring for every public class, method and function. A simple function — one line.
A complex one — full sections.

```python
def process_batch(
    items: list[Item],
    max_workers: int = 4,
    on_progress: Callable[[int, int], None] | None = None,
) -> BatchResult:
    """Process items concurrently using a worker pool.

    Processes each item using the configured number of workers. Progress can be
    monitored via the optional callback.

    Args:
        items: The items to process. Must not be empty.
        max_workers: Maximum concurrent workers. Defaults to 4.
        on_progress: Optional callback receiving (completed, total) counts.

    Returns:
        BatchResult containing succeeded items and any failures with their
        associated exceptions.

    Raises:
        ValueError: If items is empty.
        ProcessingError: If the batch cannot be processed.
    """
```

A class documents its role, `Attributes` and `Example`. A docstring does not restate the
signature — types live in annotations, not in prose.

---

## 11. Stack

The decisions are made; the reasoning lives in `docs/adr/`.

| Area | Choice | Note |
|---|---|---|
| Dependencies | **uv** | never `pip install` in this project |
| Python | 3.12+ | PEP 695 generic syntax |
| HTTP | **httpx** | sync and async under one API, swappable transport in tests |
| LLM | **openai SDK** → OpenRouter | `base_url` pointed at OpenRouter, Chat Completions |
| Tabular data | **pandas** | inside the processing layer, never at a boundary |
| Validation / DTO | **pydantic** v2 | process boundaries |
| Logging | **structlog** | logs as data (JSONL), not text — for evaluations from S03E01 |
| Lint / format | **ruff** | `line-length = 120` |
| Types | **mypy --strict** | |
| Tests | **pytest** | |
| HTTP API | **FastAPI** | deferred; arrives with a UI or at S03E03 |

The rule that keeps FastAPI cheap: **logic never reads `sys.argv` and never calls
`print()`.** A function takes arguments and returns a value. CLI and HTTP are shells only.

### Forbidden

- A secret in code, in a system prompt or in a log. Always configuration + `SecretStr`.
- A hardcoded model name in a task module — take it from configuration.
- An LLM or HTTP call that bypasses the tooling layer (cache and logs must see it).
- `except Exception` without re-raising. Every handled error has its own type.
- Swallowing an error silently.

---

## 12. Quality gates

```bash
uv run ruff format .        # formatting
uv run ruff check --fix .   # lint
uv run mypy                 # types, strict
uv run pytest -q            # tests
```

All four must be green before you report a task as done. Do not argue with the linter —
the configuration lives in `pyproject.toml`.

The gates are automated and **cannot be skipped**: a `PostToolUse` hook runs ruff and mypy
after every `.py` write, and a `Stop` hook runs all four when a turn tries to end. Both
live in `.claude/hooks/`.

### Acceptance — evidence, not assertion

> **A step is closed by the output of a run, never by a word.**

Green gates say the code is coherent. They do not say it does what we agreed. Before
reporting a step as done, **run the thing you just wrote** and paste what came back.

1. Execute the step's definition of done (section 5a) — the real program, real files,
   real network where that is the point.
2. **Paste the output.** Not a summary of it, not a claim about it.
3. **Forbidden words: "works", "done", "verified" without that output.** The author
   looks at the result of a run, not at your assurance.
4. If the output is wrong, fix it and run again — before writing that the step is closed.

Unit tests check what you yourself wrote into the test. A run checks reality, which is
why it cannot be bent to match the implementation (cf. section 5).

Collect these runs into a script only once the same checks are worth repeating — rule
of three (section 2). A script written before there is a program to run ends up testing
the linter configuration instead.

---

## 13. Workflow for one course lesson

1. The author reads the lesson in `_teoria/`.
2. **Extract the core**: which generic problem the task illustrates (section 6).
3. Update `docs/COURSE_MAP.md`: core → the tool that implements it.
4. A hard-to-reverse decision → an ADR in `docs/adr/`.
5. Plan mode using the first-principles method (section 5a), accepted by the author.
6. Tooling layer: assertions → acceptance → implementation (section 5).
7. A thin task module, a run, the flag.
8. Quality gates.
9. Acceptance: execute the step's definition of done, paste the output (section 12).

---

## 14. Course context

- Lesson transcripts: `_teoria/` (Polish markdown, `sXXeYY-*.md`). Gitignored — course
  material, not ours to redistribute. There is no file for S01E03, only a video transcript.
- Course map: `docs/COURSE_MAP.md`.
- Architectural decisions: `docs/adr/`.

### JS/TS reference material

`_exampleCode/4th-devs/` — **to read, not to copy.** Also gitignored. We write our own
implementation in Python, often against a different endpoint (the course uses the
Responses API; we use Chat Completions through OpenRouter). Rewriting from TS to Python is
part of the learning: it forces understanding, which copying does not.

Usefulness ranking, best first:

| Example | Why it is worth reading |
|---|---|
| **`05_04_api`** | **The main architectural reference.** Hexagonal architecture: `src/domain/` (ports and types), `src/application/` (use cases), `src/adapters/` (http, ai/openai, ai/google, mcp, observability), `src/app/` (composition root). The same layout as Symfony but without a DI container — exactly what we are building. |
| `05_01_agent_graph` | many agents, scheduler, memory, dashboard |
| `02_05_agent` | agents as markdown files in a workspace |
| `04_01_garden` | a knowledge base as a filesystem, predecessor of the "garden" from S05E05 |
| `05_04_ui` | the client for `05_04_api`, once we reach the interface |
| `01_05_agent` | an older agent server (Hono + drizzle); superseded by `05_04_api` |

Outside the checkout: the **Wonderlands** project from S05E05 (a production agent,
client/server monorepo, sandbox, MCP in Code Mode, context compression via Observational
Memory). The ZIP link is in `_teoria/s05e05-secret-1775803400.md`. It is absent from
`_exampleCode/4th-devs`, which ends at `05_04_ui`.
