#!/usr/bin/env python3
"""Generate Study A's six task directories and their graders.

Each task is a small, closed-world Python exercise with a deterministic answer:
Study A varies *the toolset*, so the tasks have to be things every arm can do,
or the study measures task difficulty instead.

Run it from the repository root after editing a task:

    python3 studies/a-tool-familiarity/generate.py
    python3 studies/a-tool-familiarity/generate_study.py

The second step re-pins the grader hashes in study.yaml. Editing a grader
without re-pinning is caught by tests/test_study_a.py rather than discovered
mid-study.
"""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DOCKERFILE = """FROM python:3.12-slim

WORKDIR /app

# No network at trial time: an agent that can pip-install its way out is an
# agent solving a different task than the one the arm was given.
ENV PIP_NO_INDEX=1
"""

TASK_TOML = """version = "1.0"

[metadata]
author_name = "duva-bench"
difficulty = "{difficulty}"
tags = ["study-a", "python", "stdlib"]

[agent]
timeout_sec = 600

[verifier]
timeout_sec = 90
"""

TASKS: dict[str, dict[str, str]] = {}


TASKS["config-merge"] = {
    "difficulty": "easy",
    "instruction": """Write `/app/merge.py` exposing:

```python
def merge(base: dict, override: dict) -> dict: ...
```

It deep-merges `override` into `base` and returns a **new** dict, leaving both
arguments unmodified.

- Where both sides hold a dict, merge recursively.
- Where they disagree in type, or either side is not a dict, `override` wins.
- A value of `None` in `override` **deletes** the key from the result.
- Lists are replaced, never concatenated.

Standard library only.
""",
    "solution": """cat > /app/merge.py <<'PY'
def merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result
PY
""",
    "module": "merge",
    "probe": """
from merge import merge

base = {"a": 1, "n": {"x": 1, "y": 2}, "l": [1, 2], "gone": 3}
override = {"a": 2, "n": {"y": 9, "z": 3}, "l": [9], "gone": None}
frozen = {"a": 1, "n": {"x": 1, "y": 2}, "l": [1, 2], "gone": 3}

out = merge(base, override)
results["deep-merge"] = out == {"a": 2, "n": {"x": 1, "y": 9, "z": 3}, "l": [9]}
results["none-deletes"] = "gone" not in out
results["lists-replaced"] = out.get("l") == [9]
results["inputs-untouched"] = base == frozen
results["type-conflict"] = merge({"k": {"a": 1}}, {"k": 5}) == {"k": 5}
results["new-object"] = merge(base, {}) is not base
""",
    "axes": {
        "acceptance": ["deep-merge", "none-deletes", "lists-replaced"],
        "purity": ["inputs-untouched", "new-object", "type-conflict"],
    },
}


