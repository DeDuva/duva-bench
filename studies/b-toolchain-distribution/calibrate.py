#!/usr/bin/env python3
"""Measure how hard a task actually is, before a factorial pays for it.

    python3 studies/b-toolchain-distribution/calibrate.py topo-order window-stats

The 2026-08-10 pilot spent $2.16 to discover that every arm solved every task
twice: pooled within-cell sd 0.0, no outcome signal, nothing for a contrast to
be divided by. Difficulty had been asserted in a docstring and never measured.

This measures it. Each task is run `--reps` times on the **oss** substrate only —
the cheapest arm and the one a model should find easiest — and the pass rate is
reported. A task at 0/n or n/n cannot carry an outcome axis whatever the other
arms do; the useful band is somewhere in between, where repetitions of one cell
actually differ.

Runs Harbor directly rather than through a study: calibration is a property of
the task, needs no ADP, and should not leave runs in a study's record.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from duva_bench.exec.harbor import HarborExecutor, find_trial_dir, load_trial  # noqa: E402

STUDY = Path(__file__).resolve().parent


def run_once(task_dir: Path, jobs: Path, label: str, model: str) -> tuple[bool | None, float, int]:
    completed = subprocess.run(
        [
            HarborExecutor().resolve(),
            "run",
            "--path",
            str(task_dir),
            "--agent",
            "terminus-2",
            "--model",
            model,
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
        timeout=3600,
    )
    if completed.returncode != 0:
        return None, 0.0, 0
    trial_dir = find_trial_dir(jobs / label)
    if trial_dir is None:
        return None, 0.0, 0
    trial = load_trial(trial_dir)
    cost, steps = 0.0, 0
    trajectory = trial_dir / "agent" / "trajectory.json"
    if trajectory.exists():
        data = json.loads(trajectory.read_text(encoding="utf-8"))
        cost = float((data.get("final_metrics") or {}).get("total_cost_usd") or 0.0)
        steps = len(data.get("steps") or [])
    return trial.verifier_passed, cost, steps


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", nargs="+")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--substrate", default="oss")
    parser.add_argument("--model", default="anthropic/claude-sonnet-4-5-20250929")
    parser.add_argument("--concurrent", type=int, default=3)
    args = parser.parse_args()

    spent = 0.0
    print(f"{'task':16} {'passed':>8} {'rate':>6} {'mean $':>8} {'mean steps':>11}")
    for slug in args.tasks:
        task_dir = STUDY / "tasks" / f"{slug}-{args.substrate}"
        if not task_dir.is_dir():
            print(f"{slug:16} no such task")
            continue
        outcomes: list[bool | None] = []
        costs: list[float] = []
        steps: list[int] = []
        with tempfile.TemporaryDirectory() as raw:
            jobs = Path(raw) / "jobs"
            jobs.mkdir()
            for rep in range(1, args.reps + 1):
                passed, cost, step_count = run_once(task_dir, jobs, f"{slug}-r{rep}", args.model)
                outcomes.append(passed)
                costs.append(cost)
                steps.append(step_count)
                spent += cost
        good = sum(1 for o in outcomes if o is True)
        known = [o for o in outcomes if o is not None]
        rate = f"{good}/{len(known)}" if known else "n/a"
        mean_cost = sum(costs) / len(costs) if costs else 0.0
        mean_steps = sum(steps) / len(steps) if steps else 0
        print(f"{slug:16} {good:>8} {rate:>6} {mean_cost:>8.4f} {mean_steps:>11.1f}")
    print(f"\ncalibration spend: ${spent:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
