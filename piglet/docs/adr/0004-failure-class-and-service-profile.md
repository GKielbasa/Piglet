# ADR 0004 — The failure class, the service profile, and what a retry is allowed to do

- **Date:** 2026-08-07
- **Status:** accepted
- **Supersedes:** nothing. Refines ADR 0002 decision 2, and withdraws one of the reasons that
  decision gave for writing our own retry policy.

## Context

ADR 0002 chose a hand-written `RetryPolicy` over `tenacity` and gave a reason: the decision we need
is not "retry three times with backoff" but "read what the server said and defer to it". That was
right. Three research notes written on 2026-08-06 measured the result against how AWS, Google,
Azure, urllib3 and Stripe do the same job, and each note ends in a gap table. Those tables are the
source of this ADR.

One finding sits underneath all of them: **the policy answers *whether* to repeat but never *what
went wrong*.** From a bool you cannot derive a base delay, an exception type or a log field. So the
code derived the exception from the attempt number — `if attempt == 1` — which means a 429 whose
`Retry-After` was longer than our budget got reported to the caller as *"the request is wrong"*,
about a response that said only *"too early"*.

The same absence shows on the other side: the statuses worth repeating and the headers worth
believing were constants inside the policy module. A client that hardcodes what one service means
cannot be the universal one this project is for.

And beneath both, the item the notes call the most serious: **every method was retried, POST
included.**

## Decisions

### 1. Three failure classes, carried as a value

AWS classifies failures three ways, not two, and prices them differently: transient at 50 ms base
delay because *"transient errors typically resolve within milliseconds"*, throttling at 1000 ms
because *"the service has rate-limited the request. A longer base delay gives time to recover
capacity"*, permanent not retried at all.

The distinction we did not have: **throttling is not a subtype of a transient failure.** A hiccup
passes by itself in milliseconds; a rate limit passes when the window opens. One backoff for both
means either coming back under the limit too fast, or crawling back from an ordinary stumble.

So `FailureClass` — `TRANSIENT`, `THROTTLING`, `PERMANENT` — becomes a value the profile produces
and everything else consumes. `RetryDecision` stops being a bare bool and carries `GiveUpReason`
alongside the delay, with `should_retry` derived from it, so a decision that retries *and* explains
why it stopped cannot be constructed.

Three things now follow from the class instead of being guessed:

| Give-up reason | Exception | |
|---|---|---|
| `PERMANENT_FAILURE` | `HTTPError` | the request is wrong; a plan B on the same request is pointless |
| `ATTEMPTS_EXHAUSTED` | `RetryExhaustedError` | we tried and stopped |
| `BUDGET_EXHAUSTED` | `RetryExhaustedError` | the same, with `give_up_reason` telling the two apart |
| `UNSAFE_TO_REPEAT` | `UnsafeToRepeatError` | nothing was exhausted — we refused to send it again |

`UnsafeToRepeatError` earns its own type because `RetryExhaustedError` would be a lie here — nothing
ran out, we declined — and a name that misleads costs more than six lines of class definition. It
carries `attempts` for the same reason. Once the guard gained the precondition of decision 3 it
stopped firing only on the first attempt: an exempt failure is retried, so a later attempt can be
the one that reaches the guard, and a caller told merely "not repeated" would conclude the operation
was attempted once. Budget exhaustion does **not** earn its own type: there the name tells the truth
and only the counter that ran out differs, which a field records perfectly well.

The class also becomes a log field, which is where Azure points: *"store a value in your log entries
that indicates whether throttling in the service or other types of faults [...] cause retries. This
approach helps you differentiate the causes during data analysis."* From S03E01 that file is the
evaluation dataset, so the reason we gave up and the delay we actually waited go in beside it — the
delay because under full jitter it is random, and nothing later can reconstruct it.

### 2. The service profile is injected, and it is a value object rather than a `Protocol`

The research draws the line this way, and we adopt it:

| Layer | Holds | Universal |
|---|---|---|
| core | sending, timeouts, the attempt loop, backoff, jitter, the budget, the log, `Retry-After` as a mechanism | yes, written once |
| profile | which statuses mean what | no, one per integration |
| call | whether *this* operation is safe to repeat | no, one per request |

`ServiceProfile` is a frozen dataclass holding two status sets and answering `classify`. Everything
outside both sets is permanent, 3xx included — which changes no behaviour, only names it, since
httpx does not follow redirects and no 301 becomes a 200 by being repeated.

It is deliberately **not a `Protocol`.** Section 7 of CLAUDE.md says a `Protocol` appears with the
second implementation, and the second implementation here would be classification by an error code
in a response body — the thing AWS does when it matches *"on error code first, then falls back to
HTTP status code"*. No service we talk to does that. A frozen dataclass configured per integration
already achieves the goal, which was to get the status set out of the core; when a service needs the
other algorithm it costs four lines and one annotation. An interface per class is the Symfony habit
section 7 exists to prevent.