TASKS["semver-compare"] = {
    "difficulty": "medium",
    "instruction": """Write `/app/semver.py` exposing:

```python
def compare(left: str, right: str) -> int: ...
```

It returns `-1`, `0` or `1` for semantic versions, following semver 2.0 ordering:

- numeric identifiers compare numerically, so `1.0.10 > 1.0.9`
- a pre-release version is **lower** than the release it precedes: `1.0.0-rc.1 < 1.0.0`
- pre-release identifiers compare left to right; numeric ones are lower than
  alphanumeric ones
- build metadata (`+sha.1`) is ignored entirely

Raise `ValueError` on something that is not a version. Standard library only.
""",
    "solution": """cat > /app/semver.py <<'PY'
import re

PATTERN = re.compile(
    r"^(\\d+)\\.(\\d+)\\.(\\d+)(?:-([0-9A-Za-z.-]+))?(?:\\+[0-9A-Za-z.-]+)?$"
)


def _parse(text):
    matched = PATTERN.match(text.strip())
    if not matched:
        raise ValueError(f"not a semantic version: {text!r}")
    major, minor, patch, pre = matched.groups()
    return (int(major), int(minor), int(patch), pre)


def _pre_key(part):
    return (0, int(part), "") if part.isdigit() else (1, 0, part)


def compare(left, right):
    a = _parse(left)
    b = _parse(right)
    if a[:3] != b[:3]:
        return -1 if a[:3] < b[:3] else 1
    if a[3] == b[3]:
        return 0
    if a[3] is None:
        return 1
    if b[3] is None:
        return -1
    first = [_pre_key(p) for p in a[3].split(".")]
    second = [_pre_key(p) for p in b[3].split(".")]
    if first == second:
        return 0
    return -1 if first < second else 1
PY
""",
    "module": "semver",
    "probe": """
from semver import compare

results["numeric-identifiers"] = compare("1.0.10", "1.0.9") == 1
results["equality"] = compare("2.3.4", "2.3.4") == 0
results["prerelease-is-lower"] = compare("1.0.0-rc.1", "1.0.0") == -1
results["prerelease-ordering"] = compare("1.0.0-alpha.1", "1.0.0-alpha.2") == -1
results["numeric-before-alpha"] = compare("1.0.0-1", "1.0.0-alpha") == -1
results["build-ignored"] = compare("1.0.0+aaa", "1.0.0+bbb") == 0
try:
    compare("not-a-version", "1.0.0")
    results["rejects-nonsense"] = False
except ValueError:
    results["rejects-nonsense"] = True
except Exception:
    results["rejects-nonsense"] = False
""",
    "axes": {
        "acceptance": ["numeric-identifiers", "equality", "prerelease-is-lower"],
        "spec_edges": [
            "prerelease-ordering",
            "numeric-before-alpha",
            "build-ignored",
            "rejects-nonsense",
        ],
    },
}


TASKS["safe-path"] = {
    "difficulty": "medium",
    "instruction": """Write `/app/safepath.py` exposing:

```python
def resolve(root: str, candidate: str) -> str: ...
```

It joins `candidate` onto `root` and returns the absolute result, but **refuses
anything that would escape `root`**:

- `..` segments that climb above `root` raise `ValueError`
- an absolute `candidate` raises `ValueError`
- a symlink that points outside `root` raises `ValueError`
- `.` and interior `..` that stay inside are fine and are normalized away

Standard library only.
""",
    "solution": """cat > /app/safepath.py <<'PY'
import os


def resolve(root, candidate):
    if os.path.isabs(candidate):
        raise ValueError("candidate must be relative")
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(base, candidate))
    if target != base and not target.startswith(base + os.sep):
        raise ValueError(f"{candidate!r} escapes {root!r}")
    return target
PY
""",
    "module": "safepath",
    "probe": """
import os
import tempfile

from safepath import resolve

root = tempfile.mkdtemp()
os.makedirs(os.path.join(root, "inner"), exist_ok=True)
outside = tempfile.mkdtemp()
os.symlink(outside, os.path.join(root, "link"))


def refuses(candidate):
    try:
        resolve(root, candidate)
    except ValueError:
        return True
    except Exception:
        return False
    return False


results["joins-inside"] = resolve(root, "inner/file.txt") == os.path.join(
    os.path.realpath(root), "inner", "file.txt"
)
results["normalizes"] = resolve(root, "inner/../inner/./x") == os.path.join(
    os.path.realpath(root), "inner", "x"
)
results["refuses-climbing"] = refuses("../etc/passwd")
results["refuses-absolute"] = refuses("/etc/passwd")
results["refuses-symlink-escape"] = refuses("link/secret")
""",
    "axes": {
        "acceptance": ["joins-inside", "normalizes"],
        "containment": ["refuses-climbing", "refuses-absolute", "refuses-symlink-escape"],
    },
}


