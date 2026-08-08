from piglet.domain.http.service_profile import FailureClass
from piglet.errors import TransportError


def test_a_transport_failure_assumes_the_server_may_have_acted_unless_told_otherwise() -> None:
    failure = TransportError("https://example.com", ConnectionError("refused"), FailureClass.TRANSIENT)

    assert failure.may_have_been_processed is True
