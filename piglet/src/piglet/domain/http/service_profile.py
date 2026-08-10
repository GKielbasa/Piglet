"""What one service's statuses mean, and therefore which failures are worth repeating."""

from dataclasses import dataclass
from enum import StrEnum

from piglet.domain.http.response import HTTPResponse

__all__ = ["FailureClass", "ServiceProfile"]

_DEFAULT_TRANSIENT_STATUSES = frozenset({408, 425, 500, 502, 503, 504})
_DEFAULT_THROTTLING_STATUSES = frozenset({429})


class FailureClass(StrEnum):
    """What kind of failure this is, and therefore what may be done about it."""

    TRANSIENT = "transient"
    THROTTLING = "throttling"
    PERMANENT = "permanent"


@dataclass(frozen=True, slots=True)
class ServiceProfile:
    """What one service's statuses mean, configured per integration.

    The defaults are the statuses most services use this way; they are a starting
    point rather than a truth, which is why they are values on an object instead of
    a table inside the retry policy.

    Attributes:
        transient_statuses: Statuses that may pass by themselves.
        throttling_statuses: Statuses that mean the service is holding us back. Checked
            first, so a status named in both sets counts as throttling.

    Example:
        >>> ServiceProfile().classify(HTTPResponse(503))
        <FailureClass.TRANSIENT: 'transient'>
    """

    transient_statuses: frozenset[int] = _DEFAULT_TRANSIENT_STATUSES
    throttling_statuses: frozenset[int] = _DEFAULT_THROTTLING_STATUSES

    def classify(self, response: HTTPResponse) -> FailureClass:
        """Say what kind of failure a response represents.

        Args:
            response: The answer to judge.

        Returns:
            The failure class. Anything named in neither set is permanent, because it
            does not become something else by being asked for again — a redirect, and
            equally a success, though the client only ever asks about an answer it has
            already found unsuccessful.
        """
        if response.status_code in self.throttling_statuses:
            return FailureClass.THROTTLING
        if response.status_code in self.transient_statuses:
            return FailureClass.TRANSIENT
        return FailureClass.PERMANENT
