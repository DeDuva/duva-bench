"""Study B's monorepo driver, and whether its gate actually bites.

The `proprietary` arm's claim to being a different *kind* of environment rests
on one rule: a target that uses another has to declare it, and the build refuses
otherwise. If that rule were decorative — if an undeclared dependency worked
anyway because the files happen to sit next to each other — the arm would be the
`oss` arm with extra typing, and the study's contrast would be a fiction.

So this tests the negative case, which is the only one that can prove the rule
exists.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DBUILD = ROOT / "studies" / "b-toolchain-distribution" / "tasks" / "add-median-proprietary"
DBUILD = DBUILD / "environment" / "dbuild"


def _depot(tmp_path: Path, report_deps: str) -> Path:
    depot = tmp_path / "depot"
    (depot / "stats").mkdir(parents=True)
    (depot / "stats" / "__init__.py").write_text("def mean(v):\n    return sum(v) / len(v)\n")
    (depot / "stats" / "BUILD").write_text(
        'py_library(\n    name = "stats",\n    srcs = ["__init__.py"],\n    deps = [],\n)\n'
    )
    (depot / "report").mkdir(parents=True)
    (depot / "report" / "__init__.py").write_text(
        "from stats import mean\n\n\ndef summarize(v):\n    return {'mean': mean(v)}\n"
    )
    (depot / "report" / "test_report.py").write_text(
        "from report import summarize\n\n\n"
        "def test_mean():\n    assert summarize([2, 4])['mean'] == 3\n"
    )
    (depot / "report" / "BUILD").write_text(
        'py_library(\n    name = "report",\n    srcs = ["__init__.py"],\n'
        f"    deps = [{report_deps}],\n)\n\n"
        'py_test(\n    name = "report_test",\n    srcs = ["test_report.py"],\n'
        '    deps = ["//depot/report:report"],\n)\n'
    )
    return depot


def _run(depot: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DBUILD), *args],
        capture_output=True,
        text=True,
        timeout=300,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "DBUILD_DEPOT": str(depot)},
    )


def test_a_declared_dependency_builds_and_tests() -> None:
    """The positive case, so the negative one means something."""
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        depot = _depot(Path(raw), '"//depot/stats:stats"')
        assert _run(depot, "build", "//depot/report:report").returncode == 0
        assert _run(depot, "test", "//depot/report:report_test").returncode == 0


def test_an_undeclared_dependency_fails_even_though_the_import_would_work() -> None:
    """The rule the whole arm rests on.

    `report.py` imports `stats` either way; what changes is whether the BUILD
    file says so. Only a build that follows declarations rather than the
    filesystem can tell the difference, and if this passed, the `proprietary`
    arm would just be the `oss` arm with more typing.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        depot = _depot(Path(raw), "")
        completed = _run(depot, "test", "//depot/report:report_test")
        assert completed.returncode != 0, (
            "a target with an undeclared dependency built and tested cleanly; "
            "the depot's declaration rule is decorative"
        )
