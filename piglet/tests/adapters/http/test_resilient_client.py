import asyncio
import json
import time
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog
from pydantic import SecretStr

from piglet.adapters.cache.filesystem_cache import FilesystemResponseCache
from piglet.adapters.http.resilient_client import ResilientHTTPClient
from piglet.adapters.logging.setup import bind_run_id, configure_logging
from piglet.domain.http.cache_key import compute_cache_key
from piglet.domain.http.request import HTTPMethod, HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.domain.http.retry_policy import GiveUpReason, RetryPolicy
from piglet.domain.http.service_profile import FailureClass, ServiceProfile
from piglet.domain.ports import HTTPTransport, Sleeper
from piglet.errors import HTTPError, RetryExhaustedError, TransportError, UnsafeToRepeatError

REQUEST = HTTPRequest(HTTPMethod.GET, "https://example.com/list.csv")
ORDER = HTTPRequest(HTTPMethod.POST, "https://example.com/orders", body=b'{"quantity": 2}')
QUICK_RETRIES = RetryPolicy(max_attempts=3, transient_base_delay_seconds=0.5, jitter_fraction=lambda: 1.0)
STANDARD_PROFILE = ServiceProfile()


class ScriptedTransport:
    """Answers from a script, remembers what it was asked, never touches a network."""

    def __init__(self, *answers: HTTPResponse | TransportError) -> None:
        self.scripted = list(answers)
        self.requests: list[HTTPRequest] = []
        self.is_closed = False

    async def send(self, request: HTTPRequest) -> HTTPResponse:
        self.requests.append(request)
        # The last scripted answer repeats, so "always 503" needs one entry.
        answer = self.scripted.pop(0) if len(self.scripted) > 1 else self.scripted[0]
        if isinstance(answer, TransportError):
            raise answer
        return answer

    async def aclose(self) -> None:
        self.is_closed = True


def failure_that_never_reached_the_server() -> TransportError:
    """A connection that died before a byte of the request travelled, of the kind that may pass."""
    return TransportError(
        REQUEST.url, httpx.ConnectTimeout("too slow"), FailureClass.TRANSIENT, may_have_been_processed=False
    )


def failure_the_server_may_have_processed() -> TransportError:
    """A connection that died after the request travelled, so the server may already have acted."""
    return TransportError(
        REQUEST.url, httpx.ReadTimeout("no answer"), FailureClass.TRANSIENT, may_have_been_processed=True
    )


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
    transport: HTTPTransport,
    sleep: Sleeper,
    cache: FilesystemResponseCache | None = None,
    profile: ServiceProfile = STANDARD_PROFILE,
) -> ResilientHTTPClient:
    return ResilientHTTPClient(transport, QUICK_RETRIES, profile, sleep, cache)


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


async def test_a_permanent_failure_is_reported_without_a_second_attempt() -> None:
    transport = ScriptedTransport(HTTPResponse(404))

    with pytest.raises(HTTPError) as failure:
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert failure.value.status_code == 404
    assert len(transport.requests) == 1


async def test_exhausted_attempts_report_the_class_of_the_failure() -> None:
    transport = ScriptedTransport(HTTPResponse(503))

    with pytest.raises(RetryExhaustedError) as failure:
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert failure.value.failure_class is FailureClass.TRANSIENT


async def test_exhausted_attempts_report_which_limit_ran_out() -> None:
    transport = ScriptedTransport(HTTPResponse(503))

    with pytest.raises(RetryExhaustedError) as failure:
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert failure.value.give_up_reason is GiveUpReason.ATTEMPTS_EXHAUSTED


async def test_a_throttled_request_that_outlives_the_budget_is_not_reported_as_a_bad_request() -> None:
    transport = ScriptedTransport(HTTPResponse(429, {"Retry-After": "120"}))

    with pytest.raises(RetryExhaustedError):
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert len(transport.requests) == 1


async def test_a_budget_that_runs_out_is_told_apart_from_attempts_that_do() -> None:
    transport = ScriptedTransport(HTTPResponse(429, {"Retry-After": "120"}))

    with pytest.raises(RetryExhaustedError) as failure:
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert failure.value.give_up_reason is GiveUpReason.BUDGET_EXHAUSTED
    assert failure.value.failure_class is FailureClass.THROTTLING


async def test_a_non_idempotent_request_is_refused_after_one_attempt() -> None:
    transport = ScriptedTransport(HTTPResponse(503))
    sleeper = RecordedSleeper()

    with pytest.raises(UnsafeToRepeatError):
        await build_client(transport, sleeper).send(ORDER)

    assert len(transport.requests) == 1
    assert sleeper.waits == []


async def test_a_non_idempotent_request_declared_safe_is_retried() -> None:
    transport = ScriptedTransport(HTTPResponse(503), HTTPResponse(200, {}, b"accepted"))

    answer = await build_client(transport, RecordedSleeper()).send(ORDER, is_safe_to_repeat=True)

    assert answer.status_code == 200
    assert len(transport.requests) == 2


