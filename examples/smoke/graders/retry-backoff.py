#!/usr/bin/env python3
"""Grader for the retry-backoff smoke task.

Same contract as ``json-normalizer.py``: ``python3 <grader> <workdir>``, one JSON
object on stdout, no ADP or provider tokens in the environment.

The candidate is imported in a subprocess rather than in this process. A grader
that imports what it is grading is a grader an agent can break out of, and it
would take the score with it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SPEC = {
    "grader": "retry-backoff",
    "version": "1.0.0",
    "axes": ["acceptance", "backoff_shape"],
    "cases": {
        "acceptance": ["returns-on-eventual-success", "propagates-final-failure"],
        "backoff_shape": ["exponential-delays", "attempt-count-respected"],
    },
}

TIMEOUT_SECONDS = 20

PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
results = {}
try:
    from retry import call_with_retry
except Exception as exc:
    print(json.dumps({"import_error": f"{type(exc).__name__}: {exc}"}))
    raise SystemExit(0)

slept, calls = [], {"n": 0}


def flaky():
    calls["n"] += 1
    if calls["n"] < 3:
        raise RuntimeError("boom")
    return "ok"


try:
    value = call_with_retry(flaky, attempts=4, base_delay=0.01, sleep=slept.append)
    results["returns-on-eventual-success"] = value == "ok"
    results["attempt-count-respected"] = calls["n"] == 3
    results["exponential-delays"] = slept == [0.01, 0.02]
except Exception as exc:
    results["returns-on-eventual-success"] = False
    results["attempt-count-respected"] = False
    results["exponential-delays"] = False
    results["error"] = f"{type(exc).__name__}: {exc}"


def always():
    raise ValueError("never")


try:
    call_with_retry(always, attempts=2, base_delay=0.01, sleep=lambda _: None)
    results["propagates-final-failure"] = False
except ValueError:
    results["propagates-final-failure"] = True
except Exception:
    results["propagates-final-failure"] = False

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
        return {"import_error": completed.stderr.strip()[-400:] or "probe produced no output"}
    parsed: dict[str, object] = json.loads(completed.stdout)
    return parsed


def axis(results: dict[str, object], names: list[str]) -> dict[str, object]:
    passed = [name for name in names if results.get(name) is True]
    failed = [name for name in names if name not in passed]
    summary = f"{len(passed)}/{len(names)} cases"
    if failed:
        summary += f"; failed: {', '.join(failed)}"
    if "import_error" in results:
        summary += f"; import failed: {results['import_error']}"
    return {"score": len(passed) / len(names), "passed": not failed, "summary": summary}


def grade(workdir: Path) -> dict[str, dict[str, object]]:
    if not (workdir / "retry.py").exists():
        missing = {"score": 0.0, "passed": False, "summary": "retry.py was never written"}
        return {"acceptance": dict(missing), "backoff_shape": dict(missing)}
    try:
        results = probe(workdir)
    except subprocess.TimeoutExpired:
        timed_out = {
            "score": 0.0,
            "passed": False,
            "summary": f"the candidate did not finish within {TIMEOUT_SECONDS}s",
        }
        return {"acceptance": dict(timed_out), "backoff_shape": dict(timed_out)}

    axes = SPEC["cases"]
    assert isinstance(axes, dict)
    return {name: axis(results, list(cases)) for name, cases in axes.items()}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <workdir>", file=sys.stderr)
        return 2
    json.dump({"spec": SPEC, "axes": grade(Path(argv[1]))}, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
