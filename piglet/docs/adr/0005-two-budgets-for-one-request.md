# ADR 0005 — Two budgets for one request, and why not one

- **Date:** 2026-08-10
- **Status:** accepted
- **Supersedes:** nothing. Adds a limit ADR 0002 and ADR 0004 do not cover.

## Context

ADR 0002 gave the client a retry budget, `max_total_delay_seconds`, defaulting to 60. Its name
says what it counts and the code agrees: **the sleeping summed over one request**, and nothing
else. `RetryPolicy.decide()` compares `delay_used_seconds + delay_seconds` against it.

What nobody wrote down is that this bounds only a fraction of the time a request can take. Each
failed attempt separately burns `http_timeout_seconds`, which defaults to 30, and
`retry_max_attempts` defaults to 4. Four attempts against an unroutable address therefore cost
about 120 seconds of waiting on sockets, while the budget observes roughly 3 seconds of backoff
and never fires.

The gap was found by a `/code-review max` pass over the ADR 0004 work and confirmed live:

```
$ PIGLET_HTTP_TIMEOUT_SECONDS=2 piglet http get http://10.255.255.1/
error: http://10.255.255.1/ still failing after 4 attempt(s): no response ever arrived
real    0m9.622s
```

Nine seconds where a 2-second timeout and a 60-second sleeping budget both suggest otherwise. At
the real defaults it is about two minutes. ADR 0004 §4 estimated the cost of its own change as
*"under two seconds of backoff"* — true of the sleeping, and silent about the sockets, which is
the larger number.

## Decisions

### 1. A second limit, `max_total_seconds`, counting wall clock

`RetryPolicy` gains `max_total_seconds: float = 120.0` and one method:

```python
def is_past_deadline(self, elapsed_seconds: float) -> bool: ...
```

`GiveUpReason` gains `DEADLINE_EXCEEDED`, which raises `RetryExhaustedError` — the same exception
`BUDGET_EXHAUSTED` raises, with `give_up_reason` telling the two apart, exactly as ADR 0004's
table already does for its pair. `Settings.http_deadline_seconds` feeds it through the
composition root.

The alternative was to **redefine** `max_total_delay_seconds` to count everything, leaving one
limit instead of two. It was rejected on cost, not on taste: the field is load-bearing across
`test_retry_policy.py` — named directly in several tests and indirectly, through the module-level
`WHOLE_WINDOW` and `ZERO_DRAW` policies, in most of the rest — and in ADR 0002. Changing what it
counts while keeping `BUDGET_EXHAUSTED` pointed at it would leave all of them green while they
stopped testing what they were accepted for. That is the failure mode section 5 of `CLAUDE.md` exists to prevent,
and it is worse than carrying two knobs.

The cost of this decision is the two knobs. `max_total_delay_seconds` bounds politeness — how long
we are willing to wait *for* a service. `max_total_seconds` bounds patience — how long the caller
waits for us. They answer different questions and a caller may reasonably set them independently.

### 2. The policy decides; the client supplies the clock

`decide()` does not learn about the deadline. `pyproject.toml` sets `max-args = 6` and `decide()`
already has exactly six, so a seventh was not available — but the split is right on its own terms:
`RetryPolicy` is a frozen, shared value, and the elapsed time of one request belongs to the one
request. The client reads its own clock and asks a pure question.

On the client's side the check is `ResilientHTTPClient._bound_by_deadline`, called once from each
branch of `send()` rather than written inline twice. That is the neighbouring constraint:
`pyproject.toml` also sets `max-complexity = 10` and `send()` already sits exactly on it, so a new
branch inside that function has to be a call. It is **not** an extraction on the second occurrence
in the rule-of-three sense (`CLAUDE.md` section 2) — it is the shape the ceiling permits, and the
`decide → record → give up` sequence around it stays duplicated on purpose.

The clock starts **after** the cache lookup, at the top of the retry loop, so a slow disk cannot
consume a deadline meant for the network.

### 3. `is_past_deadline` compares with `>=`, its sibling with `>`

The two are deliberately different, and it is not an oversight to be tidied away later.

The waiting budget compares a **projected** total: `delay_used + delay > ceiling`. Landing exactly
on the ceiling is harmless, because the ceiling is what we were allowed to spend. The deadline
compares time **already spent**. Allowing exactly-equal there means sleeping and then certainly
exceeding it, so equality must refuse.

## Consequences

### The deadline does not interrupt an attempt in flight

The check sits at attempt boundaries, and it reads the clock **before** the backoff is waited —
`_bound_by_deadline` is consulted in both branches of `send()`, then `await self.sleep(...)`
follows. So an attempt permitted at 119.9 s elapsed still sleeps its backoff and then runs to its
own timeout. Three terms, not two:

```
http_deadline_seconds + one backoff delay + http_timeout_seconds
```

At the defaults the third-attempt window is 2.0 s (`transient_base_delay_seconds=0.5`, doubling),
so **≈152 s, not 120 and not 150.**

`Retry-After` raises it much further, and this is the case worth remembering. `decide()` takes
`max(drawn_window, named_by_server)`, and that result is bounded only by `max_total_delay_seconds`
— never by `max_delay_seconds`, which caps the window we compute rather than the delay a server
asks for. A throttling service naming `Retry-After: 60` therefore gives
`120 + 60 + 30 = ` **210 s** for one `send()`.

`test_a_deadline_does_not_interrupt_an_attempt_already_in_flight` pins the **absence of
cancellation** — a later hand cannot quietly turn the deadline into an abort without that
assertion going red. It does not pin the arithmetic above; nothing does. Observed:

```
$ PIGLET_HTTP_TIMEOUT_SECONDS=2 PIGLET_HTTP_DEADLINE_SECONDS=5 piglet http get http://10.255.255.1/
error: http://10.255.255.1/ still failing after 3 attempt(s): no response ever arrived
real    0m6.456s
```

Six seconds against a five-second deadline is the property, not a bug.

### At the defaults it barely binds

120 seconds is roughly what four 30-second attempts cost anyway. The default does not protect
much; what the decision buys is that the limit **can** be lowered per deployment, and that a run
which hits it now says so — `give_up_reason: deadline_exceeded` in the JSONL — instead of looking
like ordinary attempt exhaustion.

### Cancellation is still out of scope

Bounding the time is not the same as being able to abandon work in flight. Whether `send()` should
cancel a running attempt, and what that means for a request the server may already have processed
under RFC 9110 §9.2.2 (ADR 0004 decision 3), is a separate decision nobody has needed yet.
