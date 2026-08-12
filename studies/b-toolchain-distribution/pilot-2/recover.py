#!/usr/bin/env python3
"""Pilot 2's numbers, recomputed from pilot 2's own artifacts.

    python3 studies/b-toolchain-distribution/pilot-2/recover.py

Every number amendment §7.1 argues from came out of a session's scratch
directory. The report committed beside them has 120 of 120 axis scores `null` —
the grader searched for `report.py` after packages had become
`report/__init__.py` — the ADP evals were deliberately left unscored, and that
ADP instance is ephemeral. For a day this repository recorded the artifacts as
lost. They were not: they were in a git worktree on an already-merged branch,
one `git worktree remove` from gone.

So the two things nothing else could reproduce are checked in beside this
script, and this recomputes the numbers from them:

``trajectories/``
    One ATIF trajectory per trial. The escape metric is computed from these and
    from nothing else, which is what makes it re-derivable at all.

``trials/``
    One duva-bench trial record per trial, carrying `harbor_verifier_passed`.
    That is the outcome axis: the graders were re-run against all sixty
    collected workspaces on 2026-08-11 and agreed with the verifier on every
    one, so the verifier's own verdict reproduces the acceptance means exactly.

**Not checked in:** the collected workspaces (6.2 MB), which is what a grader
reads. Re-grading needs them and they are not required to reproduce anything
below.

**This is a recovery, not a report.** A real report is built by
`duva-bench report` reading ADP, and pilot 2's ADP record is unscored and gone.
Nothing here is a substitute for that; it exists so the amendment's rationale
cites numbers a reader can check rather than numbers a session once saw.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from duva_bench.analysis.process import ProcessMetrics, compute  # noqa: E402
from duva_bench.exec.bridge import bridge_trajectory  # noqa: E402

HERE = Path(__file__).resolve().parent

# Pilot 2's toolchain vocabulary, which is *not* today's: its twin was the
# hand-written `kelvra`/`brivols`/`tomak` one, and both twins are seed-drawn now
# (design document §7.1.2). Recomputing pilot 2 under today's names would find
# no escapes at all and report it as a result.
RUNNERS = {"oss": "make", "twin": "tomak", "proprietary": "dbuild"}
FOREIGN = {
    arm: tuple(sorted((set(RUNNERS.values()) - {runner}) | {"pytest"}))
    for arm, runner in RUNNERS.items()
}
ARMS = ("oss", "twin", "proprietary")


def _cells() -> dict[tuple[str, str, int], dict[str, Any]]:
    """Every trial, keyed by (arm, task, repetition)."""
    cells = {}
    for record in sorted((HERE / "trials").glob("*.json")):
        meta = json.loads(record.read_text(encoding="utf-8"))
        cells[(meta["arm_id"], meta["task_id"], meta["repetition"])] = meta
    return cells


def recover() -> dict[str, Any]:
    escapes: dict[str, list[ProcessMetrics]] = defaultdict(list)
    by_cell: dict[tuple[str, str], list[bool]] = defaultdict(list)
    passed: dict[str, list[bool]] = defaultdict(list)

    for (arm, task, rep), meta in _cells().items():
        trajectory = json.loads(
            (HERE / "trajectories" / f"{arm}__{task}__r{rep}.json").read_text(encoding="utf-8")
        )
        metrics = compute(bridge_trajectory(trajectory), foreign_commands=FOREIGN[arm])
        escapes[arm].append(metrics)
        by_cell[(task, arm)].append(bool(metrics.escaped))
        passed[arm].append(bool(meta["harbor_verifier_passed"]))

    return {
        "study_digest": "sha256:ed1bb8235a36...",
        "model": "anthropic/claude-haiku-4-5-20251001",
        "harness": "terminus-2@0.20.0",
        "trials": sum(len(v) for v in escapes.values()),
        "detector": (
            "duva_bench.analysis.process.compute as of this commit — the shlex-based one, "
            "not the regex the 2026-08-11 counts were made by hand under"
        ),
        "arms": {
            arm: {
                "trials": len(escapes[arm]),
                "escaped_trials": sum(1 for m in escapes[arm] if m.escaped),
                "escaped_rate": sum(1 for m in escapes[arm] if m.escaped) / len(escapes[arm]),
                "escape_calls": sum(m.escape_calls or 0 for m in escapes[arm]),
                "probe_calls": sum(m.probe_calls or 0 for m in escapes[arm]),
                "escaped_commands": sorted({c for m in escapes[arm] for c in m.escaped_commands}),
                "acceptance": sum(passed[arm]) / len(passed[arm]),
            }
            for arm in ARMS
        },
        "escaped_by_cell": {
            f"{task}/{arm}": sum(values) for (task, arm), values in sorted(by_cell.items())
        },
    }


def main() -> int:
    payload = recover()
    (HERE / "recovered.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
