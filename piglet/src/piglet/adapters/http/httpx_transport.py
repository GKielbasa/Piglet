"""The wire: httpx does the sending, its exceptions stop at this boundary."""

import httpx

from piglet.domain.http.request import HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.domain.http.service_profile import FailureClass
from piglet.errors import TransportError

__all__ = ["HttpxTransport"]

# Two shared bases and two leaves, because httpx's hierarchy only partly splits along
# this line: `LocalProtocolError` and `RemoteProtocolError` are siblings under
# `ProtocolError`, and a request we built wrongly will not repair itself while a peer
# that broke the framing may well have been a one-off.
_FAILURES_THAT_MAY_PASS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.ProxyError,
    httpx.RemoteProtocolError,
)

# Named leaf by leaf rather than by a shared base, because httpx's hierarchy does not
# split along this line at all: `ConnectTimeout` and `ReadTimeout` are both
# `TimeoutException`, `ConnectError` and `ReadError` are both `NetworkError`. Every site
# raising `ProxyError` in httpcore precedes the request, so it belongs here too.
_FAILURES_FROM_BEFORE_THE_REQUEST_TRAVELLED = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.ProxyError,
)


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
            TransportError: If no response arrived: refused, timed out, unreachable, or
                asked for through a URL httpx will not parse.
        """
        try:
            answer = await self.client.request(
                method=request.method.value,
                url=request.url,
                headers=dict(request.headers),
                content=request.body,
            )
        # `InvalidURL` sits outside httpx.HTTPError, so without it here an unusable
        # address would leave this boundary as an httpx exception with no class.
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise TransportError(request.url, exc, _classify(exc), _may_have_been_processed(exc)) from exc
        return HTTPResponse(answer.status_code, dict(answer.headers), answer.content)

    async def aclose(self) -> None:
        """Close the client and release its connection pool."""
        await self.client.aclose()


def _classify(failure: Exception) -> FailureClass:
    """Say whether a failure that produced no response may pass by itself.

    Args:
        failure: What httpx raised.

    Returns:
        TRANSIENT for a failure the network may resolve on its own, PERMANENT for
        everything else — a failure nobody has classified included, so an unknown one
        is reported rather than repeated.
    """
    if isinstance(failure, _FAILURES_THAT_MAY_PASS):
        return FailureClass.TRANSIENT
    return FailureClass.PERMANENT


def _may_have_been_processed(failure: Exception) -> bool:
    """Say whether the server may already have acted on the request that failed.

    A second, independent question from `_classify`: how bad the failure is and how far
    the request got are unrelated axes.

    Args:
        failure: What httpx raised.

    Returns:
        False only for a failure raised before a byte of the request travelled, True for
        everything else — an unrecognised failure and a half-written one included, since
        a partial write may still have delivered a complete request.
    """
    return not isinstance(failure, _FAILURES_FROM_BEFORE_THE_REQUEST_TRAVELLED)
