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

from duva_bench.arms.twin import syllabic_name  # noqa: E402

from hard_tasks import HARD_TASKS  # noqa: E402
from tasks import TASKS as EASY_TASKS  # noqa: E402
from tasks import Task  # noqa: E402

TASKS = EASY_TASKS + HARD_TASKS

STUDY = Path(__file__).resolve().parent
TASK_ROOT = STUDY / "tasks"

OSS_WORDS = {"src": "src", "tests": "tests", "runner": "make", "verb": "test"}

# Two twins, and the second one is the point.
#
# A twin is `oss` with every user-visible name changed and nothing else, so a
# gap between a twin and `oss` is a familiarity effect. A gap between *two
# twins* is neither: they are identical in behaviour and differ only in which
# arbitrary strings the generator happened to draw, so whatever separates them
# is the instrument's own noise. That is the floor every other contrast on this
# study has to clear, and `oss` cannot supply it — `oss` differs from the twins
# in something real.
#
# Both vocabularies are now drawn by `arms/twin.py`'s own generator from a
# declared seed. Until 2026-08-11 the first twin's words were hand-written
# (`kelvra`, `brivols`, `tomak`, `vess`), which the design document's §9 already
# described as mechanical — it was not, and two twins produced by two different
# processes would not have been a noise floor. Length is matched in characters,
# which is that generator's stated rule and its stated approximation.
TWIN_SEEDS = {
    "twin": "duva-bench/study-b/twin/2026-08-11",
    "twin-b": "duva-bench/study-b/twin-b/2026-08-11",
}


def twin_words(seed: str) -> dict[str, str]:
    """The `oss` vocabulary renamed, deterministically in ``seed``.

    ``taken`` is threaded through so two roles never draw the same string; the
    twin would otherwise be able to collapse `tests/` onto `src/` and stop being
    isomorphic to what it replaces.
    """
    taken: set[str] = set()
    words: dict[str, str] = {}
    for role, source in OSS_WORDS.items():
        words[role] = syllabic_name(source, seed, length=len(source), taken=taken)
        taken.add(words[role])
    return words


TWIN_WORDS = {name: twin_words(seed) for name, seed in TWIN_SEEDS.items()}

OSS_TOOLCHAIN = """\
## Working here

This is a standard Python project.

- Each package is a directory under `{src}/`.
- A package's module is imported by its own name: the code in `{src}/stats/` is
  reached with `from stats import ...`, not `from stats.stats import ...`.
- Tests are in `{tests}/`.
- Run the tests with `{runner} {verb}`.
"""

PROPRIETARY_TOOLCHAIN = """\
## Working here

This is a monorepo. Code lives under `depot/`, and every directory that produces
something has a `BUILD` file declaring its targets.

- A target is named by its path from the depot root: `//depot/stats:stats`.
- A package's module is imported by its own name: the code in `depot/stats/` is
  reached with `from stats import ...`, not `from depot.stats import ...`.
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
import shutil
import subprocess
import sys
import tempfile
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


def packages_for(label, seen=None):
    """Package names a target may import, following declared deps only."""
    seen = seen if seen is not None else set()
    if label in seen:
        return []
    seen.add(label)
    package, target = resolve(label)
    names = [package]
    for dep in target["deps"]:
        names.extend(packages_for(dep, seen))
    return names


def declared_root(label):
    """A directory holding exactly the packages `label` declared.

    Packages are real Python packages, so a package is found by its *parent*
    being on the path — and putting the depot root there would make every
    package importable and the declaration rule decorative. So the parent is
    built: a directory of symlinks to the declared packages and nothing else.

    An import that works by accident of the filesystem is precisely what a
    declared build exists to prevent, and this is where that is enforced.
    """
    root = Path(tempfile.mkdtemp(prefix="dbuild-"))
    for package in sorted(set(packages_for(label))):
        link = root / package
        if not link.exists():
            link.symlink_to(DEPOT / package)
    return root


def run_test(label):
    package, target = resolve(label)
    if target["kind"] != "py_test":
        raise SystemExit(f"{label} is not a py_test")
    root = declared_root(label)
    try:
        completed = subprocess.run(
            # `--import-mode=importlib` is load-bearing. Packages carry an
            # `__init__.py`, so pytest's default mode walks up past them looking
            # for a directory without one, finds the depot root, and puts *that*
            # on sys.path — which makes every package importable and the
            # declaration rule decorative. importlib mode imports the test
            # without touching sys.path, so PYTHONPATH decides, which is the
            # whole point.
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "--import-mode=importlib", *target["srcs"]],
            cwd=str(DEPOT / package),
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": str(root)},
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
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
            packages_for(label)
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


def module_name(package_name: str, module: str) -> str:
    """Where a package's module lives on disk.

    A package's own module becomes ``__init__.py``. Writing it as
    ``config/config.py`` made `config` look like a package containing a module,
    and agents repeatedly wrote `from config.config import merge` — which is
    wrong, because only the package's *own* directory was on the path. Stating
    the convention in the instruction reduced it and did not stop it: the layout
    says one thing and prose says another, and the layout wins.

    As `__init__.py` there is nothing to be wrong about. `from config import
    merge` is the only reading, and it is the ordinary one.
    """
    return "__init__.py" if module == f"{package_name}.py" else module


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


def verifier(
    task: Task,
    source_roots: list[str],
    entry_source: str,
    test_source: str,
    extra_gate: str = "",
) -> str:
    """The acceptance check, identical in every variant.

    Deliberately not the agent's own test: a task that graded an agent by the
    test it was told to edit would be grading its willingness to write an
    assertion. This imports the result and checks the behaviour.
    """
    body = (
        task.acceptance.replace("SOURCE_ROOTS", json.dumps(source_roots))
        .replace("ENTRY_SOURCE", json.dumps(entry_source))
        .replace("TEST_SOURCE", json.dumps(test_source))
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


GRADER_TEMPLATE = '''#!/usr/bin/env python3
"""Grader for Study B's {slug}, in whichever toolchain it was solved.

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

