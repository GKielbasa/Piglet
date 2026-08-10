"""One request in, one response out — retries, cache and a log entry per attempt."""

import time
from types import TracebackType
from typing import NoReturn, Self

import structlog
from structlog.typing import FilteringBoundLogger

from piglet.domain.http.cache_key import CacheKey, compute_cache_key
from piglet.domain.http.request import HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.domain.http.retry_policy import GiveUpReason, RetryDecision, RetryPolicy
from piglet.domain.http.service_profile import FailureClass, ServiceProfile
from piglet.domain.ports import HTTPTransport, ResponseCache, Sleeper
from piglet.errors import HTTPError, RetryExhaustedError, TransportError, UnsafeToRepeatError

__all__ = ["ResilientHTTPClient"]


class ResilientHTTPClient:
    """Sends a request and keeps at it while the failure looks transient.

    Every attempt leaves a log entry, so a run can be reconstructed afterwards from
    the log alone. Caching is decided per call: the same address may be worth
    remembering in one place and pointless to remember in another.

    Attributes:
        transport: What actually sends.
        retry_policy: Decides whether to try again and how long to wait first.
        profile: What this service's statuses mean. A different service gets a
            different profile without a line of the client changing.
        sleep: How waiting happens. Injected so a test can record it instead.
        cache: Where answers are remembered, or None when caching is switched off.
        logger: Where attempts are recorded.

    Example:
        >>> async with ResilientHTTPClient(transport, RetryPolicy(), ServiceProfile(), asyncio.sleep) as client:
        ...     answer = await client.send(HTTPRequest(HTTPMethod.GET, "https://example.com"))
    """

    def __init__(
        self,
        transport: HTTPTransport,
        retry_policy: RetryPolicy,
        profile: ServiceProfile,
        sleep: Sleeper,
        cache: ResponseCache | None = None,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        self.transport = transport
        self.retry_policy = retry_policy
        self.profile = profile
        self.sleep = sleep
        self.cache = cache
        self.logger = logger or structlog.get_logger()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.transport.aclose()

    async def send(
        self, request: HTTPRequest, should_cache: bool = False, is_safe_to_repeat: bool | None = None
    ) -> HTTPResponse:
        """Send a request, retrying while the policy says the failure may pass.

        Args:
            request: What to send.
            should_cache: Whether this answer may be read from and written to the cache.
            is_safe_to_repeat: Whether sending this request twice is acceptable. None
                derives it from the method, which is the RFC 9110 default; pass True for
                an operation the server makes repeatable by other means.

        Returns:
            The successful response.

        Raises:
            HTTPError: If the answer was a failure the profile calls permanent — the
                request itself is wrong, so trying again changes nothing.
            RetryExhaustedError: If the failure might have passed but outlived the
                attempts, the waiting budget or the deadline the policy allowed.
            UnsafeToRepeatError: If the failure might have passed but this request may
                not be sent a second time.
            TransportError: If nothing answered and the failure is one the transport
                calls permanent — an address httpx will not parse, a scheme we cannot
                speak. A transient one is retried and arrives as one of the two above.
        """
        key = compute_cache_key(request) if should_cache and self.cache is not None else None
        remembered = await self._recall(request, key)
        if remembered is not None:
            return remembered

        if is_safe_to_repeat is None:
            is_safe_to_repeat = request.method.is_idempotent
        delay_used_seconds = 0.0
        attempt = 0
        # Started here rather than at the top of `send`, so a slow disk in the cache
        # lookup above cannot consume a deadline meant for the network.
        retrying_started = time.perf_counter()
        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                response = await self.transport.send(request)
            except TransportError as failure:
                duration_ms = _elapsed_ms(started)
                decision = self.retry_policy.decide(
                    None,
                    failure.failure_class,
                    attempt,
                    delay_used_seconds,
                    is_safe_to_repeat,
                    failure.may_have_been_processed,
                )
                decision = self._bound_by_deadline(decision, retrying_started)
                self._record_attempt(request, attempt, duration_ms, failure, decision, failure.failure_class)
                if decision.give_up_reason is not None:
                    _give_up(request, attempt, failure, failure.failure_class, decision.give_up_reason)
            else:
                duration_ms = _elapsed_ms(started)
                if response.is_success:
                    self._record_attempt(request, attempt, duration_ms, response)
                    if key is not None and self.cache is not None:
                        await self.cache.store(key, response)
                    return response

                failure_class = self.profile.classify(response)
                decision = self.retry_policy.decide(
                    response, failure_class, attempt, delay_used_seconds, is_safe_to_repeat
                )
                decision = self._bound_by_deadline(decision, retrying_started)
                self._record_attempt(request, attempt, duration_ms, response, decision, failure_class)
                if decision.give_up_reason is not None:
                    _give_up(request, attempt, response, failure_class, decision.give_up_reason)

            await self.sleep(decision.delay_seconds)
            delay_used_seconds += decision.delay_seconds

    def _bound_by_deadline(self, decision: RetryDecision, retrying_started: float) -> RetryDecision:
        """Turn a decision to try again into one to stop, once the deadline has passed.

        Asked in every branch that has a decision, and before the attempt is recorded:
        a log entry must carry the reason we stopped rather than a delay never waited.

        Args:
            decision: What the policy made of the attempt that just failed.
            retrying_started: The `time.perf_counter()` reading from when the first
                attempt of this request began.

        Returns:
            The decision unchanged when time remains, or one naming the deadline. A
            decision that has already given up keeps the reason it gave.
        """
        if decision.should_retry and self.retry_policy.is_past_deadline(time.perf_counter() - retrying_started):
            return RetryDecision(delay_seconds=0.0, give_up_reason=GiveUpReason.DEADLINE_EXCEEDED)
        return decision

    def _record_attempt(
        self,
        request: HTTPRequest,
        attempt: int,
        duration_ms: float,
        outcome: HTTPResponse | TransportError,
        decision: RetryDecision | None = None,
        failure_class: FailureClass | None = None,
    ) -> None:
        """Write the log entry for one attempt, once its verdict is known.

        A field that does not apply is absent rather than null, and the delay is written
        down as it is drawn: under full jitter nothing later can reconstruct it.

        Args:
            request: What was sent.
            attempt: Which attempt this was, counting from 1.
            duration_ms: How long the sending itself took, the waiting excluded.
            outcome: The answer, or the failure that came instead of one.
            decision: What the policy made of it, or None when the attempt succeeded.
            failure_class: What kind of failure it was, or None when it succeeded.
        """
        entry = self.logger.bind(
            url=request.url,
            method=request.method.value,
            attempt=attempt,
            duration_ms=duration_ms,
            cache_hit=False,
        )
        if isinstance(outcome, TransportError):
            entry = entry.bind(transport_error=type(outcome.cause).__name__)
        else:
            entry = entry.bind(status_code=outcome.status_code)
        if failure_class is not None:
            entry = entry.bind(failure_class=failure_class)
        if decision is not None and decision.give_up_reason is not None:
            entry = entry.bind(give_up_reason=decision.give_up_reason)
        if decision is not None and decision.should_retry:
            entry = entry.bind(delay_seconds=decision.delay_seconds)
        entry.info("http_attempt_finished")

    async def _recall(self, request: HTTPRequest, key: CacheKey | None) -> HTTPResponse | None:
        """Look for a remembered answer and record the hit.

        Args:
            request: The request being answered, for the log entry.
            key: Identity of the request, or None when this call skips the cache.

        Returns:
            The remembered response, or None when there is nothing to serve.
        """
        if key is None or self.cache is None:
            return None
        remembered = await self.cache.get(key)
        if remembered is None:
            return None
        self.logger.info(
            "http_attempt_finished",
            url=request.url,
            method=request.method.value,
            status_code=remembered.status_code,
            attempt=0,
            duration_ms=0.0,
            cache_hit=True,
        )
        return remembered


def _elapsed_ms(started: float) -> float:
    """Measure the milliseconds since a `time.perf_counter()` reading.

    Args:
        started: The reading taken when the work began.

    Returns:
        How long it took, in milliseconds.
    """
    return round((time.perf_counter() - started) * 1000, 3)


def _give_up(
    request: HTTPRequest,
    attempts: int,
    outcome: HTTPResponse | TransportError,
    failure_class: FailureClass,
    give_up_reason: GiveUpReason,
) -> NoReturn:
    """Raise what the caller should see, given why the retrying stopped.

    Args:
        request: What was being sent.
        attempts: How many attempts were made in total.
        outcome: The answer we stopped on, or the failure that came instead of one.
        failure_class: What kind of failure it was.
        give_up_reason: Why we stopped.

    Raises:
        TransportError: The failure itself, when nothing ever answered and repeating it
            would not help — there is nothing to add to what it already says.
        HTTPError: When the answer marks the request itself as wrong.
        UnsafeToRepeatError: When the failure might have passed, but this request may
            not be sent twice.
        RetryExhaustedError: When the attempts, the waiting budget or the deadline ran out.
    """
    if isinstance(outcome, TransportError):
        if give_up_reason is GiveUpReason.PERMANENT_FAILURE:
            raise outcome
        if give_up_reason is GiveUpReason.UNSAFE_TO_REPEAT:
            raise UnsafeToRepeatError(request.url, request.method, attempts) from outcome
        raise RetryExhaustedError(request.url, attempts, failure_class, give_up_reason) from outcome
    if give_up_reason is GiveUpReason.PERMANENT_FAILURE:
        raise HTTPError(request.url, outcome.status_code, attempts)
    if give_up_reason is GiveUpReason.UNSAFE_TO_REPEAT:
        raise UnsafeToRepeatError(request.url, request.method, attempts, outcome.status_code)
    raise RetryExhaustedError(request.url, attempts, failure_class, give_up_reason, outcome.status_code)
