import dataclasses

import pytest

from piglet.domain.http.request import HTTPMethod, HTTPRequest


def test_empty_url_is_rejected_by_name() -> None:
    with pytest.raises(ValueError, match="url"):
        HTTPRequest(HTTPMethod.GET, "   ")


def test_a_verb_outside_the_closed_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="SEARCH"):
        HTTPRequest(HTTPMethod("SEARCH"), "https://example.com")


def test_the_request_is_immutable() -> None:
    request = HTTPRequest(HTTPMethod.GET, "https://example.com")

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.url = "https://elsewhere.com"  # type: ignore[misc]
