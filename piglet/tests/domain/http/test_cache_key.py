from piglet.domain.http.cache_key import compute_cache_key
from piglet.domain.http.request import HTTPMethod, HTTPRequest


def test_the_same_question_gets_the_same_key() -> None:
    first = HTTPRequest(HTTPMethod.POST, "https://example.com/verify", body=b'{"answer": 42}')
    second = HTTPRequest(HTTPMethod.POST, "https://example.com/verify", body=b'{"answer": 42}')

    assert compute_cache_key(first) == compute_cache_key(second)


def test_a_different_body_gets_a_different_key() -> None:
    first = HTTPRequest(HTTPMethod.POST, "https://example.com/verify", body=b'{"answer": 42}')
    second = HTTPRequest(HTTPMethod.POST, "https://example.com/verify", body=b'{"answer": 43}')

    assert compute_cache_key(first) != compute_cache_key(second)


def test_header_order_does_not_change_the_key() -> None:
    first = HTTPRequest(HTTPMethod.GET, "https://example.com", {"Accept": "text/csv", "X-Trace": "abc"})
    second = HTTPRequest(HTTPMethod.GET, "https://example.com", {"X-Trace": "abc", "accept": "text/csv"})

    assert compute_cache_key(first) == compute_cache_key(second)


def test_credentials_stay_out_of_the_key() -> None:
    anonymous = HTTPRequest(HTTPMethod.GET, "https://example.com")
    authenticated = HTTPRequest(HTTPMethod.GET, "https://example.com", {"Authorization": "Bearer s3cr3t-key"})

    key = compute_cache_key(authenticated)
    assert key == compute_cache_key(anonymous)
    assert "s3cr3t" not in key
