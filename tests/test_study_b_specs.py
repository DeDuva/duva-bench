"""Study B's specifications, audited without spending anything.

Every point of measured "difficulty" in Study B's first three hard tasks turned
out to be an authoring defect: an import convention the layout never explained,
and an acceptance check that demanded a wrong answer and scored a correct one as
a failure. Each cost a calibration round — roughly three dollars and forty
minutes — to discover.

None of them needed a model to find. This file is the cheap loop that should run
first:

* **the oracle satisfies the acceptance check** — the admission rule, but on the
  host, in milliseconds, instead of in a container;
* **a plausible *alternative* correct implementation also satisfies it** — the
  question that would have caught the cycle-members defect on the day it was
  written. "Would a competent engineer answer differently, and be right?" is the
  whole audit, and an acceptance check that says no to a right answer is worse
  than a weak one: a weak check inflates a score, a wrong check invents an
  effect.

Runs in the ordinary suite. No Harbor, no ADP, no model.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

STUDY = Path(__file__).resolve().parents[1] / "studies" / "b-toolchain-distribution"
sys.path.insert(0, str(STUDY))

from hard_tasks import HARD_TASKS  # noqa: E402
from tasks import Task  # noqa: E402


def run_acceptance(task: Task, files: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run a task's acceptance check against a candidate solution.

    The task's own starting tree is laid down first and the candidate overlaid
    on it, because that is what a trial is: an agent edits some files and leaves
    the rest alone. Writing only the candidate's files made `window-stats` fail
    for want of the `stats` package it never touches.
    """
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        starting = {
            f"{package.name}/{module}": body
            for package in task.packages
            for module, body in package.modules.items()
        }
        for key, body in {**starting, **files}.items():
            package, _, module = key.partition("/")
            target = root / package / ("__init__.py" if module == f"{package}.py" else module)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        entry = root / task.entry / "__init__.py"
        tests = root / "tests"
        tests.mkdir(exist_ok=True)
        test_file = tests / next(iter(task.tests))
        test_file.write_text(next(iter(task.tests.values())), encoding="utf-8")
        script = (
            task.acceptance.replace("SOURCE_ROOTS", repr([str(root)]))
            .replace("ENTRY_SOURCE", repr(str(entry)))
            .replace("TEST_SOURCE", repr(str(test_file)))
        )
        return subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
        )


@pytest.mark.parametrize("task", HARD_TASKS, ids=[t.slug for t in HARD_TASKS])
def test_the_oracle_satisfies_its_own_acceptance_check(task: Task) -> None:
    """The admission rule, run on the host for nothing.

    `tests/test_tasks_through_harbor.py` proves this through a container, which
    is the real check and takes minutes. This is the same claim in milliseconds,
    so a broken spec is caught while it is being written rather than during a
    calibration run.
    """
    files = {key: body for key, body in task.oracle_files.items() if not key.startswith("tests/")}
    completed = run_acceptance(task, files)
    assert completed.returncode == 0, (
        f"{task.slug}: the reference solution fails its own acceptance check\n"
        f"{completed.stdout}{completed.stderr}"
    )


# A second implementation of each task, written differently on purpose. Where a
# rule leaves room, these take the *other* reasonable reading — which is exactly
# what an agent will do, and exactly what an over-constrained check punishes.
ALTERNATIVES: dict[str, dict[str, str]] = {
    "topo-order": {
        "graph/graph.py": '''"""Dependency resolution."""


class Cycle(Exception):
    def __init__(self, members):
        members = sorted(members)
        super().__init__(f"cycle among {members}")
        self.members = members


def _on_a_cycle(name, edges):
    """Depth-first, rather than the reference's repeated-sweep approach."""
    stack = [(name, set())]
    while stack:
        current, seen = stack.pop()
        for nxt in edges.get(current, ()):
            if nxt == name:
                return True
            if nxt not in seen:
                stack.append((nxt, seen | {current}))
    return False


def resolve(graph):
    names = set(graph)
    for needs in graph.values():
        names.update(needs)
    edges = {name: set(graph.get(name, ())) for name in names}

    if any(_on_a_cycle(name, edges) for name in edges):
        raise Cycle([name for name in edges if _on_a_cycle(name, edges)])

    ordered = []
    while edges:
        # One name at a time, smallest first — a different traversal from the
        # reference's batch sweep, and the same answer.
        nxt = min(name for name, needs in edges.items() if not needs)
        ordered.append(nxt)
        del edges[nxt]
        for needs in edges.values():
            needs.discard(nxt)
    return ordered
''',
        "report/report.py": '''"""Build planning."""

import graph


def plan_build(g):
    return graph.resolve(g)
''',
    },
    "merge-config": {
        "config/config.py": '''"""Layered configuration."""

from copy import deepcopy


def merge(base, override):
    """Built by copying the base outright, rather than key by key."""
    result = deepcopy(dict(base))
    for key in list(override):
        value = override[key]
        if value is None:
            result.pop(key, None)
            continue
        both_mappings = isinstance(value, dict) and isinstance(result.get(key), dict)
        result[key] = merge(result[key], value) if both_mappings else deepcopy(value)
    return result
''',
        "report/report.py": '''"""Effective configuration."""

import functools

import config


def effective(layers):
    return functools.reduce(config.merge, layers, {})
''',
    },
    "window-stats": {
        "stats/stats.py": '''"""Statistics helpers."""


def mean(values):
    if not values:
        raise ValueError("mean of no values")
    return sum(values) / len(values)
''',
        "window/window.py": '''"""Sliding windows over a series."""


def windows(values, size, step):
    """Built by walking an index, rather than by comprehension."""
    if not isinstance(size, int) or not isinstance(step, int):
        raise ValueError("size and step must be whole numbers")
    if size < 1 or step < 1:
        raise ValueError("size and step must both be at least 1")
    values = list(values)
    out = []
    start = 0
    while start + size <= len(values):
        chunk = values[start : start + size]
        if all(item is not None for item in chunk):
            out.append(chunk)
        start += step
    return out
''',
        "report/report.py": '''"""Rolling summaries."""

import stats
import window


def rolling_mean(values, size, step):
    return [stats.mean(chunk) for chunk in window.windows(values, size, step)]
''',
    },
}


