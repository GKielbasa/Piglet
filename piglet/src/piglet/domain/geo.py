"""Where something is, and how far it is from something else."""

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from piglet.errors import InvalidRequestError

__all__ = ["Coordinates", "distance_km"]

_EARTH_RADIUS_KM = 6371.0088
_LATITUDE_LIMIT = 90.0
_LONGITUDE_LIMIT = 180.0


@dataclass(frozen=True, slots=True)
class Coordinates:
    """One point on the earth's surface, in degrees.

    Validated on construction, because a latitude of 1000 is not a point anywhere and the
    formula below would answer for it anyway — quietly, with a plausible-looking number.

    Attributes:
        latitude: Degrees north of the equator, from -90 at the south pole to 90 at the north.
        longitude: Degrees east of the prime meridian, from -180 to 180. Both ends name the
            same meridian.

    Example:
        >>> Coordinates(52.2297, 21.0122).latitude
        52.2297
    """

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -_LATITUDE_LIMIT <= self.latitude <= _LATITUDE_LIMIT:
            raise InvalidRequestError(
                f"latitude must be between -{_LATITUDE_LIMIT} and {_LATITUDE_LIMIT} degrees, got {self.latitude}"
            )
        if not -_LONGITUDE_LIMIT <= self.longitude <= _LONGITUDE_LIMIT:
            raise InvalidRequestError(
                f"longitude must be between -{_LONGITUDE_LIMIT} and {_LONGITUDE_LIMIT} degrees, got {self.longitude}"
            )


def distance_km(here: Coordinates, there: Coordinates) -> float:
    """Measure the distance between two points, along the earth's surface.

    The haversine formula, which treats the earth as a sphere. That costs up to about 0.5%
    against an ellipsoidal formula, which is far below the precision of any coordinate that
    arrives as four decimal places, and it is why nothing heavier is used here.

    Args:
        here: Where to measure from.
        there: Where to measure to.

    Returns:
        The distance in kilometres. Never negative, and the same whichever way round the two
        points are given.

    Example:
        >>> round(distance_km(Coordinates(0.0, 0.0), Coordinates(1.0, 0.0)))
        111
    """
    latitude_gap = radians(there.latitude - here.latitude)
    longitude_gap = radians(there.longitude - here.longitude)
    half_chord_squared = (
        sin(latitude_gap / 2) ** 2
        + cos(radians(here.latitude)) * cos(radians(there.latitude)) * sin(longitude_gap / 2) ** 2
    )
    # For two points on opposite sides of the earth the term is 1, and rounding can carry it a
    # fraction above — where asin has no answer and raises instead of returning half a circumference.
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(min(1.0, half_chord_squared)))
