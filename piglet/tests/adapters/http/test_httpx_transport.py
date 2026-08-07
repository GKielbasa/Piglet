import httpx
import pytest

from piglet.adapters.http.httpx_transport import HttpxTransport
from piglet.domain.http.request import HTTPMethod, HTTPRequest
from piglet.domain.ports import HTTPTransport
from piglet.errors import TransportError


def build_transport(handler: httpx.MockTransport) -> HttpxTransport:
    return HttpxTransport(httpx.AsyncClient(transport=handler))


def test_it_satisfies_the_http_transport_port() -> None:
    # Checked by mypy, not by the assertion: the annotation is the test.
    port: HTTPTransport = build_transport(httpx.MockTransport(lambda _: httpx.Response(200)))

    assert isinstance(port, HttpxTransport)


async def test_what_was_sent_arrives_and_what_answered_comes_back() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, headers={"X-Trace": "abc"}, content=b"created")

    transport = build_transport(httpx.MockTransport(answer))
    response = await transport.send(
        HTTPRequest(HTTPMethod.POST, "https://example.com/verify", {"Accept": "text/csv"}, b'{"answer": 42}')
    )

    assert seen[0].method == "POST"
    assert seen[0].headers["accept"] == "text/csv"
    assert seen[0].content == b'{"answer": 42}'
    assert response.status_code == 201
    assert response.header("x-trace") == "abc"
    assert response.body == b"created"


async def test_a_failing_status_is_an_answer_not_an_error() -> None:
    transport = build_transport(httpx.MockTransport(lambda _: httpx.Response(503)))

    response = await transport.send(HTTPRequest(HTTPMethod.GET, "https://example.com"))

    assert response.status_code == 503


async def test_an_unreachable_server_becomes_a_transport_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = build_transport(httpx.MockTransport(refuse))

    with pytest.raises(TransportError, match="never completed"):
        await transport.send(HTTPRequest(HTTPMethod.GET, "https://example.com"))


async def test_closing_the_transport_closes_the_client() -> None:
    transport = build_transport(httpx.MockTransport(lambda _: httpx.Response(200)))

    await transport.aclose()

    assert transport.client.is_closed is True
