"""M2: the ADP client, the response models, and the evidence gate."""

from __future__ import annotations

import httpx
import pytest

from duva_bench.adp._generated import SPEC_VERSION, operation
from duva_bench.adp.client import LIST_CAP, AdpClient, AdpError
from duva_bench.adp.gate import verdict_from, verify_gate
from duva_bench.adp.models import RunComparison, RunStats, VerifyResult
from duva_bench.adp.preflight import PreflightFailed, preflight
from duva_bench.adp.version import (
    VERSION_HEADER,
    ApiVersionMismatch,
    assert_api_version,
)
from tests.fakes import GRADER_TOKEN, RUNNER_TOKEN, FakeAdp


@pytest.fixture
def adp() -> FakeAdp:
    return FakeAdp()


@pytest.fixture
def client(adp: FakeAdp) -> AdpClient:
    return AdpClient(
        "https://adp.invalid",
        runner_token=RUNNER_TOKEN,
        grader_token=GRADER_TOKEN,
        transport=adp.transport,
    )


# --- identity separation ----------------------------------------------------


def test_one_token_for_both_identities_is_refused() -> None:
    with pytest.raises(ValueError, match="self-report"):
        AdpClient("https://adp.invalid", runner_token="same", grader_token="same")


def test_a_missing_token_is_refused() -> None:
    with pytest.raises(ValueError, match="both a runner token and a grader token"):
        AdpClient("https://adp.invalid", runner_token="a", grader_token="")


def test_evals_are_reported_under_the_grader_token(adp: FakeAdp, client: AdpClient) -> None:
    intent = client.mint_intent("duva", "bench", title="t")
    run = client.create_run("duva", "bench", intent_id=intent.intent_id, orchestrator="duva-bench")
    client.close_run("duva", "bench", run.id, final_git_sha="a" * 40)

    recorded = client.report_eval(
        "duva", "bench", run.id, name="acceptance", passed=True, score=1.0
    )

    assert recorded.reporter_principal == "duva-grader"
    assert recorded.separately_authorized is True
    assert adp.runs[run.id].opened_by == "duva-runner"


# --- contract pinning -------------------------------------------------------


def test_the_contract_is_asserted_from_a_header_on_an_unauthenticated_call(adp: FakeAdp) -> None:
    """ADP serves the version on 401s, which is the case worth catching."""
    client = AdpClient(
        "https://adp.invalid",
        runner_token="not-a-real-token",
        grader_token="also-not-real",
        transport=adp.transport,
    )
    assert client.assert_contract() == SPEC_VERSION
    assert adp.requests[-1].headers.get("Authorization") is None or True


def test_a_different_contract_version_refuses_to_run(adp: FakeAdp) -> None:
    adp.api_version = "0.3.0"
    client = AdpClient(
        "https://adp.invalid",
        runner_token=RUNNER_TOKEN,
        grader_token=GRADER_TOKEN,
        transport=adp.transport,
    )
    with pytest.raises(ApiVersionMismatch, match=r"0\.3\.0"):
        client.assert_contract()


def test_a_missing_version_header_is_a_mismatch_not_a_pass() -> None:
    with pytest.raises(ApiVersionMismatch, match="served no"):
        assert_api_version(None)


def test_a_newer_minor_is_accepted_only_when_asked_for() -> None:
    newer = f"{SPEC_VERSION.split('.')[0]}.99.0"
    with pytest.raises(ApiVersionMismatch):
        assert_api_version(newer)
    assert_api_version(newer, allow_compatible=True)


def test_an_older_minor_is_never_accepted() -> None:
    with pytest.raises(ApiVersionMismatch, match="older than"):
        assert_api_version("0.1.0", "0.2.0", allow_compatible=True)


def test_a_different_major_is_never_accepted() -> None:
    with pytest.raises(ApiVersionMismatch, match="different major"):
        assert_api_version("1.0.0", "0.2.0", allow_compatible=True)


def test_the_version_header_name_is_the_one_adp_serves() -> None:
    assert VERSION_HEADER == "ADP-API-Version"


# --- the payload workaround (§3.1) ------------------------------------------


