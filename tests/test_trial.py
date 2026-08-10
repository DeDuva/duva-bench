"""M3: one trial, end to end, against an in-memory ADP and a recorded Harbor run.

What cannot be tested here is gate G1 — a real container, a real agent CLI, a
real model. What can be, and is: that the run carries the labels analysis reads,
that the bridged events reach ADP, that a crashed executor abandons rather than
closes, that a rerun rejoins instead of forking, and that the local record holds
pointers rather than results.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from duva_bench.adp.client import AdpClient
from duva_bench.exec.harbor import HarborExecutor, HarborFailed, HarborTrial, load_trial
from duva_bench.exec.trial import NULL_GIT_SHA, Trial, intent_title, run_trial
from duva_bench.state import StateDir
from duva_bench.study.load import load_study
from duva_bench.study.models import Arm, Study, TaskRef
from tests.fakes import GRADER_TOKEN, RUNNER_TOKEN, FakeAdp

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "smoke" / "study.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "harbor"


@pytest.fixture
def study() -> Study:
    return load_study(EXAMPLE)


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


class RecordedExecutor:
    """Replays a recorded Harbor trial. Records what it was asked for."""

    def __init__(self, fixture: str = "terminus-2-json-normalizer") -> None:
        self.fixture = FIXTURES / fixture
        self.calls: list[tuple[str, str, str]] = []

    def execute(
        self, task: TaskRef, arm: Arm, *, task_dir: Path, work_dir: Path, label: str
    ) -> HarborTrial:
        self.calls.append((task.id, arm.id, label))
        return load_trial(self.fixture, command=("harbor", "run", "--path", str(task_dir)))


class ExplodingExecutor:
    def execute(
        self, task: TaskRef, arm: Arm, *, task_dir: Path, work_dir: Path, label: str
    ) -> HarborTrial:
        raise HarborFailed("harbor exited 1 and wrote no result.json")


def _run(
    study: Study, client: AdpClient, state: StateDir, executor: object, repetition: int = 1
) -> object:
    return run_trial(
        study,
        Trial(task_id="json-normalizer", arm_id="standard", repetition=repetition),
        state=state,
        client=client,
        executor=executor,  # type: ignore[arg-type]
        study_dir=EXAMPLE.parent,
    )


# --- the happy path ---------------------------------------------------------


def test_a_trial_opens_a_run_labelled_with_the_cell_it_is(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    state = StateDir(tmp_path)
    record = _run(study, client, state, RecordedExecutor())

    run = adp.runs[record.run_id]
    assert run.external_ref == f"{study.slug}:standard:json-normalizer:r1"
    assert run.labels["arm"] == "standard"
    assert run.labels["arm_digest"] == study.arm("standard").arm_digest
    assert run.labels["study"] == study.study_digest
    assert run.labels["task"] == "json-normalizer"
    assert run.labels["repetition"] == "1"
    assert run.labels["harness"] == "terminus-2@0.20.0"


def test_the_bridged_trace_reaches_adp(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    record = _run(study, client, StateDir(tmp_path), RecordedExecutor())

    events = adp.events_for_run(record.run_id)
    assert [event.type for event in events if event.kind == "tool_call"] == [
        "read_file",
        "write_file",
        "run_command",
        "read_lines",
    ]
    assert record.events_recorded == len(events)
    # Contiguous from 1, so `emitters_ok` has something true to say.
    assert [event.producer_seq for event in events] == list(range(1, len(events) + 1))


def test_a_completed_trial_verifies_and_is_closed(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    record = _run(study, client, StateDir(tmp_path), RecordedExecutor())
    assert record.verdict == "VERIFIED"
    assert adp.runs[record.run_id].status == "closed"

    # The run closes against a commit the repository can actually resolve, not
    # against a sentinel. ADP refuses a sha it cannot show anyone later, so the
    # all-zero "null commit" this used to assert could never have closed a real
    # run — which is what four contract tests found the first time they met a
    # live server.
    assert record.final_git_sha is not None
    assert record.final_git_sha != NULL_GIT_SHA
    assert record.final_git_sha in adp.commits

    # And it is reachable, so the attested subject survives a gc.
    assert record.artifact_ref is not None
    assert adp.refs[record.artifact_ref] == record.final_git_sha


def test_the_local_record_holds_pointers_and_no_results(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    """A number cached locally is a number that can disagree with ADP."""
    state = StateDir(tmp_path)
    record = _run(study, client, state, RecordedExecutor())

    written = json.loads(state.trial_record(record.external_ref).read_text(encoding="utf-8"))
    assert written["run_id"] == record.run_id
    assert written["verdict"] == "VERIFIED"
    forbidden = {"score", "scores", "axes", "tokens", "cost", "cost_usd", "statistics"}
    assert not (forbidden & set(written)), "a result leaked into local state"


# --- intents ----------------------------------------------------------------


def test_an_intent_is_minted_once_per_task_per_study(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    state = StateDir(tmp_path)
    first = _run(study, client, state, RecordedExecutor(), repetition=1)
    second = _run(study, client, state, RecordedExecutor(), repetition=2)

    assert first.intent_id == second.intent_id
    assert len(adp.issues) == 1
    assert adp.issues[0]["title"] == intent_title(study, "json-normalizer")


def test_an_intent_is_found_again_from_a_fresh_state_directory(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """Losing the local cache must not mint a second intent for the same task.

    Two intents for one task would put its runs on two `/runs/compare` pages,
    and nothing downstream could tell they were the same cell.
    """
    first = _run(study, client, StateDir(tmp_path / "a"), RecordedExecutor())
    second = _run(study, client, StateDir(tmp_path / "b"), RecordedExecutor(), repetition=2)
    assert first.intent_id == second.intent_id
    assert len(adp.issues) == 1


# --- rejoin -----------------------------------------------------------------


def test_rerunning_the_same_trial_rejoins_its_run_rather_than_forking_it(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    state = StateDir(tmp_path)
    first = _run(study, client, state, RecordedExecutor())
    # The first run is closed, so a rejoin is refused rather than silently
    # appending a second trajectory to a finished run.
    with pytest.raises(Exception, match=r"409|closed"):
        _run(study, client, state, RecordedExecutor())
    assert len(adp.runs) == 1
    assert first.run_id in adp.runs


# --- failure ----------------------------------------------------------------


def test_an_executor_failure_abandons_the_run_and_records_why(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    record = _run(study, client, StateDir(tmp_path), ExplodingExecutor())

    assert adp.runs[record.run_id].status == "abandoned"
    assert record.error is not None and "result.json" in record.error
    # The trajectory is kept: a failure that leaves no record is a failure
    # nobody can distinguish from a trial that never ran.
    events = adp.events_for_run(record.run_id)
    assert [event.type for event in events] == ["duva_bench.executor_failure"]


def test_a_crashed_agent_abandons_rather_than_closing(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """Harbor ran, the agent died. There is no commit to attest."""
    record = _run(study, client, StateDir(tmp_path), RecordedExecutor("terminus-2-crashed"))

    assert adp.runs[record.run_id].status == "abandoned"
    assert record.final_git_sha is None
    assert record.harbor_verifier_passed is None, "a verifier that never ran is not a failure"
    events = adp.events_for_run(record.run_id)
    assert any(event.type == "harbor.exception" for event in events)


def test_a_tampered_run_makes_the_trial_an_error(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The evidence gate is what decides, not whether the agent looked happy."""
    original = client.close_run

    def tamper_then_close(*args: object, **kwargs: object) -> object:
        closed = original(*args, **kwargs)  # type: ignore[arg-type]
        adp.tamper(str(args[2]), at_seq=2)
        return closed

    monkeypatch.setattr(client, "close_run", tamper_then_close)
    record = _run(study, client, StateDir(tmp_path), RecordedExecutor())

    assert record.verdict == "ERROR"
    assert any("chain" in failure for failure in record.failures)


