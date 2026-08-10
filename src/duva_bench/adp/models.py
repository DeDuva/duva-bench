"""Hand-written ADP response models (execution-plan §3.2).

ADP's OpenAPI document types requests and describes responses in prose —
``description: Verification result``, no schema. So the generated client covers
half the contract and this module covers the other half, from observed
responses, pinned by ``tests/contract/``.

Two things a reader will trip over if nobody says them here.

**The naming convention is not uniform, and this is not a transcription
error.** ADP's run rows, evals and trajectory events serialize in ``snake_case``
(``final_git_sha``, ``cost_micro_usd``); ``/runs/compare`` and ``/runs/{id}/stats``
serialize their aggregate rows in ``camelCase`` (``finalGitSha``,
``costMicroUsd``) because those come straight off internal interfaces. The
aliases below are what ADP actually sends. Guessing the other convention
produces a model that validates against nothing and silently reads every numeric
field as its default.

**Absent and null are different answers.** ``score`` is null for an eval that
recorded a pass/fail without a number, and ``envelope_verified`` is null for a
run with no attestation yet — "not applicable", not "zero" and not "false".
Every optional field here keeps ``None`` rather than coercing, because the
unscored-is-not-zero rule (execution-plan §0.6) has to hold at the boundary
where the data arrives or it does not hold at all.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AdpModel(BaseModel):
    """Base for every response model.

    ``extra="allow"`` on purpose, and it is the opposite of the study spec's
    rule for a reason: a study file is ours and a stray key there is a typo, but
    a response is ADP's and a new field is ADP being additive. Refusing it would
    make a compatible server upgrade look like a client crash.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Run(AdpModel):
    """A run row, as ``POST /runs``, ``GET /runs/{id}`` and ``/close`` return it."""

    id: str
    intent_id: str | None = None
    orchestrator: str | None = None
    external_ref: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    status: str = "open"
    final_git_sha: str | None = None
    trajectory_digest: str | None = None
    # The DSSE envelope itself, not a summary of it: a consumer verifies without
    # trusting our reading of it.
    envelope: dict[str, Any] | None = None
    created_at: str | None = None
    closed_at: str | None = None


class Session(AdpModel):
    id: str
    harness: str | None = None
    status: str | None = None
    run_id: str | None = None


class AppendReceipt(AdpModel):
    """What ADP says it durably holds after an append.

    ``head``, not ``chain_head``, and ``duplicates`` is a list of
    ``client_event_id``s rather than a count — both documented in
    docs/adp-contract-findings.md as places the prose and the wire disagree. The
    second is the dangerous one: ``if duplicates:`` behaves identically either
    way, so code doing arithmetic on it breaks only once a duplicate actually
    occurs, which is during a retry, which is when the recorder is already in
    trouble.

    ``accepted_through`` is None when the batch carried no ``producer_seq`` — an
    emitter that does not count is untracked, not incomplete. A spool must not
    read that as zero.
    """

    head: str | None = None
    accepted_through: int | None = None
    appended: int = 0
    duplicates: tuple[str, ...] = ()
    count: int = 0

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicates)


class EvalRecord(AdpModel):
    """One recorded score. ``separately_authorized`` is the whole point of it."""

    id: str | None = None
    run_id: str | None = None
    name: str
    git_sha: str | None = None
    spec_digest: str | None = None
    score: float | None = None
    passed: bool | None = None
    trajectory_digest: str | None = None
    reporter_principal: str | None = None
    separately_authorized: bool | None = None
    created_at: str | None = None


class VerifiedSession(AdpModel):
    """Per-session verification. Two guarantees, reported separately.

    ``ok`` says the events ADP holds were not edited. ``emitter_complete`` says
    ADP was *given* all of them. A chain can verify perfectly and still be
    missing an event that never arrived.
    """

    session_id: str
    ok: bool
    event_count: int = 0
    head: str | None = None
    broke_at_seq: int | None = None
    reason: str | None = None
    emitter_tracked: bool | None = None
    emitter_complete: bool | None = None
    emitter_first_gap: int | None = None


class VerifyResult(AdpModel):
    """``GET /runs/{id}/verify`` — the evidence gate's raw material."""

    run_id: str
    ok: bool
    chains_ok: bool | None = None
    emitters_ok: bool | None = None
    envelope_verified: bool | None = None
    trajectory_digest_matches: bool | None = None
    recomputed_trajectory_digest: str | None = None
    attested_trajectory_digest: str | None = None
    final_git_sha: str | None = None
    attested_subject_sha: str | None = None
    sessions: tuple[VerifiedSession, ...] = ()
    evals: tuple[EvalRecord, ...] = ()


