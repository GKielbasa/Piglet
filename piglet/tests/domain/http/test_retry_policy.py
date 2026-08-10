from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from piglet.domain.http.response import HTTPResponse
from piglet.domain.http.retry_policy import GiveUpReason, RetryDecision, RetryPolicy
from piglet.domain.http.service_profile import FailureClass

# The whole window is drawn, so a delay can be asserted exactly.
WHOLE_WINDOW = RetryPolicy(max_attempts=10, max_total_delay_seconds=10_000, jitter_fraction=lambda: 1.0)
# None of the window is drawn, so a retry with no wait at all can be told from a refusal.
ZERO_DRAW = RetryPolicy(max_attempts=10, max_total_delay_seconds=10_000, jitter_fraction=lambda: 0.0)


def test_a_decision_with_no_reason_is_a_decision_to_retry() -> None:
    assert RetryDecision(delay_seconds=1.5).should_retry is True


@pytest.mark.parametrize("reason", list(GiveUpReason))
def test_a_decision_carrying_a_reason_does_not_retry(reason: GiveUpReason) -> None:
    assert RetryDecision(delay_seconds=0.0, give_up_reason=reason).should_retry is False


def test_a_decision_to_give_up_names_no_delay() -> None:
    permanent = WHOLE_WINDOW.decide(HTTPResponse(404), FailureClass.PERMANENT, attempt=1)
    unsafe = WHOLE_WINDOW.decide(
        HTTPResponse(503), FailureClass.TRANSIENT, attempt=1, is_safe_to_repeat=False, may_have_been_processed=True
    )
    out_of_attempts = RetryPolicy(max_attempts=1).decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=1)
    out_of_budget = WHOLE_WINDOW.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=1, delay_used_seconds=10_000)

    assert [decision.delay_seconds for decision in (permanent, unsafe, out_of_attempts, out_of_budget)] == [0.0] * 4


def test_a_permanent_class_ends_it_whatever_the_status_says() -> None:
    decision = WHOLE_WINDOW.decide(HTTPResponse(503), FailureClass.PERMANENT, attempt=1)

    assert decision.give_up_reason is GiveUpReason.PERMANENT_FAILURE


def test_a_transient_class_is_repeated_whatever_the_status_says() -> None:
    assert WHOLE_WINDOW.decide(HTTPResponse(404), FailureClass.TRANSIENT, attempt=1).should_retry is True


def test_a_throttling_failure_is_repeated() -> None:
    decision = WHOLE_WINDOW.decide(HTTPResponse(429), FailureClass.THROTTLING, attempt=1)

    assert decision.should_retry is True
    assert decision.give_up_reason is None


@pytest.mark.parametrize("failure_class", [FailureClass.TRANSIENT, FailureClass.THROTTLING])
def test_the_last_allowed_attempt_ends_it(failure_class: FailureClass) -> None:
    policy = RetryPolicy(max_attempts=3)

    assert policy.decide(HTTPResponse(503), failure_class, attempt=2).should_retry is True
    assert policy.decide(HTTPResponse(503), failure_class, attempt=3).give_up_reason is GiveUpReason.ATTEMPTS_EXHAUSTED


def test_a_policy_allowing_one_attempt_never_retries() -> None:
    policy = RetryPolicy(max_attempts=1)

    decision = policy.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=1)

    assert decision.give_up_reason is GiveUpReason.ATTEMPTS_EXHAUSTED


def test_the_total_waiting_ceiling_ends_it() -> None:
    policy = RetryPolicy(
        max_attempts=10, transient_base_delay_seconds=2.0, max_total_delay_seconds=10.0, jitter_fraction=lambda: 1.0
    )

    decision = policy.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=1, delay_used_seconds=9.0)

    assert decision.give_up_reason is GiveUpReason.BUDGET_EXHAUSTED


def test_waiting_that_lands_exactly_on_the_ceiling_is_still_allowed() -> None:
    policy = RetryPolicy(
        max_attempts=10, transient_base_delay_seconds=2.0, max_total_delay_seconds=10.0, jitter_fraction=lambda: 1.0
    )

    decision = policy.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=1, delay_used_seconds=8.0)

    assert decision.should_retry is True


