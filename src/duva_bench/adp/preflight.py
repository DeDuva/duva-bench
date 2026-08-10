"""Preflight: prove the identities are separate before spending anything (M2).

The constructor already refuses two equal tokens, but equality is not the
property that matters — ADP's is. Two *different* tokens minted for the same
principal, or a grader token with the runner's scopes, produce scores ADP marks
``separately_authorized: false``, and a study that discovers that after
execution has bought a corpus of self-reports.

So this opens a throwaway run, records a throwaway eval under the grader token,
and reads ADP's own answer back. It costs one run and no model tokens, and it
is the last cheap moment to find out.

Mirrors adp-replay's ``replay/runner.py`` preflight.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from duva_bench.adp.client import AdpClient

# The eval endpoint needs a commit to bind the score to, and defaults to the
# run's `final_git_sha` — which a preflight run does not have, because it never
# did any work. The all-zero sha is the null commit: it satisfies the endpoint's
# format check without claiming the score is about any real tree.
NULL_GIT_SHA = "0" * 40


@dataclass(frozen=True)
class PreflightResult:
    contract_version: str
    run_id: str
    separately_authorized: bool
    reporter_principal: str | None

    @property
    def ok(self) -> bool:
        return self.separately_authorized


class PreflightFailed(RuntimeError):
    """ADP does not consider the grader identity separate from the runner's."""


def preflight(
    client: AdpClient,
    owner: str,
    repo: str,
    *,
    orchestrator: str = "duva-bench",
    strict: bool = True,
) -> PreflightResult:
    """Check the contract version and the identity separation, in that order.

    ``strict=False`` returns the result instead of raising, for callers that
    want to report rather than abort — the CLI's ``preflight`` subcommand.
    Execution paths use the default: a study that starts spending after this
    check failed is a study nobody can use the results of.
    """
    version = client.assert_contract()

    marker = uuid.uuid4().hex[:12]
    intent = client.mint_intent(
        owner,
        repo,
        title=f"duva-bench preflight {marker}",
        body=(
            "Opened by duva-bench's preflight to check that the grader identity is "
            "separate from the runner identity. The run is abandoned immediately; it "
            "carries no trajectory and scores nothing real."
        ),
    )
    run = client.create_run(
        owner,
        repo,
        intent_id=intent.intent_id,
        orchestrator=orchestrator,
        external_ref=f"duva-bench-preflight:{marker}",
        labels={"duva_bench": "preflight"},
    )

    try:
        recorded = client.report_eval(
            owner,
            repo,
            run.id,
            name="duva-bench.preflight",
            passed=True,
            git_sha=NULL_GIT_SHA,
            spec={"grader": "duva-bench.preflight", "version": "1", "marker": marker},
            summary="identity separation check; not a measurement of anything",
        )
        separately_authorized = bool(recorded.separately_authorized)
        result = PreflightResult(
            contract_version=version,
            run_id=run.id,
            separately_authorized=separately_authorized,
            reporter_principal=recorded.reporter_principal,
        )
    finally:
        # Abandoned rather than closed: closing would attest a final git sha
        # this run never produced. The trajectory (empty) is kept, which is what
        # ADP does with every abandoned run.
        client.abandon_run(owner, repo, run.id, reason="duva-bench preflight")

    if strict and not result.ok:
        raise PreflightFailed(
            "ADP reports separately_authorized: false for a score recorded with the grader "
            f"token (reporter principal {result.reporter_principal!r}). The two tokens are "
            "different strings but the same principal to ADP, so every score this study "
            "recorded would be a self-report. Mint the grader token for a second principal "
            "(ADP's `tsx src/bootstrap.ts <principal>`) before running anything."
        )
    return result
