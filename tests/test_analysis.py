"""M6: the statistics, on their own.

Everything here is checked against a value computed by hand or by an argument
written out in the test, rather than against whatever the implementation
happened to return the first time it ran. A statistics module regression-tested
against its own output is a module that can only ever stay wrong.
"""

from __future__ import annotations

from math import isclose, sqrt
from typing import Any

import pytest

from duva_bench.analysis.process import ProcessMetrics, compute
from duva_bench.analysis.stats import (
    bootstrap_ci_over_tasks,
    discordance,
    holm,
    icc,
    mcnemar_exact,
    paired_difference_ci,
    pooled_within_cell_sd,
)


def _event(name: str, *, status: str = "success", arguments: dict[str, object] | None = None):
    from duva_bench.adp.models import TrajectoryEvent

    return TrajectoryEvent.model_validate(
        {
            "kind": "tool_call",
            "type": name,
            "status": status,
            "payload": {"arguments": arguments or {}},
        }
    )


# --- McNemar ----------------------------------------------------------------


def test_only_discordant_pairs_carry_information() -> None:
    """Tasks both arms solved, or neither did, say nothing about which is better."""
    assert mcnemar_exact(10, 3, 1, 10) == mcnemar_exact(0, 3, 1, 0)


def test_no_discordant_pairs_is_no_evidence_rather_than_an_error() -> None:
    assert mcnemar_exact(5, 0, 0, 5) == 1.0


def test_the_p_value_is_the_exact_binomial_one() -> None:
    """4 discordant pairs, all one way: 2 * (1/2)^4 = 0.125."""
    assert isclose(mcnemar_exact(0, 4, 0, 0), 0.125)
    # 5 one way, 1 the other: 2 * (C(6,0) + C(6,1)) / 2^6 = 14/64.
    assert isclose(mcnemar_exact(0, 5, 1, 0), 14 / 64)


def test_the_test_is_symmetric_in_the_two_arms() -> None:
    assert mcnemar_exact(2, 5, 1, 3) == mcnemar_exact(2, 1, 5, 3)


def test_a_negative_count_is_refused() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        mcnemar_exact(1, -1, 0, 0)


def test_discordance_reads_the_paired_table() -> None:
    control = [True, True, False, False]
    treatment = [True, False, True, False]
    assert discordance(control, treatment) == (1, 1, 1, 1)


# --- Holm --------------------------------------------------------------------


def test_holm_multiplies_by_the_remaining_comparisons_not_by_all_of_them() -> None:
    """That is the whole difference from Bonferroni, and where the power is."""
    adjusted = holm({"a": 0.01, "b": 0.02, "c": 0.03})
    assert isclose(adjusted["a"], 0.03)  # 3 * 0.01
    assert isclose(adjusted["b"], 0.04)  # 2 * 0.02
    assert isclose(adjusted["c"], 0.04)  # made monotone; 1 * 0.03 would be 0.03


def test_holm_is_monotone_so_a_later_test_never_beats_an_earlier_one() -> None:
    adjusted = holm({"a": 0.04, "b": 0.041, "c": 0.9})
    ordered = [adjusted["a"], adjusted["b"], adjusted["c"]]
    assert ordered == sorted(ordered)


def test_holm_never_exceeds_one() -> None:
    assert holm({"a": 0.5, "b": 0.6})["a"] == 1.0


def test_holm_of_one_comparison_changes_nothing() -> None:
    assert holm({"a": 0.02}) == {"a": 0.02}


def test_holm_of_nothing_is_nothing() -> None:
    assert holm({}) == {}


# --- intervals ---------------------------------------------------------------


def test_a_bootstrap_interval_is_reproducible_from_its_seed() -> None:
    """An interval nobody can recompute is not evidence."""
    tasks = [[1.0, 0.0], [1.0, 1.0], [0.0, 0.0], [1.0, 0.0]]
    assert bootstrap_ci_over_tasks(tasks, seed=7) == bootstrap_ci_over_tasks(tasks, seed=7)

    low, high = bootstrap_ci_over_tasks(tasks, seed=7)
    point = sum(sum(values) / len(values) for values in tasks) / len(tasks)
    assert low <= point <= high


