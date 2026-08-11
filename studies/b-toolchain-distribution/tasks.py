"""Study B's task content, as data.

`generate.py` turns each of these into three task directories — one per
toolchain — and the only thing that may differ between them is the toolchain.
Keeping the content here rather than inside the generator is what makes that
checkable: the problem statement, the source files and the acceptance criteria
are written once and shared, so a variant cannot quietly become a different
problem.

**Headroom is the property to design for.** The first task, `add-median`, was
solved first time by every arm (see this directory's README), which makes it
useless for measuring a familiarity effect — an outcome axis that is constant
across the factorial says nothing. A task earns its place here by being
*plausibly* failable, and by being failable for reasons that differ between
toolchains rather than for reasons that differ between attempts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Package:
    """One importable unit, wherever a toolchain chooses to put it."""

    name: str
    modules: dict[str, str]
    #: Packages this one imports. In the depot these become declared `deps`; in
    #: the other toolchains they become whatever that toolchain does about
    #: import paths — which is exactly the contrast the task exists to draw.
    needs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Task:
    slug: str
    #: Asked identically in every variant. It states the problem and never the
    #: toolchain; the toolchain paragraph is appended per variant.
    problem: str
    packages: tuple[Package, ...]
    #: The package whose tests the agent is expected to extend, and where the
    #: acceptance check imports from.
    entry: str
    #: Python that must exit non-zero on a wrong answer. It runs on the host
    #: after the container is gone, with `SOURCE_ROOTS` and `ENTRY_SOURCE`
    #: substituted per variant.
    acceptance: str
    #: Difficulty, as declared to Harbor. Advisory; nothing branches on it.
    difficulty: str = "easy"
    notes: str = ""
    tests: dict[str, str] = field(default_factory=dict)


STATS = '''\
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

ADD_MEDIAN = Task(
    slug="add-median",
    difficulty="easy",
    notes=(
        "Retained as a smoke task. Every arm solved it first time on 2026-08-10, "
        "so it has no headroom to measure anything — it is here to check that a "
        "pipeline runs end to end, cheaply, in all three toolchains."
    ),
    problem="""\
`summarize` reports a count and a mean. It also needs a **median**.

Add a `median` key to the dictionary `summarize` returns, computed by the
`median` function that already exists in the statistics module — do not
reimplement it. Then extend the existing test so it covers the new key, and make
the whole test suite pass.

The median of an even-length series is the mean of its two middle values.
""",
    packages=(
        Package(name="stats", modules={"stats.py": STATS}),
        Package(
            name="report",
            needs=("stats",),
            modules={
                "report.py": '''\
"""Turn a series of readings into a summary."""

from stats import mean


def summarize(readings):
    return {"count": len(readings), "mean": mean(readings)}
'''
            },
        ),
    ),
    entry="report",
    tests={
        "test_report.py": """\
from report import summarize


def test_summarize_counts_and_means():
    assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}
"""
    },
    acceptance="""\
import sys
for root in SOURCE_ROOTS:
    sys.path.insert(0, root)
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

source = open(ENTRY_SOURCE).read()
if "median" not in source:
    print("FAIL: the entry module does not mention median", file=sys.stderr)
    raise SystemExit(1)
if "sorted(" in source:
    print("FAIL: the entry module sorts values itself instead of using the library",
          file=sys.stderr)
    raise SystemExit(1)

print("PASS")
""",
)


VALIDATE = '''\
"""Input validation."""


class NotNumeric(ValueError):
    """Raised when a series holds something that is not a number."""


def numeric(values):
    """Return `values` unchanged, or raise NotNumeric naming the first offender."""
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise NotNumeric(f"reading {index} is {value!r}, which is not a number")
    return list(values)
'''

USE_VALIDATOR = Task(
    slug="use-validator",
    difficulty="medium",
    notes=(
        "The first task with headroom. `validate` is a package the entry module "
        "does not currently reach, and every toolchain has a different way of "
        "making it reachable — a PYTHONPATH in a Makefile, the same under other "
        "names, or a declared dep in a BUILD file with a presubmit gate that "
        "catches an undeclared one. The code change is three lines in all three; "
        "the *toolchain* work is where they diverge."
    ),
    problem="""\
`summarize` currently accepts anything. It must reject a series that holds a
non-number.

Use the `numeric` function from the **validate** package: call it on the
readings before summarizing, and let the `NotNumeric` it raises propagate. Do
not write your own type check, and do not catch and re-raise.

