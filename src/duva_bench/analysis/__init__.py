"""Analysis: outcomes from ADP, process metrics, and pre-registered statistics (M6)."""

from __future__ import annotations

from duva_bench.analysis.extract import (
    AxisOutcome,
    StudyOutcomes,
    TrialOutcome,
    digest_bands,
    extract,
)
from duva_bench.analysis.process import ProcessMetrics, compute
from duva_bench.analysis.stats import (
    NoiseFloor,
    bootstrap_ci_over_tasks,
    discordance,
    holm,
    icc,
    mcnemar_exact,
    paired_difference_ci,
    pooled_within_cell_sd,
)

__all__ = [
    "AxisOutcome",
    "NoiseFloor",
    "ProcessMetrics",
    "StudyOutcomes",
    "TrialOutcome",
    "bootstrap_ci_over_tasks",
    "compute",
    "digest_bands",
    "discordance",
    "extract",
    "holm",
    "icc",
    "mcnemar_exact",
    "paired_difference_ci",
    "pooled_within_cell_sd",
]
