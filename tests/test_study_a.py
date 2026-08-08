"""M8: Study A's definition.

The study cannot be executed here (gate G3 is blocked — see docs/blockers.md),
so what is checkable is that it *is* the design the plan asks for and that its
instrument is intact: pinned graders that still hash to their pins, oracles that
satisfy their own graders, and twin arms that differ from their controls in
exactly one factor.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from duva_bench.arms.materialize import toolset_digests
from duva_bench.arms.twin import twin_toolset
from duva_bench.study.load import load_study
from duva_bench.study.models import Study

STUDY = Path(__file__).resolve().parents[1] / "studies" / "a-tool-familiarity"


@pytest.fixture(scope="module")
def study() -> Study:
    return load_study(STUDY / "study.yaml")


# --- the design the plan asks for --------------------------------------------


def test_the_factorial_is_the_size_the_plan_specifies(study: Study) -> None:
    """>= 2 models x >= 2 harnesses, >= 6 tasks, 5 repetitions."""
    models = {(arm.model.provider, arm.model.model) for arm in study.arms}
    harnesses = {(arm.harness.agent, arm.harness.version) for arm in study.arms}

    assert len(models) >= 2
    assert len(harnesses) >= 2
    assert len(study.tasks) >= 6
    assert study.repetitions == 5
    assert study.trial_count == 480


def test_the_four_familiarity_levels_are_all_present(study: Study) -> None:
    levels = {
        (arm.toolset.twin_of is not None, arm.toolset.docs_bundle.grade) for arm in study.arms
    }
    assert levels == {(False, "none"), (True, "none"), (True, "reference"), (True, "rich")}


def test_every_twin_arm_uses_one_seed(study: Study) -> None:
    """Two seeds would be two instruments, not one factor at four levels."""
    seeds = {arm.toolset.twin_seed for arm in study.arms if arm.toolset.twin_of is not None}
    assert len(seeds) == 1


def test_the_familiarity_arms_of_one_cell_differ_in_exactly_one_factor(study: Study) -> None:
    cell = [arm for arm in study.arms if arm.id.endswith("-sonnet-terminus")]
    assert len(cell) == 4
    assert len({arm.model.digest for arm in cell}) == 1
    assert len({arm.harness.digest for arm in cell}) == 1
    assert len({arm.digest for arm in cell}) == 4, "the four arms are not four arms"


def test_the_control_is_the_standard_toolset_with_no_documentation(study: Study) -> None:
    control = study.pre_registration.control_arm
    assert control is not None
    arm = study.arm(control)
    assert arm.toolset.twin_of is None
    assert arm.toolset.docs_bundle.grade == "none"


def test_the_primary_metric_is_the_hallucinated_call_rate(study: Study) -> None:
    """The plan's choice, and the reason process metrics are rankable axes."""
    from duva_bench.report.build import PROCESS_AXES

    assert study.pre_registration.primary_metric == "process:hallucinated_call_rate"
    assert "hallucinated_call_rate" in PROCESS_AXES


def test_metaprogramming_is_recorded_rather_than_forbidden(study: Study) -> None:
    """Forbidding it would measure compliance; recording it measures behaviour."""
    assert study.pre_registration.metaprogramming_allowed is True
    assert "process:metaprogramming_rate" in study.pre_registration.secondary_metrics


def test_the_pre_registration_is_unamended(study: Study) -> None:
    registration = study.pre_registration
    assert not registration.amended
    assert registration.original_digest == registration.pre_registration_digest


def test_the_exclusion_rules_say_what_removes_a_trial(study: Study) -> None:
    rules = " ".join(study.pre_registration.exclusion_rules).lower()
    assert "verify" in rules and "error" in rules
    assert "never scored zero" in rules
    assert "no trial is excluded for its result" in rules


# --- the instrument -----------------------------------------------------------


def test_every_grader_still_hashes_to_its_pin(study: Study) -> None:
    """A grader that drifted from its pin is a different instrument."""
    for task in study.tasks:
        grader = STUDY / task.grader_path
        assert grader.exists(), f"{task.grader_path} is missing"
        digest = hashlib.sha256(grader.read_bytes()).hexdigest()
        assert digest == task.grader_sha256, f"{task.grader_path} drifted from its pin"