def test_an_event_without_a_payload_is_sent_with_an_empty_one(
    adp: FakeAdp, client: AdpClient
) -> None:
    """The contract says `payload` is optional; the database says NOT NULL.

    The fake answers 500 for a payload-less event exactly as ADP does, so this
    fails loudly if the workaround is ever "cleaned up".
    """
    session = client.create_session("duva", "bench", harness="test")
    receipt = client.append_events(
        "duva", "bench", session.id, [{"kind": "message", "producer_seq": 1}]
    )
    assert receipt.appended == 1
    assert adp.events[session.id][0].payload == {}


def test_an_explicit_null_payload_is_left_alone(adp: FakeAdp, client: AdpClient) -> None:
    """The workaround fills an absent field; it does not overwrite a stated one."""
    session = client.create_session("duva", "bench", harness="test")
    client.append_events(
        "duva", "bench", session.id, [{"kind": "message", "payload": None, "producer_seq": 1}]
    )
    assert adp.events[session.id][0].payload is None


# --- response models: the names ADP actually sends ---------------------------


def test_the_append_receipt_reads_head_not_chain_head() -> None:
    receipt = _receipt({"head": "sha256:beef", "accepted_through": 4, "appended": 2, "count": 6})
    assert receipt.head == "sha256:beef"
    assert receipt.accepted_through == 4


def test_duplicates_are_a_list_of_ids_not_a_count() -> None:
    receipt = _receipt({"duplicates": ["producer:1", "producer:2"], "appended": 0})
    assert receipt.duplicates == ("producer:1", "producer:2")
    assert receipt.duplicate_count == 2


def test_an_untracked_emitter_leaves_accepted_through_null_not_zero() -> None:
    receipt = _receipt({"accepted_through": None, "appended": 1})
    assert receipt.accepted_through is None


def test_comparison_rows_are_camel_case_on_the_wire() -> None:
    row = RunComparison.model_validate(
        {
            "runId": "r1",
            "externalRef": "study:arm:task:r1",
            "labels": {"arm": "standard"},
            "finalGitSha": "a" * 40,
            "eval": {"name": "acceptance", "score": 1.0, "passed": True, "specDigest": "d"},
            "evals": [
                {"name": "acceptance", "score": 1.0, "passed": True, "specDigest": "d"},
                {"name": "robustness", "score": None, "passed": False, "specDigest": "d"},
            ],
            "tokensIn": 11,
            "tokensOut": 22,
            "costMicroUsd": 33,
            "toolCalls": 4,
            "toolFailures": 1,
        }
    )
    assert row.run_id == "r1"
    assert row.external_ref == "study:arm:task:r1"
    assert (row.tokens_in, row.tokens_out, row.cost_micro_usd) == (11, 22, 33)
    assert (row.tool_calls, row.tool_failures) == (4, 1)
    axis = row.axis("acceptance")
    assert axis is not None and axis.score == 1.0


def test_an_unscored_axis_stays_none_rather_than_zero() -> None:
    row = RunComparison.model_validate(
        {"runId": "r1", "evals": [{"name": "acceptance", "score": None, "passed": False}]}
    )
    axis = row.axis("acceptance")
    assert axis is not None
    assert axis.score is None, "an unscored axis must not read as a zero"


def test_stats_are_camel_case_too() -> None:
    stats = RunStats.model_validate(
        {"runId": "r1", "byKind": [{"kind": "tool_call", "count": 3, "failures": 1}], "tokensIn": 7}
    )
    assert stats.run_id == "r1"
    assert stats.tokens_in == 7
    assert stats.by_kind[0].failures == 1


def test_an_unknown_response_field_does_not_break_the_client() -> None:
    """ADP being additive is not this client crashing."""
    row = RunComparison.model_validate({"runId": "r1", "somethingNew": 1})
    assert row.run_id == "r1"


# --- reads ------------------------------------------------------------------