class TrajectoryEvent(AdpModel):
    """One event as ``GET /runs/{id}/trajectory`` returns it."""

    id: str | None = None
    session_id: str | None = None
    seq: int | None = None
    kind: str
    type: str | None = None
    payload: Any = None
    status: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_micro_usd: int | None = None
    duration_ms: int | None = None
    git_sha: str | None = None
    related_session_id: str | None = None
    client_event_id: str | None = None
    producer_seq: int | None = None
    producer_id: str | None = None
    occurred_at: str | None = None
    hash: str | None = None
    prev_hash: str | None = None


class Trajectory(AdpModel):
    run_id: str | None = None
    total: int = 0
    events: tuple[TrajectoryEvent, ...] = ()


# --- the camelCase half -----------------------------------------------------


class ComparisonEval(AdpModel):
    """One axis's latest result on a compared run.

    ``score`` stays None when ADP reports none. Coercing it to 0.0 here would
    put "the grader crashed" and "the arm scored nothing" in the same bucket,
    which is the failure the unscored-is-not-zero rule names.
    """

    name: str
    score: float | None = None
    passed: bool | None = None
    spec_digest: str | None = Field(default=None, alias="specDigest")
    gate_status: str | None = Field(default=None, alias="gateStatus")
    created_at: str | None = Field(default=None, alias="createdAt")


class RunComparison(AdpModel):
    """One row of ``GET /runs/compare?intent_id=`` — camelCase on the wire.

    ``evals`` is the field analysis reads: the latest result *per axis*.
    ``eval`` is whichever score landed last overall, kept by ADP for consumers
    that predate multi-axis scoring, and ranking on it would make the surviving
    number depend on POST ordering rather than on the work.
    """

    run_id: str = Field(alias="runId")
    external_ref: str | None = Field(default=None, alias="externalRef")
    orchestrator: str | None = None
    status: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    final_git_sha: str | None = Field(default=None, alias="finalGitSha")
    trajectory_digest: str | None = Field(default=None, alias="trajectoryDigest")
    latest_eval: ComparisonEval | None = Field(default=None, alias="eval")
    evals: tuple[ComparisonEval, ...] = ()
    events: int = 0
    tokens_in: int = Field(default=0, alias="tokensIn")
    tokens_out: int = Field(default=0, alias="tokensOut")
    cost_micro_usd: int = Field(default=0, alias="costMicroUsd")
    duration_ms: int = Field(default=0, alias="durationMs")
    tool_calls: int = Field(default=0, alias="toolCalls")
    tool_failures: int = Field(default=0, alias="toolFailures")
    created_at: str | None = Field(default=None, alias="createdAt")
    closed_at: str | None = Field(default=None, alias="closedAt")

    def axis(self, name: str) -> ComparisonEval | None:
        for result in self.evals:
            if result.name == name:
                return result
        return None


class KindStat(AdpModel):
    kind: str
    count: int = 0
    tokens_in: int = Field(default=0, alias="tokensIn")
    tokens_out: int = Field(default=0, alias="tokensOut")
    cost_micro_usd: int = Field(default=0, alias="costMicroUsd")
    duration_ms: int = Field(default=0, alias="durationMs")
    failures: int = 0


class ToolStat(AdpModel):
    name: str | None = None
    count: int = 0
    failures: int = 0


class ModelStat(AdpModel):
    model: str | None = None
    calls: int = 0
    tokens_in: int = Field(default=0, alias="tokensIn")
    tokens_out: int = Field(default=0, alias="tokensOut")
    cost_micro_usd: int = Field(default=0, alias="costMicroUsd")


class RunStats(AdpModel):
    """``GET /runs/{id}/stats`` — camelCase, like ``/runs/compare``."""

    run_id: str | None = Field(default=None, alias="runId")
    sessions: int = 0
    events: int = 0
    by_kind: tuple[KindStat, ...] = Field(default=(), alias="byKind")
    tokens_in: int = Field(default=0, alias="tokensIn")
    tokens_out: int = Field(default=0, alias="tokensOut")
    cost_micro_usd: int = Field(default=0, alias="costMicroUsd")
    duration_ms: int = Field(default=0, alias="durationMs")
    tools: tuple[ToolStat, ...] = ()
    models: tuple[ModelStat, ...] = ()
    commits: tuple[str, ...] = ()


class Issue(AdpModel):
    """The compat-plane issue whose side effect is an intent (§3.3)."""

    id: str | None = None
    number: int | None = None
    title: str | None = None
    intent_id: str
    html_url: str | None = None


class GitObject(AdpModel):
    """A blob, tree or commit that ADP's compat plane just wrote.

    All four git-data writes answer with the sha of what they created, and that
    sha is the only part duva-bench uses: the artifact commit exists so a run
    has something resolvable to close against (see ``adp/artifacts.py``), not so
    anything here can read git back out.
    """

    sha: str