**This withdraws part of ADR 0002 decision 2.** That ADR justified writing our own policy partly by
`X-RateLimit-Reset` — *"as either a unix timestamp or delta-seconds"* — and recorded the assumption
that the platform actually sends these headers, to be confirmed at S01E05. The IETF draft
standardising rate-limit headers names exactly that field as an interoperability problem: the same
name carries seconds, milliseconds, a unix timestamp or a date depending on who sent it. Telling
them apart by magnitude is guessing, and guessing in the core is a bug waiting for the first service
that disagrees. So the parser and its threshold are **deleted**. The core reads `Retry-After` in both
its RFC 9110 forms and nothing else; a non-standard delay header returns as profile knowledge when a
real service is known to send one.

The rest of ADR 0002 decision 2 stands: `Retry-After` in seconds and as an HTTP date, a fall back to
backoff when the header is missing or unreadable, and a policy that is a pure function and therefore
testable in milliseconds.

### 3. A retry now requires permission

RFC 9110 §9.2.2 is normative: *"A client MUST NOT automatically retry a request with a
non-idempotent method unless it has some means of knowing the request was not processed."* The
scenario it guards is dull and real — the server received the POST, processed it, then died before
answering; the client sees a timeout, repeats, and the operation happens twice.

urllib3 solves it with a default set that excludes POST and PATCH. Stripe solves it from the other
end, with an `Idempotency-Key` header that makes a POST repeatable. Google solves it per operation
rather than per method, with a middle category that is safe only when a precondition is supplied.

We take urllib3's shape: `HTTPMethod.is_idempotent` gives the RFC default, and `send()` takes
`is_safe_to_repeat`, where `None` means *derive it from the method*. The name is not
`is_idempotent`, because a POST carrying an idempotency key is not idempotent in RFC terms — it is
safe to repeat, and that is what the caller is declaring. Generating idempotency keys is not in
scope; there is no service to generate them for.

The declaration is per call, in the same shape `should_cache` already has, because ADR 0002 already
found that verbs are the wrong unit for this kind of decision.

`is_idempotent` is asked of `request.method`, so the verb has to be an enum member by the time the
policy sees it. `HTTPRequest.__post_init__` therefore keeps the value it coerces —
`object.__setattr__(self, "method", HTTPMethod(self.method))` — rather than validating and throwing
the result away. A verb arriving as text from a file or from configuration used to reach the policy
still a `str`, where asking it about idempotency raised `AttributeError`: not a `PigletError`, and
so straight past the CLI's handler as a traceback.

**The guard has a precondition, and it is the RFC's own.** §9.2.2 names one hazard: the server
*received* the request, processed it, and died before answering. It does not say "never repeat a
POST"; it says never repeat one that might already have been carried out. Applied unconditionally
the guard also fires in two situations where it is certain nothing was carried out:

- **A 429.** A rate limiter rejects ahead of the handler, so the response *is* the server stating
  that it did not process the request — exactly the *"means of knowing"* the RFC asks for. Every
  mainstream SDK retries 429 whatever the method.

  The code keys on `FailureClass.THROTTLING`, not on the number 429, and the class comes from the
  injected profile. So **`throttling_statuses` decides more than the base delay: a status placed in
  that set also exempts non-idempotent requests from the guard.** The reasoning above holds for a
  rate limiter and not for an arbitrary status — a 500 called throttling would repeat a POST the
  server may well have carried out. The set is therefore extended only for statuses a service
  genuinely rejects *before* its handler, and that is a constraint on whoever configures a profile
  rather than something the core can check.
- **A failure from before the request travelled.** No byte left the client, so no handler received
  anything to act on.

So `decide()` takes a sixth argument, `may_have_been_processed`, and the guard fires only when the
failure may have been processed **and** is not `THROTTLING`. `PERMANENT` is still judged first, and
being exempt means falling through to the ordinary attempt and budget limits — not retrying without
end.

This is not a refinement of the guard but the condition that makes it usable here. Under the
unconditional form a 429 on a POST was refused after one attempt, which switched the guard off in
precisely the workload it was built for: `/verify` is a POST, and a rate-limited POST run is a run
of 429s.

The argument is named for RFC 9110's own wording rather than for CLAUDE.md section 9's
`is_`/`has_`/`should_` convention for booleans. That is a deliberate, single exception, and it
covers the name wherever it appears — the parameter on `decide()`, the attribute on
`TransportError`, and the transport's `_may_have_been_processed()` helper, which is consequently a
noun phrase where section 9 asks a function for a verb. The convention is worth less here than the
reader recognising the clause the name comes from.

