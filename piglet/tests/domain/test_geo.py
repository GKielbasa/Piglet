import pytest

from piglet.domain.geo import Coordinates, distance_km
from piglet.errors import InvalidRequestError

WARSAW = Coordinates(52.2297, 21.0122)
KRAKOW = Coordinates(50.0647, 19.9450)
NULL_ISLAND = Coordinates(0.0, 0.0)


def test_a_coordinate_keeps_the_numbers_it_was_built_with() -> None:
    point = Coordinates(52.2297, 21.0122)
    assert (point.latitude, point.longitude) == (52.2297, 21.0122)


def test_two_coordinates_with_the_same_numbers_are_equal() -> None:
    assert Coordinates(52.2297, 21.0122) == Coordinates(52.2297, 21.0122)


@pytest.mark.parametrize("latitude", [90.1, -90.1, 1000.0])
def test_a_latitude_outside_the_poles_is_refused(latitude: float) -> None:
    with pytest.raises(InvalidRequestError, match="latitude"):
        Coordinates(latitude, 0.0)


@pytest.mark.parametrize("longitude", [180.1, -180.1, 1000.0])
def test_a_longitude_outside_the_antimeridian_is_refused(longitude: float) -> None:
    with pytest.raises(InvalidRequestError, match="longitude"):
        Coordinates(0.0, longitude)


@pytest.mark.parametrize(("latitude", "longitude"), [(90.0, 0.0), (-90.0, 0.0), (0.0, 180.0), (0.0, -180.0)])
def test_the_poles_and_the_antimeridian_are_accepted(latitude: float, longitude: float) -> None:
    assert Coordinates(latitude, longitude).latitude == latitude


def test_the_distance_from_a_point_to_itself_is_zero() -> None:
    assert distance_km(WARSAW, WARSAW) == 0.0


def test_the_distance_is_the_same_in_both_directions() -> None:
    assert distance_km(WARSAW, KRAKOW) == distance_km(KRAKOW, WARSAW)


def test_one_degree_of_latitude_is_about_111_km() -> None:
    assert distance_km(NULL_ISLAND, Coordinates(1.0, 0.0)) == pytest.approx(111.19, rel=0.01)


def test_warsaw_to_krakow_matches_the_published_figure() -> None:
    assert distance_km(WARSAW, KRAKOW) == pytest.approx(252.0, rel=0.01)


def test_two_points_either_side_of_the_antimeridian_are_neighbours() -> None:
    assert distance_km(Coordinates(0.0, 179.5), Coordinates(0.0, -179.5)) == pytest.approx(111.19, rel=0.01)


def test_antipodal_points_are_half_the_earths_circumference_apart() -> None:
    assert distance_km(NULL_ISLAND, Coordinates(0.0, 180.0)) == pytest.approx(20015.0, rel=0.01)
