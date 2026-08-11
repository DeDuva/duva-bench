"""Every task, executed by Harbor, graded by its own grader (G2 preflight).

`tests/test_study_a.py` already asserts that each task's oracle satisfies its
grader — but it does that by running `solve.sh` on the host with `/app/`
rewritten to a temporary directory. That proves the solution and the grader
agree about the *work*. It cannot prove any of the things that actually stopped
gate G1:

* that the task's image builds at all;
* that its verifier writes a reward file where Harbor reads one, rather than
  signalling pass/fail by exit status (no task in this repository did, and every
  trial died in the verifier);
* that the work product reaches `/logs/artifacts`, survives the container, and
  lands where the grader is pointed (it did not, so graders scored 0 "never
  written" on tasks their own verifier passed).

Those three were fixed across all eight tasks while closing G1, and only the two
smoke tasks were ever run. Six tasks carried the fix and none of the evidence,
which is precisely the state this file exists to end: Study A is 480 trials, and
discovering there that a task cannot execute is discovering it at the worst
possible price.

**The oracle agent is what makes this affordable.** It runs the task's own
`solve.sh` instead of a model, so the whole path — build, agent phase, verifier,
artifact collection, grading — is exercised for the cost of the containers and
nothing else. A task that fails here is broken for every arm; a task that passes
here can still be failed by a real agent, which is the point of the study.

Marked `harbor`: needs a container runtime and the `[harbor]` extra. Excluded
from `make test`; run with `pytest -m harbor`. Expect a few minutes on a cold
image cache.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from duva_bench.exec.harbor import HarborExecutor, find_trial_dir, load_trial

pytestmark = pytest.mark.harbor

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "examples" / "smoke"
STUDY_A = ROOT / "studies" / "a-tool-familiarity"

# (task directory, grader) for every task this repository ships.
TASKS: list[tuple[Path, Path]] = [
    (SMOKE / "tasks" / "json-normalizer", SMOKE / "graders" / "json-normalizer.py"),
    (SMOKE / "tasks" / "retry-backoff", SMOKE / "graders" / "retry-backoff.py"),
    *[
        (STUDY_A / "tasks" / name, STUDY_A / "graders" / f"{name}.py")
        for name in (
            "config-merge",
            "csv-dedupe",
            "log-summary",
            "rate-window",
            "safe-path",
            "semver-compare",
        )
    ],
]


@pytest.mark.parametrize("task_dir,grader", TASKS, ids=[t.name for t, _ in TASKS])
def test_the_oracle_runs_through_harbor_and_satisfies_the_grader(
    task_dir: Path, grader: Path, tmp_path: Path
) -> None:
    """Build, run, verify, collect, grade — the whole path, without a model."""
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    label = f"oracle-{task_dir.name}"

    completed = subprocess.run(
        [
            HarborExecutor().resolve(),
            "run",
            "--path",
            str(task_dir),
            "--agent",
            "oracle",
            "--jobs-dir",
            str(jobs),
            "--job-name",
            label,
            "--n-attempts",
            "1",
            "--n-concurrent",
            "1",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert completed.returncode == 0, f"harbor exited {completed.returncode}\n{completed.stderr}"

    trial_dir = find_trial_dir(jobs / label)
    assert trial_dir is not None, (
        f"{task_dir.name}: harbor wrote no trial result under {jobs / label}"
    )
    trial = load_trial(trial_dir)

    # 1. The verifier ran and wrote a reward Harbor could read. `None` here means
    #    "did not run", which is the failure the missing reward file produced.
    assert trial.verifier_passed is True, (
        f"{task_dir.name}: verifier_passed is {trial.verifier_passed!r} for the task's own "
        "oracle. None means Harbor found no reward file at /logs/verifier/reward.txt."
    )

    # 2. The work product survived the container and is where the grader looks.
    graded = trial.graded_dir
    assert graded.is_dir(), f"{task_dir.name}: nothing was collected to grade"

    # 3. The grader agrees, on every axis. Anything less means a real arm's
    #    failure could not be told from a broken instrument.
    scored = subprocess.run(
        [sys.executable, str(grader), str(graded)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=tmp_path,
    )
    assert scored.returncode == 0, f"{task_dir.name}: grader failed\n{scored.stderr}"

    report = json.loads(scored.stdout)
    axes = report["axes"]
    assert axes, f"{task_dir.name}: grader scored no axes"
    failed = {name: axis for name, axis in axes.items() if not axis.get("passed")}
    assert not failed, (
        f"{task_dir.name}: the task's own oracle did not satisfy its grader on "
        f"{sorted(failed)} — {json.dumps(failed, sort_keys=True)}. A failing arm and a "
        "broken task would be indistinguishable in the study."
    )


# --- Study B: one problem, three toolchains ----------------------------------

STUDY_B = ROOT / "studies" / "b-toolchain-distribution" / "tasks"
STUDY_B_VARIANTS = ["add-median-oss", "add-median-twin", "add-median-proprietary"]


@pytest.mark.parametrize("variant", STUDY_B_VARIANTS)
def test_every_toolchain_variant_is_solvable_by_its_own_oracle(
    variant: str, tmp_path: Path
) -> None:
    """The admission criterion for Study B, and the reason it is strict.

    The three variants pose one problem in three toolchains. If one of them is
    unsolvable — an image that will not build, a driver that cannot run its own
    tests, a verifier that rejects a correct change — then that arm's failures
    are the instrument's and the study would report them as the agent's.

    Run with the oracle, so admitting a task costs container time and no model
    spend at all.
    """
    task_dir = STUDY_B / variant
    jobs = tmp_path / "jobs"
    jobs.mkdir()

    completed = subprocess.run(
        [
            HarborExecutor().resolve(),
            "run",
            "--path",
            str(task_dir),
            "--agent",
            "oracle",
            "--jobs-dir",
            str(jobs),
            "--job-name",
            f"oracle-{variant}",
            "--n-attempts",
            "1",
            "--n-concurrent",
            "1",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert completed.returncode == 0, f"harbor exited {completed.returncode}\n{completed.stderr}"

    trial_dir = find_trial_dir(jobs / f"oracle-{variant}")
    assert trial_dir is not None, f"{variant}: harbor wrote no trial result"
    trial = load_trial(trial_dir)
    assert trial.verifier_passed is True, (
        f"{variant}: the variant's own oracle did not satisfy its verifier "
        f"(verifier_passed={trial.verifier_passed!r})"
    )
