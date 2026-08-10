"""M4: the grader runner, its environment, and how scores reach ADP."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from duva_bench.adp.client import AdpClient
from duva_bench.env import is_secret, stripped_environment
from duva_bench.grading.runner import GraderError, GraderRunner, report_axes
from tests.fakes import GRADER_TOKEN, RUNNER_TOKEN, FakeAdp

GRADERS = Path(__file__).resolve().parent / "fixtures" / "graders"
SMOKE = Path(__file__).resolve().parents[1] / "examples" / "smoke"


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


# --- the environment --------------------------------------------------------


def test_no_credential_reaches_the_grader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proven by a grader that prints its own environment.

    The plan's done-condition, run literally: whatever this process saw is what
    an untrusted grader would have had.
    """
    monkeypatch.setenv("DUVA_ADP_RUNNER_TOKEN", "runner-secret")
    monkeypatch.setenv("DUVA_ADP_GRADER_TOKEN", "grader-secret")
    monkeypatch.setenv("DUVA_ADP_BASE_URL", "http://adp.invalid")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-secret")
    monkeypatch.setenv("MY_SERVICE_PASSWORD", "hunter2")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("LANG", "C.UTF-8")

    runner = GraderRunner()
    result = runner.run(GRADERS / "env-printer.py", tmp_path)
    assert result.scored

    # The grader printed its environment into stdout, which the runner parsed
    # as JSON; re-read it directly to inspect the variable list.
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, str(GRADERS / "env-printer.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        env=stripped_environment(),
        cwd=tmp_path,
    )
    seen = set(json.loads(completed.stdout)["environment"])

    for leaked in (
        "DUVA_ADP_RUNNER_TOKEN",
        "DUVA_ADP_GRADER_TOKEN",
        "DUVA_ADP_BASE_URL",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "MY_SERVICE_PASSWORD",
    ):
        assert leaked not in seen, f"{leaked} reached the grader"
    assert {"PATH", "LANG"} <= seen, "stripping took the environment down with it"


@pytest.mark.parametrize(
    ("name", "secret"),
    [
        ("DUVA_ADP_RUNNER_TOKEN", True),
        ("ADP_BASE_URL", True),
        ("ANTHROPIC_API_KEY", True),
        ("OPENAI_BASE_URL", True),
        ("AWS_SECRET_ACCESS_KEY", True),
        ("SOME_SERVICE_TOKEN", True),
        ("db_password", True),
        ("PATH", False),
        ("LANG", False),
        ("HOME", False),
    ],
)
def test_what_counts_as_a_secret(name: str, secret: bool) -> None:
    assert is_secret(name) is secret


def test_the_grader_runs_outside_the_tree_it_grades(tmp_path: Path) -> None:
    """A grader running inside the workdir can be shadowed by a file in it."""
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, str(GRADERS / "env-printer.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        env=stripped_environment(),
    )
    reported = json.loads(completed.stdout)
    assert Path(reported["cwd"]).resolve() != tmp_path.resolve()

    result = GraderRunner().run(GRADERS / "env-printer.py", tmp_path)
    assert result.scored


# --- the instrument's identity ----------------------------------------------


def test_the_grader_sha256_is_injected_into_the_spec_before_digesting() -> None:
    grader = GRADERS / "env-printer.py"
    result = GraderRunner().run(grader, Path.cwd())
    expected = hashlib.sha256(grader.read_bytes()).hexdigest()
    assert result.spec["grader_sha256"] == expected
    assert result.grader_sha256 == expected


def test_the_spec_digest_is_bare_hex_because_that_is_what_adp_validates() -> None:
    result = GraderRunner().run(GRADERS / "env-printer.py", Path.cwd())
    assert len(result.spec_digest) == 64
    assert not result.spec_digest.startswith("sha256:")


def test_editing_the_grader_changes_the_spec_digest(tmp_path: Path) -> None:
    """Two arms scored by two versions of a grader are not comparable."""
    original = GRADERS / "env-printer.py"
    edited = tmp_path / "env-printer.py"
    edited.write_text(original.read_text(encoding="utf-8") + "\n# a change\n", encoding="utf-8")

    first = GraderRunner().run(original, tmp_path)
    second = GraderRunner().run(edited, tmp_path)
    assert first.spec_digest != second.spec_digest


