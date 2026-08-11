"""Study B's tasks built for headroom.

The 2026-08-10 pilot found every arm solving every task twice: pooled
within-cell sd 0.0, no outcome signal, and nothing for a contrast to be divided
by. A study whose outcome axis never varies cannot answer anything, however many
trials it runs.

These are built the other way round. Each states rules that read simply and
interact badly, so a *correct-looking* first attempt is the expected outcome and
the acceptance check is where the edges live — trailing partial windows, lists
that replace rather than concatenate, an override of `None` that erases, ties
that must break deterministically. Each also puts the function in a package the
entry module does not yet reach, so the toolchain work is still in play.

**Difficulty here is measured, not asserted.** A task belongs in the study only
if this model fails it often enough for the axis to vary; `calibrate.py` runs
each on the `oss` substrate and reports the pass rate. Anything at 0/n or n/n is
no more useful than `add-median` was.

Oracles are whole files rather than substitutions: these stubs raise
`NotImplementedError`, so there is nothing to substitute into.
"""

from __future__ import annotations

from tasks import Package, Task

GRAPH_STUB = '''"""Dependency resolution."""


class Cycle(Exception):
    """Raised when a graph cannot be ordered. `members` holds who is involved."""

    def __init__(self, members):
        super().__init__(f"cycle among {sorted(members)}")
        self.members = sorted(members)


def resolve(graph):
    """Return the names of `graph` in dependency order."""
    raise NotImplementedError
'''

GRAPH_SOLVED = '''"""Dependency resolution."""


class Cycle(Exception):
    """Raised when a graph cannot be ordered. `members` holds who is involved."""

    def __init__(self, members):
        super().__init__(f"cycle among {sorted(members)}")
        self.members = sorted(members)


def resolve(graph):
    """Return the names of `graph` in dependency order."""
    names = set(graph)
    for needs in graph.values():
        names.update(needs)
    remaining = {name: set(graph.get(name, ())) for name in names}

    ordered = []
    while remaining:
        ready = sorted(name for name, needs in remaining.items() if not needs)
        if not ready:
            raise Cycle(remaining)
        for name in ready:
            ordered.append(name)
            del remaining[name]
        for needs in remaining.values():
            needs.difference_update(ready)
    return ordered
'''