TASKS["csv-dedupe"] = {
    "difficulty": "easy",
    "instruction": """Write `/app/dedupe.py`, a command-line program:

```
python3 /app/dedupe.py <key-column> < input.csv > output.csv
```

It reads CSV on standard input and writes CSV on standard output, keeping the
**last** row for each value of the key column and preserving the order of first
appearance. The header row is preserved.

A missing key column exits 2 with a message on standard error and writes nothing
to standard output. Standard library only (`csv` is standard).
""",
    "solution": """cat > /app/dedupe.py <<'PY'
import csv
import sys

key = sys.argv[1]
reader = csv.DictReader(sys.stdin)
if reader.fieldnames is None or key not in reader.fieldnames:
    print(f"no column {key!r}", file=sys.stderr)
    raise SystemExit(2)

order = []
rows = {}
for row in reader:
    value = row[key]
    if value not in rows:
        order.append(value)
    rows[value] = row

writer = csv.DictWriter(sys.stdout, fieldnames=reader.fieldnames)
writer.writeheader()
for value in order:
    writer.writerow(rows[value])
PY
""",
    "module": None,
    "probe": """
import os
import subprocess
import sys

INPUT = "id,name\\n1,a\\n2,b\\n1,c\\n3,d\\n2,e\\n"


def run(args, text):
    return subprocess.run(
        [sys.executable, os.path.join(workdir, "dedupe.py"), *args],
        input=text,
        capture_output=True,
        text=True,
        timeout=20,
    )


done = run(["id"], INPUT)
results["keeps-last"] = done.stdout.replace("\\r\\n", "\\n") == "id,name\\n1,c\\n2,e\\n3,d\\n"
results["exit-zero"] = done.returncode == 0

missing = run(["nope"], INPUT)
results["missing-column-exits-2"] = missing.returncode == 2
results["missing-column-clean-stdout"] = missing.stdout == ""

empty = run(["id"], "id,name\\n")
results["header-only"] = empty.returncode == 0 and empty.stdout.strip() == "id,name"
""",
    "axes": {
        "acceptance": ["keeps-last", "exit-zero"],
        "robustness": ["missing-column-exits-2", "missing-column-clean-stdout", "header-only"],
    },
}


TASKS["rate-window"] = {
    "difficulty": "medium",
    "instruction": """Write `/app/window.py` exposing:

```python
class SlidingWindow:
    def __init__(self, limit: int, window_s: float): ...
    def allow(self, now: float) -> bool: ...
```

A sliding-window rate limiter. `allow(now)` returns True and records the call if
fewer than `limit` calls were recorded in the half-open interval
`(now - window_s, now]`; otherwise it returns False and records nothing.

Time is passed in rather than read, so the behaviour is testable without waiting.
Old entries must not accumulate: after a call, the window holds at most `limit`
timestamps. Standard library only.
""",
    "solution": """cat > /app/window.py <<'PY'
from collections import deque


class SlidingWindow:
    def __init__(self, limit, window_s):
        self.limit = limit
        self.window_s = window_s
        self._calls = deque()

    def allow(self, now):
        while self._calls and self._calls[0] <= now - self.window_s:
            self._calls.popleft()
        if len(self._calls) >= self.limit:
            return False
        self._calls.append(now)
        return True
PY
""",
    "module": "window",
    "probe": """
from window import SlidingWindow

limiter = SlidingWindow(limit=2, window_s=10.0)
results["allows-under-limit"] = limiter.allow(0.0) and limiter.allow(1.0)
results["blocks-at-limit"] = limiter.allow(2.0) is False
results["allows-after-window"] = limiter.allow(11.5) is True

# A blocked call must not be recorded, or the limiter would ratchet itself shut.
fresh = SlidingWindow(limit=1, window_s=10.0)
fresh.allow(0.0)
fresh.allow(1.0)
results["blocked-not-recorded"] = fresh.allow(10.5) is True

trimmed = SlidingWindow(limit=2, window_s=1.0)
for tick in range(200):
    trimmed.allow(tick * 1.0)
held = getattr(trimmed, "_calls", None)
results["window-is-trimmed"] = held is None or len(held) <= 2
""",
    "axes": {
        "acceptance": ["allows-under-limit", "blocks-at-limit", "allows-after-window"],
        "bookkeeping": ["blocked-not-recorded", "window-is-trimmed"],
    },
}


