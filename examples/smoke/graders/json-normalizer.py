#!/usr/bin/env python3
"""Grader for the json-normalizer smoke task.

Contract (execution-plan M4): invoked as ``python3 <grader> <workdir>``, prints
one JSON object to stdout:

    {"spec": {...}, "axes": {"<axis>": {"score": float, "passed": bool,
                                        "summary": str}}}

Runs with its cwd outside the workdir and with every ADP and provider token
stripped from its environment. It therefore cannot report its own score — that
is duva-bench's job, under a different identity — and it must not try.

Multi-axis on purpose. A single pass/fail collapses "wrote something that works"
and "handled the error path" into one number, and the whole point of ranking per
axis is that those are different claims.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SPEC = {
    "grader": "json-normalizer",
    "version": "1.0.0",
    "axes": ["acceptance", "robustness"],
    "cases": {
        "acceptance": ["nested-object", "unicode-passthrough"],
        "robustness": ["invalid-json-exit-2", "invalid-json-clean-stdout"],
    },
}

TIMEOUT_SECONDS = 20


def run(target: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(target)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )


def grade(workdir: Path) -> dict[str, dict[str, object]]:
    target = workdir / "normalize.py"
    if not target.exists():
        missing = {"score": 0.0, "passed": False, "summary": "normalize.py was never written"}
        return {"acceptance": dict(missing), "robustness": dict(missing)}

    acceptance: list[tuple[str, bool]] = []
    robustness: list[tuple[str, bool]] = []

    try:
        nested = run(target, '{"b":1,"a":{"d":2,"c":3}}')
        acceptance.append(
            (
                "nested-object",
                nested.returncode == 0
                and nested.stdout == '{\n  "a": {\n    "c": 3,\n    "d": 2\n  },\n  "b": 1\n}\n',
            )
        )

        unicode_case = run(target, '{"k":"éè"}')
        acceptance.append(
            (
                "unicode-passthrough",
                unicode_case.returncode == 0 and "éè" in unicode_case.stdout,
            )
        )

        invalid = run(target, "not json")
        robustness.append(("invalid-json-exit-2", invalid.returncode == 2))
        robustness.append(("invalid-json-clean-stdout", invalid.stdout == ""))
    except subprocess.TimeoutExpired:
        timed_out = {
            "score": 0.0,
            "passed": False,
            "summary": f"normalize.py did not finish within {TIMEOUT_SECONDS}s",
        }
        return {"acceptance": dict(timed_out), "robustness": dict(timed_out)}

    return {
        "acceptance": axis(acceptance),
        "robustness": axis(robustness),
    }


def axis(cases: list[tuple[str, bool]]) -> dict[str, object]:
    passed = [name for name, ok in cases if ok]
    failed = [name for name, ok in cases if not ok]
    return {
        "score": len(passed) / len(cases),
        "passed": not failed,
        "summary": f"{len(passed)}/{len(cases)} cases"
        + (f"; failed: {', '.join(failed)}" if failed else ""),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <workdir>", file=sys.stderr)
        return 2
    json.dump({"spec": SPEC, "axes": grade(Path(argv[1]))}, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
