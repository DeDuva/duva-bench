"""The evidence gate (M2, execution-plan §0.6).

One rule, and everything here is machinery for it: **a trial whose ADP
``/verify`` is not ``ok: true`` gets verdict ``ERROR``, never pass or fail.**

An ERROR is not a bad score. A bad score says the arm did the work and the work
was wrong; an ERROR says nobody can tell what the arm did, because the evidence
does not check out. Averaging the two produces a number that means neither. So
ERROR trials are excluded from statistics and counted separately, and M6 prints
the count next to every table.

Two conventions, both from the plan and both easy to get backwards:

* **an absent field is a failure.** A ``/verify`` response missing ``chains_ok``
  is a response that did not say the chains were fine. Reading a missing answer
  as a pass is how a silently-changed contract becomes a corpus of runs nobody
  checked.
* **``null`` is not-applicable.** ``envelope_verified`` is null for a run with
  no attestation yet — there is nothing to check, which is different from a
  check that failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from duva_bench.adp.client import AdpClient, AdpError
from duva_bench.adp.models import VerifyResult

Status = Literal["VERIFIED", "ERROR"]

# The sub-checks a verdict is computed from, in the order a reader wants them.
# Named individually rather than trusting the top-level `ok` alone: `ok` says
# *that* something failed, and an operator fixing it needs to know which.
SUBCHECKS: tuple[str, ...] = (
    "chains_ok",
    "emitters_ok",
    "envelope_verified",
    "trajectory_digest_matches",
)


@dataclass(frozen=True)
class Verdict:
    """What ``/verify`` said, reduced to something a study can act on."""

    run_id: str
    status: Status
    failures: tuple[str, ...] = ()
    not_applicable: tuple[str, ...] = ()
    result: VerifyResult | None = None
    # Set when the verdict comes from a call that did not return a verification
    # at all — a 404, a network failure. Still ERROR: an unreachable answer is
    # not a passing one.
    error: str | None = None
    evals: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return self.status == "VERIFIED"

    def summary(self) -> str:
        if self.ok:
            return f"{self.run_id}: verified"
        reason = self.error or "; ".join(self.failures) or "no reason reported"
        return f"{self.run_id}: ERROR — {reason}"


def verdict_from(result: VerifyResult) -> Verdict:
    """Reduce a ``/verify`` response to a verdict, naming what failed."""
    failures: list[str] = []
    not_applicable: list[str] = []
    provided = result.model_fields_set

    if "ok" not in provided:
        failures.append("the response carries no `ok` field")
    elif not result.ok:
        failures.append("ADP reports ok: false")

    for name in SUBCHECKS:
        if name not in provided:
            failures.append(f"`{name}` is absent from the response")
            continue
        value = getattr(result, name)
        if value is None:
            not_applicable.append(name)
        elif value is False:
            failures.append(f"`{name}` is false")

    for session in result.sessions:
        if session.ok is False:
            where = f" at seq {session.broke_at_seq}" if session.broke_at_seq is not None else ""
            failures.append(f"session {session.session_id} chain broke{where}")
        if session.emitter_tracked and session.emitter_complete is False:
            gap = session.emitter_first_gap
            failures.append(
                f"session {session.session_id} is missing emitted events"
                + (f" from producer_seq {gap}" if gap is not None else "")
            )

    # A score reported by the identity that opened the run is a self-report. It
    # does not make the trajectory unverifiable, so it is not a chain failure —
    # but it is not evidence either, and a study that silently ranked on it
    # would have no separation at all.
    for recorded in result.evals:
        if recorded.separately_authorized is False:
            failures.append(f"eval {recorded.name!r} was reported by the run's own principal")

    return Verdict(
        run_id=result.run_id,
        status="VERIFIED" if not failures else "ERROR",
        failures=tuple(failures),
        not_applicable=tuple(not_applicable),
        result=result,
        evals=tuple(recorded.name for recorded in result.evals),
    )


def verify_gate(client: AdpClient, owner: str, repo: str, run_id: str) -> Verdict:
    """``GET /verify`` and reduce it. An unreachable verification is an ERROR."""
    try:
        result = client.verify_run(owner, repo, run_id)
    except AdpError as error:
        return Verdict(
            run_id=run_id,
            status="ERROR",
            error=(
                f"{error} (verification could not be read, so nothing about this run is evidence)"
            ),
        )
    return verdict_from(result)
