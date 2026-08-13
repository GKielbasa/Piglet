"""What the domain expects the outside world to provide.

Structural contracts, in the sense of a TypeScript interface: an adapter satisfies one
by having the right methods, never by inheriting from it.
"""

from typing import Protocol

from piglet.domain.http.cache_key import CacheKey
from piglet.domain.http.request import HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.domain.llm.chat import ChatCompletion, ChatRequest

__all__ = ["ChatModel", "HTTPTransport", "ResponseCache", "Sleeper"]


class ChatModel(Protocol):
    """Answers one request from a language model.

    Stateless by contract: a request carries its whole conversation, so an implementation holds
    a connection and credentials and nothing else. Keeping the method single and narrow is what
    lets the capabilities above it — enforced schemas, batching — be written once for every
    provider rather than once per provider.
    """

    async def complete(self, request: ChatRequest) -> ChatCompletion:
        """Ask the model, and wait for what it says.

        Args:
            request: What to ask.

        Returns:
            The answer, together with what it cost.

        Raises:
            ModelCallFailedError: If the provider's answer reports a failure of its own.
            ModelAnswerTruncatedError: If generation stopped at a token ceiling, leaving a
                fragment rather than an answer.
        """
        ...


class HTTPTransport(Protocol):
    """Sends one request and reports what came back, without judging it.

    A failing status is an answer, not an error: deciding what a status means belongs
    to the policy, not to the wire.
    """

    async def send(self, request: HTTPRequest) -> HTTPResponse:
        """Send one request and wait for the answer.

        Args:
            request: What to send.

        Returns:
            The response, whatever its status.

        Raises:
            TransportError: If no response arrived at all.
        """
        ...

    async def aclose(self) -> None:
        """Release whatever the transport holds open."""
        ...


class ResponseCache(Protocol):
    """Remembers responses, so an identical request need not travel twice."""

    async def get(self, key: CacheKey) -> HTTPResponse | None:
        """Read a remembered response.

        Args:
            key: Identity of the request.

        Returns:
            The stored response, or None when nothing valid is stored under that key.
        """
        ...

    async def store(self, key: CacheKey, response: HTTPResponse) -> None:
        """Remember a response under a key.

        Args:
            key: Identity of the request.
            response: What to remember.
        """
        ...


class Sleeper(Protocol):
    """Waits for a while.

    Injected rather than called directly, so a test can record the wait instead of
    taking it and the suite stays fast while still exercising backoff.
    """

    async def __call__(self, seconds: float, /) -> None:
        """Wait.

        Args:
            seconds: How long to wait. Positional, so `asyncio.sleep` — whose own
                parameter is named `delay` — satisfies the contract as it stands.
        """
        ...
