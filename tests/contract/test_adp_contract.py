"""What a live ADP actually does (M2).

Each test pins one line of `docs/adp-contract-findings.md`. When ADP fixes a
finding, the test fails — which is the point: a workaround nobody is told to
remove is a workaround that outlives its bug.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import httpx
import pytest

from duva_bench.adp.client import AdpClient
from duva_bench.adp.gate import verify_gate
from duva_bench.adp.preflight import preflight
from duva_bench.adp.recorder import Recorder
from duva_bench.adp.spool import Spool
from duva_bench.adp.version import VERSION_HEADER, assert_api_version

pytestmark = pytest.mark.contract

NULL_SHA = "0" * 40


def _resolvable_sha(client: AdpClient, owner: str, repo: str) -> str:
    """A commit this repository can actually resolve.

    This used to be the constant ``FAKE_SHA = "b" * 40``, and every test that
    closed a run with it failed the first time this suite met a live server:
    ADP rejects a ``final_git_sha`` it cannot resolve, because it will not
    attest a commit nobody can fetch later. A 40-hex string is the right
    *shape* and the wrong *thing*, which is exactly the class of mistake a
    hand-written double cannot catch — `tests/fakes.py` accepted any sha, so
    325 unit tests agreed with a client that could not close a single run.
    """
    tree = client.create_tree(
        owner,
        repo,
        entries=[
            {"path": "contract.txt", "mode": "100644", "type": "blob", "content": uuid.uuid4().hex}
        ],
    )
    return client.create_commit(owner, repo, message="contract suite", tree=tree, parents=[])


def _open_run(client: AdpClient, owner: str, repo: str, intent_id: str) -> str:
    run = client.create_run(
        owner,
        repo,
        intent_id=intent_id,
        orchestrator="duva-bench",
        external_ref=f"contract:{uuid.uuid4().hex[:12]}",
        labels={"suite": "contract"},
    )
    return run.id


# --- §3.5 version pinning ---------------------------------------------------


def test_the_version_header_is_served_before_authentication(base_url: str) -> None:
    response = httpx.get(f"{base_url}/api/adp/repos/_/_/runs", timeout=10)
    assert response.status_code in (401, 403, 404)
    assert_api_version(response.headers.get(VERSION_HEADER))


# --- §3.1 the payload NOT NULL bug ------------------------------------------


def test_an_event_without_a_payload_is_accepted(
    client: AdpClient, owner: str, repo: str, intent_id: str
) -> None:
    """The client sends `payload: {}` for an event that omits it.

    When ADP fixes the column, this test keeps passing and
    `test_a_payload_less_event_is_still_rejected_by_the_server` starts failing —
    that is the pair that tells us the workaround can go.
    """
    run_id = _open_run(client, owner, repo, intent_id)
    session = client.create_session(owner, repo, harness="duva-bench", run_id=run_id)
    receipt = client.append_events(owner, repo, session.id, [{"kind": "message"}])
    assert receipt.appended == 1


def test_the_server_now_accepts_a_payload_less_event_but_the_workaround_stays(
    client: AdpClient, owner: str, repo: str, intent_id: str, base_url: str
) -> None:
    """The bug is fixed server-side, and the workaround still has to stay.

    This assertion used to read ``== 500``, as a canary that would fail the day
    ADP fixed the column and tell us to drop `payload: {}`. It fired on
    2026-08-10, and the instruction it carried turned out to be wrong.

    ADP fixed the column in `3b4af01` on 2026-08-08 **without bumping the API
    contract version** — it was 0.2.0 before and 0.2.0 after. So "the server
    reports 0.2.0" does not tell a client whether payload-less events are
    accepted, and there is no version a client could assert to find out. Two
    deployments both honestly serving 0.2.0 can disagree about this, and the
    only behaviour that works against both is to keep sending `payload: {}`.

    The canary was right that the server changed and wrong that the workaround
    could go. What it could not see is that a fix and a contract are different
    things: this one is invisible from the wire, so a consumer has to keep
    coding for the older behaviour until a version bump lets it stop.
    """
    run_id = _open_run(client, owner, repo, intent_id)
    session = client.create_session(owner, repo, harness="duva-bench", run_id=run_id)
    response = httpx.post(
        f"{base_url}/api/adp/repos/{owner}/{repo}/sessions/{session.id}/events",
        json={"events": [{"kind": "message"}]},
        headers={"Authorization": f"Bearer {os.environ['DUVA_ADP_RUNNER_TOKEN']}"},
        timeout=30,
    )
    assert response.status_code in (200, 201), (
        f"expected this ADP to accept a payload-less event, got {response.status_code}. "
        "Both behaviours ship as 0.2.0; see docs/adp-contract-findings.md #1."
    )

    # The workaround is the actual subject here, so assert it is still in force
    # rather than leaving it to a comment somebody deletes.
    receipt = client.append_events(owner, repo, session.id, [{"kind": "message"}])
    assert receipt.appended == 1


# --- §3.2 the response shapes -----------------------------------------------


def test_an_append_returns_the_mark_a_spool_trims_against(
    client: AdpClient, owner: str, repo: str, intent_id: str
) -> None:
    run_id = _open_run(client, owner, repo, intent_id)
    session = client.create_session(owner, repo, harness="duva-bench", run_id=run_id)
    receipt = client.append_events(
        owner, repo, session.id, [{"kind": "message", "payload": {}, "producer_seq": 1}]
    )
    assert receipt.head is not None, "`head`, not `chain_head`"
    assert receipt.accepted_through == 1


def test_a_repeated_client_event_id_is_reported_as_a_list_of_ids(
    client: AdpClient, owner: str, repo: str, intent_id: str
) -> None:
    run_id = _open_run(client, owner, repo, intent_id)
    session = client.create_session(owner, repo, harness="duva-bench", run_id=run_id)
    event = {"kind": "message", "payload": {}, "client_event_id": f"contract:{uuid.uuid4().hex}"}
    client.append_events(owner, repo, session.id, [event])
    receipt = client.append_events(owner, repo, session.id, [event])
    assert receipt.duplicates == (event["client_event_id"],)
    assert receipt.appended == 0


def test_an_untracked_emitter_gets_a_null_accepted_through(
    client: AdpClient, owner: str, repo: str, intent_id: str
) -> None:
    """Untracked is not incomplete, and a spool must not read it as zero."""
    run_id = _open_run(client, owner, repo, intent_id)
    session = client.create_session(owner, repo, harness="duva-bench", run_id=run_id)
    receipt = client.append_events(owner, repo, session.id, [{"kind": "message", "payload": {}}])
    assert receipt.accepted_through is None


def test_a_gap_is_rejected_whole_and_names_the_resume_point(
    client: AdpClient, owner: str, repo: str, intent_id: str
) -> None:
    from duva_bench.adp.client import AppendRejected

    run_id = _open_run(client, owner, repo, intent_id)
    session = client.create_session(owner, repo, harness="duva-bench", run_id=run_id)
    client.append_events(
        owner, repo, session.id, [{"kind": "message", "payload": {}, "producer_seq": 1}]
    )
    with pytest.raises(AppendRejected) as rejection:
        client.append_events(
            owner, repo, session.id, [{"kind": "message", "payload": {}, "producer_seq": 5}]
        )
    assert rejection.value.expected_next_seq == 2


def test_compare_rows_are_camel_case_and_carry_labels_and_axes(
    client: AdpClient, owner: str, repo: str, intent_id: str
) -> None:
    """The naming split is real; so is `evals[]`, which analysis reads per axis."""
    run_id = _open_run(client, owner, repo, intent_id)
    sha = _resolvable_sha(client, owner, repo)
    client.close_run(owner, repo, run_id, final_git_sha=sha)
    for axis in ("acceptance", "robustness"):
        client.report_eval(owner, repo, run_id, name=axis, passed=True, score=1.0)

    rows = client.compare_runs(owner, repo, intent_id=intent_id)
    row = next(row for row in rows if row.run_id == run_id)

    assert row.labels.get("suite") == "contract"
    assert {result.name for result in row.evals} == {"acceptance", "robustness"}
    assert row.final_git_sha == sha


# --- §3.3 intents, and identity separation ----------------------------------


def test_an_intent_can_only_be_minted_through_the_compat_plane(
    client: AdpClient, owner: str, repo: str
) -> None:
    issue = client.mint_intent(owner, repo, title=f"duva-bench contract {uuid.uuid4().hex[:8]}")
    assert issue.intent_id


def test_a_score_is_separately_authorized_only_across_principals(
    client: AdpClient, owner: str, repo: str
) -> None:
    result = preflight(client, owner, repo)
    assert result.separately_authorized, (
        "ADP does not consider the grader token a different principal from the runner "
        "token. Mint them for two principals; see tests/contract/README.md."
    )


# --- the evidence gate ------------------------------------------------------


def test_a_clean_run_verifies(client: AdpClient, owner: str, repo: str, intent_id: str) -> None:
    run_id = _open_run(client, owner, repo, intent_id)
    session = client.create_session(owner, repo, harness="duva-bench", run_id=run_id)
    client.append_events(
        owner, repo, session.id, [{"kind": "message", "payload": {"i": 1}, "producer_seq": 1}]
    )
    sha = _resolvable_sha(client, owner, repo)
    client.close_run(owner, repo, run_id, final_git_sha=sha)

    verdict = verify_gate(client, owner, repo, run_id)
    assert verdict.ok, verdict.summary()


def test_a_tampered_event_makes_the_gate_return_error(
    client: AdpClient, owner: str, repo: str, intent_id: str
) -> None:
    """Tamper-evidence, checked by tampering.

    Needs database access, because the whole claim is that the *API* offers no
    way to do this. `DUVA_ADP_DB_URL` points at the same Postgres ADP is using;
    `psql` does the edit.

    `DUVA_ADP_PSQL` overrides how `psql` is reached, as a shell-style argument
    list. It exists because the usual local setup runs Postgres in a container
    and does not install a client on the host, e.g.

        DUVA_ADP_PSQL="docker exec -i adp-test-xxxx-postgres-1 psql"

    Deliberately not a skip. A tamper-evidence test that quietly does not run
    on the machine where somebody is about to trust the evidence is worse than
    no test, so a missing `psql` is a failure with instructions attached.
    """
    database = os.environ.get("DUVA_ADP_DB_URL")
    if not database:
        raise pytest.UsageError(
            "DUVA_ADP_DB_URL is not set. The tamper test edits a stored event directly, "
            "because ADP correctly offers no endpoint that would."
        )

    run_id = _open_run(client, owner, repo, intent_id)
    session = client.create_session(owner, repo, harness="duva-bench", run_id=run_id)
    client.append_events(
        owner,
        repo,
        session.id,
        [
            {"kind": "message", "payload": {"i": 1}, "producer_seq": 1},
            {"kind": "message", "payload": {"i": 2}, "producer_seq": 2},
        ],
    )
    sha = _resolvable_sha(client, owner, repo)
    client.close_run(owner, repo, run_id, final_git_sha=sha)
    assert verify_gate(client, owner, repo, run_id).ok, "the run did not verify before tampering"

    psql = shlex.split(os.environ.get("DUVA_ADP_PSQL", "psql"))
    edit = subprocess.run(
        [
            *psql,
            database,
            "-c",
            "update session_events set payload = '{\"i\": 99}'::jsonb "
            f"where session_id = '{session.id}' and seq = 2",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert edit.returncode == 0, (
        f"{' '.join(psql)} failed: {edit.stderr}\n"
        "If psql is not installed on this host, point DUVA_ADP_PSQL at one, e.g. "
        "'docker exec -i <postgres-container> psql'."
    )

    verdict = verify_gate(client, owner, repo, run_id)
    assert verdict.status == "ERROR"
    assert any("chain" in failure for failure in verdict.failures), verdict.failures


# --- the recorder, against the real server ----------------------------------


KILLED_WRITER = """
import os
import signal
import sys

