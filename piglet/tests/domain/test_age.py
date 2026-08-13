import pytest

from piglet.domain.age import birth_years_for_age_range


def test_someone_at_the_youngest_age_is_inside() -> None:
    assert 2006 in birth_years_for_age_range(20, 40, 2026)


def test_someone_at_the_oldest_age_is_inside() -> None:
    assert 1986 in birth_years_for_age_range(20, 40, 2026)


def test_someone_a_year_too_young_is_outside() -> None:
    assert 2007 not in birth_years_for_age_range(20, 40, 2026)


def test_someone_a_year_too_old_is_outside() -> None:
    assert 1985 not in birth_years_for_age_range(20, 40, 2026)


def test_one_age_covers_one_year() -> None:
    assert list(birth_years_for_age_range(30, 30, 2026)) == [1996]


def test_ages_the_wrong_way_round_are_refused() -> None:
    with pytest.raises(ValueError, match="greater than"):
        birth_years_for_age_range(40, 20, 2026)
