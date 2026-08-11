"""Turn a series of readings into a summary."""

from stats import mean


def summarize(readings):
    return {"count": len(readings), "mean": mean(readings)}