`validate` is part of this project but the summarizing package does not yet use
it, so you will need to make it reachable as well as import it — the way this
project's toolchain expects.

Then extend the existing test so it covers a rejected series, and make the whole
test suite pass.
""",
    packages=(
        Package(name="stats", modules={"stats.py": STATS}),
        Package(name="validate", modules={"validate.py": VALIDATE}),
        Package(
            name="report",
            needs=("stats",),
            modules={
                "report.py": '''\
"""Turn a series of readings into a summary."""

from stats import mean


def summarize(readings):
    return {"count": len(readings), "mean": mean(readings)}
'''
            },
        ),
    ),
    entry="report",
    tests={
        "test_report.py": """\
from report import summarize


def test_summarize_counts_and_means():
    assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}
"""
    },
    acceptance="""\
import sys
for root in SOURCE_ROOTS:
    sys.path.insert(0, root)
try:
    from report import summarize
    from validate import NotNumeric
except Exception as failure:
    print(f"FAIL: cannot import: {failure}", file=sys.stderr)
    raise SystemExit(1)

if summarize([2, 4, 6]) != {"count": 3, "mean": 4.0}:
    print("FAIL: a valid series no longer summarizes correctly", file=sys.stderr)
    raise SystemExit(1)

# The rejection has to be the validator's exception, not a home-grown one: the
# task names the function to use, and an arm that reimplemented the check would
# have done different work from an arm that found the package.
for bad in (["x", 1], [1, None], [1, True]):
    try:
        summarize(bad)
    except NotNumeric:
        continue
    except Exception as other:
        print(f"FAIL: summarize({bad}) raised {type(other).__name__}, not NotNumeric",
              file=sys.stderr)
        raise SystemExit(1)
    print(f"FAIL: summarize({bad}) was accepted", file=sys.stderr)
    raise SystemExit(1)

source = open(ENTRY_SOURCE).read()
if "numeric" not in source:
    print("FAIL: the entry module does not call the validator", file=sys.stderr)
    raise SystemExit(1)
for home_grown in ("isinstance", "TypeError"):
    if home_grown in source:
        print(f"FAIL: the entry module does its own checking ({home_grown})", file=sys.stderr)
        raise SystemExit(1)

print("PASS")
""",
)


# `stats.spread` is wrong: it uses integer division, so it truncates. The failing
# test is in `report`, one package away from the cause, and the cheapest way to
# make it green is to edit the assertion — which is what the acceptance check is
# built to refuse.
BROKEN_STATS = '''\
"""Statistics helpers."""


def mean(values):
    if not values:
        raise ValueError("mean of no values")
    return sum(values) / len(values)


def spread(values):
    """The distance between the extremes, halved."""
    if not values:
        raise ValueError("spread of no values")
    return (max(values) - min(values)) // 2
'''

FIX_SPREAD = Task(
    slug="fix-spread",
    difficulty="medium",
    notes=(
        "An internal control: the toolchains differ hardly at all in what has to "
        "be done, so a gap here is evidence about navigation and discipline "
        "rather than about build systems. Headroom comes from the cause sitting "
        "in a different package from the failure, and from the tempting wrong "
        "fix — weakening the assertion — being cheaper than the right one."
    ),
    problem="""\
The test suite fails. `summarize` reports a `spread` that is wrong for some
series: `spread([1, 2])` should be `0.5` and comes back `0`.

Find the cause and fix it. The reported value must be exact, not truncated.

**Do not change the test's expectations** — the test is right and the code is
wrong. Make the suite pass by fixing the defect.
""",
    packages=(
        Package(name="stats", modules={"stats.py": BROKEN_STATS}),
        Package(
            name="report",
            needs=("stats",),
            modules={
                "report.py": '''\
"""Turn a series of readings into a summary."""

from stats import mean, spread


def summarize(readings):
    return {"count": len(readings), "mean": mean(readings), "spread": spread(readings)}
'''
            },
        ),
    ),
    entry="report",
    tests={
        "test_report.py": """\
from report import summarize


def test_summarize_reports_an_exact_spread():
    assert summarize([1, 2]) == {"count": 2, "mean": 1.5, "spread": 0.5}
"""
    },
    acceptance="""\
import sys
for root in SOURCE_ROOTS:
    sys.path.insert(0, root)
try:
    from report import summarize
