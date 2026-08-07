"""What a server answered, as one immutable value."""

from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = ["HTTPResponse"]

_SUCCESS_STATUS_CODES = range(200, 300)


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    """One answer: its status, its headers and its raw body.

    The body stays bytes all the way through, so an image survives the trip through
    the cache exactly as it arrived.

    Attributes:
        status_code: The status the server answered with.
        headers: Headers as received.
        body: The raw payload.
    """

    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    body: bytes = b""

    @property
    def is_success(self) -> bool:
        """Whether the status falls in the 2xx range."""
        return self.status_code in _SUCCESS_STATUS_CODES

    @property
    def text(self) -> str:
        """The body decoded as UTF-8, with undecodable bytes replaced."""
        return self.body.decode("utf-8", errors="replace")

    def header(self, name: str) -> str | None:
        """Look up one header, ignoring case.

        Args:
            name: Header name, in any case.

        Returns:
            The value, or None when the response carries no such header.
        """
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None
