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
