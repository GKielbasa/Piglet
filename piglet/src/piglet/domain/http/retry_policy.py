"""Whether a failed request is worth repeating, and how long to wait first.

The decision is pure: it reads a failure class, the response it came from when there was
one, and returns a verdict. Nothing here sends, sleeps or touches a clock beyond reading
it, which is why it can be tested exhaustively without a network and without waiting.

What a status *means* is not here either — that is one service's knowledge and lives in
its profile. This module holds only the mechanism: the attempt count, the window, the
two budgets — waiting and wall clock — and the delay a server asked for.
"""

import math
import random
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum

from piglet.domain.http.response import HTTPResponse
from piglet.domain.http.service_profile import FailureClass

__all__ = ["GiveUpReason", "RetryDecision", "RetryPolicy"]


class GiveUpReason(StrEnum):
    """Why the retrying stopped, when it stopped."""

    PERMANENT_FAILURE = "permanent_failure"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    UNSAFE_TO_REPEAT = "unsafe_to_repeat"


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """The verdict on one failed attempt.

    Attributes:
        delay_seconds: How long to wait before trying again. Zero when there is no
            next attempt.
        give_up_reason: Why we stopped, or None when another attempt is worth making.
            Derived from rather than beside `should_retry`, so a decision cannot both
            retry and explain why it did not.
    """

    delay_seconds: float
    give_up_reason: GiveUpReason | None = None

    @property
    def should_retry(self) -> bool:
        """Whether another attempt is worth making."""
        return self.give_up_reason is None


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Full jitter over a doubling window, deferring to the server when it names a delay.

    Attributes:
        max_attempts: How many attempts one request gets, the first included.
        transient_base_delay_seconds: First window for a failure that may pass by itself.
        throttling_base_delay_seconds: First window for a service holding us back. Longer,
            because a rate limit passes when its window opens rather than in milliseconds.
        max_delay_seconds: Ceiling on one window we compute.
        max_total_delay_seconds: Ceiling on the waiting summed over one request.
        max_total_seconds: Ceiling on the real time one request may spend altogether,
            the sending included. A separate limit from the waiting budget: a service
            answering slowly spends no waiting at all and would otherwise be unbounded.
        jitter_fraction: Draws how much of the window is actually waited. Injected so a
            test can pin the delay exactly.

    Example:
        >>> RetryPolicy().decide(HTTPResponse(404), FailureClass.PERMANENT, attempt=1).should_retry
        False
    """

    max_attempts: int = 4
    transient_base_delay_seconds: float = 0.5
    throttling_base_delay_seconds: float = 1.0
    max_delay_seconds: float = 20.0
    max_total_delay_seconds: float = 60.0
    max_total_seconds: float = 120.0
    jitter_fraction: Callable[[], float] = random.random

    def is_past_deadline(self, elapsed_seconds: float) -> bool:
        """Say whether one request has already spent all the time it is allowed.

        Args:
            elapsed_seconds: Real time this request has consumed so far, the sending
                and the waiting both included.

        Returns:
            True when nothing more may be attempted.
        """
        # The waiting budget compares a delay not yet taken, so landing exactly on its
        # ceiling is harmless. This compares time already spent, so exactly-equal means
        # anything further certainly overruns it — hence `>=` where the sibling has `>`.
        return elapsed_seconds >= self.max_total_seconds

    def decide(
        self,
        response: HTTPResponse | None,
        failure_class: FailureClass,
        attempt: int,
        delay_used_seconds: float = 0.0,
        is_safe_to_repeat: bool = True,
        may_have_been_processed: bool = True,
    ) -> RetryDecision:
        """Judge one failed attempt.

        Args:
            response: What came back from the attempt, or None when nothing did.
            failure_class: What kind of failure it was.
            attempt: Which attempt produced it, counting from 1.
            delay_used_seconds: Waiting already spent on this request.
            is_safe_to_repeat: Whether sending this request a second time is allowed.
            may_have_been_processed: Whether the server may already have acted on this
                attempt. RFC 9110's own wording. False only when it is certain nothing
                travelled; True when we cannot tell, which is the conservative reading.

        Returns:
            RetryDecision saying how long to wait before trying again, or why we stopped.
        """
        if failure_class is FailureClass.PERMANENT:
            return _give_up(GiveUpReason.PERMANENT_FAILURE)
        # RFC 9110 §9.2.2 refuses a repeat because the server may already have acted. Both
        # exemptions are cases where it certainly did not: a rate limiter rejects ahead of
        # the handler, and a failure from before the request travelled reached no handler.
        if not is_safe_to_repeat and may_have_been_processed and failure_class is not FailureClass.THROTTLING:
            return _give_up(GiveUpReason.UNSAFE_TO_REPEAT)
        if attempt >= self.max_attempts:
            return _give_up(GiveUpReason.ATTEMPTS_EXHAUSTED)

        delay_seconds = self._draw_delay_seconds(failure_class, attempt)
        named_by_server = _delay_named_by_server(response)
        if named_by_server is not None:
            delay_seconds = max(delay_seconds, named_by_server)

        if delay_used_seconds + delay_seconds > self.max_total_delay_seconds:
            return _give_up(GiveUpReason.BUDGET_EXHAUSTED)
        return RetryDecision(delay_seconds=delay_seconds)

    def _draw_delay_seconds(self, failure_class: FailureClass, attempt: int) -> float:
        """Draw a wait from the window that `attempt` failures have opened.

        Args:
            failure_class: Which base delay the window starts from.
            attempt: Which attempt just failed, counting from 1.

        Returns:
            The delay in seconds, anywhere between nothing and the whole window.
        """
        base_delay_seconds = (
            self.throttling_base_delay_seconds
            if failure_class is FailureClass.THROTTLING
            else self.transient_base_delay_seconds
        )
        doubling = float(2 ** (attempt - 1))
        window_seconds = min(self.max_delay_seconds, base_delay_seconds * doubling)
        # The whole window is randomised rather than a surcharge added to it: an added
        # tail is a rounding error once the window has doubled a few times, and stops
        # dispersing the workers that failed together.
        return self.jitter_fraction() * window_seconds


def _give_up(reason: GiveUpReason) -> RetryDecision:
    """Build the decision to stop, which never names a delay.

    Args:
        reason: Why the retrying stopped.

    Returns:
        A RetryDecision carrying the reason and no waiting, so a log entry cannot
        record a wait that never happened.
    """
    return RetryDecision(delay_seconds=0.0, give_up_reason=reason)


def _delay_named_by_server(response: HTTPResponse | None) -> float | None:
    """Read the delay the server asked for, if it asked for one.

    Args:
        response: The response to inspect, or None when none arrived.

    Returns:
        The requested delay in seconds, or None when nothing answered, no header names
        one, or the header cannot be understood.
    """
    if response is None:
        return None
    retry_after = response.header("Retry-After")
    if retry_after is None:
        return None
    return _parse_retry_after(retry_after)


def _parse_retry_after(value: str) -> float | None:
    """Read a `Retry-After` header, which may be seconds or an HTTP date.

    Args:
        value: The raw header value.

    Returns:
        Seconds to wait, or None when the value is neither form.
    """
    stripped = value.strip()
    with suppress(ValueError):
        seconds = float(stripped)
        # `float()` also reads `inf` and `nan`, which are delay-seconds under no reading
        # of RFC 9110. An infinite delay wins every comparison `decide()` makes and then
        # ends the retrying on the waiting budget — the opposite of the computed window
        # an unreadable header is meant to fall back to.
        if math.isfinite(seconds):
            return max(seconds, 0.0)

    try:
        moment = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    return _seconds_until(moment)


def _seconds_until(moment: datetime) -> float:
    """Measure how far ahead a moment is, never below zero.

    Args:
        moment: The point in time. Assumed UTC when it carries no zone.

    Returns:
        Seconds from now until then, or 0.0 when it has already passed.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max((moment - datetime.now(UTC)).total_seconds(), 0.0)