def test_a_policy_is_past_its_deadline_once_more_time_has_passed_than_it_allows() -> None:
    policy = RetryPolicy(max_total_seconds=5.0)

    assert policy.is_past_deadline(5.1) is True


def test_a_policy_is_not_past_its_deadline_while_time_remains() -> None:
    policy = RetryPolicy(max_total_seconds=5.0)

    assert policy.is_past_deadline(4.9) is False


def test_elapsed_time_landing_exactly_on_the_deadline_has_reached_it() -> None:
    policy = RetryPolicy(max_total_seconds=5.0)

    assert policy.is_past_deadline(5.0) is True


def test_the_deadline_and_the_waiting_budget_are_separate_limits() -> None:
    long_waiting_short_deadline = RetryPolicy(max_total_delay_seconds=600.0, max_total_seconds=5.0)
    short_waiting_long_deadline = RetryPolicy(max_total_delay_seconds=5.0, max_total_seconds=600.0)

    assert long_waiting_short_deadline.is_past_deadline(10.0) is True
    assert short_waiting_long_deadline.is_past_deadline(10.0) is False


def test_a_request_that_is_not_safe_to_repeat_is_refused_after_one_attempt_when_the_server_may_have_acted() -> None:
    decision = WHOLE_WINDOW.decide(
        HTTPResponse(503), FailureClass.TRANSIENT, attempt=1, is_safe_to_repeat=False, may_have_been_processed=True
    )

    assert decision.give_up_reason is GiveUpReason.UNSAFE_TO_REPEAT


def test_a_request_declared_safe_to_repeat_is_retried_whatever_its_method_would_imply() -> None:
    decision = WHOLE_WINDOW.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=1, is_safe_to_repeat=True)

    assert decision.should_retry is True


def test_a_permanent_failure_on_a_request_that_may_not_be_repeated_is_reported_as_permanent() -> None:
    decision = WHOLE_WINDOW.decide(HTTPResponse(404), FailureClass.PERMANENT, attempt=1, is_safe_to_repeat=False)

    assert decision.give_up_reason is GiveUpReason.PERMANENT_FAILURE


def test_a_throttled_failure_on_a_request_that_may_not_be_repeated_is_still_retried() -> None:
    decision = WHOLE_WINDOW.decide(
        HTTPResponse(429, {"Retry-After": "1"}), FailureClass.THROTTLING, attempt=1, is_safe_to_repeat=False
    )

    assert decision.should_retry is True
    assert decision.give_up_reason is None


def test_a_failure_that_never_reached_the_server_is_retried_though_the_request_may_not_be_repeated() -> None:
    decision = WHOLE_WINDOW.decide(
        None, FailureClass.TRANSIENT, attempt=1, is_safe_to_repeat=False, may_have_been_processed=False
    )

    assert decision.should_retry is True
    assert decision.give_up_reason is None


def test_a_failure_the_server_may_have_processed_is_refused_when_the_request_may_not_be_repeated() -> None:
    decision = WHOLE_WINDOW.decide(
        None, FailureClass.TRANSIENT, attempt=1, is_safe_to_repeat=False, may_have_been_processed=True
    )

    assert decision.give_up_reason is GiveUpReason.UNSAFE_TO_REPEAT


def test_a_failure_of_unstated_phase_counts_as_one_the_server_may_have_processed() -> None:
    decision = WHOLE_WINDOW.decide(None, FailureClass.TRANSIENT, attempt=1, is_safe_to_repeat=False)

    assert decision.give_up_reason is GiveUpReason.UNSAFE_TO_REPEAT


def test_a_permanent_failure_that_never_reached_the_server_is_still_reported_as_permanent() -> None:
    decision = WHOLE_WINDOW.decide(
        None, FailureClass.PERMANENT, attempt=1, is_safe_to_repeat=False, may_have_been_processed=False
    )

    assert decision.give_up_reason is GiveUpReason.PERMANENT_FAILURE


