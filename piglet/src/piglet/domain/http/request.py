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
        # configuration would otherwise reach the socket unchecked.
        HTTPMethod(self.method)