@pytest.mark.parametrize("task", HARD_TASKS, ids=[t.slug for t in HARD_TASKS])
def test_a_different_but_correct_solution_also_passes(task: Task) -> None:
    """The audit that would have caught the cycle-members defect for nothing.

    `topo-order` once demanded that a cycle's `members` include a name that
    merely *depended* on the cycle. An agent answered without it, was right, and
    was marked wrong — the failure this project's own design cites SWE-bench for,
    reproduced in its own instrument. A second implementation, written to take
    the other reasonable reading wherever a rule leaves room, is what catches
    that class of defect before a single trial is paid for.
    """
    alternative = ALTERNATIVES.get(task.slug)
    assert alternative is not None, (
        f"{task.slug} has no alternative implementation to audit against"
    )

    completed = run_acceptance(task, alternative)
    assert completed.returncode == 0, (
        f"{task.slug}: a plausible alternative correct solution fails the acceptance check, "
        "so the check is over-constrained — it is testing one implementation rather than the "
        f"behaviour the task states.\n{completed.stdout}{completed.stderr}"
    )


# --- the grader, against the layout a trial actually leaves behind ------------


def _collected_workspace(root: Path, source_dir: str, task: Task) -> Path:
    """What Harbor leaves for the grader: `<collected>/workspace/<source>/...`.

    Built rather than mocked, because the two defects this catches were both
    about the *shape* of that tree — where packages sit, and what is importable
    from where.
    """
    workspace = root / "workspace"
    for package in task.packages:
        target = workspace / source_dir / package.name / "__init__.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        body = next(iter(package.modules.values()))
        target.write_text(body, encoding="utf-8")
    for key, content in task.oracle_files.items():
        package = key.partition("/")[0]
        if package == "tests":
            continue
        target = workspace / source_dir / package / "__init__.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