@pytest.mark.parametrize("may_have_been_processed", [True, False])
def test_the_phase_of_a_failure_changes_nothing_when_the_request_may_be_repeated(may_have_been_processed: bool) -> None:
    decision = WHOLE_WINDOW.decide(
        None,
        FailureClass.TRANSIENT,
        attempt=1,
        is_safe_to_repeat=True,
        may_have_been_processed=may_have_been_processed,
    )

    assert decision.should_retry is True


@pytest.mark.parametrize(
    ("failure_class", "may_have_been_processed"),
    [(FailureClass.THROTTLING, True), (FailureClass.TRANSIENT, False)],
)
def test_a_failure_exempt_from_the_guard_still_runs_out_of_attempts(
    failure_class: FailureClass, may_have_been_processed: bool
) -> None:
    policy = RetryPolicy(max_attempts=3)

    decision = policy.decide(
        None,
        failure_class,
        attempt=3,
        is_safe_to_repeat=False,
        may_have_been_processed=may_have_been_processed,
    )

    assert decision.give_up_reason is GiveUpReason.ATTEMPTS_EXHAUSTED


@pytest.mark.parametrize(
    ("failure_class", "may_have_been_processed"),
    [(FailureClass.THROTTLING, True), (FailureClass.TRANSIENT, False)],
)
def test_a_failure_exempt_from_the_guard_still_runs_out_of_the_waiting_budget(
    failure_class: FailureClass, may_have_been_processed: bool
) -> None:
    policy = RetryPolicy(max_attempts=10, max_total_delay_seconds=10.0, jitter_fraction=lambda: 1.0)

    decision = policy.decide(
        None,
        failure_class,
        attempt=1,
        delay_used_seconds=10.0,
        is_safe_to_repeat=False,
        may_have_been_processed=may_have_been_processed,
    )

    assert decision.give_up_reason is GiveUpReason.BUDGET_EXHAUSTED


def test_the_backoff_window_doubles_with_every_attempt() -> None:
    delays = [
        WHOLE_WINDOW.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=n).delay_seconds for n in (1, 2, 3, 4)
    ]

    assert delays == [0.5, 1.0, 2.0, 4.0]


@given(attempt=st.integers(min_value=1, max_value=8), drawn=st.floats(min_value=0.0, max_value=1.0))
def test_the_delay_lands_anywhere_inside_the_window(attempt: int, drawn: float) -> None:
    policy = RetryPolicy(max_attempts=10, max_total_delay_seconds=10_000, jitter_fraction=lambda: drawn)

    decision = policy.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=attempt)

    window = min(policy.max_delay_seconds, policy.transient_base_delay_seconds * 2 ** (attempt - 1))
    assert 0.0 <= decision.delay_seconds <= window


def test_a_jitter_draw_of_zero_still_retries() -> None:
    decision = ZERO_DRAW.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=1)

    assert decision.delay_seconds == 0.0
    assert decision.should_retry is True


def test_the_single_delay_cap_binds_a_window_that_would_outgrow_it() -> None:
    # An uncapped window at attempt 7 would be 0.5 * 2 ** 6 = 32 seconds.
    decision = WHOLE_WINDOW.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=7)

    assert decision.delay_seconds == 20.0


def test_throttling_waits_longer_than_a_transient_failure() -> None:
    throttled = WHOLE_WINDOW.decide(HTTPResponse(429), FailureClass.THROTTLING, attempt=1)
    transient = WHOLE_WINDOW.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=1)

    assert throttled.delay_seconds > transient.delay_seconds


def test_the_default_policy_draws_its_own_jitter() -> None:
    policy = RetryPolicy()

    decision = policy.decide(HTTPResponse(503), FailureClass.TRANSIENT, attempt=1)

    assert 0.0 <= decision.delay_seconds <= policy.transient_base_delay_seconds


def test_a_delay_named_by_the_server_wins_when_it_exceeds_the_window() -> None:
    decision = WHOLE_WINDOW.decide(HTTPResponse(429, {"Retry-After": "120"}), FailureClass.THROTTLING, attempt=1)

    assert decision.delay_seconds == 120.0