def test_a_task_with_more_repetitions_does_not_outvote_one_with_fewer() -> None:
    """The statistic is the mean over tasks of each task's own mean."""
    lopsided = [[1.0] * 30, [0.0]]
    low, high = bootstrap_ci_over_tasks(lopsided, resamples=2000, seed=1)
    assert low <= 0.5 <= high


def test_an_interval_over_identical_tasks_is_a_point() -> None:
    low, high = bootstrap_ci_over_tasks([[1.0], [1.0], [1.0]], resamples=500, seed=1)
    assert (low, high) == (1.0, 1.0)


def test_an_interval_needs_at_least_one_task() -> None:
    with pytest.raises(ValueError, match="at least one task"):
        bootstrap_ci_over_tasks([])


def test_a_paired_interval_keeps_the_arms_together() -> None:
    """Every task improves by exactly 0.5, so the interval must be a point.

    Resampled independently the two arms would drift apart and the interval
    would open up — which is the bug this test exists to catch.
    """
    control = [[0.0], [0.5], [0.25], [0.5]]
    treatment = [[0.5], [1.0], [0.75], [1.0]]
    low, high = paired_difference_ci(control, treatment, resamples=500, seed=3)
    assert isclose(low, 0.5) and isclose(high, 0.5)


def test_a_paired_interval_needs_the_same_tasks_in_both_arms() -> None:
    with pytest.raises(ValueError, match="same tasks"):
        paired_difference_ci([[1.0]], [[1.0], [0.0]])


# --- the noise floor ---------------------------------------------------------


def test_the_noise_floor_is_the_pooled_within_cell_sd() -> None:
    """Two cells of [0,2] and [1,3]: each has variance 2, pooled sd is sqrt(2)."""
    floor = pooled_within_cell_sd([[0.0, 2.0], [1.0, 3.0]])
    assert floor.sd is not None and isclose(floor.sd, sqrt(2))
    assert floor.cells == 2
    assert floor.degrees_of_freedom == 2


def test_cells_that_ran_once_contribute_nothing_to_the_floor() -> None:
    floor = pooled_within_cell_sd([[0.0, 2.0], [1.0]])
    assert floor.cells == 1
    assert floor.degrees_of_freedom == 1


def test_a_study_with_one_repetition_per_cell_has_no_noise_floor() -> None:
    """Reported as unavailable with a reason, never as zero."""
    floor = pooled_within_cell_sd([[1.0], [0.0], [1.0]])
    assert floor.sd is None
    assert "no cell has two or more repetitions" in floor.as_dict()["unavailable"]


def test_a_contrast_is_expressed_in_noise_floors() -> None:
    floor = pooled_within_cell_sd([[0.0, 2.0], [1.0, 3.0]])
    assert isclose(floor.in_sd_units(sqrt(2)), 1.0)  # type: ignore[arg-type]


def test_a_contrast_in_sd_units_is_unavailable_when_nothing_varied() -> None:
    floor = pooled_within_cell_sd([[1.0, 1.0], [1.0, 1.0]])
    assert floor.sd == 0.0
    assert "unavailable" in floor.in_sd_units(0.3)  # type: ignore[operator]


# --- ICC ---------------------------------------------------------------------


def test_icc_is_one_when_repetitions_agree_and_tasks_differ() -> None:
    result = icc([[1.0, 1.0], [0.0, 0.0]])
    assert result["icc"] == 1.0


def test_icc_is_zero_when_the_outcome_is_all_noise() -> None:
    result = icc([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0], [0.0, 1.0]])
    assert result["icc"] == 0.0


def test_icc_says_why_it_is_unavailable_rather_than_raising() -> None:
    assert "unavailable" in icc([[1.0, 0.0]])
    assert "unavailable" in icc([[1.0], [0.0], [1.0]])


# --- process metrics ---------------------------------------------------------


def test_the_tool_error_rate_counts_failed_statuses() -> None:
    metrics = compute(
        [
            _event("read_file"),
            _event("run_command", status="failure"),
            _event("run_command", status="error"),
            _event("write_file", status="rejected"),
        ]
    )
    assert metrics.tool_calls == 4
    assert metrics.tool_failures == 3
    assert metrics.tool_error_rate == 0.75


def test_a_trial_with_no_tool_calls_has_no_rates_rather_than_zeros() -> None:
    """'Did not use tools' and 'used tools perfectly' are different columns."""
    metrics = compute([])
    assert metrics.tool_error_rate is None
    assert metrics.hallucinated_call_rate is None
    assert metrics.retry_rate is None


