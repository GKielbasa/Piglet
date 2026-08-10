import dataclasses

import pytest

from piglet.domain.http.request import HTTPMethod, HTTPRequest
from piglet.errors import InvalidRequestError


def test_empty_url_is_rejected_by_name() -> None:
    with pytest.raises(ValueError, match="url"):
        HTTPRequest(HTTPMethod.GET, "   ")


def test_an_empty_url_is_refused_as_a_failure_of_this_library() -> None:
    with pytest.raises(InvalidRequestError):
        HTTPRequest(HTTPMethod.GET, "   ")


def test_a_refused_request_is_still_a_value_error() -> None:
    with pytest.raises(ValueError) as refused:
        HTTPRequest(HTTPMethod.GET, "   ")

    assert isinstance(refused.value, InvalidRequestError)


def test_a_verb_outside_the_closed_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="SEARCH"):
        HTTPRequest(HTTPMethod("SEARCH"), "https://example.com")


@pytest.mark.parametrize("method", [HTTPMethod.GET, HTTPMethod.HEAD, HTTPMethod.PUT, HTTPMethod.DELETE])
def test_the_verbs_the_rfc_calls_idempotent_may_be_repeated(method: HTTPMethod) -> None:
    assert method.is_idempotent is True


@pytest.mark.parametrize("method", [HTTPMethod.POST, HTTPMethod.PATCH])
def test_post_and_patch_are_not_idempotent(method: HTTPMethod) -> None:
    assert method.is_idempotent is False


# The five below pass a plain string on purpose. Annotations vanish at runtime, so a verb
# read from a file or from configuration arrives exactly like this; both type checkers are
# right to object, and the tests exist because reality does not honour the annotation.
def test_a_verb_given_as_text_becomes_the_enum_member() -> None:
    assert HTTPRequest("GET", "https://example.com").method is HTTPMethod.GET  # type: ignore[arg-type]


def test_a_verb_given_as_text_can_still_say_whether_it_may_be_repeated() -> None:
    assert HTTPRequest("POST", "https://example.com").method.is_idempotent is False  # type: ignore[arg-type]


def test_a_verb_given_as_text_outside_the_closed_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="SEARCH"):
        HTTPRequest("SEARCH", "https://example.com")  # type: ignore[arg-type]


def test_a_verb_the_request_cannot_send_is_refused_as_a_failure_of_this_library() -> None:
    with pytest.raises(InvalidRequestError):
        HTTPRequest("SEARCH", "https://example.com")  # type: ignore[arg-type]


def test_coercing_the_verb_leaves_the_request_immutable() -> None:
    request = HTTPRequest("GET", "https://example.com")  # type: ignore[arg-type]

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.method = HTTPMethod.POST  # type: ignore[misc]


def test_the_request_is_immutable() -> None:
    request = HTTPRequest(HTTPMethod.GET, "https://example.com")

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.url = "https://elsewhere.com"  # type: ignore[misc]