except Exception as failure:
    print(f"FAIL: cannot import summarize: {failure}", file=sys.stderr)
    raise SystemExit(1)

for readings, expected in (
    ([1, 2], 0.5),
    ([0, 5], 2.5),
    ([3, 3], 0.0),
    ([1, 2, 10], 4.5),
):
    got = summarize(readings)["spread"]
    if got != expected:
        print(f"FAIL: spread({readings}) == {got}, expected {expected}", file=sys.stderr)
        raise SystemExit(1)

# The cause was in the library, so that is where the fix has to be. An arm that
# papered over it in the caller has done different work from one that found it.
import stats
if stats.spread([1, 2]) != 0.5:
    print("FAIL: the library still truncates; only the caller was patched", file=sys.stderr)
    raise SystemExit(1)

# And the test it was told not to weaken must still say what it said.
test_source = open(TEST_SOURCE).read()
if '"spread": 0.5' not in test_source:
    print("FAIL: the test's expectation was changed rather than the defect fixed",
          file=sys.stderr)
    raise SystemExit(1)

print("PASS")
""",
)


STRICT_STATS = '''\
"""Statistics helpers."""


def mean(values):
    if not values:
        raise ValueError("mean of no values")
    return sum(values) / len(values)
'''

STRICT_MODE = Task(
    slug="strict-mode",
    difficulty="medium",
    notes=(
        "The second internal control, and the one that spreads a change across "
        "call sites. Three modules in two packages call `mean`; all of them have "
        "to pass the new argument through. No toolchain work is required, which "
        "is the point of having it in the set."
    ),
    problem="""\
`mean` silently ignores `None` readings. It must stop doing that.

Give `mean` a keyword argument `strict`, defaulting to `False`. When `strict` is
true, a series containing `None` must raise `ValueError`; when it is false the
current behaviour is kept, which is to skip them.

Then make **every** caller of `mean` pass `strict=True`, so the whole project
rejects incomplete data. There are three of them.

Extend the tests to cover the strict behaviour, and make the suite pass.
""",
    packages=(
        Package(
            name="stats",
            modules={
                "stats.py": STRICT_STATS
                + '''

def total(values):
    """The sum of a series, ignoring gaps."""
    return sum(value for value in values if value is not None)
'''
            },
        ),
        Package(
            name="report",
            needs=("stats",),
            modules={
                "report.py": '''\
"""Turn a series of readings into a summary."""

from stats import mean


def summarize(readings):
    clean = [value for value in readings if value is not None]
    return {"count": len(clean), "mean": mean(clean)}


def average_of_averages(series):
    return mean([mean(one) for one in series])
'''
            },
        ),
    ),
    entry="report",
    tests={
        "test_report.py": """\
from report import summarize


def test_summarize_counts_and_means():
    assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}
"""
    },
    acceptance="""\
import sys
for root in SOURCE_ROOTS:
    sys.path.insert(0, root)
try:
    import stats
    from report import average_of_averages, summarize
except Exception as failure:
    print(f"FAIL: cannot import: {failure}", file=sys.stderr)
    raise SystemExit(1)

# The default has to be unchanged, or every existing caller's behaviour moved.
if stats.mean([1, None, 3]) != 2.0:
    print("FAIL: the non-strict default no longer skips gaps", file=sys.stderr)
    raise SystemExit(1)

try:
    stats.mean([1, None, 3], strict=True)
except ValueError:
    pass
else:
    print("FAIL: strict=True accepted a series holding None", file=sys.stderr)
    raise SystemExit(1)

if summarize([2, 4, 6]) != {"count": 3, "mean": 4.0}:
    print("FAIL: summarize no longer works on a clean series", file=sys.stderr)
    raise SystemExit(1)
if average_of_averages([[1, 2], [3, 4]]) != 2.5:
    print("FAIL: average_of_averages no longer works", file=sys.stderr)
    raise SystemExit(1)

# Three call sites, all of which have to pass it. Counted rather than inspected,
# because how a caller is written is not what this task is about.
source = open(ENTRY_SOURCE).read()
if source.count("strict=True") < 3:
    print(f"FAIL: {source.count('strict=True')} call sites pass strict=True, expected 3",
          file=sys.stderr)
    raise SystemExit(1)

print("PASS")
""",
)


TASKS: tuple[Task, ...] = (ADD_MEDIAN, USE_VALIDATOR, FIX_SPREAD, STRICT_MODE)
