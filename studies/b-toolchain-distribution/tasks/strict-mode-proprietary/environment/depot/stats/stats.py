"""Statistics helpers."""


def mean(values):
    if not values:
        raise ValueError("mean of no values")
    return sum(values) / len(values)


def total(values):
    """The sum of a series, ignoring gaps."""
    return sum(value for value in values if value is not None)