async def test_an_idempotent_request_declared_unsafe_is_not_retried() -> None:
    transport = ScriptedTransport(HTTPResponse(503))

    with pytest.raises(UnsafeToRepeatError):
        await build_client(transport, RecordedSleeper()).send(REQUEST, is_safe_to_repeat=False)

    assert len(transport.requests) == 1


async def test_the_refusal_names_the_method_that_may_not_be_repeated() -> None:
    transport = ScriptedTransport(HTTPResponse(503))

    with pytest.raises(UnsafeToRepeatError) as failure:
        await build_client(transport, RecordedSleeper()).send(ORDER)

    assert failure.value.method == HTTPMethod.POST


async def test_a_throttled_post_is_retried() -> None:
    transport = ScriptedTransport(HTTPResponse(429), HTTPResponse(200, {}, b"accepted"))

    answer = await build_client(transport, RecordedSleeper()).send(ORDER)

    assert answer.status_code == 200
    assert len(transport.requests) == 2


async def test_the_refusal_of_a_request_that_may_not_be_repeated_names_how_many_attempts_were_made() -> None:
    transport = ScriptedTransport(HTTPResponse(429), HTTPResponse(503))

    with pytest.raises(UnsafeToRepeatError) as failure:
        await build_client(transport, RecordedSleeper()).send(ORDER)

    assert failure.value.attempts == 2
    assert len(transport.requests) == 2


async def test_a_throttled_post_that_runs_out_of_attempts_is_not_reported_as_unrepeatable() -> None:
    transport = ScriptedTransport(HTTPResponse(429))

    with pytest.raises(RetryExhaustedError) as failure:
        await build_client(transport, RecordedSleeper()).send(ORDER)

    assert failure.value.failure_class is FailureClass.THROTTLING
    assert failure.value.give_up_reason is GiveUpReason.ATTEMPTS_EXHAUSTED
    assert len(transport.requests) == QUICK_RETRIES.max_attempts


async def test_a_transport_failure_is_slept_off_and_retried() -> None:
    transport = ScriptedTransport(failure_that_never_reached_the_server(), HTTPResponse(200, {}, b"finally"))
    sleeper = RecordedSleeper()

    answer = await build_client(transport, sleeper).send(REQUEST)

    assert answer.status_code == 200
    assert len(transport.requests) == 2
    assert sleeper.waits == [0.5]


async def test_attempts_that_never_get_an_answer_report_no_last_status() -> None:
    transport = ScriptedTransport(failure_that_never_reached_the_server())

    with pytest.raises(RetryExhaustedError) as failure:
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert failure.value.attempts == 3
    assert failure.value.last_status_code is None


async def test_a_request_that_never_got_an_answer_says_so() -> None:
    transport = ScriptedTransport(failure_that_never_reached_the_server())

    with pytest.raises(RetryExhaustedError, match="no response ever arrived"):
        await build_client(transport, RecordedSleeper()).send(REQUEST)


async def test_the_failure_that_ran_out_of_attempts_stays_in_the_chain() -> None:
    never_answers = failure_that_never_reached_the_server()
    transport = ScriptedTransport(never_answers)

    with pytest.raises(RetryExhaustedError) as failure:
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert failure.value.__cause__ is never_answers


async def test_a_permanent_transport_failure_propagates_unchanged() -> None:
    unusable = TransportError(REQUEST.url, httpx.UnsupportedProtocol("no scheme"), FailureClass.PERMANENT)
    transport = ScriptedTransport(unusable)

    with pytest.raises(TransportError) as failure:
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert failure.value is unusable


async def test_a_permanent_transport_failure_is_not_slept_off() -> None:
    transport = ScriptedTransport(
        TransportError(REQUEST.url, httpx.UnsupportedProtocol("no scheme"), FailureClass.PERMANENT)
    )
    sleeper = RecordedSleeper()

    with pytest.raises(TransportError):
        await build_client(transport, sleeper).send(REQUEST)

    assert len(transport.requests) == 1
    assert sleeper.waits == []


async def test_a_post_that_never_reached_the_server_is_retried() -> None:
    transport = ScriptedTransport(failure_that_never_reached_the_server(), HTTPResponse(200, {}, b"accepted"))

    answer = await build_client(transport, RecordedSleeper()).send(ORDER)

    assert answer.status_code == 200
    assert len(transport.requests) == 2


async def test_a_post_the_server_may_have_processed_is_refused_after_one_attempt() -> None:
    transport = ScriptedTransport(failure_the_server_may_have_processed())

    with pytest.raises(UnsafeToRepeatError):
        await build_client(transport, RecordedSleeper()).send(ORDER)

    assert len(transport.requests) == 1


async def test_the_refusal_of_a_request_that_never_answered_carries_no_status() -> None:
    transport = ScriptedTransport(failure_the_server_may_have_processed())

    with pytest.raises(UnsafeToRepeatError) as failure:
        await build_client(transport, RecordedSleeper()).send(ORDER)

    assert failure.value.status_code is None