def test_a_delay_named_by_the_server_is_ignored_when_the_window_is_longer() -> None:
    decision = WHOLE_WINDOW.decide(HTTPResponse(503, {"Retry-After": "0.1"}), FailureClass.TRANSIENT, attempt=1)

    assert decision.delay_seconds == 0.5


def test_a_server_asking_for_longer_than_the_ceiling_ends_the_retries() -> None:
    # The two rules meet here: the server's delay wins over the window we computed, and
    # the total waiting ceiling then rejects it. Waiting is capped by us, not by them.
    policy = RetryPolicy(max_attempts=10, max_total_delay_seconds=60.0)

    decision = policy.decide(HTTPResponse(429, {"Retry-After": "120"}), FailureClass.THROTTLING, attempt=1)

    assert decision.give_up_reason is GiveUpReason.BUDGET_EXHAUSTED


def test_the_single_delay_cap_does_not_truncate_a_delay_the_server_named() -> None:
    policy = RetryPolicy(max_attempts=10, max_delay_seconds=20.0, max_total_delay_seconds=60.0)

    decision = policy.decide(HTTPResponse(429, {"Retry-After": "30"}), FailureClass.THROTTLING, attempt=1)

    assert decision.delay_seconds == 30.0


def test_retry_after_as_an_http_date_becomes_seconds() -> None:
    moment = format_datetime(datetime.now(UTC) + timedelta(seconds=120), usegmt=True)

    decision = WHOLE_WINDOW.decide(HTTPResponse(503, {"Retry-After": moment}), FailureClass.TRANSIENT, attempt=1)

    assert 117.0 <= decision.delay_seconds <= 120.0


@pytest.mark.parametrize("header_value", ["soon", "", "Tue, 32 Foo 2026 99:99:99 GMT"])
def test_an_unreadable_delay_header_falls_back_to_the_computed_window(header_value: str) -> None:
    decision = WHOLE_WINDOW.decide(HTTPResponse(503, {"Retry-After": header_value}), FailureClass.TRANSIENT, attempt=2)

    assert decision.should_retry is True
    assert decision.delay_seconds == 1.0


@pytest.mark.parametrize("header_value", ["inf", "-inf", "nan"])
def test_a_delay_header_that_is_not_a_finite_number_falls_back_to_the_computed_window(header_value: str) -> None:
    decision = WHOLE_WINDOW.decide(HTTPResponse(503, {"Retry-After": header_value}), FailureClass.TRANSIENT, attempt=2)

    assert decision.should_retry is True
    assert decision.delay_seconds == 1.0


@pytest.mark.parametrize("header_value", ["-5", "Tue, 01 Jan 2019 00:00:00 GMT"])
def test_a_delay_the_server_named_in_the_past_never_shortens_the_wait(header_value: str) -> None:
    decision = WHOLE_WINDOW.decide(HTTPResponse(503, {"Retry-After": header_value}), FailureClass.TRANSIENT, attempt=2)

    assert decision.delay_seconds == 1.0


def test_a_missing_response_falls_back_to_the_computed_window() -> None:
    decision = WHOLE_WINDOW.decide(None, FailureClass.TRANSIENT, attempt=2)

    assert decision.delay_seconds == 1.0


def test_a_permanent_transport_failure_is_not_repeated() -> None:
    decision = WHOLE_WINDOW.decide(None, FailureClass.PERMANENT, attempt=1)

    assert decision.give_up_reason is GiveUpReason.PERMANENT_FAILURE


def test_a_transient_transport_failure_is_repeated() -> None:
    decision = WHOLE_WINDOW.decide(None, FailureClass.TRANSIENT, attempt=1)

    assert decision.should_retry is True
    assert decision.give_up_reason is None


def test_a_non_standard_delay_header_is_not_believed() -> None:
    decision = WHOLE_WINDOW.decide(HTTPResponse(429, {"X-RateLimit-Reset": "90"}), FailureClass.THROTTLING, attempt=1)

    assert decision.delay_seconds == 1.0
