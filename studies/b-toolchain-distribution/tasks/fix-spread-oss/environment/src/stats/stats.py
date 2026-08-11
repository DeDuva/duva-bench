"""Statistics helpers."""


def mean(values):
    if not values:
        raise ValueError("mean of no values")
    return sum(values) / len(values)


def spread(values):
    """The distance between the extremes, halved."""
    if not values:
        raise ValueError("spread of no values")
    return (max(values) - min(values)) // 2