async def test_a_post_that_keeps_not_reaching_the_server_runs_out_of_attempts() -> None:
    transport = ScriptedTransport(failure_that_never_reached_the_server())

    with pytest.raises(RetryExhaustedError) as failure:
        await build_client(transport, RecordedSleeper()).send(ORDER)

    assert failure.value.attempts == QUICK_RETRIES.max_attempts
    assert failure.value.last_status_code is None


async def test_a_post_that_times_out_may_be_retried_when_declared_safe() -> None:
    transport = ScriptedTransport(failure_the_server_may_have_processed(), HTTPResponse(200, {}, b"accepted"))

    answer = await build_client(transport, RecordedSleeper()).send(ORDER, is_safe_to_repeat=True)

    assert answer.status_code == 200
    assert len(transport.requests) == 2


async def test_the_injected_profile_decides_what_is_worth_repeating() -> None:
    transport = ScriptedTransport(HTTPResponse(503))
    profile = ServiceProfile(transient_statuses=frozenset({500}))

    with pytest.raises(HTTPError) as failure:
        await build_client(transport, RecordedSleeper(), profile=profile).send(REQUEST)

    assert failure.value.status_code == 503
    assert len(transport.requests) == 1


async def test_a_profile_that_calls_a_status_throttling_exempts_it_from_the_guard() -> None:
    transport = ScriptedTransport(HTTPResponse(503), HTTPResponse(200, {}, b"accepted"))
    profile = ServiceProfile(throttling_statuses=frozenset({503}))

    answer = await build_client(transport, RecordedSleeper(), profile=profile).send(ORDER)

    assert answer.status_code == 200
    assert len(transport.requests) == 2


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


async def test_a_failed_attempt_records_the_class_of_the_failure(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(HTTPResponse(503), HTTPResponse(200))

    await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert read_entries(tmp_path)[0]["failure_class"] == FailureClass.TRANSIENT


async def test_a_successful_attempt_records_no_failure_class(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(HTTPResponse(503), HTTPResponse(200))

    await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert "failure_class" not in read_entries(tmp_path)[1]


async def test_the_attempt_we_stop_at_records_why_we_stopped(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(HTTPResponse(503))

    with pytest.raises(RetryExhaustedError):
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert read_entries(tmp_path)[-1]["give_up_reason"] == GiveUpReason.ATTEMPTS_EXHAUSTED


async def test_an_attempt_we_wait_after_records_how_long_we_waited(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(HTTPResponse(503), HTTPResponse(200))
    sleeper = RecordedSleeper()

    await build_client(transport, sleeper).send(REQUEST)

    assert read_entries(tmp_path)[0]["delay_seconds"] == sleeper.waits[0]


async def test_an_attempt_we_do_not_wait_after_records_no_delay(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(HTTPResponse(503), HTTPResponse(200))

    await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert "delay_seconds" not in read_entries(tmp_path)[1]


async def test_the_recorded_duration_excludes_the_waiting(tmp_path: Path) -> None:
    class RealSleeper:
        async def __call__(self, seconds: float) -> None:
            await asyncio.sleep(0.05)

    configure_logging(tmp_path)
    transport = ScriptedTransport(HTTPResponse(503), HTTPResponse(200))

    await build_client(transport, RealSleeper()).send(REQUEST)

    assert read_entries(tmp_path)[0]["duration_ms"] < 50


async def test_an_attempt_that_never_got_an_answer_records_no_status(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(failure_that_never_reached_the_server(), HTTPResponse(200))

    await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert "status_code" not in read_entries(tmp_path)[0]


async def test_an_attempt_that_never_got_an_answer_records_the_class_of_the_failure(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(failure_that_never_reached_the_server(), HTTPResponse(200))

    await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert read_entries(tmp_path)[0]["failure_class"] == FailureClass.TRANSIENT


async def test_an_attempt_that_never_got_an_answer_names_the_transport_failure(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(failure_that_never_reached_the_server(), HTTPResponse(200))

    await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert read_entries(tmp_path)[0]["transport_error"] == "ConnectTimeout"


async def test_an_attempt_that_never_got_an_answer_is_still_measured(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(failure_that_never_reached_the_server(), HTTPResponse(200))

    await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert isinstance(read_entries(tmp_path)[0]["duration_ms"], float)


async def test_the_transport_failure_we_stop_at_records_why_we_stopped(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(
        TransportError(REQUEST.url, httpx.UnsupportedProtocol("no scheme"), FailureClass.PERMANENT)
    )

    with pytest.raises(TransportError):
        await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert read_entries(tmp_path)[-1]["give_up_reason"] == GiveUpReason.PERMANENT_FAILURE


async def test_an_attempt_that_got_an_answer_names_no_transport_failure(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    transport = ScriptedTransport(HTTPResponse(200))

    await build_client(transport, RecordedSleeper()).send(REQUEST)

    assert "transport_error" not in read_entries(tmp_path)[0]


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
