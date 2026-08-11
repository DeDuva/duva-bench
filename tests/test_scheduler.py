"""M5: the factorial scheduler, its budget cap, and its resume."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from duva_bench.adp.client import AdpClient
from duva_bench.exec.harbor import HarborTrial, load_trial
from duva_bench.exec.ledger import BudgetExceeded, CostLedger, ProviderLimiter
from duva_bench.exec.scheduler import plan_trials, run_study, study_status
from duva_bench.exec.trial import Trial, run_trial
from duva_bench.state import StateDir
from duva_bench.study.load import load_study, parse_study
from duva_bench.study.models import Arm, Study, TaskRef
from tests.fakes import GRADER_TOKEN, RUNNER_TOKEN, FakeAdp

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "smoke" / "study.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "harbor"

# What the fixture trial's model_call events add up to, in micro-dollars. The
# ledger reads this back out of ADP rather than being told it.
FIXTURE_MICRO_USD = 4200 + 13100 + 900


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


class CountingExecutor:
    """Replays a recorded trial and remembers every trial it was asked for."""

    def __init__(self, *, die_after: int | None = None) -> None:
        self.calls: list[str] = []
        self.die_after = die_after

    def execute(
        self, task: TaskRef, arm: Arm, *, task_dir: Path, work_dir: Path, label: str
    ) -> HarborTrial:
        if self.die_after is not None and len(self.calls) >= self.die_after:
            # What a scheduler being killed looks like from inside: the study
            # stops mid-flight with some trials done and some not.
            raise KeyboardInterrupt("the scheduler was killed")
        self.calls.append(label)
        return load_trial(FIXTURES / "terminus-2-json-normalizer")


def _unpaced() -> ProviderLimiter:
    """A limiter that never waits.

    The smoke study paces anthropic at 30/minute, which is correct for a study
    that spends money on somebody else's API and wrong for a test suite: it
    would put 2 real seconds between trial starts and buy nothing. The pacing
    itself is tested directly, with a fake clock, further down.
    """
    return ProviderLimiter(limits={})


def _run(study: Study, client: AdpClient, state: StateDir, executor: Any, **kwargs: Any) -> Any:
    return run_study(
        study,
        state=state,
        client=client,
        executor=executor,
        study_dir=EXAMPLE.parent,
        concurrency=kwargs.pop("concurrency", 1),
        limiter=kwargs.pop("limiter", _unpaced()),
        **kwargs,
    )


# --- the plan ---------------------------------------------------------------


def test_the_plan_is_the_full_factorial_in_a_stable_order(study: Study) -> None:
    trials = plan_trials(study)
    assert len(trials) == study.trial_count == 8
    assert plan_trials(study) == trials
    assert [(t.task_id, t.arm_id, t.repetition) for t in trials[:4]] == [
        ("json-normalizer", "standard", 1),
        ("json-normalizer", "standard", 2),
        ("json-normalizer", "twin", 1),
        ("json-normalizer", "twin", 2),
    ]


# --- a whole study ----------------------------------------------------------


def test_a_study_runs_every_cell_once(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    executor = CountingExecutor()
    outcome = _run(study, client, StateDir(tmp_path), executor)

    assert outcome.ok
    assert len(outcome.completed) == 8
    assert len(executor.calls) == 8
    assert len(adp.runs) == 8
    assert len({run.external_ref for run in adp.runs.values()}) == 8


def test_every_trial_is_written_to_the_progress_log(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    state = StateDir(tmp_path)
    _run(study, client, state, CountingExecutor())
    entries = state.progress_entries()
    assert len(entries) == 8
    assert {entry["verdict"] for entry in entries} == {"VERIFIED"}


def test_rerunning_a_finished_study_runs_nothing(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    state = StateDir(tmp_path)
    _run(study, client, state, CountingExecutor())

    second = CountingExecutor()
    outcome = _run(study, client, state, second)

    assert second.calls == []
    assert outcome.skipped == 8
    assert len(adp.runs) == 8


# --- resume -----------------------------------------------------------------


def test_a_killed_study_resumes_and_completes_exactly_the_missing_trials(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """The done-condition: kill it, rerun it, no duplicates and nothing skipped."""
    state = StateDir(tmp_path)
    killed = CountingExecutor(die_after=3)
    with pytest.raises(KeyboardInterrupt):
        _run(study, client, state, killed)

    assert len(killed.calls) == 3

    resumed = CountingExecutor()
    outcome = _run(study, client, state, resumed)

    assert outcome.skipped == 3
    assert len(resumed.calls) == 5
    assert set(killed.calls) & set(resumed.calls) == set(), "a trial ran twice"
    assert len(adp.runs) == 8
    assert len({run.external_ref for run in adp.runs.values()}) == 8


def test_a_resume_consults_adp_when_the_local_log_is_gone(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """The local log is a cache. ADP is the system of record."""
    state = StateDir(tmp_path)
    _run(study, client, state, CountingExecutor())
    state.progress.unlink()

    executor = CountingExecutor()
    outcome = _run(study, client, state, executor)

    assert executor.calls == []
    assert outcome.skipped == 8


def test_a_local_log_that_claims_too_much_does_not_survive_contact_with_adp(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """A verified line for a run ADP has never heard of still needs running.

    The two sources are unioned, so this test pins the direction that matters:
    the log can add to what ADP knows, and this asserts the run really exists
    rather than that the line was believed.
    """
    state = StateDir(tmp_path).ensure()
    state.append_progress(
        {"external_ref": f"{study.slug}:standard:json-normalizer:r1", "verdict": "VERIFIED"}
    )

    executor = CountingExecutor()
    outcome = _run(study, client, state, executor)

    assert outcome.skipped == 1
    assert len(executor.calls) == 7
    assert len(adp.runs) == 7


def test_status_answers_from_the_local_log_without_credentials(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    state = StateDir(tmp_path)
    killed = CountingExecutor(die_after=2)
    with pytest.raises(KeyboardInterrupt):
        _run(study, client, state, killed)

    status = study_status(study, state=state)
    assert status["planned"] == 8
    assert status["verified"] == 2
    assert len(status["remaining"]) == 6
    assert status["adp_consulted"] is False


# --- the budget cap ---------------------------------------------------------


def _cheap_study(study: Study, cap: str) -> Study:
    document = study.model_dump(mode="json")
    document["budget_usd_cap"] = cap
    return parse_study(__import__("yaml").safe_dump(document))


def test_no_trial_starts_past_the_cap(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """One fixture trial costs $0.0182, so a $0.03 cap allows exactly two."""
    capped = _cheap_study(study, "0.03")
    executor = CountingExecutor()

    outcome = _run(capped, client, StateDir(tmp_path), executor)

    assert outcome.budget_stopped is not None
    assert len(executor.calls) == 2
    assert len(adp.runs) == 2
    assert not outcome.ok


def test_the_cap_survives_a_resume(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """A resume that started from zero would let a study spend its cap twice."""
    capped = _cheap_study(study, "0.03")
    state = StateDir(tmp_path)
    _run(capped, client, state, CountingExecutor())

    second = CountingExecutor()
    outcome = _run(capped, client, state, second)

    assert second.calls == [], "the resumed study started a trial past the cap"
    assert outcome.budget_stopped is not None


def test_the_ledger_reads_its_numbers_back_out_of_adp(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    outcome = _run(_cheap_study(study, "0.03"), client, StateDir(tmp_path), CountingExecutor())
    assert outcome.ledger["spent_usd"] == str(Decimal(2 * FIXTURE_MICRO_USD) / Decimal(1_000_000))


# --- the ledger and the limiter, on their own -------------------------------


def test_an_unpriced_trial_is_counted_separately_rather_than_as_free() -> None:
    ledger = CostLedger(cap_usd=Decimal("1.00"))
    ledger.record(500_000)
    ledger.record(None)
    assert ledger.spent_usd == Decimal("0.5")
    assert ledger.unpriced_trials == 1
    assert ledger.priced_trials == 1
    assert ledger.summary()["unpriced_trials"] == 1


def test_the_cap_is_reached_at_exactly_the_cap() -> None:
    ledger = CostLedger(cap_usd=Decimal("1.00"))
    ledger.record(999_999)
    ledger.check()
    ledger.record(1)
    with pytest.raises(BudgetExceeded, match=r"\$1.00 cap"):
        ledger.check()


def test_the_limiter_spaces_trials_of_one_provider() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = ProviderLimiter(limits={"anthropic": 30}, clock=lambda: now[0], sleep=sleep)
    assert limiter.acquire("anthropic") == 0.0
    assert limiter.acquire("anthropic") == pytest.approx(2.0)  # 30/minute
    assert slept == [2.0]


def test_a_provider_with_no_limit_is_not_paced() -> None:
    limiter = ProviderLimiter(limits={}, clock=lambda: 0.0, sleep=lambda _: None)
    assert limiter.acquire("local") == 0.0
    assert limiter.acquire("local") == 0.0


def test_two_providers_do_not_pace_each_other() -> None:
    now = [0.0]
    limiter = ProviderLimiter(
        limits={"a": 60, "b": 60},
        clock=lambda: now[0],
        sleep=lambda s: now.__setitem__(0, now[0] + s),
    )
    assert limiter.acquire("a") == 0.0
    assert limiter.acquire("b") == 0.0


def test_a_studys_rate_limit_paces_its_trial_starts(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    """The pacing is real, and it comes from the study spec rather than a guess."""
    now = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    limiter = ProviderLimiter(
        limits=dict(study.provider_rate_limits), clock=lambda: now[0], sleep=sleep
    )
    _run(study, client, StateDir(tmp_path), CountingExecutor(), limiter=limiter)

    # 30 requests per minute is one every two seconds, and eight trials wait
    # seven times.
    assert waits == [pytest.approx(2.0)] * 7


def test_status_reads_adp_when_the_state_directory_is_gone(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """`status --check-adp` has to answer from ADP, not from a lost cache.

    `adp_completed_refs` read intents from the state directory alone and gave up
    on a miss. `run_study` was immune by accident — it calls `ensure_intent` for
    every task first, which repopulates the cache — but `study_status` does not,
    so a checkout whose `.duva-bench/` was gone reported a *finished* study as
    entirely unstarted while reporting `adp_consulted: true`.

    A wrong answer labelled authoritative is worse than the local-only one
    beside it, which at least admits it did not look. A fresh clone, a second
    machine and a cleaned scratch directory are all this situation, and on this
    project's own machine `/tmp` is cleared between sessions.
    """
    first = StateDir(tmp_path / "first")
    run_study(
        study, state=first, client=client, executor=CountingExecutor(), study_dir=EXAMPLE.parent
    )
    planned = len(plan_trials(study))
    closed = {run.external_ref for run in adp.runs.values() if run.status == "closed"}
    assert len(closed) == planned, "the first run did not finish the study"

    # A different machine: same study, same ADP, no local state whatsoever.
    status = study_status(study, state=StateDir(tmp_path / "elsewhere"), client=client)

    assert status["adp_consulted"] is True
    assert status["verified"] == planned
    assert status["remaining"] == [], (
        "status claimed to have consulted ADP and still reported a finished study as unstarted"
    )


def test_status_counts_only_the_trials_this_study_planned(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """`planned + verified + remaining` has to describe one study.

    ADP holds every run ever closed against this study's intents — including
    repetitions past the study's own and any one-off `duva-bench trial`
    invocations, both of which happened while closing gate G1. Counting them raw
    reported `planned: 8, verified: 4, remaining: 7`: eleven trials in an
    eight-trial study, which is not a state anything can be in.
    """
    state = StateDir(tmp_path)
    run_study(
        study, state=state, client=client, executor=CountingExecutor(), study_dir=EXAMPLE.parent
    )

    # A repetition beyond the study's own, exactly as `duva-bench trial` makes.
    run_trial(
        study,
        Trial(task_id="json-normalizer", arm_id="standard", repetition=99),
        state=state,
        client=client,
        executor=CountingExecutor(),
        study_dir=EXAMPLE.parent,
    )

    status = study_status(study, state=state, client=client)
    planned = len(plan_trials(study))

    assert status["planned"] == planned
    assert status["verified"] == planned, "a run outside the plan was counted as progress"
    assert status["remaining"] == []
    assert status["verified"] + len(status["remaining"]) == status["planned"]
