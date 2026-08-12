"""`make preserve` — the step that makes a run's evidence outlive its ADP.

A study's ADP record dies with `make down` and its local state is gitignored, so
every number a run produces is unverifiable the moment the session ends unless
something copies the evidence into the tree. Pilot 2's survived by accident: its
state happened to still exist in a git worktree on an already-merged branch, and
for a day this repository recorded it as destroyed.

So this is tested like a thing results depend on, because it is one.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from duva_bench.state import StateDir
from duva_bench.study.load import load_study

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "smoke" / "study.yaml"


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location(
        "preserve_run", ROOT / "tools" / "preserve-run.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state_with(tmp_path: Path, cells: list[tuple[str, str, int]], *, drop: set[str]) -> Path:
    """A state directory shaped like one a real run leaves behind."""
    study = load_study(EXAMPLE)
    state = StateDir(tmp_path).for_study(study, tmp_path)
    root = Path(state.root)
    (root / "trials").mkdir(parents=True, exist_ok=True)

    for arm, task, rep in cells:
        cell = f"{arm}__{task}__r{rep}"
        (root / "trials" / f"{cell}.json").write_text(
            json.dumps({"arm_id": arm, "task_id": task, "repetition": rep}), encoding="utf-8"
        )
        trial_dir = root / "work" / f"{root.name}__{cell}" / "jobs" / "job" / f"{task}__abc"
        (trial_dir / "agent").mkdir(parents=True, exist_ok=True)
        # `trial_name` is what marks this as the *trial* result rather than the
        # job summary Harbor writes under the same filename.
        (trial_dir / "result.json").write_text(
            json.dumps({"trial_name": cell, "task_name": task}), encoding="utf-8"
        )
        if cell not in drop:
            (trial_dir / "agent" / "trajectory.json").write_text(
                json.dumps({"steps": [], "agent": {"model_name": "m"}}), encoding="utf-8"
            )
    return tmp_path


def test_a_runs_trajectories_and_trial_records_are_copied_into_the_tree(tmp_path: Path) -> None:
    cells = [("oss", "json-normalizer", 1), ("twin", "json-normalizer", 1)]
    state = _state_with(tmp_path / "state", cells, drop=set())
    into = tmp_path / "preserved"

    manifest = _tool().preserve(EXAMPLE, into, state_dir=state)

    assert manifest["trial_records"] == 2
    assert manifest["trajectories"] == 2
    assert manifest["trajectories_missing"] == []
    assert (into / "trajectories" / "oss__json-normalizer__r1.json").is_file()
    assert (into / "trials" / "twin__json-normalizer__r1.json").is_file()
    # The digest travels with the copy, or a reader cannot tell which study it is.
    assert json.loads((into / "MANIFEST.json").read_text())["study_digest"].startswith("sha256:")


def test_a_trajectory_that_did_not_survive_is_named_rather_than_counted(tmp_path: Path) -> None:
    """A hole in the evidence must not read as a rounding error.

    The process metrics — `escaped` among them — are computed from trajectories
    and from nothing else, so a missing one is a trial that can never be
    recomputed. Reporting "59 of 60" invites a shrug; naming the cell does not.
    """
    cells = [("oss", "json-normalizer", 1), ("twin", "json-normalizer", 1)]
    state = _state_with(tmp_path / "state", cells, drop={"twin__json-normalizer__r1"})

    manifest = _tool().preserve(EXAMPLE, tmp_path / "preserved", state_dir=state)

    assert manifest["trajectories"] == 1
    assert manifest["trajectories_missing"] == ["twin__json-normalizer__r1"]
    # And the trial record is still copied: knowing the trial ran and its
    # trajectory did not survive is better than dropping both.
    assert (tmp_path / "preserved" / "trials" / "twin__json-normalizer__r1.json").is_file()


def test_preserving_a_study_that_never_ran_is_an_error_not_an_empty_directory(
    tmp_path: Path,
) -> None:
    """An empty `preserved/` would be indistinguishable from a preserved run of nothing."""
    state = _state_with(tmp_path / "state", [], drop=set())
    with pytest.raises(SystemExit, match="has this study run"):
        _tool().preserve(EXAMPLE, tmp_path / "preserved", state_dir=state)


def test_the_tool_exits_nonzero_when_evidence_is_incomplete(tmp_path: Path) -> None:
    """`make preserve` has to fail loudly, or a partial copy passes for a whole one."""
    state = _state_with(
        tmp_path / "state",
        [("oss", "json-normalizer", 1)],
        drop={"oss__json-normalizer__r1"},
    )
    code = _tool().main([str(EXAMPLE), "--into", str(tmp_path / "out"), "--state-dir", str(state)])
    assert code == 1
