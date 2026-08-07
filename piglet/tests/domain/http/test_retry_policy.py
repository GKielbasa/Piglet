from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from piglet.domain.http.response import HTTPResponse
from piglet.domain.http.retry_policy import RetryPolicy

# Wide enough that only the rule under test can stop a retry.
PERMISSIVE = RetryPolicy(
    max_attempts=10, base_delay_seconds=0.5, jitter_max_seconds=0.5, max_total_delay_seconds=10_000
)
# Jitter switched off, so a delay can be asserted exactly.
PREDICTABLE = RetryPolicy(
    max_attempts=10, base_delay_seconds=0.5, jitter_max_seconds=0.0, max_total_delay_seconds=10_000
)


def test_a_successful_response_is_not_repeated() -> None:
    assert PERMISSIVE.decide(HTTPResponse(200), attempt=1).should_retry is False


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_a_transient_failure_is_repeated(status_code: int) -> None:
    assert PERMISSIVE.decide(HTTPResponse(status_code), attempt=1).should_retry is True


@pytest.mark.parametrize("status_code", [400, 404])
def test_a_client_mistake_is_not_repeated(status_code: int) -> None:
    assert PERMISSIVE.decide(HTTPResponse(status_code), attempt=1).should_retry is False


@pytest.mark.parametrize("status_code", [429, 503])
def test_the_last_allowed_attempt_ends_it_whatever_the_status(status_code: int) -> None:
    policy = RetryPolicy(max_attempts=3)

    assert policy.decide(HTTPResponse(status_code), attempt=2).should_retry is True
    assert policy.decide(HTTPResponse(status_code), attempt=3).should_retry is False


def test_the_total_waiting_ceiling_ends_it() -> None:
    policy = RetryPolicy(max_attempts=10, base_delay_seconds=1.0, jitter_max_seconds=0.0, max_total_delay_seconds=10.0)

    assert policy.decide(HTTPResponse(503), attempt=2, delay_used_seconds=7.0).should_retry is True
    assert policy.decide(HTTPResponse(503), attempt=2, delay_used_seconds=9.0).should_retry is False


def test_the_delay_doubles_with_every_attempt() -> None:
    delays = [PREDICTABLE.decide(HTTPResponse(503), attempt=n).delay_seconds for n in (1, 2, 3, 4)]

    assert delays == [0.5, 1.0, 2.0, 4.0]


@given(attempt=st.integers(min_value=1, max_value=8))
def test_the_delay_stays_inside_the_backoff_window(attempt: int) -> None:
    decision = PERMISSIVE.decide(HTTPResponse(503), attempt=attempt)

    floor = PERMISSIVE.base_delay_seconds * 2 ** (attempt - 1)
    assert floor <= decision.delay_seconds <= floor + PERMISSIVE.jitter_max_seconds


def test_retry_after_in_seconds_wins_when_longer_than_the_backoff() -> None:
    long_wait = PREDICTABLE.decide(HTTPResponse(429, {"Retry-After": "120"}), attempt=1)
    short_wait = PREDICTABLE.decide(HTTPResponse(429, {"Retry-After": "0.1"}), attempt=1)

    assert long_wait.delay_seconds == 120.0
    assert short_wait.delay_seconds == 0.5  # the backoff is longer, so it stands


def test_a_server_asking_for_longer_than_the_ceiling_ends_the_retries() -> None:
    # The two rules meet here: the server's delay wins over the backoff, and the total
    # waiting ceiling then rejects it. Waiting is capped by our budget, not by the server.
    policy = RetryPolicy(max_attempts=10, max_total_delay_seconds=60.0)

    assert policy.decide(HTTPResponse(429, {"Retry-After": "120"}), attempt=1).should_retry is False


def test_retry_after_as_an_http_date_becomes_seconds() -> None:
    moment = format_datetime(datetime.now(UTC) + timedelta(seconds=120), usegmt=True)

    decision = PREDICTABLE.decide(HTTPResponse(503, {"Retry-After": moment}), attempt=1)

    assert 117.0 <= decision.delay_seconds <= 120.0


def test_rate_limit_reset_is_respected_when_retry_after_is_absent() -> None:
    as_timestamp = str(datetime.now(UTC).timestamp() + 90)
    as_delta = "45"

    from_timestamp = PREDICTABLE.decide(HTTPResponse(429, {"X-RateLimit-Reset": as_timestamp}), attempt=1)
    from_delta = PREDICTABLE.decide(HTTPResponse(429, {"X-RateLimit-Reset": as_delta}), attempt=1)

    assert 87.0 <= from_timestamp.delay_seconds <= 90.0
    assert from_delta.delay_seconds == 45.0


@pytest.mark.parametrize("header_value", ["soon", "", "Tue, 32 Foo 2026 99:99:99 GMT", "-5"])
def test_an_unreadable_delay_header_falls_back_to_the_backoff(header_value: str) -> None:
    decision = PREDICTABLE.decide(HTTPResponse(503, {"Retry-After": header_value}), attempt=2)

    assert decision.should_retry is True
    assert decision.delay_seconds == 1.0
