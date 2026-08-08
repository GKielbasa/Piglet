"""Exception hierarchy for the whole library.

Every failure raised by piglet inherits from `PigletError`, so a caller can catch
this library without catching unrelated failures from the runtime. Each handled
error has its own type; nothing is ever swallowed.
"""

from piglet.domain.http.request import HTTPMethod
from piglet.domain.http.retry_policy import GiveUpReason
from piglet.domain.http.service_profile import FailureClass

__all__ = ["HTTPError", "PigletError", "RetryExhaustedError", "TransportError", "UnsafeToRepeatError"]


class PigletError(Exception):
    """Root of the library's exception hierarchy."""


class TransportError(PigletError):
    """No response arrived: the connection failed, timed out or was refused.

    Attributes:
        url: The address the request was sent to.
        cause: What the underlying library raised. Kept rather than only formatted into
            the message, so a caller and a log entry can name the kind of failure.
        failure_class: Whether the failure may pass by itself. Decided by the adapter
            that caught it, which is the only place that knows the library's taxonomy.
        may_have_been_processed: Whether the server may already have acted on the
            request. RFC 9110's own wording. False only when the adapter is certain
            nothing travelled; True whenever it cannot tell, so a request that must not
            be repeated is refused rather than sent twice.
    """

    def __init__(
        self, url: str, cause: Exception, failure_class: FailureClass, may_have_been_processed: bool = True
    ) -> None:
        super().__init__(f"request to {url} never completed: {cause}")
        self.url = url
        self.cause = cause
        self.failure_class = failure_class
        self.may_have_been_processed = may_have_been_processed


class HTTPError(PigletError):
    """A response arrived and its status marks the request as failed.

    Attributes:
        url: The address that answered.
        status_code: The status it answered with.
    """

    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(f"{url} answered with status {status_code}")
        self.url = url
        self.status_code = status_code


class RetryExhaustedError(PigletError):
    """The retry policy gave up before the request succeeded.

    Attributes:
        url: The address that kept failing.
        attempts: How many attempts were made in total.
        failure_class: What kind of failure it kept answering with.
        give_up_reason: Which limit ran out — the attempts or the waiting budget.
        last_status_code: The status of the final attempt, if one arrived.
    """

    def __init__(
        self,
        url: str,
        attempts: int,
        failure_class: FailureClass,
        give_up_reason: GiveUpReason,
        last_status_code: int | None = None,
    ) -> None:
        ending = f"last status {last_status_code}" if last_status_code is not None else "no response ever arrived"
        super().__init__(f"{url} still failing after {attempts} attempt(s): {ending}")
        self.url = url
        self.attempts = attempts
        self.failure_class = failure_class
        self.give_up_reason = give_up_reason
        self.last_status_code = last_status_code


class UnsafeToRepeatError(PigletError):
    """A failure that might have passed, on a request that must not be sent twice.

    Nothing ran out here: we refused to send it again, because the server may already
    have acted on it. The remedy is a change at the call site rather than a longer
    budget, which is why this is not a `RetryExhaustedError`.

    `attempts` is not always 1. A failure the guard exempts — throttling, or one raised
    before the request travelled — is retried, so a later attempt can be the one that
    reaches the guard. The caller needs the count to know how many times the operation
    may already have been carried out.

    Attributes:
        url: The address that failed.
        method: The verb that may not be repeated.
        attempts: How many times the request was sent before we refused to send it again.
        status_code: The status that failed, or None when no response arrived at all.
    """

    def __init__(self, url: str, method: HTTPMethod, attempts: int, status_code: int | None = None) -> None:
        ending = f"answered with status {status_code}" if status_code is not None else "never completed"
        super().__init__(
            f"{method.value} {url} {ending} after {attempts} attempt(s) and may not be repeated automatically"
        )
        self.url = url
        self.method = method
        self.attempts = attempts
        self.status_code = status_code