SPEC = {{
    "task": "{slug}",
    "axes": ["acceptance", "discipline"],
}}

# Where the container's /workspace was collected to. The verifier copies it, so
# the grader sees the work product without needing the container to still exist.
WORKSPACE = "workspace"
ENTRY_PACKAGE = "{entry_module}"

# **The layout is discovered, not assumed.** One grader serves all three
# toolchains: `src/report/report.py`, `kelvra/report/report.py` and
# `depot/report/report.py` are the same work in three arrangements, and a grader
# pinned to one of them would score the other two as "never written" — which is
# the failure gate G2 found in the smoke study, arriving from the other side.
#
# It also means the study pins **one** grader per task rather than one per
# substrate, so the instrument is provably identical across the arms it compares.

CHECK = {check!r}


def unscored(reason: str) -> dict:
    """A crashed check leaves an axis unscored, never zero (execution-plan §0.6)."""
    return {{"score": None, "passed": False, "summary": reason}}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {{argv[0]}} <workdir>", file=sys.stderr)
        return 2
    workdir = Path(argv[1]).resolve()
    root = workdir / WORKSPACE
    axes: dict[str, dict] = {{}}

    if not root.is_dir():
        reason = f"nothing was collected at {{root}}"
        axes = {{"acceptance": unscored(reason), "discipline": unscored(reason)}}
        json.dump({{"spec": SPEC, "axes": axes}}, sys.stdout, sort_keys=True)
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
        reason = f"no {{ENTRY_PACKAGE}}/__init__.py anywhere under {{root}}"
        axes = {{"acceptance": unscored(reason), "discipline": unscored(reason)}}
        json.dump({{"spec": SPEC, "axes": axes}}, sys.stdout, sort_keys=True)
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
        {{
            str(path.parent.parent)
            for path in root.rglob("__init__.py")
            if path.parent.parent != path.parent
        }}
        | {{str(root)}}
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

    axes["acceptance"] = {{
        "score": 1.0 if passed else 0.0,
        "passed": passed,
        "summary": "behaviour is correct" if passed else output.splitlines()[-1][:200]
        if output
        else "the check failed and said nothing",
    }}
    # Discipline is the subset of the check that is about *how* — the shortcuts
    # each task forbids. It is only meaningful once behaviour is right; before
    # that it is unscored rather than failed, because a trial that never worked
    # has not demonstrated anything about its method.
    if passed:
        axes["discipline"] = {{
            "score": 1.0,
            "passed": True,
            "summary": "no forbidden shortcut detected",
        }}
    else:
        forbidden = any(
            marker in output
            for marker in ("only the caller", "was changed rather than", "does its own",
                           "reimplement", "sorts values itself", "call sites pass")
        )
        axes["discipline"] = (
            {{"score": 0.0, "passed": False, "summary": output.splitlines()[-1][:200]}}
            if forbidden
            else unscored("behaviour is wrong, so method says nothing yet")
        )

    json.dump({{"spec": SPEC, "axes": axes}}, sys.stdout, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def write_grader(task: Task) -> Path:
    """One grader per task, serving every substrate.

    Identical instrument across the arms being compared, which is what makes the
    comparison a comparison — see `digest_bands` and execution-plan §0.6.
    """
    body = GRADER_TEMPLATE.format(
        slug=task.slug,
        entry_module=task.entry,
        check=task.acceptance.replace("SOURCE_ROOTS", "__ROOTS__")
        .replace("ENTRY_SOURCE", "__ENTRY__")
        .replace("TEST_SOURCE", "__TEST__"),
    )
    path = STUDY / "graders" / f"{task.slug}.py"
    write(path, body)
    return path


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


def whole_file_oracle(task: Task, layout: dict[str, str]) -> str:
    """An oracle that writes files outright.

    For a task whose starting point is a stub that raises, there is nothing to
    substitute into, and an oracle expressed as edits would be a fiction about
    how the work is done.
    """
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "python3 - <<'ORACLE'",
        "from pathlib import Path",
    ]
    for key, body in task.oracle_files.items():
        target = layout.get(key)
        if target is None:
            raise SystemExit(f"{task.slug}: no place for oracle file {key!r} in this substrate")
        lines.append(f"p = Path({target!r})")
        lines.append("p.parent.mkdir(parents=True, exist_ok=True)")
        lines.append(f"p.write_text({body!r})")
    lines.append("ORACLE")
    return "\n".join(lines) + "\n"


