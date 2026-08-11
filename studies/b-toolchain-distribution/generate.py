#!/usr/bin/env python3
"""Generate Study B's task variants: each problem, posed in three toolchains.

    python3 studies/b-toolchain-distribution/generate.py

The design is `docs/studies/b-toolchain-distribution.md`; the task content is
`tasks.py`. What matters here is the constraint that governs every line: **the
variants of a task must pose the same problem.** If the `proprietary` variant is
harder in substance rather than only in convention, the study measures difficulty
and its headline claim evaporates. So source files, tests and acceptance criteria
come from one definition and only the toolchain around them changes:

``oss``
    What a model has read a million times: packages under ``src/``, ``pytest``,
    a ``Makefile`` whose ``test`` target sets ``PYTHONPATH``.

``twin``
    ``oss`` with every user-visible identifier mechanically renamed — the source
    directory, the test directory, the runner, its target — and byte-identical
    behaviour. This is the **control**. If it costs an agent nothing, a deficit
    on ``proprietary`` is structural; if it costs as much, the deficit is names.

``proprietary``
    A monorepo in the published Google style: ``//depot/...`` labels, ``BUILD``
    files declaring targets and their dependencies, a ``dbuild`` driver, and a
    presubmit gate that rejects an undeclared dependency.

**The build driver is a reconstruction**, not Blaze and deliberately not Bazel:
Bazel is public and therefore itself in distribution, which would blunt the
contrast, and a real Bazel image is a large download. `dbuild` implements only
what these tasks exercise, from the conventions in Potvin and Levenberg (CACM
2016). That it is a reconstruction is the study's central limitation and is
recorded in the design document rather than hidden here.
"""

from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tasks import TASKS, Task  # noqa: E402

STUDY = Path(__file__).resolve().parent
TASK_ROOT = STUDY / "tasks"

# The `twin` vocabulary: pronounceable, non-dictionary, length-matched to what it
# replaces, which is the twin generator's own rule (`arms/twin.py`).
TWIN_WORDS = {
    "src": "kelvra",
    "tests": "brivols",
    "runner": "tomak",
    "verb": "vess",
}
OSS_WORDS = {"src": "src", "tests": "tests", "runner": "make", "verb": "test"}

OSS_TOOLCHAIN = """\
## Working here

This is a standard Python project.

- Each package is a directory under `{src}/`.
- Tests are in `{tests}/`.
- Run the tests with `{runner} {verb}`.
"""

PROPRIETARY_TOOLCHAIN = """\
## Working here

This is a monorepo. Code lives under `depot/`, and every directory that produces
something has a `BUILD` file declaring its targets.

- A target is named by its path from the depot root: `//depot/stats:stats`.
- A target that uses another must **declare it** in that target's `deps`. A
  build with an undeclared dependency fails even if the import would work.
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

DBUILD = '''\
#!/usr/bin/env python3
"""A minimal monorepo build driver, in the published Google style.

Not Blaze and not Bazel: it implements only what these tasks exercise — resolve
a `//depot/pkg:target`, refuse a target whose dependencies are not declared, run
tests, gate on presubmit. It exists so the *conventions* are real without a large
toolchain download, and the reconstruction is recorded as this study's central
limitation.
"""

import os
import subprocess
import sys
from pathlib import Path

# Overridable so the driver can be tested against a temporary depot. The default
# is the only value any task uses.
DEPOT = Path(os.environ.get("DBUILD_DEPOT", "/workspace/depot"))


def parse_build(package):
    """Targets declared by a package's BUILD file: {name: {kind, srcs, deps}}."""
    build = DEPOT / package / "BUILD"
    if not build.exists():
        raise SystemExit(f"no BUILD file for //depot/{package}")
    targets, current, collecting = {}, None, None
    for raw in build.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # A list spread over several lines, which is how BUILD files are
        # actually written. Reading only single-line lists silently produced
        # targets with no sources, and a test target with no sources passes.
        if collecting is not None:
            if line.startswith("]"):
                collecting = None
                continue
            item = line.strip().strip(",").strip('"')
            if item:
                current[collecting].append(item)
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
            if value.strip() == "[":
                collecting = key
                continue
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


def roots_for(label, seen=None):
    """Directories a target may import from, following declared deps only."""
    seen = seen if seen is not None else set()
    if label in seen:
        return []
    seen.add(label)
    package, target = resolve(label)
    roots = [str(DEPOT / package)]
    for dep in target["deps"]:
        roots.extend(roots_for(dep, seen))
    return roots


def run_test(label):
    package, target = resolve(label)
    if target["kind"] != "py_test":
        raise SystemExit(f"{label} is not a py_test")
    # Only declared dependencies are importable. An import that works by
    # accident of the filesystem is exactly what a declared build prevents.
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *target["srcs"]],
        cwd=str(DEPOT / package),
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONPATH": ":".join(sorted(set(roots_for(label)))),
        },
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
            roots_for(label)
            print(f"BUILD OK {label}")
            return 0
        return run_test(label)
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''

