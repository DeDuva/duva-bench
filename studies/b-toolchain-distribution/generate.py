#!/usr/bin/env python3
"""Generate Study B's task variants: one problem, three toolchains.

    python3 studies/b-toolchain-distribution/generate.py

The design is `docs/studies/b-toolchain-distribution.md`. What matters here is
the constraint that governs every line: **the three variants must pose the same
problem.** If the `proprietary` variant is harder in substance rather than only
in convention, the study measures difficulty and its headline claim evaporates.
So the source files, the assertions and the acceptance criteria are shared, and
only the *toolchain* around them changes:

``oss``
    What a model has seen a million times: ``src/`` and ``tests/``, ``pytest``,
    a ``Makefile``.

``twin``
    ``oss`` with every user-visible identifier mechanically renamed — the
    command, the config file, the target names — and byte-identical behaviour.
    This is the control. If it costs an agent nothing, the deficit on
    ``proprietary`` is structural; if it costs as much, the deficit is names.

``proprietary``
    A monorepo in the published Google style: ``//depot/...`` target paths,
    ``BUILD`` files declaring targets and their dependencies, a build driver
    invoked as ``dbuild``, and a presubmit gate the change must satisfy.

**The build driver is a reconstruction, not Blaze**, and not Bazel either: a
real Bazel image is a large download and Bazel is itself public and therefore in
distribution, which would blunt the contrast. `dbuild` implements the parts the
tasks exercise — resolve a target, run its dependencies, run its tests — from
the conventions described in Potvin and Levenberg (CACM 2016). That it is a
reconstruction is the study's central limitation and is recorded in the design
document, not hidden here.
"""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

STUDY = Path(__file__).resolve().parent
TASKS = STUDY / "tasks"

# The problem, identical in all three variants: `summarize` must gain a median,
# which means touching a second module and the test that covers it.
LIBRARY = '''\
"""Statistics helpers."""


def mean(values):
    if not values:
        raise ValueError("mean of no values")
    return sum(values) / len(values)


def median(values):
    if not values:
        raise ValueError("median of no values")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2
'''

REPORT_BEFORE = '''\
"""Turn a series of readings into a summary."""

from stats import mean


def summarize(readings):
    return {"count": len(readings), "mean": mean(readings)}
'''

TEST_BEFORE = """\
from report import summarize


def test_summarize_counts_and_means():
    assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}
"""

# What the agent is asked for, worded the same in every variant. Only the
# toolchain paragraph differs, and that paragraph is the manipulation.
PROBLEM = """\
`summarize` reports a count and a mean. It also needs a **median**.

Add a `median` key to the dictionary `summarize` returns, computed by the
`median` function that already exists in the statistics module — do not
reimplement it. Then extend the existing test so it covers the new key, and make
the whole test suite pass.

The median of an even-length series is the mean of its two middle values.
"""

OSS_TOOLCHAIN = """\
## Working here

This is a standard Python project.

- Source is in `src/`, tests are in `tests/`.
- Run the tests with `make test`, which runs `pytest`.
"""

TWIN_TOOLCHAIN = """\
## Working here

This is a standard {lang} project.

- Source is in `{src}/`, tests are in `{tests}/`.
- Run the tests with `{runner} {verb}`, which runs `{harness}`.
"""

PROPRIETARY_TOOLCHAIN = """\
## Working here

This is a monorepo. Code lives under `depot/`, and every directory that produces
something has a `BUILD` file declaring its targets.

- A target is named by its path from the depot root: `//depot/stats:stats`.
- A target that uses another must **declare it** in its `deps`. A build with an
  undeclared dependency fails even if the import would work.
- Build and test with the depot's driver:

  ```
  dbuild test //depot/report:report_test
  ```

- Before a change counts as landed it must pass presubmit:

  ```
  dbuild presubmit
  ```

  Presubmit builds and tests every target in the depot and rejects any target
  whose dependencies are not declared.
"""

# The `twin` vocabulary. Pronounceable, non-dictionary, and length-matched to
# what it replaces, which is the twin generator's own rule (`arms/twin.py`).
TWIN_WORDS = {
    "lang": "Python",  # the language is not the manipulation; the toolchain is
    "src": "kelvra",
    "tests": "brivols",
    "runner": "tomak",
    "verb": "vess",
    "harness": "pelmatest",
}

