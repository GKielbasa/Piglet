import dataclasses

import pytest

from piglet.domain.http.response import HTTPResponse
from piglet.domain.http.service_profile import FailureClass, ServiceProfile


@pytest.mark.parametrize("status_code", [408, 425, 500, 502, 503, 504])
def test_the_default_transient_statuses_are_transient(status_code: int) -> None:
    assert ServiceProfile().classify(HTTPResponse(status_code)) is FailureClass.TRANSIENT


def test_the_default_throttling_status_is_throttling() -> None:
    assert ServiceProfile().classify(HTTPResponse(429)) is FailureClass.THROTTLING


@pytest.mark.parametrize("status_code", [200, 301, 304, 400, 404, 501])
def test_a_status_in_neither_set_is_permanent(status_code: int) -> None:
    assert ServiceProfile().classify(HTTPResponse(status_code)) is FailureClass.PERMANENT


def test_a_profile_may_refuse_a_status_the_default_repeats() -> None:
    profile = ServiceProfile(transient_statuses=frozenset({500}))

    assert profile.classify(HTTPResponse(503)) is FailureClass.PERMANENT


def test_a_profile_may_repeat_a_status_the_default_refuses() -> None:
    profile = ServiceProfile(transient_statuses=frozenset({418}))

    assert profile.classify(HTTPResponse(418)) is FailureClass.TRANSIENT


def test_a_profile_may_call_throttling_what_another_calls_transient() -> None:
    profile = ServiceProfile(transient_statuses=frozenset({500}), throttling_statuses=frozenset({503}))

    assert profile.classify(HTTPResponse(503)) is FailureClass.THROTTLING


def test_the_profile_is_immutable() -> None:
    profile = ServiceProfile()

    # The assignment is the test, so both checkers are right to reject it. `frozen=True`
    # is enforced at runtime and that is what has to be proven — a profile shared between
    # clients would otherwise be editable by any of them.
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.transient_statuses = frozenset({418})  # type: ignore[misc]