@pytest.mark.parametrize("source_dir", ["src", "kelvra", "depot"])
def test_a_grader_scores_a_solved_trial_in_every_layout(source_dir: str, tmp_path: Path) -> None:
    """The check whose absence let a 60-trial pilot come back entirely unscored.

    `tests/test_study_b_specs.py` proved the acceptance *script* was right and
    `tests/test_tasks_through_harbor.py` proved the *task* ran — and nothing
    exercised the grader against the tree a finished trial leaves. So when
    packages became packages, the grader kept looking for `report.py`, found
    nothing, and reported every axis of every trial as unscored while every
    trial had in fact been solved. Sixty trials, and not one number.

    The second defect was subtler and the same shape: a package is reached
    through its parent, and inside the container the agent's cwd is on the path
    as well — so a grader with only the package directories marks solved work
    unsolved. Both are shape, and shape is what this builds.
    """
    from hard_tasks import MERGE_CONFIG

    task = MERGE_CONFIG
    collected = _collected_workspace(tmp_path, source_dir, task)
    grader = STUDY / "graders" / f"{task.slug}.py"
    assert grader.is_file(), f"{grader} does not exist; run generate.py"

    completed = subprocess.run(
        [sys.executable, str(grader), str(collected)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    axes = json.loads(completed.stdout)["axes"]

    assert axes["acceptance"]["score"] == 1.0, (
        f"the grader scored a solved trial {axes['acceptance']['score']!r} in a {source_dir} "
        f"layout: {axes['acceptance'].get('summary')}"
    )
    assert axes["acceptance"]["passed"] is True


# --- the pre-registration, amended ------------------------------------------

# The digest pilot 2 actually ran under, taken from its own report artifact
# (`report/report.json`, `pre_registration.original_digest`). It is here so the
# amendment is checkable against the run it amends rather than against itself.
PILOT_2_PRE_REGISTRATION = "sha256:4215f18fae9008d5acb21724af9c5632933f9ae037e11ec467e660d887228c6a"


def test_the_amendment_keeps_the_pre_amendment_reading_computable() -> None:
    """§8's rule, and the only thing that separates an amendment from no pre-registration.

    Amendment 1 (design doc §7.1) moves the primary measure to `escaped`. The
    reading a reader would have computed before it must survive unchanged — and
    "unchanged" is checkable here, because pilot 2 recorded its own
    pre-registration digest and this is that digest.
    """
    from duva_bench.study.load import load_study

    registration = load_study(STUDY / "study.yaml").pre_registration
    original = registration.original()

    assert registration.amended
    assert registration.primary_metric == "process:escaped"
    assert original.primary_metric == "acceptance"
    assert registration.original_digest == PILOT_2_PRE_REGISTRATION
    assert registration.digest != registration.original_digest


def _runners() -> dict[str, str]:
    """Each substrate's own test runner, read from what the generator produced.

    Not written down here: the twin vocabularies come from a seed, so a literal
    would be a copy that can go stale against the tasks the study actually runs.
    """
    manifest = json.loads((STUDY / "manifest.json").read_text(encoding="utf-8"))
    runners = {"oss": "make", "proprietary": "dbuild"}
    for twin, words in manifest["twin_words"].items():
        runners[twin] = words["runner"]
    return runners


def test_every_arm_declares_the_toolchains_it_was_not_given() -> None:
    """The escape metric's vocabulary, pinned in the spec rather than in an analysis script.

    An arm's own runner must not be in its own foreign list — that would score
    every ordinary trial as an escape — and every other toolchain's runner must
    be, or an arm reaching for it would go unmeasured. `pytest` is foreign to
    all of them: no toolchain here names it as its runner, and it is what the
    2026-08-11 pilot actually saw the twin arm reach for.
    """
    from duva_bench.study.load import load_study

    runners = _runners()
    arms = {arm.id: set(arm.foreign_commands) for arm in load_study(STUDY / "study.yaml").arms}

    assert set(arms) == set(runners)
    for arm, own in runners.items():
        assert own not in arms[arm], f"{arm} declares its own runner foreign"
        assert arms[arm] == (set(runners.values()) - {own}) | {"pytest"}


def test_the_two_twins_are_symmetric_in_everything_but_their_names() -> None:
    """The noise floor is only a floor if the twins differ in nothing else.

    Same substrate treatment, same model, same harness, same toolset, same
    environment, and foreign vocabularies of the same shape — each naming the
    other's runner, `make`, `dbuild` and `pytest`. A twin that also differed in,
    say, its docs grade would put a real effect in the floor and hide everything
    smaller than it.
    """
    from duva_bench.study.load import load_study

    study = load_study(STUDY / "study.yaml")
    first, second = (study.arm(name) for name in study.pre_registration.instrument_arms or ())

    assert first.model == second.model
    assert first.harness == second.harness
    assert first.toolset == second.toolset
    assert first.env == second.env
    assert len(first.foreign_commands) == len(second.foreign_commands)

    runners = _runners()
    assert set(first.foreign_commands) - {runners[second.id]} == set(second.foreign_commands) - {
        runners[first.id]
    }


def test_the_twin_vocabularies_are_recomputable_from_their_seeds() -> None:
    """A recorded output nobody can re-derive is what this study keeps being bitten by.

    The words in `manifest.json` are what the tasks were built with; the seeds
    beside them are what a reader has to be able to turn back into those words.
    Until 2026-08-11 the first twin's vocabulary was hand-written while §9 of the
    design document described it as mechanical — two twins produced by two
    different processes would not have been a noise floor.
    """
    from duva_bench.arms.twin import syllabic_name

    manifest = json.loads((STUDY / "manifest.json").read_text(encoding="utf-8"))
    sources = {"src": "src", "tests": "tests", "runner": "make", "verb": "test"}

    for twin, seed in manifest["twin_seeds"].items():
        taken: set[str] = set()
        for role, source in sources.items():
            name = syllabic_name(source, seed, length=len(source), taken=taken)
            taken.add(name)
            assert manifest["twin_words"][twin][role] == name, f"{twin}/{role}"


def test_no_twin_name_is_an_english_word() -> None:
    """A twin renames things the model knows; a rename onto another word it knows is not that.

    Checked across both twins because the asymmetry is what matters: the second
    twin drew `jibe` and `tape` on its first attempt while the first drew
    neither, which would have put a real difference into the one contrast that
    is supposed to contain none.
    """
    from duva_bench.arms.twin import DICTIONARY

    manifest = json.loads((STUDY / "manifest.json").read_text(encoding="utf-8"))
    for twin, words in manifest["twin_words"].items():
        for role, name in words.items():
            assert name not in DICTIONARY, f"{twin}/{role} is {name!r}"
