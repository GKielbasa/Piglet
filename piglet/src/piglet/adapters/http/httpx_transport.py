"""The wire: httpx does the sending, its exceptions stop at this boundary."""

import httpx

from piglet.domain.http.request import HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.errors import TransportError

__all__ = ["HttpxTransport"]


class HttpxTransport:
    """Sends requests through an httpx client and hands back plain values.

    A failing status is returned like any other answer — judging it belongs to the
    policy. Only the absence of an answer is an error here.

    Attributes:
        client: The injected httpx client. One client keeps its connection pool alive
            across requests, and a test can substitute its own transport.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def send(self, request: HTTPRequest) -> HTTPResponse:
        """Send one request and wait for the answer.

        Args:
            request: What to send.

        Returns:
            The response, whatever its status.

        Raises:
            TransportError: If no response arrived: refused, timed out or unreachable.
        """
        try:
            answer = await self.client.request(
                method=request.method.value,
                url=request.url,
                headers=dict(request.headers),
                content=request.body,
            )
        except httpx.HTTPError as exc:
            raise TransportError(request.url, exc) from exc
        return HTTPResponse(answer.status_code, dict(answer.headers), answer.content)

    async def aclose(self) -> None:
        """Close the client and release its connection pool."""
        await self.client.aclose()
