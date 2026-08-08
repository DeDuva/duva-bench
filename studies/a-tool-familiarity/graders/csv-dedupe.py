#!/usr/bin/env python3
"""Grader for the csv-dedupe task (Study A).

Contract: ``python3 <grader> <workdir>``, one JSON object on stdout. Runs with
its cwd outside the workdir and with every ADP and provider token stripped from
its environment — it is an instrument, and it reports nothing on its own behalf.

The candidate is exercised in a subprocess. A grader that imports what it is
grading is a grader the candidate can break out of, and it would take the score
with it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SPEC = {'grader': 'csv-dedupe', 'version': '1.0.0', 'axes': ['acceptance', 'robustness'], 'cases': {'acceptance': ['keeps-last', 'exit-zero'], 'robustness': ['missing-column-exits-2', 'missing-column-clean-stdout', 'header-only']}}

TIMEOUT_SECONDS = 60

PROBE = r"""
import json
import sys

workdir = sys.argv[1]
sys.path.insert(0, workdir)
results = {}
try:
    import os
    import subprocess
    import sys

    INPUT = "id,name\n1,a\n2,b\n1,c\n3,d\n2,e\n"


    def run(args, text):
        return subprocess.run(
            [sys.executable, os.path.join(workdir, "dedupe.py"), *args],
            input=text,
            capture_output=True,
            text=True,
            timeout=20,
        )


    done = run(["id"], INPUT)
    results["keeps-last"] = done.stdout.replace("\r\n", "\n") == "id,name\n1,c\n2,e\n3,d\n"
    results["exit-zero"] = done.returncode == 0

    missing = run(["nope"], INPUT)
    results["missing-column-exits-2"] = missing.returncode == 2
    results["missing-column-clean-stdout"] = missing.stdout == ""

    empty = run(["id"], "id,name\n")
    results["header-only"] = empty.returncode == 0 and empty.stdout.strip() == "id,name"
except Exception as exc:
    results["probe_error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(results))
"""


def probe(workdir: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-c", PROBE, str(workdir)],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return {"probe_error": completed.stderr.strip()[-400:] or "no output"}
    parsed: dict[str, object] = json.loads(completed.stdout)
    return parsed


def axis(results: dict[str, object], names: list[str]) -> dict[str, object]:
    passed = [name for name in names if results.get(name) is True]
    failed = [name for name in names if name not in passed]
    summary = f"{len(passed)}/{len(names)} cases"
    if failed:
        summary += "; failed: " + ", ".join(failed)
    if "probe_error" in results:
        summary += f"; probe failed: {results['probe_error']}"
    return {"score": len(passed) / len(names), "passed": not failed, "summary": summary}


def grade(workdir: Path) -> dict[str, dict[str, object]]:
    expected = 'dedupe.py'
    if not (workdir / expected).exists():
        missing = {"score": 0.0, "passed": False, "summary": f"{expected} was never written"}
        return {name: dict(missing) for name in SPEC["axes"]}
    try:
        results = probe(workdir)
    except subprocess.TimeoutExpired:
        stalled = {
            "score": 0.0,
            "passed": False,
            "summary": f"the candidate did not finish within {TIMEOUT_SECONDS}s",
        }
        return {name: dict(stalled) for name in SPEC["axes"]}

    cases = SPEC["cases"]
    assert isinstance(cases, dict)
    return {name: axis(results, list(names)) for name, names in cases.items()}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <workdir>", file=sys.stderr)
        return 2
    json.dump({"spec": SPEC, "axes": grade(Path(argv[1]))}, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
