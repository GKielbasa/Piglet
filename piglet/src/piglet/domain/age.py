"""An age and a birth year are the same fact told two ways."""

__all__ = ["birth_years_for_age_range"]


def birth_years_for_age_range(minimum_age: int, maximum_age: int, as_of_year: int) -> range:
    """The birth years of everyone whose age falls in a range during one year.

    The range is closed: both ages count as inside it. Callers that want it open pass their
    own bounds — where the edge lies is the question being asked, not something this function
    can know.

    Where a source records a birth year rather than a date, that is the only reading available:
    "age" can only mean the age reached at some point during `as_of_year`, because whether the
    birthday has already passed is not in the data.

    Args:
        minimum_age: The youngest age that counts, included.
        maximum_age: The oldest age that counts, included.
        as_of_year: The year the ages are measured in.

    Returns:
        The birth years, earliest first.

    Raises:
        ValueError: If the two ages are the wrong way round. That is a caller's mistake, and
            returning nothing at all would hide it behind an empty result.

    Example:
        >>> 1986 in birth_years_for_age_range(20, 40, 2026)
        True
    """
    if minimum_age > maximum_age:
        raise ValueError(f"minimum_age {minimum_age} is greater than maximum_age {maximum_age}")
    return range(as_of_year - maximum_age, as_of_year - minimum_age + 1)