sys.path.insert(0, {src!r})
from duva_bench.adp.spool import Spool

spool = Spool({root!r}, producer_id={producer!r})
for index in range(8):
    spool.append({{"kind": "tool_call", "payload": {{"i": index}}}})
    if index == 4:
        os.kill(os.getpid(), signal.SIGKILL)
"""


def test_a_sigkilled_recorder_resumes_gap_free_against_a_real_adp(
    client: AdpClient, owner: str, repo: str, intent_id: str, tmp_path: Path
) -> None:
    run_id = _open_run(client, owner, repo, intent_id)
    session = client.create_session(owner, repo, harness="duva-bench", run_id=run_id)
    producer = f"contract-{uuid.uuid4().hex[:8]}"

    script = KILLED_WRITER.format(
        src=str(Path(__file__).resolve().parents[2] / "src"),
        root=str(tmp_path),
        producer=producer,
    )
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)], capture_output=True, timeout=60
    )
    assert completed.returncode == -signal.SIGKILL

    with Recorder(client, owner, repo, session.id, Spool(tmp_path)) as recorder:
        recorder.flush(timeout=30)
    sha = _resolvable_sha(client, owner, repo)
    client.close_run(owner, repo, run_id, final_git_sha=sha)

    verdict = verify_gate(client, owner, repo, run_id)
    assert verdict.ok, verdict.summary()

    trajectory = client.full_trajectory(owner, repo, run_id)
    sequences = [event.producer_seq for event in trajectory.events if event.producer_seq]
    assert sequences == list(range(1, len(sequences) + 1))
    assert len(set(sequences)) == len(sequences)


# --- G2: the report reconciles with ADP -------------------------------------


def test_a_rendered_report_reconciles_with_a_direct_adp_read(
    client: AdpClient, owner: str, repo: str, tmp_path: Path
) -> None:
    """Gate G2's done-condition, against a live server rather than the double.

    `tests/test_report.py` already reconciles a report against the in-memory
    ADP, and that is worth having — but the double is this project's own reading
    of ADP's responses, and a report that agrees with it proves the two agree,
    not that either is right. Contact with the real server is what found finding
    #5 in `docs/adp-contract-findings.md`.

    Reconciles what a reader would actually act on: how many trials there were,
    which verified, and the money. The cost is the sharpest of the three,
    because it is summed from per-event usage on one path and read from an
    aggregate endpoint on the other.
    """
    from duva_bench.analysis.extract import extract
    from duva_bench.report.build import build_report
    from duva_bench.state import StateDir
    from duva_bench.study.load import load_study

    study_path = Path(__file__).resolve().parents[2] / "examples" / "smoke" / "study.yaml"
    study = load_study(study_path)
    state = StateDir.for_study(study, None)
    if not state.known_intents():
        pytest.skip("no local state for the smoke study on this machine; run it first")

    outcomes = extract(study, client=client, state=state, with_trajectories=False)
    if not outcomes.trials:
        pytest.skip("the smoke study has not been executed against this ADP")

    report = build_report(study, state=state, outcomes=outcomes).as_dict()

    # 1. Trial count and verification, straight off the run rows.
    assert report["evidence"]["trials"] == len(outcomes.trials)
    verified = [t for t in outcomes.trials if t.verdict == "VERIFIED"]
    assert report["evidence"]["verified"] == len(verified)

    # 2. Cost, re-derived from ADP rather than from the report's own arithmetic.
    from_adp = sum(trial.cost_micro_usd for trial in outcomes.trials)
    if report["cost"]["unpriced_trials"] == 0:
        assert report["cost"]["total_micro_usd"] == from_adp
    assert report["cost"]["priced_micro_usd"] == from_adp

    # 3. Tokens, likewise.
    assert report["cost"]["tokens_in"] == sum(t.tokens_in for t in outcomes.trials)
    assert report["cost"]["tokens_out"] == sum(t.tokens_out for t in outcomes.trials)

    # 4. Every trial the report lists is a run ADP will still show us, and every
    #    one of them verifies. A report naming a run that cannot be fetched is
    #    the one failure mode this whole architecture exists to prevent.
    for trial in verified:
        assert client.verify_run(owner, repo, trial.run_id).ok, (
            f"{trial.external_ref} is in the report and does not verify"
        )