DBUILD = '''\
#!/usr/bin/env python3
"""A minimal monorepo build driver, in the published Google style.

Not Blaze and not Bazel: it implements only what these tasks exercise — resolve
a `//depot/pkg:target`, refuse a target whose dependencies are not declared, run
tests. It exists so the *conventions* are real (declared deps, target paths, a
presubmit gate) without a large toolchain download, and the reconstruction is
recorded as this study's central limitation.
"""

import os
import subprocess
import sys
from pathlib import Path

# Overridable so the driver can be tested against a temporary depot. The default
# is the only value any task uses.
DEPOT = Path(os.environ.get("DBUILD_DEPOT", "/workspace/depot"))


def parse_build(package):
    """Targets declared by a package's BUILD file: {name: {srcs, deps}}."""
    build = DEPOT / package / "BUILD"
    if not build.exists():
        raise SystemExit(f"no BUILD file for //depot/{package}")
    targets, current = {}, None
    for raw in build.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.endswith("("):
            current = {"kind": line[:-1].strip(), "srcs": [], "deps": []}
            continue
        if line == ")":
            current = None
            continue
        if current is None or "=" not in line:
            continue
        key, value = (part.strip().rstrip(",") for part in line.split("=", 1))
        if key == "name":
            current["name"] = value.strip('"')
            targets[current["name"]] = current
        elif key in ("srcs", "deps"):
            current[key] = [
                item.strip().strip('",') for item in value.strip("[]").split() if item.strip(' ",')
            ]
    return targets


def resolve(label):
    if not label.startswith("//depot/") or ":" not in label:
        raise SystemExit(f"not a target label: {label}")
    package, name = label[len("//depot/") :].split(":", 1)
    targets = parse_build(package)
    if name not in targets:
        raise SystemExit(f"no target {name!r} in //depot/{package}")
    return package, targets[name]


def sources_for(label, seen=None):
    """Every source file a target needs, following declared deps only."""
    seen = seen if seen is not None else set()
    if label in seen:
        return []
    seen.add(label)
    package, target = resolve(label)
    paths = [str(DEPOT / package / src) for src in target["srcs"]]
    for dep in target["deps"]:
        paths.extend(sources_for(dep, seen))
    return paths


def run_test(label):
    package, target = resolve(label)
    if target["kind"] != "py_test":
        raise SystemExit(f"{label} is not a py_test")
    # Only declared dependencies are on the path. An import that works by
    # accident of the filesystem is exactly what a declared build prevents.
    roots = {str(Path(path).parent) for path in sources_for(label)}
    env_path = ":".join(sorted(roots))
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *[s for s in target["srcs"]]],
        cwd=str(DEPOT / package),
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": env_path},
    )
    return completed.returncode


def presubmit():
    failures = []
    for build in sorted(DEPOT.rglob("BUILD")):
        package = str(build.parent.relative_to(DEPOT))
        for name, target in parse_build(package).items():
            label = f"//depot/{package}:{name}"
            for dep in target["deps"]:
                try:
                    resolve(dep)
                except SystemExit as bad:
                    failures.append(f"{label}: {bad}")
            if target["kind"] == "py_test" and run_test(label) != 0:
                failures.append(f"{label}: tests failed")
    if failures:
        print("PRESUBMIT FAILED")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("PRESUBMIT OK")
    return 0


def main(argv):
    if len(argv) < 2:
        print("usage: dbuild [test <label> | build <label> | presubmit]", file=sys.stderr)
        return 2
    command = argv[1]
    if command == "presubmit":
        return presubmit()
    if command in ("test", "build") and len(argv) > 2:
        label = argv[2]
        if command == "build":
            sources_for(label)
            print(f"BUILD OK {label}")
            return 0
        return run_test(label)
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def write(path: Path, body: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def dockerfile(extra: str = "") -> str:
    return textwrap.dedent(
        f"""\
        FROM python:3.12-slim

        RUN pip install --no-cache-dir pytest==8.3.3
        WORKDIR /workspace
        {extra}
        """
    )


def verifier(check: str) -> str:
    """Every variant's verifier runs the same acceptance check.

    Deliberately not the agent's own test: a task that graded an agent by the
    test the agent was told to edit would grade it on its willingness to write
    an assertion. This imports the result and checks the behaviour.
    """
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -uo pipefail

        REWARD_FILE="${{HARBOR_REWARD_FILE:-/logs/verifier/reward.txt}}"
        mkdir -p "$(dirname "$REWARD_FILE")"
        printf '0' > "$REWARD_FILE"
        reward_pass() {{ printf '1' > "$REWARD_FILE"; }}

        mkdir -p /logs/artifacts
        cp -a /workspace /logs/artifacts/workspace 2>/dev/null || true

        {check}

        status=$?
        [ "$status" -eq 0 ] && reward_pass
        exit "$status"
        """
    )


ACCEPTANCE = """\
python3 - <<'PY'
import subprocess, sys
sys.path.insert(0, SOURCE_ROOT)
try:
    from report import summarize
except Exception as failure:
    print(f"FAIL: cannot import summarize: {failure}", file=sys.stderr)
    raise SystemExit(1)

cases = [
    ([2, 4, 6], {"count": 3, "mean": 4.0, "median": 4.0}),
    ([1, 2, 3, 4], {"count": 4, "mean": 2.5, "median": 2.5}),
    ([5], {"count": 1, "mean": 5.0, "median": 5.0}),
]
for readings, expected in cases:
    got = summarize(readings)
    if got != expected:
        print(f"FAIL: summarize({readings}) == {got}, expected {expected}", file=sys.stderr)
        raise SystemExit(1)

# The median must come from the statistics module rather than be reimplemented:
# the task says so, and a study that let either pass would be scoring two
# different pieces of work as one.
import report
if "median" not in getattr(report, "__dict__", {}) and not hasattr(report, "median"):
    pass
source = open(REPORT_PATH).read()
if "median" not in source:
    print("FAIL: report does not mention median", file=sys.stderr)
    raise SystemExit(1)
if "sorted(" in source:
    print("FAIL: report sorts values itself instead of using the statistics module",
          file=sys.stderr)
    raise SystemExit(1)

print("PASS")
PY
"""


def oss_variant() -> None:
    root = TASKS / "add-median-oss"
    if root.exists():
        shutil.rmtree(root)
    write(root / "environment" / "Dockerfile", dockerfile())
    write(root / "environment" / "src" / "stats.py", LIBRARY)
    write(root / "environment" / "src" / "report.py", REPORT_BEFORE)
    write(root / "environment" / "tests" / "test_report.py", TEST_BEFORE)
    write(
        root / "environment" / "Makefile",
        "test:\n\tPYTHONPATH=src python3 -m pytest -q tests\n",
    )
    write(root / "instruction.md", PROBLEM + "\n" + OSS_TOOLCHAIN)
    write(
        root / "environment" / "Dockerfile",
        dockerfile(
            "COPY src/ /workspace/src/\nCOPY tests/ /workspace/tests/\nCOPY Makefile /workspace/Makefile\n"
        ),
    )
    check = ACCEPTANCE.replace("SOURCE_ROOT", '"/workspace/src"').replace(
        "REPORT_PATH", '"/workspace/src/report.py"'
    )
    write(root / "tests" / "test.sh", verifier(check), executable=True)
    write(
        root / "solution" / "solve.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "p = Path('/workspace/src/report.py')\n"
        "p.write_text(p.read_text()\n"
        "  .replace('from stats import mean', 'from stats import mean, median')\n"
        '  .replace(\'"mean": mean(readings)}\', \'"mean": mean(readings), "median": median(readings)}\'))\n'
        "t = Path('/workspace/tests/test_report.py')\n"
        "t.write_text(t.read_text().replace(\n"
        '  \'{"count": 3, "mean": 4.0}\', \'{"count": 3, "mean": 4.0, "median": 4.0}\'))\n'
        "PY\n",
        executable=True,
    )
    write(root / "task.toml", TASK_TOML)


def twin_variant() -> None:
    root = TASKS / "add-median-twin"
    if root.exists():
        shutil.rmtree(root)
    words = TWIN_WORDS
    write(root / "environment" / words["src"] / "stats.py", LIBRARY)
    write(root / "environment" / words["src"] / "report.py", REPORT_BEFORE)
    write(root / "environment" / words["tests"] / "test_report.py", TEST_BEFORE)
    # `tomak vess` is `make test` under another name: same runner semantics,
    # same output, a name the model has never read.
    write(
        root / "environment" / "tomakfile",
        f"{words['verb']}:\n\tPYTHONPATH={words['src']} python3 -m pytest -q {words['tests']}\n",
    )
    write(
        root / "environment" / "tomak",
        "#!/usr/bin/env bash\n"
        "# The twin's build runner. Identical in behaviour to the standard one;\n"
        "# only the name it is invoked by, and the file it reads, are different.\n"
        'exec make -f tomakfile "$@"\n',
        executable=True,
    )
    write(
        root / "environment" / "Dockerfile",
        dockerfile(
            "RUN apt-get update && apt-get install -y --no-install-recommends make "
            "&& rm -rf /var/lib/apt/lists/*\n"
            f"COPY {words['src']}/ /workspace/{words['src']}/\n"
            f"COPY {words['tests']}/ /workspace/{words['tests']}/\n"
            "COPY tomakfile /workspace/tomakfile\n"
            "COPY tomak /usr/local/bin/tomak\n"
        ),
    )
    write(root / "instruction.md", PROBLEM + "\n" + TWIN_TOOLCHAIN.format(**words))
    check = ACCEPTANCE.replace("SOURCE_ROOT", f'"/workspace/{words["src"]}"').replace(
        "REPORT_PATH", f'"/workspace/{words["src"]}/report.py"'
    )
    write(root / "tests" / "test.sh", verifier(check), executable=True)
    write(
        root / "solution" / "solve.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        f"p = Path('/workspace/{words['src']}/report.py')\n"
        "p.write_text(p.read_text()\n"
        "  .replace('from stats import mean', 'from stats import mean, median')\n"
        '  .replace(\'"mean": mean(readings)}\', \'"mean": mean(readings), "median": median(readings)}\'))\n'
        f"t = Path('/workspace/{words['tests']}/test_report.py')\n"
        "t.write_text(t.read_text().replace(\n"
        '  \'{"count": 3, "mean": 4.0}\', \'{"count": 3, "mean": 4.0, "median": 4.0}\'))\n'
        "PY\n",
        executable=True,
    )
    write(root / "task.toml", TASK_TOML)


def proprietary_variant() -> None:
    root = TASKS / "add-median-proprietary"
    if root.exists():
        shutil.rmtree(root)
    env = root / "environment"
    write(env / "depot" / "stats" / "stats.py", LIBRARY)
    write(
        env / "depot" / "stats" / "BUILD",
        'py_library(\n    name = "stats",\n    srcs = ["stats.py"],\n    deps = [],\n)\n',
    )
    write(env / "depot" / "report" / "report.py", REPORT_BEFORE)
    write(env / "depot" / "report" / "test_report.py", TEST_BEFORE)
    write(
        env / "depot" / "report" / "BUILD",
        'py_library(\n    name = "report",\n    srcs = ["report.py"],\n'
        '    deps = ["//depot/stats:stats"],\n)\n\n'
        'py_test(\n    name = "report_test",\n    srcs = ["test_report.py"],\n'
        '    deps = ["//depot/report:report"],\n)\n',
    )
    write(env / "dbuild", DBUILD, executable=True)
    write(
        env / "Dockerfile",
        dockerfile("COPY depot/ /workspace/depot/\nCOPY dbuild /usr/local/bin/dbuild\n"),
    )
    write(root / "instruction.md", PROBLEM + "\n" + PROPRIETARY_TOOLCHAIN)
    check = ACCEPTANCE.replace("SOURCE_ROOT", '"/workspace/depot/report"').replace(
        "REPORT_PATH", '"/workspace/depot/report/report.py"'
    )
    # The depot variant additionally has to satisfy its own gate: a change that
    # works but leaves the build graph undeclared has not landed here.
    check = (
        'export PYTHONPATH="/workspace/depot/stats:/workspace/depot/report"\n'
        + check.rstrip()
        + "\nif [ $? -eq 0 ]; then dbuild presubmit >&2 || exit 1; fi\n"
    )
    write(root / "tests" / "test.sh", verifier(check), executable=True)
    write(
        root / "solution" / "solve.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "p = Path('/workspace/depot/report/report.py')\n"
        "p.write_text(p.read_text()\n"
        "  .replace('from stats import mean', 'from stats import mean, median')\n"
        '  .replace(\'"mean": mean(readings)}\', \'"mean": mean(readings), "median": median(readings)}\'))\n'
        "t = Path('/workspace/depot/report/test_report.py')\n"
        "t.write_text(t.read_text().replace(\n"
        '  \'{"count": 3, "mean": 4.0}\', \'{"count": 3, "mean": 4.0, "median": 4.0}\'))\n'
        "PY\n",
        executable=True,
    )
    write(root / "task.toml", TASK_TOML)


TASK_TOML = """\
version = "1.0"

[metadata]
author_name = "duva-bench"
difficulty = "easy"
tags = ["study-b", "toolchain"]

[agent]
timeout_sec = 600

[verifier]
timeout_sec = 120
"""


def main() -> int:
    for build in (oss_variant, twin_variant, proprietary_variant):
        build()
    manifest = {
        "task": "add-median",
        "variants": sorted(path.name for path in TASKS.iterdir() if path.is_dir()),
        "twin_words": TWIN_WORDS,
    }
    write(STUDY / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
