"""Assembling a report (M6).

The report is the deliverable, and its rules are the plan's non-cuttable ones,
enforced here rather than remembered:

* **Rank per axis, never blended.** There is no composite score anywhere in this
  module, and adding one would mean inventing weights nobody pre-registered.
* **Unscored ≠ zero.** A trial with no score for an axis is not in that axis's
  numbers at all, and the count of such trials is printed beside them.
* **Digest mismatch ⇒ no comparison.** When one axis's trials were scored by two
  different grader specs, or one arm ran under two harness digests, the table is
  emitted **banded** — rows still shown, ranking withheld, warning attached.
* **Evidence gating.** ERROR trials are excluded from every statistic and
  counted; they never become failures.
* **Pre-registration echo.** The analysis block is printed as it was registered
  and as it now reads, with every amendment and its rationale.

A repetition verdict is a majority over repetitions **with errors counting
against**: an arm that solved a task twice and produced one unverifiable run has
two passes and one non-pass, not two passes out of two.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from duva_bench.adp.client import AdpClient
from duva_bench.analysis.extract import StudyOutcomes, TrialOutcome, digest_bands, extract
from duva_bench.analysis.process import ProcessMetrics, compute
from duva_bench.analysis.stats import (
    NoiseFloor,
    bootstrap_ci_over_tasks,
    discordance,
    holm,
    icc,
    mcnemar_exact,
    mean,
    paired_difference_ci,
    pooled_within_cell_sd,
)
from duva_bench.state import StateDir
from duva_bench.study.models import Study

# Seeded, and the seed is printed in the report. An interval nobody can
# reproduce is decoration.
BOOTSTRAP_SEED = 20260807

# Process metrics that are ranked like an axis. For Study A the first of these
# is the *primary* metric, which is why they are first-class rather than a
# footnote under the grader axes.
PROCESS_AXES: tuple[str, ...] = (
    "hallucinated_call_rate",
    "tool_error_rate",
    "metaprogramming_rate",
    "retry_rate",
)


@dataclass
class Report:
    """Everything a reader needs, and nothing derived from local state."""

    study: dict[str, Any]
    pre_registration: dict[str, Any]
    trials: list[dict[str, Any]] = field(default_factory=list)
    axes: dict[str, Any] = field(default_factory=dict)
    process: dict[str, Any] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "study": self.study,
            "pre_registration": self.pre_registration,
            "evidence": self.evidence,
            "axes": self.axes,
            "process": self.process,
            "cost": self.cost,
            "trials": self.trials,
            "warnings": self.warnings,
        }


def build_report(
    study: Study,
    *,
    state: StateDir,
    client: AdpClient | None = None,
    outcomes: StudyOutcomes | None = None,
    toolsets: dict[str, frozenset[str]] | None = None,
) -> Report:
    """Read the study back out of ADP and assemble its report."""
    from duva_bench.env import adp_credentials

    owned = client is None and outcomes is None
    if outcomes is None:
        client = client or adp_credentials().client()
        try:
            outcomes = extract(study, client=client, state=state)
        finally:
            if owned and client is not None:
                client.close()

    toolsets = toolsets or _toolsets_from_study(study)
    bands = digest_bands(outcomes)

    report = Report(
        study=_study_block(study),
        pre_registration=_pre_registration_block(study),
    )
    report.evidence = _evidence_block(outcomes, bands)
    report.warnings = _warnings(outcomes, bands)

    metrics = {
        trial.run_id: compute(trial.events, toolset=toolsets.get(trial.labels.get("toolset", "")))
        for trial in outcomes.trials
    }
    report.trials = [_trial_row(trial, metrics[trial.run_id]) for trial in outcomes.trials]

    for axis in outcomes.axis_names():
        report.axes[axis] = _axis_block(
            study,
            outcomes,
            axis,
            banded=axis in bands["split_axes"],
            value=_grader_score(axis),
            binary=_grader_passed(axis),
        )

    # Process metrics are rankable axes too, and for Study A one of them is the
    # *primary* metric. They are computed from trajectories rather than from a
    # grader, so they carry no pass/fail outcome and no McNemar test — the
    # interval is the inference, and the report says so rather than inventing a
    # p-value for a rate.
    for name in PROCESS_AXES:
        report.axes[f"process:{name}"] = _axis_block(
            study,
            outcomes,
            f"process:{name}",
            banded=bool(bands["split_arms"]),
            value=_process_value(name, metrics),
            binary=None,
        )

    report.process = _process_block(study, outcomes, metrics)
    report.cost = _cost_block(outcomes)
    return report


# --- blocks ------------------------------------------------------------------


def _study_block(study: Study) -> dict[str, Any]:
    return {
        "title": study.title,
        "digest": study.study_digest,
        "tasks": [task.id for task in study.tasks],
        "arms": {arm.id: arm.labels() for arm in study.arms},
        "repetitions": study.repetitions,
        "budget_usd_cap": str(study.budget_usd_cap),
        "adp": {"owner": study.adp.owner, "repo": study.adp.repo},
        "bootstrap_seed": BOOTSTRAP_SEED,
    }


def _pre_registration_block(study: Study) -> dict[str, Any]:
    registration = study.pre_registration
    return {
        "digest": registration.pre_registration_digest,
        "original_digest": registration.original_digest,
        "amended": registration.amended,
        # Both readings, always. An amended pre-registration that only printed
        # its current form would be indistinguishable from one written after the
        # results were in.
        "as_registered": registration.original().model_dump(mode="json"),
        "as_analyzed": registration.model_dump(mode="json"),
        "amendments": [amendment.model_dump(mode="json") for amendment in registration.amendments],
    }


def _evidence_block(outcomes: StudyOutcomes, bands: dict[str, Any]) -> dict[str, Any]:
    return {
        "trials": len(outcomes.trials),
        "verified": len(outcomes.included),
        # Counted and named, so "excluded" is never silent.
        "errors": len(outcomes.errored),
        "error_refs": [trial.external_ref or trial.run_id for trial in outcomes.errored],
        "missing_tasks": outcomes.missing_tasks,
        "read_errors": outcomes.read_errors,
        "digests": bands,
    }


def _warnings(outcomes: StudyOutcomes, bands: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for cell in bands["split_cells"]:
        warnings.append(
            f"{cell} was scored under more than one grader spec digest, so two arms on the "
            "same task were measured by different instruments. That axis is shown banded and "
            "is not ranked."
        )
    for arm in bands["split_arms"]:
        warnings.append(
            f"arm {arm!r} ran under more than one harness digest, so its rows are not one arm. "
            "Ranking is withheld."
        )
    if outcomes.errored:
        warnings.append(
            f"{len(outcomes.errored)} trial(s) failed the evidence gate and are excluded from "
            "every statistic below. They are listed, with the sub-check that failed, in the "
            "trial table."
        )
    if outcomes.missing_tasks:
        warnings.append(
            f"{len(outcomes.missing_tasks)} task(s) have no ADP intent, which means they were "
            f"never run: {', '.join(outcomes.missing_tasks)}."
        )
    return warnings


def _trial_row(trial: TrialOutcome, metrics: ProcessMetrics) -> dict[str, Any]:
    return {
        "run_id": trial.run_id,
        "external_ref": trial.external_ref,
        "task": trial.task_id,
        "arm": trial.arm_id,
        "repetition": trial.repetition,
        "verdict": trial.verdict,
        "failures": list(trial.failures),
        "axes": {
            axis.name: {"score": axis.score, "passed": axis.passed, "spec_digest": axis.spec_digest}
            for axis in trial.axes
        },
        "tokens_in": trial.tokens_in,
        "tokens_out": trial.tokens_out,
        "cost_micro_usd": trial.cost_micro_usd,
        "duration_ms": trial.duration_ms,
        "process": metrics.as_dict(),
    }


def _grader_score(axis: str) -> Callable[[TrialOutcome], float | None]:
    def value(trial: TrialOutcome) -> float | None:
        result = trial.axis(axis)
        return result.score if result is not None else None

    return value


def _grader_passed(axis: str) -> Callable[[TrialOutcome], bool | None]:
    def outcome(trial: TrialOutcome) -> bool | None:
        result = trial.axis(axis)
        return result.passed if result is not None else None

    return outcome


def _process_value(
    name: str, metrics: dict[str, ProcessMetrics]
) -> Callable[[TrialOutcome], float | None]:
    def value(trial: TrialOutcome) -> float | None:
        found = metrics.get(trial.run_id)
        # None when the rate is undefined — a trial with no tool calls has no
        # tool-error rate — and None stays out of the numbers rather than
        # entering them as a zero.
        return getattr(found, name) if found is not None else None

    return value


def _axis_block(
    study: Study,
    outcomes: StudyOutcomes,
    axis: str,
    *,
    banded: bool,
    value: Callable[[TrialOutcome], float | None],
    binary: Callable[[TrialOutcome], bool | None] | None,
) -> dict[str, Any]:
    tasks = [task.id for task in study.tasks]
    arms = [arm.id for arm in study.arms]

    cells: dict[tuple[str, str], list[TrialOutcome]] = {}
    for trial in outcomes.included:
        cells.setdefault((trial.task_id, trial.arm_id), []).append(trial)

    scored: dict[tuple[str, str], list[float]] = {}
    unscored: dict[str, int] = dict.fromkeys(arms, 0)
    for (task_id, arm_id), trials in cells.items():
        values: list[float] = []
        for trial in trials:
            measurement = value(trial)
            if measurement is None:
                unscored[arm_id] = unscored.get(arm_id, 0) + 1
                continue
            values.append(measurement)
        if values:
            scored[(task_id, arm_id)] = values

    noise = pooled_within_cell_sd(list(scored.values()))
    block: dict[str, Any] = {
        "axis": axis,
        "banded": banded,
        # The noise floor comes before any contrast, deliberately: it is the
        # answer to "is this difference worth a sentence".
        "noise_floor": noise.as_dict(),
        "cells": {
            f"{task}/{arm}": {
                "n": len(scored.get((task, arm), [])),
                "mean": mean(scored.get((task, arm), [])),
                "values": scored.get((task, arm), []),
            }
            for task in tasks
            for arm in arms
        },
        "unscored_trials": unscored,
        "arms": _arm_summaries(tasks, arms, scored, unscored),
        "icc": icc(
            [[value for value in scored.get((task, arm), [])] for task in tasks for arm in arms]
        ),
    }

    control = study.pre_registration.control_arm
    if banded:
        block["contrasts"] = {
            "unavailable": (
                "the trials on this axis were scored by more than one grader spec; ranking "
                "across different instruments would produce a number whose meaning depends "
                "on which rows were included"
            )
        }
    elif control is None:
        block["contrasts"] = {
            "unavailable": "the pre-registration declares no control arm to contrast against"
        }
    else:
        block["contrasts"] = _contrasts(
            study, outcomes, axis, tasks, control, scored, noise, binary=binary
        )
    return block


def _arm_summaries(
    tasks: list[str],
    arms: list[str],
    scored: dict[tuple[str, str], list[float]],
    unscored: dict[str, int],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for arm in arms:
        per_task = [scored[(task, arm)] for task in tasks if (task, arm) in scored]
        if not per_task:
            summaries.append(
                {
                    "arm": arm,
                    "n": 0,
                    "mean": None,
                    "ci": {"unavailable": "no scored trials"},
                    "unscored": unscored.get(arm, 0),
                }
            )
            continue
        task_means = [sum(values) / len(values) for values in per_task]
        low, high = bootstrap_ci_over_tasks(per_task, seed=BOOTSTRAP_SEED)
        summaries.append(
            {
                "arm": arm,
                "n": sum(len(values) for values in per_task),
                "tasks": len(per_task),
                # Mean over tasks of each task's mean, so a task with more
                # repetitions does not outvote one with fewer.
                "mean": sum(task_means) / len(task_means),
                "ci": {"low": low, "high": high, "confidence": 0.95},
                "unscored": unscored.get(arm, 0),
            }
        )
    # Ranked per axis, descending. No composite anywhere.
    return sorted(summaries, key=lambda row: (row["mean"] is None, -(row["mean"] or 0.0)))


def _contrasts(
    study: Study,
    outcomes: StudyOutcomes,
    axis: str,
    tasks: list[str],
    control: str,
    scored: dict[tuple[str, str], list[float]],
    noise: NoiseFloor,
    *,
    binary: Callable[[TrialOutcome], bool | None] | None,
) -> dict[str, Any]:
    raw_p: dict[str, float] = {}
    rows: dict[str, dict[str, Any]] = {}

    for arm in [a.id for a in study.arms if a.id != control]:
        paired_tasks = [
            task for task in tasks if (task, control) in scored and (task, arm) in scored
        ]
        if not paired_tasks:
            rows[arm] = {
                "unavailable": f"no task has scored trials in both {control!r} and {arm!r}"
            }
            continue

        control_values = [scored[(task, control)] for task in paired_tasks]
        arm_values = [scored[(task, arm)] for task in paired_tasks]
        delta = sum(
            sum(b) / len(b) - sum(a) / len(a)
            for a, b in zip(control_values, arm_values, strict=True)
        ) / len(paired_tasks)

        low, high = paired_difference_ci(control_values, arm_values, seed=BOOTSTRAP_SEED)

        rows[arm] = {
            "vs": control,
            "tasks": len(paired_tasks),
            "delta": delta,
            "ci": {"low": low, "high": high, "confidence": 0.95},
            # The contrast in units of the noise the design already has. A
            # difference smaller than one noise floor is a difference the study
            # cannot distinguish from a rerun.
            "delta_in_sd": noise.in_sd_units(delta),
        }

        if binary is None:
            # A rate has no pass/fail outcome to build a 2x2 table from, so
            # there is no exact test to run. The interval above *is* the
            # inference; a p-value here would be one this design did not earn.
            rows[arm]["mcnemar"] = {
                "unavailable": (
                    "this metric is a rate rather than a pass/fail outcome, so there is no "
                    "discordance table; read the interval"
                )
            }
            continue

        control_pass = [_majority_pass(outcomes, task, control, binary) for task in paired_tasks]
        arm_pass = [_majority_pass(outcomes, task, arm, binary) for task in paired_tasks]
        both_pass, a_only, b_only, both_fail = discordance(control_pass, arm_pass)
        p_value = mcnemar_exact(both_pass, a_only, b_only, both_fail)
        raw_p[arm] = p_value
        rows[arm]["mcnemar"] = {
            "both_pass": both_pass,
            "control_only": a_only,
            "arm_only": b_only,
            "both_fail": both_fail,
            "p": p_value,
        }

    for arm, adjusted in holm(raw_p).items():
        rows[arm]["holm_p"] = adjusted
    return {"control": control, "correction": "holm", "arms": rows}


def _majority_pass(
    outcomes: StudyOutcomes,
    task: str,
    arm: str,
    binary: Callable[[TrialOutcome], bool | None],
) -> bool:
    """The repetition verdict for one cell: majority pass, errors counting against.

    An arm that solved a task twice and produced one unverifiable run has two
    passes and one non-pass — not two out of two. Counting an ERROR as absent
    would let an arm improve its record by failing to produce evidence.
    """
    passes = 0
    total = 0
    for trial in outcomes.trials:
        if trial.task_id != task or trial.arm_id != arm:
            continue
        total += 1
        if not trial.included:
            continue  # an ERROR is a non-pass, and it still counts in the total
        if binary(trial):
            passes += 1
    return total > 0 and passes * 2 > total


def _process_block(
    study: Study, outcomes: StudyOutcomes, metrics: dict[str, ProcessMetrics]
) -> dict[str, Any]:
    per_arm: dict[str, Any] = {}
    for arm in study.arms:
        trials = [trial for trial in outcomes.included if trial.arm_id == arm.id]
        collected = [metrics[trial.run_id] for trial in trials]
        calls = sum(item.tool_calls for item in collected)
        per_arm[arm.id] = {
            "trials": len(trials),
            "tool_calls": calls,
            "tool_failures": sum(item.tool_failures for item in collected),
            # Rates over the arm's whole corpus of calls, and None rather than
            # zero when the arm made none.
            "tool_error_rate": (
                sum(item.tool_failures for item in collected) / calls if calls else None
            ),
            "hallucinated_call_rate": (
                sum(item.hallucinated_calls for item in collected) / calls if calls else None
            ),
            "metaprogramming_rate": (
                sum(item.metaprogramming_calls for item in collected) / calls if calls else None
            ),
            "retry_rate": (sum(item.retries for item in collected) / calls if calls else None),
            "unknown_names": sorted({name for item in collected for name in item.unknown_names}),
        }
    return per_arm


def _cost_block(outcomes: StudyOutcomes) -> dict[str, Any]:
    priced = [trial for trial in outcomes.trials if trial.cost_micro_usd]
    return {
        "total_micro_usd": sum(trial.cost_micro_usd for trial in outcomes.trials),
        "total_usd": sum(trial.cost_micro_usd for trial in outcomes.trials) / 1_000_000,
        "priced_trials": len(priced),
        # Trials ADP reported no cost for. Not free trials.
        "unpriced_trials": len(outcomes.trials) - len(priced),
        "tokens_in": sum(trial.tokens_in for trial in outcomes.trials),
        "tokens_out": sum(trial.tokens_out for trial in outcomes.trials),
        "by_arm": _cost_by_arm(outcomes),
    }


def _cost_by_arm(outcomes: StudyOutcomes) -> dict[str, Any]:
    by_arm: dict[str, dict[str, int]] = {}
    for trial in outcomes.trials:
        bucket = by_arm.setdefault(
            trial.arm_id, {"cost_micro_usd": 0, "tokens_in": 0, "tokens_out": 0, "trials": 0}
        )
        bucket["cost_micro_usd"] += trial.cost_micro_usd
        bucket["tokens_in"] += trial.tokens_in
        bucket["tokens_out"] += trial.tokens_out
        bucket["trials"] += 1
    return by_arm


def _toolsets_from_study(study: Study) -> dict[str, frozenset[str]]:
    """Tool vocabularies per toolset name, from the study spec.

    The spec records a digest per tool name, which is exactly the vocabulary the
    hallucinated-call rate needs — a call to a name not in it is a call to a tool
    the arm did not have.
    """
    return {arm.toolset.name: frozenset(arm.toolset.tools) for arm in study.arms}


def write_report(report: Report, destination: Path) -> Path:
    """Write ``report.json`` and ``report.html`` into ``destination``."""
    from duva_bench.report.render import render_html

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    payload = report.as_dict()
    (destination / "report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (destination / "report.html").write_text(render_html(report), encoding="utf-8")
    return destination
