"""Statistics (M6).

Transliterated from adp-replay's ``stats/paired.py`` and extended with the two
things this project needs and that one did not: **Holm correction** across the
pairwise comparisons a factorial produces, and a **pooled within-cell standard
deviation** as a noise floor, so a contrast can be stated in units of the
variation the design already has (mirroring squad-lab's ``variance.ts``).

The rules that shape every function here:

* **Resample tasks, never trajectories.** Repetitions within a task are not
  independent samples; resampling them treats correlated runs as fresh evidence
  and produces an interval that is narrower than the experiment supports.
* **Keep pairs together.** The advantage of a paired design is that task
  difficulty cancels. A bootstrap that drew the two arms independently would
  throw that away.
* **Seeded.** Every interval here is reproducible from the report, or it is not
  evidence.
* **Never invent a number.** Where a statistic is not computable, the return is
  ``{"unavailable": <reason>}`` — not zero, not NaN, not omitted.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from math import comb, sqrt
from typing import Any

DEFAULT_RESAMPLES = 10_000
DEFAULT_CONFIDENCE = 0.95


# --- pairwise significance ---------------------------------------------------


def mcnemar_exact(both_pass: int, a_only: int, b_only: int, both_fail: int) -> float:
    """Exact McNemar p-value for paired pass/fail outcomes.

    Only the discordant pairs carry information: a task both arms solved, or
    neither did, says nothing about which is better. Conditional on the number
    of discordant pairs, the null is that each falls either way with equal
    probability — an exact two-sided binomial test at p = 0.5.

    Exact rather than the chi-square approximation because the discordant count
    *is* the sample size here. A six-task study can easily produce three
    discordant pairs, and the approximation is not trustworthy there — which is
    exactly the regime a controlled experiment lives in.
    """
    for name, value in (
        ("both_pass", both_pass),
        ("a_only", a_only),
        ("b_only", b_only),
        ("both_fail", both_fail),
    ):
        if value < 0:
            raise ValueError(f"{name} must not be negative")

    discordant = a_only + b_only
    if discordant == 0:
        # No evidence either way. Reporting 1.0 rather than raising keeps a
        # sweep over many arms from turning "these two tied everywhere" into an
        # exception.
        return 1.0

    smaller = min(a_only, b_only)
    tail: float = sum(comb(discordant, k) for k in range(smaller + 1)) / 2**discordant
    return min(1.0, 2.0 * tail)


def holm(p_values: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni step-down correction.

    A factorial with four arms produces three comparisons against the control,
    per axis. Reporting three uncorrected p-values and calling the smallest one
    significant is how a study finds an effect in noise, and doing it per axis
    multiplies the problem.

    Holm rather than Bonferroni because it is uniformly more powerful and needs
    no extra assumptions: same family-wise error rate, more findings survive it.
    Adjusted values are made monotone, so a later comparison can never come out
    more significant than an earlier one it does not beat.
    """
    if not p_values:
        return {}

    ordered = sorted(p_values.items(), key=lambda item: item[1])
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - index) * value))
        adjusted[name] = running
    return adjusted


# --- intervals ---------------------------------------------------------------


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    position = q * (len(values) - 1)
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def bootstrap_ci_over_tasks(
    per_task: Sequence[Sequence[float]],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = 0,
) -> tuple[float, float]:
    """CI for the mean over tasks, resampling **tasks** whole.

    The statistic is the mean over tasks of each task's own mean, so a task with
    thirty repetitions does not outvote one with three.
    """
    tasks = [list(values) for values in per_task if values]
    if not tasks:
        raise ValueError("a confidence interval needs at least one task with observations")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")

    rng = random.Random(seed)
    means = [sum(values) / len(values) for values in tasks]
    count = len(means)

    draws = sorted(
        sum(means[rng.randrange(count)] for _ in range(count)) / count for _ in range(resamples)
    )
    tail = (1.0 - confidence) / 2.0
    return (_quantile(draws, tail), _quantile(draws, 1.0 - tail))


def paired_difference_ci(
    control: Sequence[Sequence[float]],
    treatment: Sequence[Sequence[float]],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = 0,
) -> tuple[float, float]:
    """CI for the treatment-minus-control difference, tasks resampled in pairs."""
    if len(control) != len(treatment):
        raise ValueError("paired arms must cover the same tasks")

    pairs = [
        (list(first), list(second))
        for first, second in zip(control, treatment, strict=True)
        if first and second
    ]
    if not pairs:
        raise ValueError("a paired interval needs at least one task with observations in both arms")

    rng = random.Random(seed)
    deltas = [sum(second) / len(second) - sum(first) / len(first) for first, second in pairs]
    count = len(deltas)

    draws = sorted(
        sum(deltas[rng.randrange(count)] for _ in range(count)) / count for _ in range(resamples)
    )
    tail = (1.0 - confidence) / 2.0
    return (_quantile(draws, tail), _quantile(draws, 1.0 - tail))


# --- the noise floor ---------------------------------------------------------


