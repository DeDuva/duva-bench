"""Input validation."""


class NotNumeric(ValueError):
    """Raised when a series holds something that is not a number."""


def numeric(values):
    """Return `values` unchanged, or raise NotNumeric naming the first offender."""
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise NotNumeric(f"reading {index} is {value!r}, which is not a number")
    return list(values)