TASKS["log-summary"] = {
    "difficulty": "easy",
    "instruction": """Write `/app/summarize.py`, a command-line program that reads
log lines on standard input and writes one JSON object to standard output:

```
2026-08-07T10:00:00Z INFO  starting
2026-08-07T10:00:01Z ERROR db unreachable
```

The object holds:

- `counts`: number of lines per level, e.g. `{"INFO": 1, "ERROR": 1}`
- `first_error`: the message of the first `ERROR` line, or `null` if there is none
- `malformed`: how many lines did not match the format

Keys sorted, one trailing newline. A line is well-formed if it is an ISO-8601
timestamp, whitespace, an uppercase level, whitespace, and a message. Standard
library only.
""",
    "solution": """cat > /app/summarize.py <<'PY'
import json
import re
import sys

LINE = re.compile(r"^(\\S+)\\s+([A-Z]+)\\s+(.*)$")

counts = {}
first_error = None
malformed = 0

for raw in sys.stdin:
    line = raw.rstrip("\\n")
    if not line.strip():
        continue
    matched = LINE.match(line)
    if not matched:
        malformed += 1
        continue
    _, level, message = matched.groups()
    counts[level] = counts.get(level, 0) + 1
    if level == "ERROR" and first_error is None:
        first_error = message

json.dump(
    {"counts": counts, "first_error": first_error, "malformed": malformed},
    sys.stdout,
    sort_keys=True,
)
sys.stdout.write("\\n")
PY
""",
    "module": None,
    "probe": """
import json
import os
import subprocess
import sys

LOG = (
    "2026-08-07T10:00:00Z INFO starting\\n"
    "2026-08-07T10:00:01Z ERROR db unreachable\\n"
    "garbage line\\n"
    "2026-08-07T10:00:02Z ERROR second failure\\n"
    "2026-08-07T10:00:03Z INFO recovered\\n"
)


def run(text):
    return subprocess.run(
        [sys.executable, os.path.join(workdir, "summarize.py")],
        input=text,
        capture_output=True,
        text=True,
        timeout=20,
    )


done = run(LOG)
try:
    parsed = json.loads(done.stdout)
except Exception:
    parsed = {}

results["counts"] = parsed.get("counts") == {"INFO": 2, "ERROR": 2}
results["first-error"] = parsed.get("first_error") == "db unreachable"
results["malformed-counted"] = parsed.get("malformed") == 1

empty = run("")
try:
    parsed_empty = json.loads(empty.stdout)
except Exception:
    parsed_empty = {}
results["empty-input"] = parsed_empty == {"counts": {}, "first_error": None, "malformed": 0}
results["trailing-newline"] = done.stdout.endswith("\\n")
""",
    "axes": {
        "acceptance": ["counts", "first-error", "malformed-counted"],
        "output_shape": ["empty-input", "trailing-newline"],
    },
}


