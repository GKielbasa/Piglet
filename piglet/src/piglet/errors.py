"""Exception hierarchy for the whole library.

Every failure raised by piglet inherits from `PigletError`, so a caller can catch
this library without catching unrelated failures from the runtime. Each handled
error has its own type; nothing is ever swallowed.
"""

__all__ = ["HTTPError", "PigletError", "RetryExhaustedError", "TransportError"]


class PigletError(Exception):
    """Root of the library's exception hierarchy."""


class TransportError(PigletError):
    """No response arrived: the connection failed, timed out or was refused.

    Attributes:
        url: The address the request was sent to.
    """

    def __init__(self, url: str, cause: Exception) -> None:
        super().__init__(f"request to {url} never completed: {cause}")
        self.url = url


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
        last_status_code: The status of the final attempt, if one arrived.
    """

    def __init__(self, url: str, attempts: int, last_status_code: int | None = None) -> None:
        ending = f"last status {last_status_code}" if last_status_code is not None else "no response ever arrived"
        super().__init__(f"{url} still failing after {attempts} attempt(s): {ending}")
        self.url = url
        self.attempts = attempts
        self.last_status_code = last_status_code