@dataclass(frozen=True)
class NoiseFloor:
    """Pooled within-cell standard deviation, and what it is pooled from.

    This is the number a report has to print **before** any contrast, because it
    is the answer to "how big is a difference worth talking about". A study that
    reports a 4-point difference without saying that repeated runs of the same
    cell vary by 6 has not reported anything.
    """

    sd: float | None
    cells: int
    degrees_of_freedom: int
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.sd is None:
            return {"unavailable": self.reason or "not computable"}
        return {
            "pooled_sd": self.sd,
            "cells": self.cells,
            "degrees_of_freedom": self.degrees_of_freedom,
        }

    def in_sd_units(self, contrast: float) -> float | dict[str, str]:
        """A contrast expressed in noise floors, or why it cannot be."""
        if self.sd is None:
            return {"unavailable": self.reason or "no noise floor"}
        if self.sd == 0:
            return {"unavailable": "every repetition of every cell gave the same value"}
        return contrast / self.sd


def pooled_within_cell_sd(cells: Sequence[Sequence[float]]) -> NoiseFloor:
    """The noise floor: how much repeated runs of one cell differ.

    Pooled across cells rather than computed per cell, because a single cell of
    three repetitions gives an sd nobody should lean on, while twenty such cells
    pooled give a usable one. Cells with fewer than two repetitions contribute
    nothing — there is no within-cell variation to measure in a cell that ran
    once.
    """
    usable = [list(values) for values in cells if len(values) >= 2]
    if not usable:
        return NoiseFloor(
            sd=None,
            cells=0,
            degrees_of_freedom=0,
            reason=(
                "no cell has two or more repetitions, so there is no within-cell variation "
                "to measure; a study with one repetition per cell has no noise floor"
            ),
        )

    numerator = 0.0
    degrees = 0
    for values in usable:
        mean = sum(values) / len(values)
        numerator += sum((value - mean) ** 2 for value in values)
        degrees += len(values) - 1

    if degrees == 0:  # pragma: no cover - guarded by the filter above
        return NoiseFloor(sd=None, cells=len(usable), degrees_of_freedom=0, reason="no residual df")
    return NoiseFloor(sd=sqrt(numerator / degrees), cells=len(usable), degrees_of_freedom=degrees)


# --- variance decomposition --------------------------------------------------


def icc(per_task: Sequence[Sequence[float]]) -> dict[str, Any]:
    """ICC(1): how much variance sits between tasks versus within them.

    Near 1, tasks differ and repetitions agree — the corpus is doing the work
    and more repetitions buy little. Near 0, the outcome is mostly noise, and no
    number of such tasks will settle anything.

    Returns ``{"unavailable": reason}`` rather than raising, because a study
    with one repetition per cell is a legitimate study whose report simply
    cannot carry this number.
    """
    tasks = [list(values) for values in per_task if values]
    if len(tasks) < 2:
        return {"unavailable": "ICC needs at least two tasks"}
    if all(len(values) < 2 for values in tasks):
        return {"unavailable": "ICC needs at least one task with two or more repetitions"}

    total = sum(len(values) for values in tasks)
    grand = sum(sum(values) for values in tasks) / total
    groups = len(tasks)

    between = sum(len(values) * (sum(values) / len(values) - grand) ** 2 for values in tasks) / (
        groups - 1
    )
    within_df = total - groups
    if within_df == 0:
        return {"unavailable": "no within-task degrees of freedom"}
    within = (
        sum(
            sum((value - mean) ** 2 for value in values)
            for values, mean in ((v, sum(v) / len(v)) for v in tasks)
        )
        / within_df
    )

    sizes = [len(values) for values in tasks]
    effective = (total - sum(size**2 for size in sizes) / total) / (groups - 1)
    denominator = between + (effective - 1) * within
    # A negative estimate means the between component is smaller than the within
    # one. Reported as zero rather than as a negative share of variance, which
    # is not a thing.
    coefficient = 0.0 if denominator == 0 else max(0.0, min(1.0, (between - within) / denominator))

    return {
        "icc": coefficient,
        "between_tasks": coefficient,
        "within_tasks": 1.0 - coefficient,
        "tasks": groups,
        "observations": total,
    }


# --- helpers the report uses -------------------------------------------------


def mean(values: Sequence[float]) -> float | None:
    """The mean, or None for an empty sample. Never 0.0 for 'nothing here'."""
    return sum(values) / len(values) if values else None


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def discordance(control: Sequence[bool], treatment: Sequence[bool]) -> tuple[int, int, int, int]:
    """The 2×2 table McNemar reads, from paired per-task outcomes."""
    if len(control) != len(treatment):
        raise ValueError("paired arms must cover the same tasks")
    both_pass = sum(1 for a, b in zip(control, treatment, strict=True) if a and b)
    a_only = sum(1 for a, b in zip(control, treatment, strict=True) if a and not b)
    b_only = sum(1 for a, b in zip(control, treatment, strict=True) if b and not a)
    both_fail = sum(1 for a, b in zip(control, treatment, strict=True) if not a and not b)
    return both_pass, a_only, b_only, both_fail