TOPO_ORDER = Task(
    slug="topo-order",
    difficulty="hard",
    notes=(
        "Subtle algorithm plus cross-package work. A depth-first solution gets "
        "the common cases and misses deterministic ordering; a self-edge is a "
        "cycle; and the exception has to name the members rather than merely "
        "report that there was one."
    ),
    problem="""\
Builds have to run in dependency order. Implement `resolve` in the **graph**
package and use it from `plan_build`.

`resolve(graph)` takes a mapping of name to the list of names it depends on, and
returns a list of names in an order where every dependency comes before the
thing that needs it.

Rules, all of which are tested:

- Among names that are equally ready to run, the result must be **alphabetical**,
  so the same graph always produces the same order.
- A name that depends on itself is a cycle.
- A cycle must raise `graph.Cycle`, and the exception's `members` attribute must
  hold exactly the names taking part in it, sorted.
- A name that appears only as a dependency is still part of the result.
- An empty graph returns an empty list.

Then make `plan_build` in the reporting package return `resolve`'s answer.
`graph` is part of this project but the reporting package does not yet reach it.

Extend the tests, and make the suite pass.
""",
    packages=(
        Package(name="graph", modules={"graph.py": GRAPH_STUB}),
        Package(
            name="report",
            modules={
                "report.py": '''"""Build planning."""


def plan_build(graph):
    """The order this build should run in."""
    raise NotImplementedError
'''
            },
        ),
    ),
    entry="report",
    tests={
        "test_report.py": """from report import plan_build


def test_plan_build_orders_a_simple_chain():
    assert plan_build({"a": ["b"], "b": []}) == ["b", "a"]
"""
    },
    oracle_files={
        "graph/graph.py": GRAPH_SOLVED,
        "report/report.py": '''"""Build planning."""

from graph import resolve


def plan_build(graph):
    """The order this build should run in."""
    return resolve(graph)
''',
        "tests/test_report.py": """import pytest

from graph import Cycle
from report import plan_build


def test_plan_build_orders_a_simple_chain():
    assert plan_build({"a": ["b"], "b": []}) == ["b", "a"]


def test_plan_build_breaks_ties_alphabetically():
    assert plan_build({"b": [], "a": [], "c": []}) == ["a", "b", "c"]


def test_plan_build_rejects_a_cycle():
    with pytest.raises(Cycle) as raised:
        plan_build({"a": ["b"], "b": ["a"]})
    assert raised.value.members == ["a", "b"]
""",
    },
    acceptance="""import sys
for root in SOURCE_ROOTS:
    sys.path.insert(0, root)
try:
    import graph
    from report import plan_build
except Exception as failure:
    print(f"FAIL: cannot import: {failure}", file=sys.stderr)
    raise SystemExit(1)


def check(name, got, expected):
    if got != expected:
        print(f"FAIL: {name}: got {got!r}, expected {expected!r}", file=sys.stderr)
        raise SystemExit(1)


check("empty", plan_build({}), [])
check("chain", plan_build({"a": ["b"], "b": []}), ["b", "a"])
check("ties", plan_build({"b": [], "a": [], "c": []}), ["a", "b", "c"])
check("diamond", plan_build({"d": ["b", "c"], "b": ["a"], "c": ["a"], "a": []}),
      ["a", "b", "c", "d"])
check("implicit", plan_build({"a": ["b"]}), ["b", "a"])
check("ready-first", plan_build({"z": [], "y": ["z"], "x": []}), ["x", "z", "y"])

for name, bad, expected in (
    ("self-edge", {"a": ["a"]}, ["a"]),
    ("two-cycle", {"a": ["b"], "b": ["a"]}, ["a", "b"]),
    ("cycle-with-tail", {"a": ["b"], "b": ["c"], "c": ["a"], "d": ["a"]}, ["a", "b", "c", "d"]),
):
    try:
        plan_build(bad)
    except graph.Cycle as cycle:
        if list(cycle.members) != expected:
            print(f"FAIL: {name}: members {list(cycle.members)!r}, expected {expected!r}",
                  file=sys.stderr)
            raise SystemExit(1)
    except Exception as other:
        print(f"FAIL: {name} raised {type(other).__name__}, not graph.Cycle", file=sys.stderr)
        raise SystemExit(1)
    else:
        print(f"FAIL: {name} was accepted", file=sys.stderr)
        raise SystemExit(1)

source = open(ENTRY_SOURCE).read()
if "resolve" not in source:
    print("FAIL: the entry module does not use resolve", file=sys.stderr)
    raise SystemExit(1)

print("PASS")
""",
)