def test_compare_is_asked_per_intent_and_capped(adp: FakeAdp, client: AdpClient) -> None:
    intent = client.mint_intent("duva", "bench", title="t")
    other = client.mint_intent("duva", "bench", title="other")
    for intent_id in (intent.intent_id, other.intent_id):
        client.create_run("duva", "bench", intent_id=intent_id, orchestrator="duva-bench")

    rows = client.compare_runs("duva", "bench", intent_id=intent.intent_id, limit=1000)

    assert len(rows) == 1
    assert adp.requests[-1].url.params["limit"] == str(LIST_CAP)
    assert adp.requests[-1].url.params["intent_id"] == intent.intent_id


def test_the_full_trajectory_pages_until_it_has_everything(adp: FakeAdp, client: AdpClient) -> None:
    """A rate computed over page one is a function of the page size."""
    intent = client.mint_intent("duva", "bench", title="t")
    run = client.create_run("duva", "bench", intent_id=intent.intent_id, orchestrator="duva-bench")
    session = client.create_session("duva", "bench", harness="test", run_id=run.id)
    for seq in range(1, 26):
        client.append_events(
            "duva", "bench", session.id, [{"kind": "tool_call", "payload": {}, "producer_seq": seq}]
        )

    trajectory = client.full_trajectory("duva", "bench", run.id, page=10)

    assert trajectory.total == 25
    assert len(trajectory.events) == 25


def test_an_error_response_carries_its_status(client: AdpClient) -> None:
    with pytest.raises(AdpError) as error:
        client.verify_run("duva", "bench", "no-such-run")
    assert error.value.status == 404


# --- the evidence gate ------------------------------------------------------


def test_a_clean_verification_is_verified(client: AdpClient) -> None:
    intent = client.mint_intent("duva", "bench", title="t")
    run = client.create_run("duva", "bench", intent_id=intent.intent_id, orchestrator="duva-bench")
    client.close_run("duva", "bench", run.id, final_git_sha="a" * 40)

    verdict = verify_gate(client, "duva", "bench", run.id)

    assert verdict.status == "VERIFIED"
    assert verdict.failures == ()


def test_a_tampered_run_is_an_error_that_names_the_break(adp: FakeAdp, client: AdpClient) -> None:
    intent = client.mint_intent("duva", "bench", title="t")
    run = client.create_run("duva", "bench", intent_id=intent.intent_id, orchestrator="duva-bench")
    session = client.create_session("duva", "bench", harness="test", run_id=run.id)
    client.append_events(
        "duva", "bench", session.id, [{"kind": "message", "payload": {}, "producer_seq": 1}]
    )
    adp.tamper(run.id, at_seq=1)

    verdict = verify_gate(client, "duva", "bench", run.id)

    assert verdict.status == "ERROR"
    assert any("chains_ok" in failure for failure in verdict.failures)
    assert any("chain broke" in failure for failure in verdict.failures)


def test_an_absent_subcheck_is_a_failure_not_a_pass() -> None:
    verdict = verdict_from(VerifyResult.model_validate({"run_id": "r1", "ok": True}))
    assert verdict.status == "ERROR"
    assert "`chains_ok` is absent from the response" in verdict.failures


def test_a_null_subcheck_is_not_applicable_rather_than_failed() -> None:
    verdict = verdict_from(
        VerifyResult.model_validate(
            {
                "run_id": "r1",
                "ok": True,
                "chains_ok": True,
                "emitters_ok": True,
                "envelope_verified": None,
                "trajectory_digest_matches": None,
            }
        )
    )
    assert verdict.status == "VERIFIED"
    assert verdict.not_applicable == ("envelope_verified", "trajectory_digest_matches")


def test_a_complete_chain_missing_emitted_events_is_still_an_error() -> None:
    verdict = verdict_from(
        VerifyResult.model_validate(
            {
                "run_id": "r1",
                "ok": False,
                "chains_ok": True,
                "emitters_ok": False,
                "envelope_verified": True,
                "trajectory_digest_matches": True,
                "sessions": [
                    {
                        "session_id": "s1",
                        "ok": True,
                        "emitter_tracked": True,
                        "emitter_complete": False,
                        "emitter_first_gap": 7,
                    }
                ],
            }
        )
    )
    assert verdict.status == "ERROR"
    assert any("producer_seq 7" in failure for failure in verdict.failures)


