"""Running a grader, and reporting what it said (M4).

A grader is an **instrument**, not a participant. Three things follow, and each
is enforced here rather than documented and hoped for:

**It runs outside the work.** The subprocess's cwd is a scratch directory, never
the workdir it is grading. A grader that runs inside the tree it scores is a
grader an agent can shadow with a file of the same name.

**It holds no credentials.** Its environment is built by
:func:`duva_bench.env.stripped_environment`, so no ADP token and no provider key
reaches it. It could not call a model or write to ADP if it tried, and the score
it produces is posted afterwards by duva-bench under the grader principal.

**It cannot report its own result.** duva-bench posts one eval per axis. The
grader's job ends at printing JSON.

The contract, from the plan: ``python3 <grader> <workdir>`` (or ``node``), one
JSON object on stdout::

    {"spec": {...}, "axes": {"<axis>": {"score": 0.5, "passed": false,
                                        "summary": "..."}}}

The grader file's sha256 is injected into the spec before it is digested, so the
``spec_digest`` ADP stores identifies *the instrument that produced the score*,
not just the shape of its output. Two arms scored by two versions of a grader
are not comparable, and this is what makes that detectable instead of invisible.

**A crashed grader leaves the trial unscored.** Not zero. Nothing here ever
substitutes a number for a missing one.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from duva_bench.adp.client import AdpClient
from duva_bench.env import stripped_environment
from duva_bench.study.digest import canonical_bytes

DEFAULT_TIMEOUT = 300.0

# ADP's evals endpoint validates `spec_digest` against ^[0-9a-f]{64}$ — no
# `sha256:` prefix, unlike every digest this project computes for itself. The
# difference is ADP's, and it is converted here rather than being allowed to
# leak into the rest of the codebase.
INTERPRETERS = {".py": [sys.executable], ".js": ["node"], ".mjs": ["node"], ".ts": ["npx", "tsx"]}


class GraderError(RuntimeError):
    """The grader did not produce a result. The trial is unscored, not zero."""


@dataclass(frozen=True)
class AxisResult:
    """One axis of one grader's verdict."""

    name: str
    score: float | None
    passed: bool
    summary: str = ""


@dataclass(frozen=True)
class GraderResult:
    """What a grader said, or why it said nothing."""

    spec: dict[str, Any]
    axes: tuple[AxisResult, ...] = ()
    error: str | None = None
    stderr: str = ""
    returncode: int = 0
    grader_sha256: str = ""

    @property
    def scored(self) -> bool:
        """False when the grader crashed. Callers must not read this as zero."""
        return self.error is None

    @property
    def spec_digest(self) -> str:
        """The digest ADP stores: bare hex, no prefix (see :data:`INTERPRETERS`)."""
        return hashlib.sha256(canonical_bytes(self.spec)).hexdigest()

    def axis(self, name: str) -> AxisResult | None:
        for axis in self.axes:
            if axis.name == name:
                return axis
        return None


@dataclass
class GraderRunner:
    """Invokes graders under the rules above."""

    timeout: float = DEFAULT_TIMEOUT
    # Extra environment for the grader. Merged *after* stripping, so a caller
    # can hand it what it needs without reopening the hole stripping closed.
    env: dict[str, str] = field(default_factory=dict)

    def command(self, grader: Path) -> list[str]:
        interpreter = INTERPRETERS.get(grader.suffix)
        if interpreter is None:
            raise GraderError(
                f"no interpreter for {grader.name}: graders are {sorted(INTERPRETERS)} files"
            )
        return [*interpreter, str(grader)]

    def run(
        self, grader: Path, workdir: Path, *, expected_sha256: str | None = None
    ) -> GraderResult:
        """Run one grader over one workdir.

        ``expected_sha256`` comes from the study spec. A grader that no longer
        matches its pin is refused *before* it runs: it would produce a score
        that looked like the study's and came from a different instrument.
        """
        grader = Path(grader).resolve()
        workdir = Path(workdir).resolve()
        if not grader.exists():
            raise GraderError(f"{grader} does not exist")

        actual = hashlib.sha256(grader.read_bytes()).hexdigest()
        if expected_sha256 is not None and actual != expected_sha256:
            raise GraderError(
                f"{grader.name} hashes to {actual}, and the study pins {expected_sha256}. "
                "That is a different instrument; scoring with it would put two graders' "
                "results in one column."
            )

        with tempfile.TemporaryDirectory(prefix="duva-grader-") as scratch:
            try:
                completed = subprocess.run(
                    [*self.command(grader), str(workdir)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    # Outside the tree being graded.
                    cwd=scratch,
                    env={**stripped_environment(), **self.env},
                )
            except subprocess.TimeoutExpired:
                return GraderResult(
                    spec={},
                    error=f"the grader did not finish within {self.timeout}s",
                    grader_sha256=actual,
                )
            except OSError as failure:
                return GraderResult(spec={}, error=str(failure), grader_sha256=actual)

        return self._parse(completed, actual)

    def _parse(self, completed: subprocess.CompletedProcess[str], sha256: str) -> GraderResult:
        stderr = (completed.stderr or "")[-4000:]
        if completed.returncode != 0:
            return GraderResult(
                spec={},
                error=f"the grader exited {completed.returncode}",
                stderr=stderr,
                returncode=completed.returncode,
                grader_sha256=sha256,
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as failure:
            return GraderResult(
                spec={},
                error=f"the grader printed something that is not JSON: {failure}",
                stderr=stderr,
                grader_sha256=sha256,
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("axes"), dict):
            return GraderResult(
                spec={},
                error="the grader printed JSON with no `axes` object",
                stderr=stderr,
                grader_sha256=sha256,
            )

        spec = dict(payload.get("spec") or {})
        # The instrument's identity, inside the thing that gets digested.
        spec["grader_sha256"] = sha256

        axes: list[AxisResult] = []
        for name in sorted(payload["axes"]):
            raw = payload["axes"][name]
            if not isinstance(raw, dict):
                continue
            score = raw.get("score")
            axes.append(
                AxisResult(
                    name=str(name),
                    # A non-numeric score stays None rather than becoming 0.0.
                    score=float(score) if isinstance(score, int | float) else None,
                    passed=bool(raw.get("passed")),
                    summary=str(raw.get("summary", "")),
                )
            )

        return GraderResult(spec=spec, axes=tuple(axes), stderr=stderr, grader_sha256=sha256)


def report_axes(
    client: AdpClient,
    owner: str,
    repo: str,
    run_id: str,
    result: GraderResult,
    *,
    git_sha: str | None = None,
) -> list[str]:
    """POST one eval per axis, under the grader token. Returns the axis names.

    One eval per axis, never a blended score: ADP keeps the latest result per
    *name*, so per-axis rows are what make ``/runs/compare``'s ``evals[]``
    readable, and a composite would be a number nobody could take apart again.

    An unscored result posts nothing. A trial with no eval renders as unscored
    downstream, which is the true statement; posting a zero would be a false one.
    """
    if not result.scored:
        return []

    posted: list[str] = []
    for axis in result.axes:
        client.report_eval(
            owner,
            repo,
            run_id,
            name=axis.name,
            passed=axis.passed,
            **({"score": axis.score} if axis.score is not None else {}),
            summary=axis.summary,
            spec_digest=result.spec_digest,
            spec=result.spec,
            **({"git_sha": git_sha} if git_sha else {}),
        )
        posted.append(axis.name)
    return posted