WINDOW_STATS = Task(
    slug="window-stats",
    difficulty="hard",
    notes=(
        "Calibrated at 3/3 on 2026-08-10, so a rule was added that interacts "
        "with the others rather than sitting beside them: a gap removes a window "
        "without moving the ones after it, which rules out the natural "
        "implementation of filtering the series first."
    ),
    problem="""\
Readings arrive in a stream and have to be summarised over a sliding window.

Implement `windows(values, size, step)` in the **window** package. It returns a
list of lists: each is a consecutive run of `size` values, advancing by `step`.

Rules, all tested:

- Only **complete** windows are returned; a trailing partial window is dropped.
- `step` may be smaller than `size`, so windows overlap.
- `step` may be larger than `size`, so values are skipped.
- A `size` larger than the series returns an empty list.
- `size` or `step` below 1 raises `ValueError`.
- Readings of `None` are **gaps**. A window containing one is not a window: it is
  skipped, and it does not shift the ones after it — positions are decided by
  `size` and `step` alone, before gaps are considered.

Then make `rolling_mean(values, size, step)` in the reporting package return the
mean of each window, using `windows` and the existing `mean`. `window` is part
of this project but the reporting package does not yet reach it.

Extend the tests, and make the suite pass.
""",
    packages=(
        Package(
            name="stats",
            modules={
                "stats.py": '''"""Statistics helpers."""


def mean(values):
    if not values:
        raise ValueError("mean of no values")
    return sum(values) / len(values)
'''
            },
        ),
        Package(
            name="window",
            modules={
                "window.py": '''"""Sliding windows over a series."""


def windows(values, size, step):
    """Consecutive runs of `size` values, advancing by `step`."""
    raise NotImplementedError
'''
            },
        ),
        Package(
            name="report",
            needs=("stats",),
            modules={
                "report.py": '''"""Rolling summaries."""

from stats import mean


def rolling_mean(values, size, step):
    """The mean of each complete window."""
    raise NotImplementedError
'''
            },
        ),
    ),
    entry="report",
    tests={
        "test_report.py": """from report import rolling_mean


def test_rolling_mean_over_adjacent_windows():
    assert rolling_mean([1, 2, 3, 4], 2, 2) == [1.5, 3.5]
"""
    },
    oracle_files={
        "window/window.py": '''"""Sliding windows over a series."""


def windows(values, size, step):
    """Consecutive runs of `size` values, advancing by `step`."""
    if size < 1 or step < 1:
        raise ValueError("size and step must both be at least 1")
    values = list(values)
    return [
        window
        for start in range(0, len(values) - size + 1, step)
        # Positions come from size and step alone; a gap removes a window
        # without moving the ones after it.
        if None not in (window := values[start : start + size])
    ]
''',
        "report/report.py": '''"""Rolling summaries."""

from stats import mean
from window import windows


def rolling_mean(values, size, step):
    """The mean of each complete window."""
    return [mean(one) for one in windows(values, size, step)]
''',
        "tests/test_report.py": """import pytest

from report import rolling_mean
from window import windows


def test_rolling_mean_over_adjacent_windows():
    assert rolling_mean([1, 2, 3, 4], 2, 2) == [1.5, 3.5]


def test_a_trailing_partial_window_is_dropped():
    assert windows([1, 2, 3, 4, 5], 2, 2) == [[1, 2], [3, 4]]


def test_a_bad_size_is_refused():
    with pytest.raises(ValueError):
        windows([1, 2, 3], 0, 1)


def test_a_gap_removes_a_window_without_shifting_the_rest():
    assert windows([1, None, 3, 4], 2, 2) == [[3, 4]]
""",
    },
    acceptance="""import sys
for root in SOURCE_ROOTS:
    sys.path.insert(0, root)
try:
    from report import rolling_mean
    from window import windows
except Exception as failure:
    print(f"FAIL: cannot import: {failure}", file=sys.stderr)
    raise SystemExit(1)


def check(name, got, expected):
    if got != expected:
        print(f"FAIL: {name}: got {got!r}, expected {expected!r}", file=sys.stderr)
        raise SystemExit(1)


check("adjacent", windows([1, 2, 3, 4], 2, 2), [[1, 2], [3, 4]])
check("partial-dropped", windows([1, 2, 3, 4, 5], 2, 2), [[1, 2], [3, 4]])
check("overlapping", windows([1, 2, 3, 4], 2, 1), [[1, 2], [2, 3], [3, 4]])
check("skipping", windows([1, 2, 3, 4, 5, 6], 2, 3), [[1, 2], [4, 5]])
check("size-exceeds", windows([1, 2], 3, 1), [])
check("exact-fit", windows([1, 2, 3], 3, 1), [[1, 2, 3]])
check("empty", windows([], 1, 1), [])
# Gaps remove a window without shifting the rest.
check("gap-skips", windows([1, None, 3, 4], 2, 2), [[3, 4]])
check("gap-overlap", windows([1, 2, None, 4, 5], 2, 1), [[1, 2], [4, 5]])
check("gap-all", windows([None, None], 2, 1), [])
check("gap-does-not-shift", windows([1, None, 3, 4, 5, 6], 2, 2), [[3, 4], [5, 6]])

for size, step in ((0, 1), (1, 0), (-1, 1), (1, -2)):
    try:
        windows([1, 2, 3], size, step)
    except ValueError:
        pass
    except Exception as other:
        print(f"FAIL: windows(size={size}, step={step}) raised {type(other).__name__}",
              file=sys.stderr)
        raise SystemExit(1)
    else:
        print(f"FAIL: windows(size={size}, step={step}) was accepted", file=sys.stderr)
        raise SystemExit(1)

check("rolling-adjacent", rolling_mean([1, 2, 3, 4], 2, 2), [1.5, 3.5])
check("rolling-overlap", rolling_mean([1, 2, 3, 4], 2, 1), [1.5, 2.5, 3.5])
check("rolling-partial", rolling_mean([1, 2, 3, 4, 5], 2, 2), [1.5, 3.5])
check("rolling-none", rolling_mean([1], 2, 1), [])
check("rolling-gap", rolling_mean([1, None, 3, 4], 2, 2), [3.5])

source = open(ENTRY_SOURCE).read()
if "windows" not in source:
    print("FAIL: the entry module does not use windows", file=sys.stderr)
    raise SystemExit(1)

print("PASS")
""",
)