### 4. Full jitter, a ceiling on one delay, a base delay per class

Our jitter was a tail appended to the backoff, and the research shows it stops working as the delay
grows: at `base · 2ⁿ + U(0, 0.5)` the first retry spreads over `[0.5, 1.0]`, but the fifth spreads
over `[8.0, 8.5]` — six percent of noise, which disperses nothing. AWS randomises the whole window
instead:

```
delay = random(0, 1) × min(20_000 ms, base_delay × 2^retry)
```

We adopt that, with `transient_base_delay_seconds = 0.5`, `throttling_base_delay_seconds = 1.0` and
`max_delay_seconds = 20.0`. AWS's 50 ms transient base is refused: it is a number for services inside
AWS's own network behind a token bucket, not for the open internet. urllib3's 120 s ceiling is
refused for a harder reason — our total budget for one request is 60 s, so a 120 s ceiling could
never bind and would be decoration in a constructor.

That argument is uncomfortable next to the field it justifies, so it is answered rather than left to
be noticed: **at the shipped defaults `max_delay_seconds` never binds either.** With
`max_attempts = 4` the last window is computed at attempt 3, giving [0.5, 1.0, 2.0] transient and
[1.0, 2.0, 4.0] throttling; 20 s would first bind at attempt 7. It stays because unlike urllib3's
120 s it *can* bind — a caller who raises `max_attempts` reaches it, and
`test_the_single_delay_cap_binds_a_window_that_would_outgrow_it` exercises exactly that. The
distinction is between a ceiling no configuration can reach and one the default configuration
happens not to.

Full jitter costs something, and the note names it: a draw may return 0.02 and burn an attempt on a
service that needed a second. The per-class base delay is the counterweight, which is precisely why
AWS carries both.

`jitter_max_seconds` disappears, because full jitter has no separate jitter amount. In its place
`jitter_fraction` is injected — the same testability seam as `Sleeper`. Without it, "throttling waits
longer than transient" would be a probabilistic assertion, since one `U(0,1)` draw can hand
throttling the shorter delay.

### 5. A failure that never became a response is retried too, and the core decides its class

`HttpxTransport` turns every httpx failure into our `TransportError`, and the client never caught
it. So a connection reset — the most ordinary transient failure there is — escaped the loop on the
first attempt, while a 503 got three retries. None of the three gap tables caught this, because all
three were reading responses; the classification research names timeouts and dropped connections in
the first line of its transient class and we read past it.

It also left decision 3 quoting a scenario its own code could not reach. The RFC describes a server
that processed the POST and died before answering — the client sees a timeout. Ours saw a timeout
and gave up before the idempotency guard was ever consulted.

The class cannot come from the profile. A connection that never completed carries no information
about the service; there is nothing to interpret, so this is knowledge about the network rather than
about the rival at the other end. Nor is it uniformly transient, and httpx's own hierarchy shows
why — `UnsupportedProtocol` for a scheme we cannot speak and `DecodingError` for a body we cannot
read sit beside `ConnectTimeout` under the same parent.

So the class travels on the exception, set by the one module allowed to know httpx's taxonomy and
already doing that translation. Timeouts, network errors, proxy errors and a remote protocol
violation are transient. An unsupported scheme, a locally malformed request, a decoding failure and
too many redirects are permanent, and go straight back to the caller.

One httpx exception is caught that does not descend from `HTTPError` at all: `InvalidURL` inherits
straight from `Exception`. Without naming it, an address httpx refuses to parse leaves this boundary
as an httpx type carrying no failure class, and the module's first line — *"its exceptions stop at
this boundary"* — is untrue. It is classified permanent: an address we cannot build does not repair
itself by being sent again. The assertion list for this step had placed it out of scope, as noticed
but unfixed; the author accepted it afterwards rather than open a step to close four lines, and it is
recorded here because a decision nobody wrote down is indistinguishable from an accident. The two
remaining httpx exceptions outside `HTTPError` stay uncaught deliberately — `CookieConflict` is
raised by `Cookies.get()` and `StreamError` by the streaming API, and `client.request()` reaches
neither.

Two small revisions follow. `decide()` takes `HTTPResponse | None`, because a failure with no
response has no `Retry-After` to read. And `UnsafeToRepeatError.status_code` becomes optional, since
a POST that timed out never got one.

`RetryExhaustedError` needs nothing: it has carried a *"no response ever arrived"* branch since ADR
0002 and no code path could reach it. This is the one that does.

**How far the request got is a second, independent question.** The failure class says how bad a
failure is and nothing about whether the server saw the request. `ConnectTimeout` and `ReadTimeout`
are both transient and both timeouts, and only one of them means the server may have acted. So a
second classifier sits beside `_classify` and answers only that, feeding decision 3's precondition.

