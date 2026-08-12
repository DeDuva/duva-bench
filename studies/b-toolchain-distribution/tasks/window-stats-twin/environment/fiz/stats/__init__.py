"""Statistics helpers."""


def mean(values):
    if not values:
        raise ValueError("mean of no values")
    return sum(values) / len(values)
