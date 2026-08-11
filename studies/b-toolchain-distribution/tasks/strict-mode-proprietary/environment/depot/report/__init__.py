"""Turn a series of readings into a summary."""

from stats import mean


def summarize(readings):
    clean = [value for value in readings if value is not None]
    return {"count": len(clean), "mean": mean(clean)}


def average_of_averages(series):
    return mean([mean(one) for one in series])
