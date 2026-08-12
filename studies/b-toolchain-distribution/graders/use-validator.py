#!/usr/bin/env python3
"""Grader for Study B's use-validator, in whichever toolchain it was solved.

Invoked as ``python3 <grader> <workdir>``, prints one JSON object. Runs with its
cwd outside the workdir and with every ADP and provider token stripped from its
environment, so it cannot report its own score — that is duva-bench's job, under
a different identity.

The check is the task's acceptance criterion, which is shared by all three
toolchain variants: the same behaviour is required of every arm, and only the
paths differ. Scored as two axes rather than one because "it works" and "it was
done the way the task asked" are different claims, and blending them would hide
an arm that passed by taking the shortcut the task forbids.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SPEC = {
    "task": "use-validator",
    "axes": ["acceptance", "discipline"],
}

# Where the container's /workspace was collected to. The verifier copies it, so
# the grader sees the work product without needing the container to still exist.
WORKSPACE = "workspace"
ENTRY_PACKAGE = "report"

# **The layout is discovered, not assumed.** One grader serves all three
# toolchains: `src/report/report.py`, `kelvra/report/report.py` and
# `depot/report/report.py` are the same work in three arrangements, and a grader
# pinned to one of them would score the other two as "never written" — which is
# the failure gate G2 found in the smoke study, arriving from the other side.
#
# It also means the study pins **one** grader per task rather than one per
# substrate, so the instrument is provably identical across the arms it compares.

CHECK = 'import sys\nfor root in __ROOTS__:\n    sys.path.insert(0, root)\ntry:\n    from report import summarize\n    from validate import NotNumeric\nexcept Exception as failure:\n    print(f"FAIL: cannot import: {failure}", file=sys.stderr)\n    raise SystemExit(1)\n\nif summarize([2, 4, 6]) != {"count": 3, "mean": 4.0}:\n    print("FAIL: a valid series no longer summarizes correctly", file=sys.stderr)\n    raise SystemExit(1)\n\n# The rejection has to be the validator\'s exception, not a home-grown one: the\n# task names the function to use, and an arm that reimplemented the check would\n# have done different work from an arm that found the package.\nfor bad in (["x", 1], [1, None], [1, True]):\n    try:\n        summarize(bad)\n    except NotNumeric:\n        continue\n    except Exception as other:\n        print(f"FAIL: summarize({bad}) raised {type(other).__name__}, not NotNumeric",\n              file=sys.stderr)\n        raise SystemExit(1)\n    print(f"FAIL: summarize({bad}) was accepted", file=sys.stderr)\n    raise SystemExit(1)\n\nsource = open(__ENTRY__).read()\nif "numeric" not in source:\n    print("FAIL: the entry module does not call the validator", file=sys.stderr)\n    raise SystemExit(1)\nfor home_grown in ("isinstance", "TypeError"):\n    if home_grown in source:\n        print(f"FAIL: the entry module does its own checking ({home_grown})", file=sys.stderr)\n        raise SystemExit(1)\n\nprint("PASS")\n'


def unscored(reason: str) -> dict:
    """A crashed check leaves an axis unscored, never zero (execution-plan §0.6)."""
    return {"score": None, "passed": False, "summary": reason}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <workdir>", file=sys.stderr)
        return 2
    workdir = Path(argv[1]).resolve()
    root = workdir / WORKSPACE
    axes: dict[str, dict] = {}

    if not root.is_dir():
        reason = f"nothing was collected at {root}"
        axes = {"acceptance": unscored(reason), "discipline": unscored(reason)}
        json.dump({"spec": SPEC, "axes": axes}, sys.stdout, sort_keys=True)
        return 0

    # A package's module is its `__init__.py`, so the entry is found by its
    # *directory* name. Searching for `<entry>.py` found nothing once packages
    # became packages, and every axis of a 60-trial pilot came back unscored
    # while every trial had in fact been solved.
    entry = next(
        (
            path / "__init__.py"
            for path in sorted(root.rglob(ENTRY_PACKAGE))
            if path.is_dir() and (path / "__init__.py").is_file()
        ),
        None,
    )
    tests = sorted(root.rglob("test_*.py"))
    if entry is None:
        reason = f"no {ENTRY_PACKAGE}/__init__.py anywhere under {root}"
        axes = {"acceptance": unscored(reason), "discipline": unscored(reason)}
        json.dump({"spec": SPEC, "axes": axes}, sys.stdout, sort_keys=True)
        return 0

    # A package is found through its *parent*, so the importable roots are the
    # directories holding packages — `src`, `kelvra`, `depot` — not the package
    # directories themselves. Adding the package directories instead made every
    # import fail, which the grader then reported as work that was never done.
    # Two kinds of root, because the container has both and a grader that has
    # fewer scores solved work as unsolved:
    #
    #   * the directory holding the packages — `src`, `kelvra`, `depot` — since
    #     a package is found through its parent;
    #   * the workspace itself, because inside the container the agent's cwd is
    #     /workspace and Python puts the cwd on the path. An agent that writes
    #     `from kelvra.stats import mean` is therefore *correct in the
    #     container*, and a grader without the workspace root marks it wrong.
    roots = sorted(
        {
            str(path.parent.parent)
            for path in root.rglob("__init__.py")
            if path.parent.parent != path.parent
        }
        | {str(root)}
    )

    script = CHECK
    for name, value in (
        ("__ROOTS__", json.dumps(roots)),
        ("__ENTRY__", json.dumps(str(entry))),
        ("__TEST__", json.dumps(str(tests[0]) if tests else "")),
    ):
        script = script.replace(name, value)

    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=300
    )
    output = (completed.stdout + completed.stderr).strip()
    passed = completed.returncode == 0

    axes["acceptance"] = {
        "score": 1.0 if passed else 0.0,
        "passed": passed,
        "summary": "behaviour is correct" if passed else output.splitlines()[-1][:200]
        if output
        else "the check failed and said nothing",
    }
    # Discipline is the subset of the check that is about *how* — the shortcuts
    # each task forbids. It is only meaningful once behaviour is right; before
    # that it is unscored rather than failed, because a trial that never worked
    # has not demonstrated anything about its method.
    if passed:
        axes["discipline"] = {
            "score": 1.0,
            "passed": True,
            "summary": "no forbidden shortcut detected",
        }
    else:
        forbidden = any(
            marker in output
            for marker in ("only the caller", "was changed rather than", "does its own",
                           "reimplement", "sorts values itself", "call sites pass")
        )
        axes["discipline"] = (
            {"score": 0.0, "passed": False, "summary": output.splitlines()[-1][:200]}
            if forbidden
            else unscored("behaviour is wrong, so method says nothing yet")
        )

    json.dump({"spec": SPEC, "axes": axes}, sys.stdout, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
