"""Whether a failed request is worth repeating, and how long to wait first.

The decision is pure: it reads a response and returns a verdict. Nothing here sends,
sleeps or touches a clock beyond reading it, which is why it can be tested exhaustively
without a network and without waiting.
"""

import random
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from piglet.domain.http.response import HTTPResponse

__all__ = ["RetryDecision", "RetryPolicy"]

# Transient by nature: the same request may well succeed a moment later. A 4xx other
# than 429 says the request itself is wrong, and repeating it changes nothing.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# A reset header holding a value this large is a point in time, not a count of seconds:
# some services send a unix timestamp, others send delta-seconds. Both are in the wild,
# and the magnitude is the only thing that tells them apart.
_EPOCH_THRESHOLD_SECONDS = 1_000_000_000.0


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """The verdict on one failed attempt.

    Attributes:
        should_retry: Whether another attempt is worth making.
        delay_seconds: How long to wait first. Zero when there is no next attempt.
    """

    should_retry: bool
    delay_seconds: float


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff with jitter, deferring to the server when it names a delay.

    Attributes:
        max_attempts: How many attempts one request gets, the first included.
        base_delay_seconds: The wait after the first failure; doubles from there.
        jitter_max_seconds: Upper bound of the random surcharge added to each wait.
        max_total_delay_seconds: Ceiling on the waiting summed over one request.

    Example:
        >>> RetryPolicy().decide(HTTPResponse(404), attempt=1).should_retry
        False
    """

    max_attempts: int = 4
    base_delay_seconds: float = 0.5
    jitter_max_seconds: float = 0.5
    max_total_delay_seconds: float = 60.0

    def decide(self, response: HTTPResponse, attempt: int, delay_used_seconds: float = 0.0) -> RetryDecision:
        """Judge one failed attempt.

        Args:
            response: What came back from the attempt.
            attempt: Which attempt produced it, counting from 1.
            delay_used_seconds: Waiting already spent on this request.

        Returns:
            RetryDecision saying whether to try again and how long to wait first.
        """
        if response.status_code not in _RETRYABLE_STATUS_CODES:
            return _GIVE_UP
        if attempt >= self.max_attempts:
            return _GIVE_UP

        delay_seconds = self._backoff_seconds(attempt)
        requested = _delay_named_by_server(response)
        if requested is not None:
            delay_seconds = max(delay_seconds, requested)

        if delay_used_seconds + delay_seconds > self.max_total_delay_seconds:
            return _GIVE_UP
        return RetryDecision(should_retry=True, delay_seconds=delay_seconds)

    def _backoff_seconds(self, attempt: int) -> float:
        """Compute the wait after `attempt` failures: doubling, plus a random surcharge.

        Args:
            attempt: Which attempt just failed, counting from 1.

        Returns:
            The delay in seconds.
        """
        # Jitter spreads workers that failed together across the window; without it they
        # would all come back at the same instant and hit the same wall again.
        surcharge = random.uniform(0, self.jitter_max_seconds)  # noqa: S311 - spreading load, not generating a key
        doubling = float(2 ** (attempt - 1))
        return self.base_delay_seconds * doubling + surcharge


def _delay_named_by_server(response: HTTPResponse) -> float | None:
    """Read the delay the server asked for, if it asked for one.

    Args:
        response: The response to inspect.

    Returns:
        The requested delay in seconds, or None when no header names one or the
        header cannot be understood.
    """
    retry_after = response.header("Retry-After")
    if retry_after is not None:
        named = _parse_retry_after(retry_after)
        if named is not None:
            return named

    reset = response.header("X-RateLimit-Reset")
    if reset is not None:
        return _parse_rate_limit_reset(reset)
    return None


def _parse_retry_after(value: str) -> float | None:
    """Read a `Retry-After` header, which may be seconds or an HTTP date.

    Args:
        value: The raw header value.

    Returns:
        Seconds to wait, or None when the value is neither form.
    """
    stripped = value.strip()
    with suppress(ValueError):
        return max(float(stripped), 0.0)

    try:
        moment = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    return _seconds_until(moment)


def _parse_rate_limit_reset(value: str) -> float | None:
    """Read an `X-RateLimit-Reset` header, either a unix timestamp or delta-seconds.

    Args:
        value: The raw header value.

    Returns:
        Seconds to wait, or None when the value is not a number.
    """
    try:
        number = float(value.strip())
    except ValueError:
        return None
    if number > _EPOCH_THRESHOLD_SECONDS:
        return max(number - datetime.now(UTC).timestamp(), 0.0)
    return max(number, 0.0)


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


_GIVE_UP = RetryDecision(should_retry=False, delay_seconds=0.0)