def test_a_grader_that_no_longer_matches_its_pin_is_refused_before_it_runs() -> None:
    with pytest.raises(GraderError, match="different instrument"):
        GraderRunner().run(GRADERS / "env-printer.py", Path.cwd(), expected_sha256="0" * 64)


def test_a_grader_matching_its_pin_runs() -> None:
    grader = SMOKE / "graders" / "json-normalizer.py"
    pinned = hashlib.sha256(grader.read_bytes()).hexdigest()
    assert GraderRunner().run(grader, Path.cwd(), expected_sha256=pinned).scored


# --- unscored is not zero ---------------------------------------------------


def test_a_crashed_grader_leaves_the_trial_unscored(tmp_path: Path) -> None:
    result = GraderRunner().run(GRADERS / "crasher.py", tmp_path)
    assert not result.scored
    assert result.axes == ()
    assert "exited 3" in (result.error or "")


def test_a_grader_that_prints_nonsense_is_unscored_rather_than_zero(tmp_path: Path) -> None:
    result = GraderRunner().run(GRADERS / "babbler.py", tmp_path)
    assert not result.scored
    assert "not JSON" in (result.error or "")


def test_an_axis_with_no_number_keeps_none(tmp_path: Path) -> None:
    result = GraderRunner().run(GRADERS / "partial.py", tmp_path)
    acceptance = result.axis("acceptance")
    latency = result.axis("latency")
    assert acceptance is not None and acceptance.score == 0.5
    assert latency is not None and latency.score is None, "a missing measurement is not a zero"


def test_a_grader_that_hangs_is_unscored(tmp_path: Path) -> None:
    slow = tmp_path / "slow.py"
    slow.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    result = GraderRunner(timeout=0.5).run(slow, tmp_path)
    assert not result.scored
    assert "did not finish" in (result.error or "")


def test_a_grader_in_an_unknown_language_is_refused(tmp_path: Path) -> None:
    grader = tmp_path / "grader.rb"
    grader.write_text("puts 'hi'", encoding="utf-8")
    with pytest.raises(GraderError, match="no interpreter"):
        GraderRunner().run(grader, tmp_path)


# --- reporting --------------------------------------------------------------


def _closed_run(client: AdpClient) -> str:
    intent = client.mint_intent("duva", "bench", title="t")
    run = client.create_run("duva", "bench", intent_id=intent.intent_id, orchestrator="duva-bench")
    client.close_run("duva", "bench", run.id, final_git_sha="a" * 40)
    return run.id


def test_one_eval_is_posted_per_axis_never_a_blend(
    adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    run_id = _closed_run(client)
    result = GraderRunner().run(SMOKE / "graders" / "json-normalizer.py", tmp_path)

    posted = report_axes(client, "duva", "bench", run_id, result)

    assert posted == ["acceptance", "robustness"]
    assert {record.name for record in adp.evals} == {"acceptance", "robustness"}
    assert all(record.separately_authorized for record in adp.evals)
    assert all(record.reporter_principal == "duva-grader" for record in adp.evals)


def test_every_axis_carries_the_same_spec_digest(
    adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """One instrument, one identity — so a mismatch across arms is detectable."""
    run_id = _closed_run(client)
    result = GraderRunner().run(SMOKE / "graders" / "json-normalizer.py", tmp_path)
    report_axes(client, "duva", "bench", run_id, result)
    assert {record.spec_digest for record in adp.evals} == {result.spec_digest}


def test_an_unscored_result_posts_nothing(adp: FakeAdp, client: AdpClient, tmp_path: Path) -> None:
    """A trial with no eval renders as unscored. A zero would be a false claim."""
    run_id = _closed_run(client)
    result = GraderRunner().run(GRADERS / "crasher.py", tmp_path)

    assert report_axes(client, "duva", "bench", run_id, result) == []
    assert adp.evals == []


def test_an_axis_with_no_score_still_records_its_pass_fail(
    adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    run_id = _closed_run(client)
    result = GraderRunner().run(GRADERS / "partial.py", tmp_path)

    report_axes(client, "duva", "bench", run_id, result)

    latency = next(record for record in adp.evals if record.name == "latency")
    assert latency.score is None
    assert latency.passed is False