Four types are raised before a byte of the request travels, and they are named leaf by leaf:

```
ConnectError, ConnectTimeout, PoolTimeout, ProxyError
```

Everything else counts as possibly processed, an unrecognised failure included — the same
fail-closed shape the class axis already has. A write-phase failure stays on the conservative side
deliberately: a partial write may still have delivered a complete request.

**The check must name the four leaves rather than a shared base**, because httpx's hierarchy does
not split along this line at all: `ConnectTimeout` and `ReadTimeout` are both `TimeoutException`,
`ConnectError` and `ReadError` are both `NetworkError`. An `isinstance` against either base collapses
the two phases, and the failure is silent — a delivered request exempted from the guard, which is
the one outcome the guard exists to prevent.

`ProxyError` is placed with the never-sent group on evidence rather than on reasoning. Every site
raising it in httpcore 1.0.9 precedes the request: the `CONNECT` tunnel answering outside 2xx, and
three SOCKS handshake failures. The forwarding path, which hands the request straight to the proxy,
never raises it at all. The structure agrees — `ProxyError` descends directly from httpx's own
`TransportError` rather than from `NetworkError`, so a failure after the tunnel stands surfaces as
`ReadError` or `ReadTimeout` instead.

## Consequences

- The exception a caller sees now describes the failure rather than the arithmetic of the loop. A
  429 that outlives the budget says "transient, we ran out of time", not "your request is wrong".
- One new module, `domain/http/service_profile.py`, and one new exception. `domain/ports.py` is
  untouched: a profile performs no I/O and is therefore not a port.
- `RetryPolicy` grows from four fields to six, and `decide()` takes six arguments. That is the
  ceiling: ruff's `max-args` is 6 and does not count `self`, so a seventh parameter fails the gate
  with `PLR0913 (7 > 6)`. The next requirement of this kind forces the class to be split — it is not
  a decision left open.
- Retrying a POST is now a decision somebody made in writing, visible at the call site and in review.
  The course's `/verify` endpoint will need that declaration, and that is the point.
- **A throttled POST is retried**, with backoff, inside the client. Under the guard as first written
  it was refused after one attempt, and the caller had to build its own loop — without the backoff,
  the jitter or the waiting budget the client already owns. The same correction applies from the
  other side: a POST to a host that is temporarily unreachable is retried, because the connection
  never opened.
- `may_have_been_processed` is a named exception to section 9's boolean naming, covering the
  parameter, the attribute and the helper. It is the only one; the next such request is a reason to
  reread section 9, not a precedent.
- The client works out whether the server may have acted and then does not tell the caller.
  `UnsafeToRepeatError` says that it refused, not why. The fact is recoverable — through `__cause__`
  for a transport failure, or from the status code for a response — but not through a stated
  contract, and it is the caller who now has to make the decision the client declined. One attribute
  would close it. Recorded here so it stays a decision rather than becoming an oversight.
- `UnsafeToRepeatError` carries `attempts`, and its message names the count. A caller deciding
  whether to re-issue a POST by hand needs to know how many times it has already gone out, and after
  decision 3's precondition that number is no longer always one.
- `Retry-After` is read only as a finite number of seconds or an HTTP date. `float()` alone also
  accepts `inf` and `nan`; an infinite delay won every comparison and ended the retrying on the
  waiting budget, turning one malformed header into a single-attempt failure — the opposite of the
  computed window an unreadable header falls back to. Fractional and negative values still parse, so
  the accepted assertions covering them keep their meaning; narrowing further to RFC 9110's literal
  `1*DIGIT` would change what two of them test and is deliberately not done here.
- `build_http_client` takes a `ServiceProfile`, defaulting to the standard set. Without it decision
  2's seam existed in the domain and was unreachable from the application: every client the
  composition root built classified statuses by the defaults, and the first integration needing its
  own would have had to edit the composition root — the coupling the profile was extracted to
  remove.
- We lose `X-RateLimit-Reset` support and one assertion with it. The capability returns as a service
  profile the day a service is known to send it — with knowledge of what it means, rather than a
  guess about its magnitude.
- The JSONL log gains `failure_class`, `give_up_reason` and `delay_seconds`. Offline evaluation from
  S03E01 can separate "the service throttled us" from "the service was down" without re-running
  anything.
- A failure that never became a response now costs up to `max_attempts` attempts where it used to
  cost exactly one. A mistyped hostname is therefore retried before it is reported — under two
  seconds of backoff, and the same trade urllib3 makes by default. Its log entry carries a failure
  class and the httpx exception type, and no status code at all.
- Still absent, and named here so nobody re-derives them: a process-wide retry budget (AWS's token
  bucket), which is the real gap under `asyncio.gather`; a circuit breaker; timeouts split into
  connect, read, write and pool. Each waits for the pressure that justifies it.
