"""What we ask of a server, as one immutable value."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = ["HTTPMethod", "HTTPRequest"]


class HTTPMethod(StrEnum):
    """The verbs this library knows how to send."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"

    @property
    def is_idempotent(self) -> bool:
        """Whether sending this verb twice is defined to mean the same as sending it once."""
        return self in _IDEMPOTENT_METHODS


# RFC 9110 §9.2.2: nothing outside this set may be repeated automatically, because the
# server may have processed the first request and died before it could answer.
_IDEMPOTENT_METHODS = frozenset({HTTPMethod.GET, HTTPMethod.HEAD, HTTPMethod.PUT, HTTPMethod.DELETE})


@dataclass(frozen=True, slots=True)
class HTTPRequest:
    """One request, complete enough to be sent, cached and compared by value.

    Attributes:
        method: The verb to send.
        url: Full address, including scheme and any query string.
        headers: Headers to send. Empty by default.
        body: Raw payload, or None for a request that carries none.

    Example:
        >>> HTTPRequest(HTTPMethod.GET, "https://example.com").method
        <HTTPMethod.GET: 'GET'>
    """

    method: HTTPMethod
    url: str
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    body: bytes | None = None

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise ValueError("url must not be empty")
        # Annotations vanish at runtime, so a verb arriving from a file or from
        # configuration would otherwise reach the socket unchecked — and, still a plain
        # string, would have no `is_idempotent` for the retry policy to ask about.
        object.__setattr__(self, "method", HTTPMethod(self.method))