GRADER = '''#!/usr/bin/env python3
"""Grader for the {name} task (Study A).

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

SPEC = {spec!r}

TIMEOUT_SECONDS = 60

PROBE = r"""
import json
import sys

workdir = sys.argv[1]
sys.path.insert(0, workdir)
results = {{}}
try:
{probe}
except Exception as exc:
    results["probe_error"] = f"{{type(exc).__name__}}: {{exc}}"
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
        return {{"probe_error": completed.stderr.strip()[-400:] or "no output"}}
    parsed: dict[str, object] = json.loads(completed.stdout)
    return parsed


def axis(results: dict[str, object], names: list[str]) -> dict[str, object]:
    passed = [name for name in names if results.get(name) is True]
    failed = [name for name in names if name not in passed]
    summary = f"{{len(passed)}}/{{len(names)}} cases"
    if failed:
        summary += "; failed: " + ", ".join(failed)
    if "probe_error" in results:
        summary += f"; probe failed: {{results['probe_error']}}"
    return {{"score": len(passed) / len(names), "passed": not failed, "summary": summary}}


def grade(workdir: Path) -> dict[str, dict[str, object]]:
    expected = {required!r}
    if not (workdir / expected).exists():
        missing = {{"score": 0.0, "passed": False, "summary": f"{{expected}} was never written"}}
        return {{name: dict(missing) for name in SPEC["axes"]}}
    try:
        results = probe(workdir)
    except subprocess.TimeoutExpired:
        stalled = {{
            "score": 0.0,
            "passed": False,
            "summary": f"the candidate did not finish within {{TIMEOUT_SECONDS}}s",
        }}
        return {{name: dict(stalled) for name in SPEC["axes"]}}

    cases = SPEC["cases"]
    assert isinstance(cases, dict)
    return {{name: axis(results, list(names)) for name, names in cases.items()}}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {{argv[0]}} <workdir>", file=sys.stderr)
        return 2
    json.dump({{"spec": SPEC, "axes": grade(Path(argv[1]))}}, sys.stdout, sort_keys=True)
    sys.stdout.write("\\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


TEST_SH = """#!/usr/bin/env bash
# Harbor's verifier: did the environment end up in the state the task asked for.
# Deliberately separate from duva-bench's grader, which answers "how well" under
# a different ADP identity.
set -uo pipefail

test -f /app/{required} || {{ echo "FAIL: no /app/{required}" >&2; exit 1; }}

python3 - <<'PY'
import json
import sys

workdir = "/app"
sys.path.insert(0, workdir)
results = {{}}
try:
{probe}
except Exception as exc:
    print(f"FAIL: {{type(exc).__name__}}: {{exc}}", file=sys.stderr)
    raise SystemExit(1)

failed = [name for name, ok in results.items() if ok is not True]
if failed:
    print("FAIL: " + ", ".join(failed), file=sys.stderr)
    raise SystemExit(1)
print("PASS")
PY
"""


def indent(text: str, spaces: int = 4) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.strip().split("\n"))


def write(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> None:
    digests: dict[str, str] = {}

    for name, task in TASKS.items():
        directory = ROOT / "tasks" / name
        required = f"{task['module']}.py" if task["module"] else _entrypoint(task)

        write(directory / "instruction.md", task["instruction"])
        write(directory / "task.toml", TASK_TOML.format(difficulty=task["difficulty"]))
        write(directory / "environment" / "Dockerfile", DOCKERFILE)
        write(
            directory / "solution" / "solve.sh",
            "#!/usr/bin/env bash\n"
            "# Harbor's oracle: proves the task and its verifier agree, so a failing\n"
            "# arm is a failing arm rather than a broken task.\n"
            "set -euo pipefail\n\n" + task["solution"],
            executable=True,
        )
        write(
            directory / "tests" / "test.sh",
            TEST_SH.format(required=required, probe=indent(task["probe"])),
            executable=True,
        )

        spec = {
            "grader": name,
            "version": "1.0.0",
            "axes": sorted(task["axes"]),
            "cases": task["axes"],
        }
        grader = ROOT / "graders" / f"{name}.py"
        write(
            grader,
            GRADER.format(name=name, spec=spec, probe=indent(task["probe"]), required=required),
            executable=True,
        )
        digests[name] = hashlib.sha256(grader.read_bytes()).hexdigest()

    for name, digest in digests.items():
        print(f"{name} {digest}")


def _entrypoint(task: dict[str, str]) -> str:
    # Command-line tasks name their file in the instruction; take it from there.
    import re

    found = re.search(r"`/app/([\w.-]+\.py)`", task["instruction"])
    if not found:
        raise SystemExit("could not work out the entrypoint")
    return found.group(1)


if __name__ == "__main__":
    main()