# --- the Harbor invocation --------------------------------------------------


def test_the_harbor_command_names_the_arm_exactly(study: Study, tmp_path: Path) -> None:
    argv = HarborExecutor().command(
        Path("/tasks/json-normalizer"), study.arm("standard"), jobs_dir=tmp_path, label="job-1"
    )
    assert "--agent" in argv and argv[argv.index("--agent") + 1] == "terminus-2"
    assert argv[argv.index("--model") + 1] == "anthropic/claude-sonnet-4-5-20250929"
    assert "--agent-kwarg" in argv and "temperature=0" in argv
    assert argv[argv.index("--n-attempts") + 1] == "1"


def test_arm_environment_pins_go_to_agent_env_not_env(study: Study, tmp_path: Path) -> None:
    """`--env` is Harbor's *environment type*, not a variable.

    In Harbor 0.20.0 `--env` selects the backend the container runs on — an enum
    of `docker`, `modal`, `e2b` and friends — while `KEY=VALUE` belongs to
    `--agent-env`. Passing an arm's environment pins as `--env LANG=C.UTF-8`
    makes Harbor reject `LANG=C.UTF-8` as an unknown environment type before a
    container is ever built, so every trial of an arm with env pins fails
    identically and for a reason that looks nothing like its cause.
    """
    argv = HarborExecutor().command(
        Path("/tasks/json-normalizer"), study.arm("standard"), jobs_dir=tmp_path, label="job-1"
    )
    assert "--agent-env" in argv
    assert argv[argv.index("--agent-env") + 1] == "LANG=C.UTF-8"
    # Not merely "the right flag is present": the wrong one must be absent, or a
    # regression that adds it back keeps this test green.
    assert "--env" not in argv


def test_the_trial_directory_is_found_by_its_results_file(tmp_path: Path) -> None:
    """Harbor's directory naming is Harbor's business; result.json is the contract."""
    from duva_bench.exec.harbor import find_trial_dir

    job = tmp_path / "job"
    nested = job / "task.1-of-1"
    nested.mkdir(parents=True)
    (nested / "result.json").write_text('{"trial_name": "task.1-of-1"}', encoding="utf-8")

    # Harbor writes a *job* summary under the same name, and it is written last.
    # Picking it yields a directory with no trajectory beside it, which is how a
    # trial came back fully verified and carrying zero bridged events.
    (job / "result.json").write_text('{"n_total_trials": 1, "stats": {}}', encoding="utf-8")

    assert find_trial_dir(job) == nested
    assert find_trial_dir(tmp_path / "absent") is None


def test_building_a_command_does_not_require_harbor_to_be_installed(
    study: Study, tmp_path: Path
) -> None:
    """`command` is pure, and CI is where that gets tested.

    Resolving the Harbor binary inside `command` made building an argv depend on
    Harbor being installed. Every local check still passed — this machine has
    Harbor — and CI, which does not, failed two tests that only wanted to read
    the flags. The executor named here cannot exist, so the day resolution
    creeps back in, this fails everywhere rather than only where it is absent.
    """
    executor = HarborExecutor(harbor="harbor-that-is-not-installed-anywhere")
    argv = executor.command(
        Path("/tasks/json-normalizer"),
        study.arm("standard"),
        jobs_dir=tmp_path,
        label="pure",
    )
    assert argv[0] == "harbor-that-is-not-installed-anywhere"
    assert argv[1] == "run"
