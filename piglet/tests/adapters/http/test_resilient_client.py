import asyncio
import json
import time
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import structlog
from pydantic import SecretStr

from piglet.adapters.cache.filesystem_cache import FilesystemResponseCache
from piglet.adapters.http.resilient_client import ResilientHTTPClient
from piglet.adapters.logging.setup import bind_run_id, configure_logging
from piglet.domain.http.cache_key import compute_cache_key
from piglet.domain.http.request import HTTPMethod, HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.domain.http.retry_policy import RetryPolicy
from piglet.domain.ports import HTTPTransport, Sleeper
from piglet.errors import HTTPError, RetryExhaustedError

REQUEST = HTTPRequest(HTTPMethod.GET, "https://example.com/list.csv")
QUICK_RETRIES = RetryPolicy(max_attempts=3, base_delay_seconds=0.5, jitter_max_seconds=0.0)


class ScriptedTransport:
    """Answers from a script, remembers what it was asked, never touches a network."""

    def __init__(self, *responses: HTTPResponse) -> None:
        self.scripted = list(responses)
        self.requests: list[HTTPRequest] = []
        self.is_closed = False

    async def send(self, request: HTTPRequest) -> HTTPResponse:
        self.requests.append(request)
        # The last scripted answer repeats, so "always 503" needs one entry.
        return self.scripted.pop(0) if len(self.scripted) > 1 else self.scripted[0]

    async def aclose(self) -> None:
        self.is_closed = True


class RecordedSleeper:
    """Records how long it was asked to wait instead of waiting."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


@pytest.fixture(autouse=True)
def clean_structlog() -> Iterator[None]:
    yield
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()


def read_entries(log_dir: Path) -> list[dict[str, Any]]:
    log_file = log_dir / f"{date.today().isoformat()}.jsonl"
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]


def build_client(
    transport: HTTPTransport, sleep: Sleeper, cache: FilesystemResponseCache | None = None
) -> ResilientHTTPClient:
    return ResilientHTTPClient(transport, QUICK_RETRIES, sleep, cache)


async def test_a_successful_request_is_sent_once() -> None:
    transport = ScriptedTransport(HTTPResponse(200, {}, b"name,city\n"))

    answer = await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert answer.body == b"name,city\n"
    assert len(transport.requests) == 1


async def test_a_transient_failure_is_slept_off_and_retried() -> None:
    transport = ScriptedTransport(HTTPResponse(503), HTTPResponse(200, {}, b"finally"))
    sleeper = RecordedSleeper()

    answer = await build_client(transport, sleeper).send(REQUEST)

    assert answer.status_code == 200
    assert len(transport.requests) == 2
    assert sleeper.waits == [0.5]


async def test_exhausted_attempts_report_how_many_and_what_failed() -> None:
    transport = ScriptedTransport(HTTPResponse(503))

    with pytest.raises(RetryExhaustedError) as failure:
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert failure.value.attempts == 3
    assert failure.value.last_status_code == 503
    assert len(transport.requests) == 3


async def test_a_client_mistake_is_reported_without_a_second_attempt() -> None:
    transport = ScriptedTransport(HTTPResponse(404))

    with pytest.raises(HTTPError) as failure:
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert failure.value.status_code == 404
    assert len(transport.requests) == 1


async def test_a_cache_hit_keeps_the_request_off_the_wire(tmp_path: Path) -> None:
    cache = FilesystemResponseCache(tmp_path, ttl_seconds=60)
    first = ScriptedTransport(HTTPResponse(200, {}, b"remembered"))
    await build_client(first, RecordedSleeper(), cache).send(REQUEST, should_cache=True)

    second = ScriptedTransport(HTTPResponse(200, {}, b"from the wire"))
    answer = await build_client(second, RecordedSleeper(), cache).send(REQUEST, should_cache=True)

    assert answer.body == b"remembered"
    assert second.requests == []


async def test_a_cache_miss_travels_and_is_remembered(tmp_path: Path) -> None:
    cache = FilesystemResponseCache(tmp_path, ttl_seconds=60)
    transport = ScriptedTransport(HTTPResponse(200, {}, b"fresh"))

    await build_client(transport, RecordedSleeper(), cache).send(REQUEST, should_cache=True)

    assert len(transport.requests) == 1
    assert await cache.get(compute_cache_key(REQUEST)) == HTTPResponse(200, {}, b"fresh")


async def test_a_call_that_opts_out_ignores_a_stored_answer(tmp_path: Path) -> None:
    cache = FilesystemResponseCache(tmp_path, ttl_seconds=60)
    await build_client(ScriptedTransport(HTTPResponse(200, {}, b"remembered")), RecordedSleeper(), cache).send(
        REQUEST, should_cache=True
    )
    transport = ScriptedTransport(HTTPResponse(200, {}, b"from the wire"))

    answer = await build_client(transport, RecordedSleeper(), cache).send(REQUEST)

    assert answer.body == b"from the wire"
    assert len(transport.requests) == 1


async def test_leaving_the_block_closes_the_transport() -> None:
    transport = ScriptedTransport(HTTPResponse(200))

    async with build_client(transport, RecordedSleeper()) as client:
        await client.send(REQUEST)

    assert transport.is_closed is True


async def test_leaving_the_block_closes_the_transport_after_a_failure() -> None:
    transport = ScriptedTransport(HTTPResponse(404))

    with pytest.raises(HTTPError):
        async with build_client(transport, RecordedSleeper()) as client:
            await client.send(REQUEST)

    assert transport.is_closed is True


async def test_every_attempt_leaves_a_log_entry(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    run_id = bind_run_id()
    transport = ScriptedTransport(HTTPResponse(503), HTTPResponse(200))

    await build_client(transport, RecordedSleeper()).send(REQUEST)

    entries = read_entries(tmp_path)
    assert [entry["status_code"] for entry in entries] == [503, 200]
    assert [entry["attempt"] for entry in entries] == [1, 2]
    assert all(entry["url"] == REQUEST.url for entry in entries)
    assert all(entry["run_id"] == run_id for entry in entries)
    assert all(isinstance(entry["duration_ms"], float) for entry in entries)


async def test_no_secret_reaches_the_log(tmp_path: Path) -> None:
    api_key = "s3cr3t-key"
    configure_logging(tmp_path / "logs", secrets=[SecretStr(api_key)])
    request = HTTPRequest(
        HTTPMethod.GET,
        f"https://example.com/data/{api_key}/list.csv",
        {"Authorization": f"Bearer {api_key}"},
    )

    await build_client(ScriptedTransport(HTTPResponse(200)), RecordedSleeper()).send(request)

    raw_log = (tmp_path / "logs" / f"{date.today().isoformat()}.jsonl").read_text(encoding="utf-8")
    assert api_key not in raw_log
    assert "***" in raw_log


async def test_independent_requests_do_not_queue_behind_each_other() -> None:
    class SlowTransport:
        async def send(self, request: HTTPRequest) -> HTTPResponse:
            await asyncio.sleep(0.1)
            return HTTPResponse(200)

        async def aclose(self) -> None: ...

    client = build_client(SlowTransport(), RecordedSleeper())
    started = time.perf_counter()

    await asyncio.gather(*(client.send(REQUEST) for _ in range(3)))

    assert time.perf_counter() - started < 0.25
