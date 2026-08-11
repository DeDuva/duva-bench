"""Turn a series of readings into a summary."""

from stats import mean, spread


def summarize(readings):
    return {"count": len(readings), "mean": mean(readings), "spread": spread(readings)}