def test_a_repeat_of_the_same_call_with_the_same_arguments_is_a_retry() -> None:
    metrics = compute(
        [
            _event("run_command", arguments={"command": "pytest"}),
            _event("run_command", arguments={"command": "pytest"}),
            _event("run_command", arguments={"command": "pytest -x"}),
        ]
    )
    assert metrics.retries == 1


def test_a_call_to_a_name_the_arm_does_not_have_is_hallucinated() -> None:
    """The primary metric of Study A, and the reason the rename map is kept."""
    metrics = compute(
        [_event("veshanu"), _event("read_file"), _event("read_file")],
        toolset=frozenset({"veshanu", "bodaki"}),
    )
    assert metrics.hallucinated_calls == 2
    assert metrics.hallucinated_call_rate == pytest.approx(2 / 3)
    assert metrics.unknown_names == ("read_file",)


def test_the_hallucination_rate_is_not_computed_without_a_vocabulary() -> None:
    """Computing it against an assumption would report every call as a hit."""
    metrics = compute([_event("read_file")], toolset=None)
    assert metrics.hallucinated_calls == 0
    assert metrics.hallucinated_call_rate == 0.0
    assert metrics.unknown_names == ()


@pytest.mark.parametrize(
    ("command", "escaped"),
    [
        ("python3 -c 'print(1)'", True),
        ("python solve.py", True),
        ("bash fix.sh", True),
        ("node build.js", True),
        ("chmod +x run.sh", True),
        ("ls -la /app", False),
        ("cat /app/normalize.py", False),
        ("grep -r python /app", False),
    ],
)
def test_metaprogramming_is_writing_and_running_code_not_using_a_terminal(
    command: str, escaped: bool
) -> None:
    metrics = compute([_event("run_command", arguments={"command": command})])
    assert (metrics.metaprogramming_calls == 1) is escaped


def test_process_metrics_serialize_their_nones() -> None:
    payload = ProcessMetrics().as_dict()
    assert payload["tool_error_rate"] is None
    assert payload["tool_calls"] == 0


def _outcomes_with_labels(labels: list[dict[str, str]]) -> Any:
    """Trials of one arm, differing only in the labels under test."""
    from duva_bench.analysis.extract import StudyOutcomes, TrialOutcome

    return StudyOutcomes(
        trials=[
            TrialOutcome(
                run_id=f"run-{i}",
                external_ref=f"ref-{i}",
                task_id="json-normalizer",
                arm_id="standard",
                repetition=i + 1,
                labels=dict(label),
                verdict="VERIFIED",
                failures=(),
                axes=(),
                tokens_in=0,
                tokens_out=0,
                cost_micro_usd=0,
                duration_ms=0,
                tool_calls=0,
                tool_failures=0,
            )
            for i, label in enumerate(labels)
        ]
    )


def test_one_arm_run_by_two_adapter_versions_is_banded() -> None:
    """The harness is Harbor's agent *and* the thing driving it.

    Closing gate G1 fixed seven defects in the adapter and the bridge in a
    single day — including one that recorded every tool call as a failure. Runs
    from before and after were indistinguishable in ADP, because the only
    harness identity on a run was Harbor's own agent and version. An arm whose
    trials came from two versions of this project is not one arm, and ranking
    across them is the comparison §0.6 says to refuse.
    """
    from duva_bench.analysis.extract import digest_bands

    outcomes = _outcomes_with_labels(
        [
            {"harness_digest": "sha256:same", "adapter": "duva-bench/1"},
            {"harness_digest": "sha256:same", "adapter": "duva-bench/2"},
        ]
    )

    bands = digest_bands(outcomes)

    assert "standard" in bands["split_arms"], (
        "an arm whose trials were produced by two adapter versions was not banded"
    )
    assert len(bands["harness_digests"]["standard"]) == 2


def test_one_adapter_version_and_one_harness_is_not_banded() -> None:
    """The band has to stay quiet in the normal case, or it says nothing."""
    from duva_bench.analysis.extract import digest_bands

    outcomes = _outcomes_with_labels(
        [
            {"harness_digest": "sha256:same", "adapter": "duva-bench/2"},
            {"harness_digest": "sha256:same", "adapter": "duva-bench/2"},
        ]
    )

    assert digest_bands(outcomes)["split_arms"] == []
