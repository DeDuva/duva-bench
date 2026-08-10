"""Outcome extraction, from ADP and only from ADP (M6).

Every number in a report is read back out of the system of record. Nothing here
consults ``progress.jsonl``, a trial record, or anything else on disk except to
learn *which intent to ask about*. That is the difference between a report and a
summary of what a script believed while it was running: this one can be
recomputed by anyone holding a read token, and if it disagrees with the run it
describes, the run wins.

Three reads per task, all per-intent because ADP caps its lists at 200 rows
(§3.6):

* ``GET /runs/compare?intent_id=`` — labels, per-axis evals, tokens, cost, tool
  counts, one row per run
* ``GET /runs/{id}/verify`` — the evidence gate
* ``GET /runs/{id}/trajectory`` — the events the process metrics are computed
  from

The gate runs on every row. A trial whose evidence does not check out is an
``ERROR``: it keeps its row, it is excluded from every statistic, and the count
is printed. It never becomes a failure, and it never becomes a zero.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from duva_bench.adp.client import AdpClient, AdpError
from duva_bench.adp.gate import Verdict, verify_gate
from duva_bench.adp.models import RunComparison, TrajectoryEvent
from duva_bench.state import StateDir
from duva_bench.study.models import Study

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AxisOutcome:
    """One axis of one trial.

    ``score`` is None when the grader did not produce a number. It is never
    coerced: "unscored" and "scored zero" are different claims about the arm,
    and only one of them is about the work.
    """

    name: str
    score: float | None
    passed: bool | None
    spec_digest: str | None


@dataclass(frozen=True)
class TrialOutcome:
    """One trial, as ADP describes it."""

    run_id: str
    external_ref: str | None
    task_id: str
    arm_id: str
    repetition: int | None
    labels: dict[str, str]
    verdict: str
    failures: tuple[str, ...]
    axes: tuple[AxisOutcome, ...]
    tokens_in: int
    tokens_out: int
    cost_micro_usd: int
    duration_ms: int
    tool_calls: int
    tool_failures: int
    events: tuple[TrajectoryEvent, ...] = ()

    @property
    def included(self) -> bool:
        """Whether this trial may enter a statistic."""
        return self.verdict == "VERIFIED"

    @property
    def arm_digest(self) -> str | None:
        return self.labels.get("arm_digest")

    def axis(self, name: str) -> AxisOutcome | None:
        for axis in self.axes:
            if axis.name == name:
                return axis
        return None


@dataclass
class StudyOutcomes:
    """Every trial of a study, plus what could not be read."""

    trials: list[TrialOutcome] = field(default_factory=list)
    # Intents the study never minted, i.e. tasks that were never run.
    missing_tasks: list[str] = field(default_factory=list)
    read_errors: list[str] = field(default_factory=list)
    # Runs ADP holds against this study's intents that are not this study's
    # results — a repetition past the study's own, or a cell produced by an
    # older adapter. Counted and named rather than dropped in silence: a report
    # that quietly discards rows is as hard to trust as one that quietly
    # includes them.
    out_of_scope: list[str] = field(default_factory=list)

    @property
    def included(self) -> list[TrialOutcome]:
        return [trial for trial in self.trials if trial.included]

    @property
    def errored(self) -> list[TrialOutcome]:
        return [trial for trial in self.trials if not trial.included]

    def axis_names(self) -> list[str]:
        return sorted({axis.name for trial in self.trials for axis in trial.axes})

    def by_cell(self, axis: str) -> dict[tuple[str, str], list[TrialOutcome]]:
        """Trials grouped by (task, arm), included only."""
        cells: dict[tuple[str, str], list[TrialOutcome]] = {}
        for trial in self.included:
            if trial.axis(axis) is not None:
                cells.setdefault((trial.task_id, trial.arm_id), []).append(trial)
        return cells


def extract(
    study: Study,
    *,
    client: AdpClient,
    state: StateDir,
    with_trajectories: bool = True,
) -> StudyOutcomes:
    """Read every trial of ``study`` back out of ADP.

    "Every trial of this study" is narrower than "every run against this study's
    intents", and the difference is not academic. An intent accumulates
    everything ever run for its task: repetitions beyond the study's own, one-off
    `duva-bench trial` invocations while debugging, and cells re-run after an
    adapter change. The first report rendered here described **13 trials for an
    eight-trial study** and banded an arm as having two harness identities —
    correctly, because it had gathered up runs from before and after gate G1's
    seven fixes.

    So a row is this study's result when its cell is one the study planned *and*
    it was produced by the adapter now installed. Everything else is recorded in
    ``out_of_scope`` and counted in the report.
    """
    from duva_bench import ADAPTER_VERSION
    from duva_bench.exec.scheduler import plan_trials

    outcomes = StudyOutcomes()
    intents = state.known_intents()
    planned = {trial.external_ref(study) for trial in plan_trials(study)}
    adapter = f"duva-bench/{ADAPTER_VERSION}"

    for task in study.tasks:
        intent_id = intents.get(task.id)
        if intent_id is None:
            outcomes.missing_tasks.append(task.id)
            continue

        try:
            rows = client.compare_runs(study.adp.owner, study.adp.repo, intent_id=intent_id)
        except AdpError as error:
            outcomes.read_errors.append(f"{task.id}: {error}")
            continue

        for row in rows:
            if row.labels.get("study") not in (None, study.study_digest):
                # Another study's runs against the same task. Skipped rather
                # than counted: a report that quietly included them would be
                # describing an experiment nobody ran.
                continue
            ref = row.external_ref or ""
            if _cell_of(ref) not in planned:
                outcomes.out_of_scope.append(f"{ref} (not a cell this study plans)")
                continue
            if row.labels.get("adapter") != adapter:
                outcomes.out_of_scope.append(
                    f"{ref} (produced by {row.labels.get('adapter') or 'an unrecorded adapter'}, "
                    f"not {adapter})"
                )
                continue
            outcomes.trials.append(
                _outcome(study, client, task.id, row, with_trajectories=with_trajectories)
            )

    return outcomes


def _outcome(
    study: Study,
    client: AdpClient,
    task_id: str,
    row: RunComparison,
    *,
    with_trajectories: bool,
) -> TrialOutcome:
    verdict: Verdict = verify_gate(client, study.adp.owner, study.adp.repo, row.run_id)

    events: tuple[TrajectoryEvent, ...] = ()
    if with_trajectories:
        try:
            events = client.full_trajectory(study.adp.owner, study.adp.repo, row.run_id).events
        except AdpError as error:
            logger.warning("could not read the trajectory of %s: %s", row.run_id, error)

    repetition = row.labels.get("repetition")
    return TrialOutcome(
        run_id=row.run_id,
        external_ref=row.external_ref,
        task_id=row.labels.get("task", task_id),
        arm_id=row.labels.get("arm", "?"),
        repetition=int(repetition) if repetition and repetition.isdigit() else None,
        labels=dict(row.labels),
        verdict=verdict.status,
        failures=verdict.failures,
        axes=tuple(
            AxisOutcome(
                name=result.name,
                score=result.score,
                passed=result.passed,
                spec_digest=result.spec_digest,
            )
            for result in row.evals
        ),
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        cost_micro_usd=row.cost_micro_usd,
        duration_ms=row.duration_ms,
        tool_calls=row.tool_calls,
        tool_failures=row.tool_failures,
        events=events,
    )


def _cell_of(external_ref: str) -> str:
    """The cell an external ref belongs to, ignoring which attempt it was.

    `…:r1` and `…:r1/a2` are the same cell — one is the retry of the other after
    an abandoned or stale-instrument attempt. See `duva_bench.exec.trial._open_run`.
    """
    return external_ref.split("/a", 1)[0]


def digest_bands(outcomes: StudyOutcomes) -> dict[str, Any]:
    """Which digests the included trials disagree about.

    **Digest mismatch ⇒ no comparison** (execution-plan §0.6). Two arms scored
    by different grader specs, or run under different harness identities, are
    not two arms of one experiment; ranking them would produce a number whose
    meaning changes with which rows happened to be included.

    The comparison a band protects is **between arms within a task**, so that is
    the unit the split is computed over. Two *tasks* being scored by two
    different graders is not a mismatch — it is the normal case, since each task
    has its own grader — and banding an axis for that would band every study
    with more than one task and make the warning meaningless.

    This decides nothing on its own. It reports the bands; the report renders
    the warning and withholds the ranking.
    """
    per_task_axis: dict[tuple[str, str], set[str]] = {}
    axis_digests: dict[str, set[str]] = {}
    harnesses: dict[str, set[str]] = {}

    for trial in outcomes.included:
        for axis in trial.axes:
            if not axis.spec_digest:
                continue
            per_task_axis.setdefault((trial.task_id, axis.name), set()).add(axis.spec_digest)
            axis_digests.setdefault(axis.name, set()).add(axis.spec_digest)
        # The harness identity is Harbor's *and ours*. A run says which agent
        # and version it used; until 2026-08-10 it said nothing about the
        # adapter that drove that agent and mapped its trace, so seven defects
        # could be fixed in a day and the runs from either side of the fix
        # ranked against each other without a word of warning. An arm whose
        # trials were produced by two different instruments is not one arm.
        harness = trial.labels.get("harness_digest")
        adapter = trial.labels.get("adapter")
        if harness or adapter:
            harnesses.setdefault(trial.arm_id, set()).add(
                f"{harness or 'unknown'}+{adapter or 'adapter:unrecorded'}"
            )

    split = sorted({axis for (_task, axis), values in per_task_axis.items() if len(values) > 1})
    return {
        "grader_spec_digests": {name: sorted(values) for name, values in axis_digests.items()},
        "grader_spec_digests_by_task": {
            f"{task}/{axis}": sorted(values) for (task, axis), values in per_task_axis.items()
        },
        "split_axes": split,
        "split_cells": sorted(
            f"{task}/{axis}" for (task, axis), values in per_task_axis.items() if len(values) > 1
        ),
        "harness_digests": {arm: sorted(values) for arm, values in harnesses.items()},
        "split_arms": sorted(arm for arm, values in harnesses.items() if len(values) > 1),
    }
