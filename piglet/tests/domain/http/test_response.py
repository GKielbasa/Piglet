from piglet.domain.http.response import HTTPResponse


def test_header_lookup_ignores_case() -> None:
    response = HTTPResponse(503, {"Retry-After": "120"})

    assert response.header("retry-after") == "120"
    assert response.header("RETRY-AFTER") == "120"
    assert response.header("X-Missing") is None


def test_success_is_the_2xx_range_only() -> None:
    assert HTTPResponse(200).is_success is True
    assert HTTPResponse(299).is_success is True
    assert HTTPResponse(301).is_success is False
    assert HTTPResponse(503).is_success is False


def test_body_stays_bytes_and_decodes_on_demand() -> None:
    response = HTTPResponse(200, {}, b"caf\xc3\xa9 \xe2\x98\x95")

    assert response.text == "café ☕"