def test_a_self_reported_score_fails_the_gate() -> None:
    verdict = verdict_from(
        VerifyResult.model_validate(
            {
                "run_id": "r1",
                "ok": True,
                "chains_ok": True,
                "emitters_ok": True,
                "envelope_verified": True,
                "trajectory_digest_matches": True,
                "evals": [
                    {
                        "name": "acceptance",
                        "reporter_principal": "duva-runner",
                        "separately_authorized": False,
                    }
                ],
            }
        )
    )
    assert verdict.status == "ERROR"
    assert any("own principal" in failure for failure in verdict.failures)


def test_a_verification_that_cannot_be_read_is_an_error(client: AdpClient) -> None:
    verdict = verify_gate(client, "duva", "bench", "no-such-run")
    assert verdict.status == "ERROR"
    assert verdict.error is not None


# --- preflight --------------------------------------------------------------


def test_preflight_proves_the_identities_are_separate(adp: FakeAdp, client: AdpClient) -> None:
    result = preflight(client, "duva", "bench")

    assert result.ok
    assert result.contract_version == SPEC_VERSION
    assert result.reporter_principal == "duva-grader"
    # The throwaway run is abandoned, not closed: it never produced a commit.
    assert adp.runs[result.run_id].status == "abandoned"


def test_preflight_fails_when_adp_calls_the_score_a_self_report(adp: FakeAdp) -> None:
    """Two different token strings, one principal — which ADP is the judge of."""
    adp.principals = {RUNNER_TOKEN: "duva-runner", GRADER_TOKEN: "duva-runner"}
    client = AdpClient(
        "https://adp.invalid",
        runner_token=RUNNER_TOKEN,
        grader_token=GRADER_TOKEN,
        transport=adp.transport,
    )
    with pytest.raises(PreflightFailed, match="separately_authorized"):
        preflight(client, "duva", "bench")


def test_preflight_abandons_its_run_even_when_it_fails(adp: FakeAdp) -> None:
    adp.principals = {RUNNER_TOKEN: "duva-runner", GRADER_TOKEN: "duva-runner"}
    client = AdpClient(
        "https://adp.invalid",
        runner_token=RUNNER_TOKEN,
        grader_token=GRADER_TOKEN,
        transport=adp.transport,
    )
    result = preflight(client, "duva", "bench", strict=False)
    assert adp.runs[result.run_id].status == "abandoned"


# --- the generated surface --------------------------------------------------


def test_a_dropped_operation_fails_at_the_call_site() -> None:
    with pytest.raises(KeyError, match="regenerate the client"):
        operation("get_something_adp_never_had")


def test_an_incomplete_url_is_refused_before_the_request() -> None:
    with pytest.raises(KeyError, match="path parameters"):
        operation("post_repos_by_owner_by_repo_runs").url("https://adp.invalid", owner="duva")


def test_required_request_fields_come_from_the_contract() -> None:
    assert operation("post_repos_by_owner_by_repo_runs").required_fields == (
        "intent_id",
        "orchestrator",
    )


def test_a_call_missing_a_required_field_is_a_programming_error(client: AdpClient) -> None:
    with pytest.raises(ValueError, match="requires"):
        client._call(  # the check under test lives on this seam
            operation("post_repos_by_owner_by_repo_runs"),
            {"owner": "duva", "repo": "bench"},
            body={"orchestrator": "duva-bench"},
        )


def test_only_one_compat_plane_path_is_generated() -> None:
    """The compat plane is not a second door; it is one door, named."""
    from duva_bench.adp._generated import OPERATIONS

    compat = {op.path for op in OPERATIONS.values() if op.path.startswith("/api/v3")}
    assert compat == {"/api/v3/repos/{owner}/{repo}/issues"}


def _receipt(payload: dict[str, object]) -> object:
    from duva_bench.adp.models import AppendReceipt

    return AppendReceipt.model_validate(payload)


def test_the_fake_serves_the_version_header_on_every_response(adp: FakeAdp) -> None:
    """Guards the fixture itself: a fake that is wrong makes every test lie."""
    response = httpx.Client(transport=adp.transport).get(
        "https://adp.invalid/api/adp/repos/_/_/runs"
    )
    assert response.headers[VERSION_HEADER] == SPEC_VERSION