def test_every_task_directory_is_a_harbor_task(study: Study) -> None:
    for task in study.tasks:
        assert task.path is not None
        directory = STUDY / task.path
        for required in ("instruction.md", "task.toml"):
            assert (directory / required).exists(), f"{task.id} has no {required}"
        assert (directory / "environment" / "Dockerfile").exists()
        assert (directory / "tests" / "test.sh").exists()
        assert (directory / "solution" / "solve.sh").exists()


def test_the_twin_arms_carry_the_twins_vocabulary(study: Study) -> None:
    """Analysis computes the hallucinated-call rate against exactly these names.

    Recomputed here from the toolset and the seed rather than compared against a
    stored copy: the study spec has to be reproducible from its inputs, and a
    stored copy could agree with a wrong spec.
    """
    definition = json.loads((STUDY / "toolset.json").read_text(encoding="utf-8"))
    twin = twin_toolset(definition, seed="study-a-2026")
    expected = toolset_digests(twin.definition)

    twinned = next(arm for arm in study.arms if arm.toolset.twin_of is not None)
    assert dict(twinned.toolset.tools) == expected
    assert set(twinned.toolset.tools) == set(twin.tool_names.values())

    standard = next(arm for arm in study.arms if arm.toolset.twin_of is None)
    assert set(standard.toolset.tools) == set(twin.tool_names)
    assert set(standard.toolset.tools) & set(twinned.toolset.tools) == set()


def test_the_rename_map_is_beside_the_study_and_not_inside_a_task() -> None:
    """An agent that could read the map would be handed the answer."""
    assert (STUDY / "twin-rename-map.json").exists()
    assert not list((STUDY / "tasks").rglob("*rename*"))
    assert not list((STUDY / "tasks").rglob("toolset*.json"))


@pytest.mark.parametrize(
    "task_id",
    ["config-merge", "semver-compare", "safe-path", "csv-dedupe", "rate-window", "log-summary"],
)
def test_each_grader_runs_and_scores_a_workdir(task_id: str, tmp_path: Path) -> None:
    """The grader answers about an empty workdir rather than crashing on it.

    A grader that crashes on "nothing was written" would turn every failed trial
    into an unscored one, which is the difference between "the arm did not solve
    it" and "we could not tell".
    """
    completed = subprocess.run(
        [sys.executable, str(STUDY / "graders" / f"{task_id}.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)

    assert payload["spec"]["grader"] == task_id
    assert set(payload["axes"]) == set(payload["spec"]["axes"])
    assert len(payload["axes"]) >= 2, "one axis is a pass/fail benchmark, not a study"
    for axis in payload["axes"].values():
        assert axis["score"] == 0.0
        assert axis["passed"] is False
        assert "never written" in axis["summary"]


@pytest.mark.parametrize(
    "task_id",
    ["config-merge", "semver-compare", "safe-path", "csv-dedupe", "rate-window", "log-summary"],
)
def test_each_task_oracle_satisfies_its_own_grader(task_id: str, tmp_path: Path) -> None:
    """The task and its instruments agree, so a failing arm is a failing arm.

    The oracle writes to `/app` because that is where the task runs inside its
    container; here it is redirected into a temporary directory, which is the
    only edit made to it.
    """
    solve = (STUDY / "tasks" / task_id / "solution" / "solve.sh").read_text(encoding="utf-8")
    workdir = tmp_path / "app"
    workdir.mkdir()
    script = tmp_path / "solve.sh"
    script.write_text(solve.replace("/app/", f"{workdir}/"), encoding="utf-8")

    subprocess.run(["bash", str(script)], check=True, capture_output=True, timeout=60)

    completed = subprocess.run(
        [sys.executable, str(STUDY / "graders" / f"{task_id}.py"), str(workdir)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    payload = json.loads(completed.stdout)
    for name, axis in payload["axes"].items():
        assert axis["score"] == 1.0, f"the oracle does not satisfy {task_id}/{name}: {axis}"