MERGE_CONFIG = Task(
    slug="merge-config",
    difficulty="hard",
    notes=(
        "Three rules that read simply and interact badly: lists replace rather "
        "than concatenate, an override of None erases, and recursion applies "
        "only when both sides are mappings. Most first attempts miss one."
    ),
    problem="""\
Configuration comes from several layers and has to be merged.

Implement `merge(base, override)` in the **config** package. It returns a new
mapping and must not modify either argument.

Rules, all tested:

- A key in `override` wins.
- When **both** values are mappings, merge them recursively.
- When either value is not a mapping, the override's value replaces the base's
  outright — **lists replace, they do not concatenate**.
- An override value of `None` **removes** the key from the result.
- Keys only in `base` survive untouched.

Then make `effective(layers)` in the reporting package fold a list of layers
left to right with `merge`, so later layers win. `config` is part of this project
but the reporting package does not yet reach it.

Extend the tests, and make the suite pass.
""",
    packages=(
        Package(
            name="config",
            modules={
                "config.py": '''"""Layered configuration."""


def merge(base, override):
    """Merge `override` onto `base`, returning a new mapping."""
    raise NotImplementedError
'''
            },
        ),
        Package(
            name="report",
            modules={
                "report.py": '''"""Effective configuration."""


def effective(layers):
    """Fold `layers` left to right so later layers win."""
    raise NotImplementedError
'''
            },
        ),
    ),
    entry="report",
    tests={
        "test_report.py": """from report import effective


def test_effective_prefers_the_later_layer():
    assert effective([{"a": 1}, {"a": 2}]) == {"a": 2}
"""
    },
    oracle_files={
        "config/config.py": '''"""Layered configuration."""


def merge(base, override):
    """Merge `override` onto `base`, returning a new mapping."""
    result = dict(base)
    for key, value in override.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result
''',
        "report/report.py": '''"""Effective configuration."""

from config import merge


def effective(layers):
    """Fold `layers` left to right so later layers win."""
    result = {}
    for layer in layers:
        result = merge(result, layer)
    return result
''',
        "tests/test_report.py": """from config import merge
from report import effective


def test_effective_prefers_the_later_layer():
    assert effective([{"a": 1}, {"a": 2}]) == {"a": 2}


def test_lists_replace_rather_than_concatenate():
    assert merge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}


def test_none_erases_a_key():
    assert merge({"a": 1, "b": 2}, {"a": None}) == {"b": 2}
""",
    },
    acceptance="""import sys
for root in SOURCE_ROOTS:
    sys.path.insert(0, root)
try:
    from config import merge
    from report import effective
except Exception as failure:
    print(f"FAIL: cannot import: {failure}", file=sys.stderr)
    raise SystemExit(1)


def check(name, got, expected):
    if got != expected:
        print(f"FAIL: {name}: got {got!r}, expected {expected!r}", file=sys.stderr)
        raise SystemExit(1)


check("override-wins", merge({"a": 1}, {"a": 2}), {"a": 2})
check("base-survives", merge({"a": 1, "b": 2}, {"a": 3}), {"a": 3, "b": 2})
check("nested", merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 3}}), {"a": {"x": 1, "y": 3}})
check("lists-replace", merge({"a": [1, 2]}, {"a": [3]}), {"a": [3]})
check("scalar-over-map", merge({"a": {"x": 1}}, {"a": 5}), {"a": 5})
check("map-over-scalar", merge({"a": 5}, {"a": {"x": 1}}), {"a": {"x": 1}})
check("none-erases", merge({"a": 1, "b": 2}, {"a": None}), {"b": 2})
check("none-erases-nested", merge({"a": {"x": 1, "y": 2}}, {"a": {"x": None}}), {"a": {"y": 2}})
check("none-on-absent", merge({"a": 1}, {"b": None}), {"a": 1})
check("deep", merge({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"c": 9}}}),
      {"a": {"b": {"c": 9, "d": 2}}})

base = {"a": {"x": 1}}
override = {"a": {"y": 2}}
merge(base, override)
check("base-unmodified", base, {"a": {"x": 1}})
check("override-unmodified", override, {"a": {"y": 2}})

check("effective-two", effective([{"a": 1}, {"a": 2}]), {"a": 2})
check("effective-three", effective([{"a": 1, "b": 1}, {"b": 2}, {"c": 3}]),
      {"a": 1, "b": 2, "c": 3})
check("effective-empty", effective([]), {})
check("effective-nested", effective([{"a": {"x": 1}}, {"a": {"y": 2}}]), {"a": {"x": 1, "y": 2}})

source = open(ENTRY_SOURCE).read()
if "merge" not in source:
    print("FAIL: the entry module does not use merge", file=sys.stderr)
    raise SystemExit(1)

print("PASS")
""",
)

HARD_TASKS: tuple[Task, ...] = (TOPO_ORDER, WINDOW_STATS, MERGE_CONFIG)