def oracle_edits(
    task: Task, entry_source: str, test_path: str, roots: list[str]
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
    if task.slug == "fix-spread":
        # The defect is in the library, which is a different file from the one
        # the failure is reported in — that is the task.
        stats_source = f"{roots[0]}/stats/__init__.py"
        return [
            (
                stats_source,
                [("(max(values) - min(values)) // 2", "(max(values) - min(values)) / 2")],
            )
        ]
    if task.slug == "strict-mode":
        stats_source = f"{roots[0]}/stats/__init__.py"
        return [
            (
                stats_source,
                [
                    (
                        "def mean(values):\n    if not values:\n"
                        '        raise ValueError("mean of no values")\n'
                        "    return sum(values) / len(values)",
                        "def mean(values, *, strict=False):\n"
                        "    if strict and any(value is None for value in values):\n"
                        '        raise ValueError("mean of a series holding None")\n'
                        "    kept = [value for value in values if value is not None]\n"
                        "    if not kept:\n"
                        '        raise ValueError("mean of no values")\n'
                        "    return sum(kept) / len(kept)",
                    )
                ],
            ),
            (
                entry_source,
                [
                    ("mean(clean)", "mean(clean, strict=True)"),
                    (
                        "mean([mean(one) for one in series])",
                        "mean([mean(one, strict=True) for one in series], strict=True)",
                    ),
                ],
            ),
            (
                test_path,
                [
                    (
                        'assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}',
                        'assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}\n\n\n'
                        "def test_mean_is_strict_when_asked():\n"
                        "    import pytest\n\n"
                        "    from stats import mean\n\n"
                        "    with pytest.raises(ValueError):\n"
                        "        mean([1, None], strict=True)",
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
            write(env / words["src"] / package.name / module_name(package.name, name), body)
    for name, body in task.tests.items():
        write(env / words["tests"] / name, body)

    # Only the packages the entry already needs are on the path. A task that
    # requires reaching a *new* one is a task about this toolchain's way of
    # making a package reachable, which is the contrast the study draws.
    # The source root, not each package directory: packages are packages now.
    # A task that requires reaching a *new* package is still about the
    # toolchain's way of making one reachable — here that is the source root
    # being on the path at all, and in the depot it is a declared dependency.
    path = words["src"]
    runner_file = "Makefile" if words["runner"] == "make" else f"{words['runner']}file"
    write(
        env / runner_file,
        # `--import-mode=importlib` for the same reason the depot needs it: with
        # packages carrying an `__init__.py`, pytest's default mode rewrites
        # sys.path on its own, and a suite that passes for a reason the project
        # did not arrange is a suite that will surprise somebody later.
        f"{words['verb']}:\n\tPYTHONPATH={path} python3 -m pytest -q "
        f"--import-mode=importlib {words['tests']}\n",
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

    roots = [f"/workspace/{words['src']}"]
    entry_source = f"/workspace/{words['src']}/{task.entry}/__init__.py"
    test_path = f"/workspace/{words['tests']}/{next(iter(task.tests))}"
    write(
        root / "tests" / "test.sh",
        verifier(task, roots, entry_source, test_path),
        executable=True,
    )
    if task.oracle_files:
        layout = {
            f"{p.name}/{m}": f"/workspace/{words['src']}/{p.name}/{module_name(p.name, m)}"
            for p in task.packages
            for m in p.modules
        }
        layout.update(
            {f"tests/{name}": f"/workspace/{words['tests']}/{name}" for name in task.tests}
        )
        body = whole_file_oracle(task, layout)
    else:
        body = solution(oracle_edits(task, entry_source, test_path, roots))
    write(root / "solution" / "solve.sh", body, executable=True)
    write(root / "task.toml", TASK_TOML.format(difficulty=task.difficulty))
    write_grader(task)


def build_proprietary(task: Task, root: Path) -> None:
    env = root / "environment"
    for package in task.packages:
        for name, body in package.modules.items():
            write(env / "depot" / package.name / module_name(package.name, name), body)
        deps = "".join(f'        "//depot/{need}:{need}",\n' for need in package.needs)
        srcs = "".join(
            f'        "{module_name(package.name, name)}",\n' for name in package.modules
        )
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

    roots = ["/workspace/depot"]
    entry_source = f"/workspace/depot/{task.entry}/__init__.py"
    test_path = f"/workspace/depot/{task.entry}/{next(iter(task.tests))}"
    # The depot's own gate, on top of the shared acceptance check: a change that
    # works but leaves the build graph undeclared has not landed here.
    gate = 'if [ "$status" -eq 0 ]; then dbuild presubmit >&2 || status=1; fi\n'
    write(
        root / "tests" / "test.sh",
        verifier(task, roots, entry_source, test_path, gate),
        executable=True,
    )

    if task.oracle_files:
        layout = {
            f"{p.name}/{m}": f"/workspace/depot/{p.name}/{module_name(p.name, m)}"
            for p in task.packages
            for m in p.modules
        }
        # The depot keeps a package's tests beside it rather than in one tree.
        layout.update(
            {f"tests/{name}": f"/workspace/depot/{task.entry}/{name}" for name in task.tests}
        )
        body = whole_file_oracle(task, layout)
    else:
        body = solution(oracle_edits(task, entry_source, test_path, roots))
    # Every package the entry does not already declare has to be declared, or
    # presubmit rejects a change that is otherwise correct. That declaration *is*
    # the toolchain work this arm exists to require, so the oracle has to do it —
    # and generically, because a bespoke BUILD edit per task is easy to forget,
    # and forgetting it turns a shared task into one only this arm fails.
    entry_pkg = next(package for package in task.packages if package.name == task.entry)
    undeclared = [
        package.name
        for package in task.packages
        if package.name not in (task.entry, *entry_pkg.needs)
    ]
    if undeclared:
        declarations = "".join(f'        "//depot/{name}:{name}",\n' for name in undeclared)
        body += (
            "python3 - <<'DEPS'\n"
            "from pathlib import Path\n"
            f"b = Path('/workspace/depot/{task.entry}/BUILD')\n"
            "body = b.read_text()\n"
            "marker = '    deps = [\\n'\n"
            f"body = body.replace(marker, marker + {declarations!r}, 1)\n"
            "b.write_text(body)\n"
            "DEPS\n"
        )
    write(root / "solution" / "solve.sh", body, executable=True)
    write(root / "task.toml", TASK_TOML.format(difficulty=task.difficulty))
    write_grader(task)


def main() -> int:
    if TASK_ROOT.exists():
        shutil.rmtree(TASK_ROOT)
    if (STUDY / "graders").exists():
        shutil.rmtree(STUDY / "graders")
    built: list[str] = []
    for task in TASKS:
        build_flat(task, TASK_ROOT / f"{task.slug}-oss", OSS_WORDS)
        for twin, words in TWIN_WORDS.items():
            build_flat(task, TASK_ROOT / f"{task.slug}-{twin}", words)
        build_proprietary(task, TASK_ROOT / f"{task.slug}-proprietary")
        built.extend(
            f"{task.slug}-{kind}" for kind in ("oss", *TWIN_WORDS, "proprietary")
        )
    manifest = {
        "tasks": [task.slug for task in TASKS],
        "variants": sorted(built),
        # The seeds as well as the words: the words are recomputable from the
        # seeds by anyone with this repository, and a recorded output nobody can
        # re-derive is the thing this study keeps being bitten by.
        "twin_seeds": TWIN_SEEDS,
        "twin_words": TWIN_WORDS,
    }
    write(STUDY / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