TASK_TOML = """\
version = "1.0"

[metadata]
author_name = "duva-bench"
difficulty = "{difficulty}"
tags = ["study-b", "toolchain"]

[agent]
timeout_sec = 900

[verifier]
timeout_sec = 180
"""


def write(path: Path, body: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def dockerfile(extra: str) -> str:
    return (
        textwrap.dedent(
            """\
            FROM python:3.12-slim

            RUN apt-get update && apt-get install -y --no-install-recommends make \\
                && rm -rf /var/lib/apt/lists/*
            RUN pip install --no-cache-dir pytest==8.3.3
            WORKDIR /workspace
            """
        )
        + extra
    )


def verifier(task: Task, source_roots: list[str], entry_source: str, extra_gate: str = "") -> str:
    """The acceptance check, identical in every variant.

    Deliberately not the agent's own test: a task that graded an agent by the
    test it was told to edit would be grading its willingness to write an
    assertion. This imports the result and checks the behaviour.
    """
    body = (
        task.acceptance.replace("SOURCE_ROOTS", json.dumps(source_roots))
        .replace("ENTRY_SOURCE", json.dumps(entry_source))
        .rstrip()
    )
    return (
        "#!/usr/bin/env bash\n"
        "set -uo pipefail\n\n"
        'REWARD_FILE="${HARBOR_REWARD_FILE:-/logs/verifier/reward.txt}"\n'
        'mkdir -p "$(dirname "$REWARD_FILE")"\n'
        "printf '0' > \"$REWARD_FILE\"\n"
        "reward_pass() { printf '1' > \"$REWARD_FILE\"; }\n\n"
        "mkdir -p /logs/artifacts\n"
        "cp -a /workspace /logs/artifacts/workspace 2>/dev/null || true\n\n"
        "python3 - <<'PY'\n" + body + "\nPY\n\n"
        "status=$?\n" + extra_gate + '[ "$status" -eq 0 ] && reward_pass\n'
        'exit "$status"\n'
    )


def solution(edits: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """An oracle expressed as literal substitutions on named files."""
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "python3 - <<'PY'",
        "from pathlib import Path",
    ]
    for path, replacements in edits:
        lines.append(f"p = Path({path!r})")
        lines.append("body = p.read_text()")
        for old, new in replacements:
            lines.append(f"body = body.replace({old!r}, {new!r})")
        lines.append("p.write_text(body)")
    lines.append("PY")
    return "\n".join(lines) + "\n"


def oracle_edits(
    task: Task, entry_source: str, test_path: str
) -> list[tuple[str, list[tuple[str, str]]]]:
    """What a correct change looks like, per task.

    Written per task rather than derived: "the right change" is the one thing a
    generator cannot infer, and an oracle that guessed would admit tasks whose
    graders it does not actually satisfy.
    """
    if task.slug == "add-median":
        return [
            (
                entry_source,
                [
                    ("from stats import mean", "from stats import mean, median"),
                    (
                        '"mean": mean(readings)}',
                        '"mean": mean(readings), "median": median(readings)}',
                    ),
                ],
            ),
            (
                test_path,
                [('{"count": 3, "mean": 4.0}', '{"count": 3, "mean": 4.0, "median": 4.0}')],
            ),
        ]
    if task.slug == "use-validator":
        return [
            (
                entry_source,
                [
                    (
                        "from stats import mean",
                        "from stats import mean\nfrom validate import numeric",
                    ),
                    (
                        "def summarize(readings):\n    return {",
                        "def summarize(readings):\n    readings = numeric(readings)\n    return {",
                    ),
                ],
            ),
            (
                test_path,
                [
                    (
                        "from report import summarize",
                        "import pytest\n\nfrom report import summarize\n"
                        "from validate import NotNumeric",
                    ),
                    (
                        'assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}',
                        'assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}\n\n\n'
                        "def test_summarize_rejects_a_non_number():\n"
                        "    with pytest.raises(NotNumeric):\n"
                        '        summarize([1, "x"])',
                    ),
                ],
            ),
        ]
    raise SystemExit(f"no oracle recorded for task {task.slug!r}")


def build_flat(task: Task, root: Path, words: dict[str, str]) -> None:
    """`oss`, and `twin` — one layout under two vocabularies."""
    env = root / "environment"
    for package in task.packages:
        for name, body in package.modules.items():
            write(env / words["src"] / package.name / name, body)
    for name, body in task.tests.items():
        write(env / words["tests"] / name, body)

    # Only the packages the entry already needs are on the path. A task that
    # requires reaching a *new* one is a task about this toolchain's way of
    # making a package reachable, which is the contrast the study draws.
    entry = next(p for p in task.packages if p.name == task.entry)
    reachable = [entry.name, *entry.needs]
    path = ":".join(f"{words['src']}/{name}" for name in reachable)
    runner_file = "Makefile" if words["runner"] == "make" else f"{words['runner']}file"
    write(
        env / runner_file,
        f"{words['verb']}:\n\tPYTHONPATH={path} python3 -m pytest -q {words['tests']}\n",
    )

    copies = [
        f"COPY {words['src']}/ /workspace/{words['src']}/\n",
        f"COPY {words['tests']}/ /workspace/{words['tests']}/\n",
        f"COPY {runner_file} /workspace/{runner_file}\n",
    ]
    if words["runner"] != "make":
        write(
            env / words["runner"],
            "#!/usr/bin/env bash\n"
            "# This project's build runner. Identical in behaviour to the usual\n"
            "# one; only its name, and the file it reads, are different.\n"
            f'exec make -f {runner_file} "$@"\n',
            executable=True,
        )
        copies.append(f"COPY {words['runner']} /usr/local/bin/{words['runner']}\n")
    write(env / "Dockerfile", dockerfile("".join(copies)))
    write(root / "instruction.md", task.problem + "\n" + OSS_TOOLCHAIN.format(**words))

    roots = [f"/workspace/{words['src']}/{p.name}" for p in task.packages]
    entry_source = f"/workspace/{words['src']}/{task.entry}/{task.entry}.py"
    test_path = f"/workspace/{words['tests']}/{next(iter(task.tests))}"
    write(root / "tests" / "test.sh", verifier(task, roots, entry_source), executable=True)
    write(
        root / "solution" / "solve.sh",
        solution(oracle_edits(task, entry_source, test_path)),
        executable=True,
    )
    write(root / "task.toml", TASK_TOML.format(difficulty=task.difficulty))


def build_proprietary(task: Task, root: Path) -> None:
    env = root / "environment"
    for package in task.packages:
        for name, body in package.modules.items():
            write(env / "depot" / package.name / name, body)
        deps = "".join(f'        "//depot/{need}:{need}",\n' for need in package.needs)
        srcs = "".join(f'        "{name}",\n' for name in package.modules)
        build = (
            f'py_library(\n    name = "{package.name}",\n    srcs = [\n{srcs}    ],\n'
            f"    deps = [\n{deps}    ],\n)\n"
        )
        if package.name == task.entry:
            for name, body in task.tests.items():
                write(env / "depot" / package.name / name, body)
            test_srcs = "".join(f'        "{name}",\n' for name in task.tests)
            build += (
                f'\npy_test(\n    name = "{package.name}_test",\n'
                f"    srcs = [\n{test_srcs}    ],\n"
                f'    deps = [\n        "//depot/{package.name}:{package.name}",\n    ],\n)\n'
            )
        write(env / "depot" / package.name / "BUILD", build)

    write(env / "dbuild", DBUILD, executable=True)
    write(
        env / "Dockerfile",
        dockerfile("COPY depot/ /workspace/depot/\nCOPY dbuild /usr/local/bin/dbuild\n"),
    )
    write(root / "instruction.md", task.problem + "\n" + PROPRIETARY_TOOLCHAIN)

    roots = [f"/workspace/depot/{p.name}" for p in task.packages]
    entry_source = f"/workspace/depot/{task.entry}/{task.entry}.py"
    test_path = f"/workspace/depot/{task.entry}/{next(iter(task.tests))}"
    # The depot's own gate, on top of the shared acceptance check: a change that
    # works but leaves the build graph undeclared has not landed here.
    gate = 'if [ "$status" -eq 0 ]; then dbuild presubmit >&2 || status=1; fi\n'
    write(root / "tests" / "test.sh", verifier(task, roots, entry_source, gate), executable=True)

    body = solution(oracle_edits(task, entry_source, test_path))
    if task.slug == "use-validator":
        # The declaration this toolchain requires and the other two do not. It is
        # the task's whole point, and without it presubmit rejects a change that
        # is otherwise correct.
        body += (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            f"b = Path('/workspace/depot/{task.entry}/BUILD')\n"
            "body = b.read_text()\n"
            "body = body.replace('        \"//depot/stats:stats\",\\n',\n"
            '                    \'        "//depot/stats:stats",\\n'
            '        "//depot/validate:validate",\\n\')\n'
            "b.write_text(body)\n"
            "PY\n"
        )
    write(root / "solution" / "solve.sh", body, executable=True)
    write(root / "task.toml", TASK_TOML.format(difficulty=task.difficulty))


def main() -> int:
    if TASK_ROOT.exists():
        shutil.rmtree(TASK_ROOT)
    built: list[str] = []
    for task in TASKS:
        build_flat(task, TASK_ROOT / f"{task.slug}-oss", OSS_WORDS)
        build_flat(task, TASK_ROOT / f"{task.slug}-twin", TWIN_WORDS)
        build_proprietary(task, TASK_ROOT / f"{task.slug}-proprietary")
        built.extend(f"{task.slug}-{kind}" for kind in ("oss", "twin", "proprietary"))
    manifest = {
        "tasks": [task.slug for task in TASKS],
        "variants": sorted(built),
        "twin_words": TWIN_WORDS,
    }
    write(STUDY / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
