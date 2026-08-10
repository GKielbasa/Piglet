from piglet.domain.http.service_profile import FailureClass
from piglet.errors import HTTPError, TransportError


def test_a_transport_failure_assumes_the_server_may_have_acted_unless_told_otherwise() -> None:
    failure = TransportError("https://example.com", ConnectionError("refused"), FailureClass.TRANSIENT)

    assert failure.may_have_been_processed is True


def test_a_failed_status_names_the_attempt_count_in_its_message() -> None:
    failure = HTTPError("https://example.com", 404, attempts=3)

    assert "3 attempt(s)" in str(failure)
