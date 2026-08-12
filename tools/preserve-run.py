#!/usr/bin/env python3
"""Copy a run's irreplaceable evidence out of local state and into the tree.

    make preserve STUDY=studies/b-toolchain-distribution/study.yaml INTO=.../pilot-3

Local state holds Harbor's job directories under `work/`, and those hold the one
thing nothing else can reproduce once the ADP instance is gone — which on this
machine is the next `make down`. `state.py` used to describe the directory as
carrying "no trajectories"; see its docstring for why that reading is what this
target exists to correct.

Pilot 2 is why this exists as a target rather than a habit. Its numbers survived
only because its `.duva-bench/` happened to still be in a git worktree on an
already-merged branch: gitignored, unmentioned, and one `git worktree remove`
from taking the study's whole evidentiary basis with it. For a day this
repository recorded them as destroyed.

What gets copied is deliberately narrow — the trajectories and the trial
records, about 2 MB for sixty trials:

* **trajectories** are what the process metrics are computed from, `escaped`
  included, and no other artifact contains them;
* **trial records** carry `harbor_verifier_passed`, which is the outcome axis
  when the graders and the verifier agree.

What is *not* copied is the collected workspace per trial — 6 MB or so, and only
needed to re-run a grader. Re-grading is worth having and is not worth putting
in git for every study; if a grader changes, the run has to be re-reported from
ADP anyway.

This is not a substitute for `duva-bench report`, which reads ADP and is the
system of record. It is what makes the report's numbers checkable after the
system of record has been torn down.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from duva_bench.exec.harbor import find_trial_dir
from duva_bench.state import StateDir
from duva_bench.study.load import load_study

TRAJECTORY = Path("agent") / "trajectory.json"


def preserve(study_path: Path, into: Path, *, state_dir: Path | None = None) -> dict[str, object]:
    study = load_study(study_path)
    state = StateDir.for_study(study, state_dir)
    root = Path(state.root)

    trials = sorted(root.glob("trials/*.json"))
    if not trials:
        raise SystemExit(f"no trial records under {root}/trials — has this study run?")

    (into / "trajectories").mkdir(parents=True, exist_ok=True)
    (into / "trials").mkdir(parents=True, exist_ok=True)

    copied, missing = 0, []
    for record in trials:
        meta = json.loads(record.read_text(encoding="utf-8"))
        cell = f"{meta['arm_id']}__{meta['task_id']}__r{meta['repetition']}"
        shutil.copy2(record, into / "trials" / record.name)

        # The trial record names its own Harbor trial directory, but by absolute
        # path from the machine that ran it. Re-derive it from the state dir so
        # this works on a copy of the state as well as on the original.
        jobs = (
            root
            / "work"
            / f"{root.name}__{meta['arm_id']}__{meta['task_id']}__r{meta['repetition']}"
            / "jobs"
        )
        found = next(jobs.iterdir(), None) if jobs.is_dir() else None
        trial_dir = find_trial_dir(found) if found is not None else None
        source = trial_dir / TRAJECTORY if trial_dir is not None else None
        if source is None or not source.is_file():
            missing.append(cell)
            continue
        shutil.copy2(source, into / "trajectories" / f"{cell}.json")
        copied += 1

    manifest = {
        "study_digest": study.study_digest,
        "study_title": study.title,
        "arms": {arm.id: arm.labels() for arm in study.arms},
        "trial_records": len(trials),
        "trajectories": copied,
        # Named, not counted: a trial whose trajectory did not survive is a hole
        # in the evidence and a number would let it read as a rounding error.
        "trajectories_missing": missing,
        "preserved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "preserved_from": str(root),
    }
    (into / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("study", type=Path)
    parser.add_argument("--into", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    manifest = preserve(args.study, args.into, state_dir=args.state_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if manifest["trajectories_missing"]:
        print(
            f"WARNING: {len(manifest['trajectories_missing'])} trial(s) have no trajectory; "
            "their process metrics cannot be recomputed from this copy",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
