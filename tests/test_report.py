"""M6: the whole `run` → `report` path, against an in-memory ADP.

This is as close to gate G2 as an environment with no container runtime, no
provider key and no live ADP can get, and the gap is recorded in
docs/blockers.md rather than papered over. What *is* checked here is the part
the gate is really about: **every number in the report reconciles with a direct
ADP read**, an unscored trial renders as unscored, and a tampered run renders as
ERROR and is excluded from the statistics with a printed count.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from duva_bench.adp.client import AdpClient
from duva_bench.analysis.extract import extract
from duva_bench.exec.harbor import HarborTrial, load_trial
from duva_bench.exec.ledger import ProviderLimiter
from duva_bench.exec.scheduler import run_study
from duva_bench.report.build import build_report, write_report
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


class SmokeExecutor:
    """Replays a recorded trial per (task, arm).

    The twin arm replays a solution that handles the happy path and not the
    error path, so the study has a real contrast to report rather than an
    invented one.
    """

    def __init__(self, *, crash_grader_for: str | None = None) -> None:
        self.crash_grader_for = crash_grader_for

    def execute(
        self, task: TaskRef, arm: Arm, *, task_dir: Path, work_dir: Path, label: str
    ) -> HarborTrial:
        if task.id == "retry-backoff":
            return load_trial(FIXTURES / "terminus-2-retry-backoff")
        if arm.id == "twin":
            return load_trial(FIXTURES / "terminus-2-json-normalizer-partial")
        return load_trial(FIXTURES / "terminus-2-json-normalizer")


def _run(study: Study, client: AdpClient, state: StateDir, executor: Any) -> Any:
    return run_study(
        study,
        state=state,
        client=client,
        executor=executor,
        study_dir=EXAMPLE.parent,
        concurrency=1,
        limiter=ProviderLimiter(limits={}),
    )


@pytest.fixture
def executed(study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path) -> tuple[StateDir, Any]:
    state = StateDir(tmp_path)
    outcome = _run(study, client, state, SmokeExecutor())
    return state, outcome


# --- the study actually produced scores --------------------------------------


def test_the_smoke_study_scores_every_trial_on_every_axis(
    study: Study, adp: FakeAdp, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    _, outcome = executed
    assert outcome.ok
    assert len(adp.evals) == 16  # 8 trials × 2 axes each
    assert {record.name for record in adp.evals} == {
        "acceptance",
        "robustness",
        "backoff_shape",
    }
    assert all(record.separately_authorized for record in adp.evals), "a score self-reported"


# --- the reconciliation the gate asks for ------------------------------------


def test_every_number_in_the_report_reconciles_with_a_direct_adp_read(
    study: Study, adp: FakeAdp, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    """The gate's condition, run against the fake: nothing here was cached.

    Each assertion re-derives a report figure from ADP by a different route than
    the report took, so agreement is evidence rather than a tautology.
    """
    state, _ = executed
    report = build_report(study, state=state, client=client).as_dict()

    # Trials, straight off the fake's own tables.
    assert report["evidence"]["trials"] == len(adp.runs)
    assert report["evidence"]["verified"] == len(adp.runs)

    # Cost, summed from the events ADP holds rather than from the report's own
    # aggregation.
    from_events = sum(
        event.cost_micro_usd or 0 for run_id in adp.runs for event in adp.events_for_run(run_id)
    )
    assert report["cost"]["total_micro_usd"] == from_events

    # Per-axis cell means, recomputed from the evals ADP stored.
    for axis in ("acceptance", "robustness"):
        recorded: dict[tuple[str, str], list[float]] = {}
        for record in adp.evals:
            if record.name != axis or record.score is None:
                continue
            labels = adp.runs[record.run_id].labels
            recorded.setdefault((labels["task"], labels["arm"]), []).append(record.score)
        for (task, arm), scores in recorded.items():
            cell = report["axes"][axis]["cells"][f"{task}/{arm}"]
            assert cell["n"] == len(scores)
            assert cell["mean"] == pytest.approx(sum(scores) / len(scores))

    # Tool-call counts, recomputed from the trajectories.
    for row in report["trials"]:
        calls = [event for event in adp.events_for_run(row["run_id"]) if event.kind == "tool_call"]
        assert row["process"]["tool_calls"] == len(calls)


def test_the_report_is_the_same_whether_or_not_it_was_just_run(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    """A report read back later must equal the one produced now, or it is a cache."""
    state, _ = executed
    first = build_report(study, state=state, client=client).as_dict()
    second = build_report(study, state=state, client=client).as_dict()
    assert first == second


# --- the rules ---------------------------------------------------------------


def test_the_contrast_is_against_the_pre_registered_control(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    state, _ = executed
    contrasts = build_report(study, state=state, client=client).as_dict()["axes"]["robustness"][
        "contrasts"
    ]
    assert contrasts["control"] == "standard"
    assert contrasts["correction"] == "holm"
    twin = contrasts["arms"]["twin"]
    # The twin arm's replay fails the error-path cases, so the contrast is real
    # and negative.
    assert twin["delta"] < 0
    assert "holm_p" in twin


def test_the_noise_floor_is_reported_before_any_contrast(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    state, _ = executed
    report = build_report(study, state=state, client=client)
    html = report.as_dict()
    for axis in html["axes"].values():
        assert "noise_floor" in axis
    rendered = write_report(report, Path(state.root) / "report")
    text = (rendered / "report.html").read_text(encoding="utf-8")
    assert text.index("noise floor") < text.index("contrasts")


def test_there_is_no_composite_score_anywhere(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    """Rank per axis, never blended. The absence is the assertion."""
    state, _ = executed
    payload = json.dumps(build_report(study, state=state, client=client).as_dict())
    for forbidden in ("composite", "overall_score", "blended", "total_score"):
        assert forbidden not in payload


def test_an_unscored_trial_renders_as_unscored_rather_than_zero(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grader that will not run leaves the trial unscored, and it says so."""
    from duva_bench.grading.runner import GraderResult, GraderRunner

    real_run = GraderRunner.run
    calls = {"n": 0}

    def sometimes_crash(self: GraderRunner, *args: Any, **kwargs: Any) -> GraderResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return GraderResult(spec={}, error="the grader exited 3")
        return real_run(self, *args, **kwargs)

    monkeypatch.setattr(GraderRunner, "run", sometimes_crash)

    state = StateDir(tmp_path)
    _run(study, client, state, SmokeExecutor())
    report = build_report(study, state=state, client=client).as_dict()

    unscored = [row for row in report["trials"] if not row["axes"]]
    assert len(unscored) == 1

    # Both tasks are scored on `acceptance`, so all eight trials would appear in
    # its cells — except the one whose grader died, which appears in none of
    # them rather than as a zero in one.
    acceptance = report["axes"]["acceptance"]
    total_scored = sum(cell["n"] for cell in acceptance["cells"].values())
    assert total_scored == 7, "the unscored trial was counted as a scored one"
    assert all(0.0 not in cell["values"] for cell in acceptance["cells"].values())

    rendered = write_report(build_report(study, state=state, client=client), tmp_path / "report")
    assert "unscored" in (rendered / "report.html").read_text(encoding="utf-8")


def test_a_report_that_scored_nothing_says_so_loudly(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pilot 2, reproduced: 60 verified trials, $12.49, and every axis `null`.

    That report carried **no warnings at all**. Every individual rule was right —
    unscored is not zero, an unscored trial stays out of the numbers, a mean over
    nothing is `None` — and nothing was responsible for noticing that the sum of
    those correct refusals was a report about nothing. A reader skimming it saw
    empty columns and no reason to distrust them.
    """
    from duva_bench.grading.runner import AxisResult, GraderResult, GraderRunner

    # Exactly pilot 2's shape: the grader *ran*, posted its axes, and every score
    # was null. Not a crash — a crash is loud, and this was not.
    monkeypatch.setattr(
        GraderRunner,
        "run",
        lambda self, *args, **kwargs: GraderResult(
            spec={"axes": ["acceptance"]},
            axes=(AxisResult(name="acceptance", score=None, passed=False),),
        ),
    )

    state = StateDir(tmp_path)
    _run(study, client, state, SmokeExecutor())
    report = build_report(study, state=state, client=client).as_dict()

    assert report["evidence"]["verified"] == 8, "the trials themselves were fine"
    assert all(row["n"] == 0 for row in report["axes"]["acceptance"]["arms"])
    assert any("no scored trial in any arm" in warning for warning in report["warnings"]), (
        "a report about nothing announced nothing"
    )

    rendered = write_report(build_report(study, state=state, client=client), tmp_path / "report")
    assert "no scored trial in any arm" in (rendered / "report.html").read_text(encoding="utf-8")


def test_a_study_whose_graders_all_crashed_has_no_axes_and_says_that_instead(
    study: Study, adp: FakeAdp, client: AdpClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worse shape of the same failure: not an empty axis, no axis at all.

    Per-axis warnings cannot fire when there are no axes to iterate, which is
    precisely when the report is emptiest.
    """
    from duva_bench.grading.runner import GraderResult, GraderRunner

    monkeypatch.setattr(
        GraderRunner,
        "run",
        lambda self, *args, **kwargs: GraderResult(spec={}, error="no module named 'report'"),
    )

    state = StateDir(tmp_path)
    _run(study, client, state, SmokeExecutor())
    report = build_report(study, state=state, client=client).as_dict()

    assert report["evidence"]["verified"] == 8
    assert any("not one grader axis exists" in warning for warning in report["warnings"])


def test_the_warning_does_not_fire_on_a_study_that_simply_has_not_run(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    """An empty study is already reported as never-run; two warnings for one fact is noise."""
    state = StateDir(tmp_path).ensure()
    report = build_report(study, state=state, client=client).as_dict()

    assert not any("no scored trial" in warning for warning in report["warnings"])
    assert any("never run" in warning for warning in report["warnings"])


def test_a_tampered_run_is_an_error_excluded_from_statistics_and_counted(
    study: Study, adp: FakeAdp, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    """The other half of the gate's condition."""
    state, _ = executed
    tampered = next(run for run in adp.runs.values() if run.labels["arm"] == "standard")
    adp.tamper(tampered.id, at_seq=2)

    report = build_report(study, state=state, client=client).as_dict()

    assert report["evidence"]["errors"] == 1
    assert tampered.external_ref in report["evidence"]["error_refs"]
    assert any("evidence gate" in warning for warning in report["warnings"])

    row = next(row for row in report["trials"] if row["run_id"] == tampered.id)
    assert row["verdict"] == "ERROR"
    assert any("chain" in failure for failure in row["failures"])

    # Excluded from the statistics: its cell is one trial lighter.
    labels = tampered.labels
    cell = report["axes"]["acceptance"]["cells"][f"{labels['task']}/{labels['arm']}"]
    assert cell["n"] == 1

    rendered = write_report(build_report(study, state=state, client=client), state.root / "r")
    assert "ERROR" in (rendered / "report.html").read_text(encoding="utf-8")


def bands_are_per_task(report: dict[str, Any]) -> bool:
    """A band names the (task, axis) whose arms disagreed, not just the axis.

    Two *tasks* using two graders is the normal case — each task has its own —
    and banding for that would band every multi-task study.
    """
    return bool(report["evidence"]["digests"]["split_cells"])


def test_two_tasks_with_their_own_graders_do_not_band_an_axis(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    state, _ = executed
    report = build_report(study, state=state, client=client).as_dict()
    # `acceptance` is scored on both tasks, by each task's own grader.
    assert len(report["evidence"]["digests"]["grader_spec_digests"]["acceptance"]) == 2
    assert report["axes"]["acceptance"]["banded"] is False
    assert "control" in report["axes"]["acceptance"]["contrasts"]


def test_a_split_grader_digest_bands_the_axis_and_withholds_the_ranking(
    study: Study, adp: FakeAdp, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    """Digest mismatch ⇒ no comparison."""
    state, _ = executed
    for record in adp.evals:
        if record.name == "acceptance" and adp.runs[record.run_id].labels["arm"] == "twin":
            adp.evals[adp.evals.index(record)] = type(record)(
                **{**record.__dict__, "spec_digest": "f" * 64}
            )

    report = build_report(study, state=state, client=client).as_dict()
    acceptance = report["axes"]["acceptance"]

    assert acceptance["banded"] is True
    assert "unavailable" in acceptance["contrasts"]
    assert any("different instruments" in warning for warning in report["warnings"])
    assert bands_are_per_task(report)

    rendered = write_report(build_report(study, state=state, client=client), state.root / "banded")
    assert "Banded" in (rendered / "report.html").read_text(encoding="utf-8")


def test_the_pre_registration_is_echoed_both_ways(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    state, _ = executed
    block = build_report(study, state=state, client=client).as_dict()["pre_registration"]
    assert block["digest"] == study.pre_registration.pre_registration_digest
    assert block["original_digest"] == study.pre_registration.original_digest
    assert block["as_registered"]["primary_metric"] == "acceptance"
    assert block["as_analyzed"]["primary_metric"] == "acceptance"


def test_process_metrics_reach_the_report(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    state, _ = executed
    process = build_report(study, state=state, client=client).as_dict()["process"]
    # The fixture trajectory calls `read_lines`, which is not in either arm's
    # toolset — a hallucinated call, computable because the study records the
    # vocabulary.
    for arm in ("standard", "twin"):
        assert process[arm]["hallucinated_call_rate"] == pytest.approx(0.25)
        assert "read_lines" in process[arm]["unknown_names"]
        assert process[arm]["tool_error_rate"] == pytest.approx(0.5)


# --- the artifacts -----------------------------------------------------------


def test_the_report_writes_json_and_a_self_contained_page(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any], tmp_path: Path
) -> None:
    state, _ = executed
    destination = write_report(build_report(study, state=state, client=client), tmp_path / "out")

    payload = json.loads((destination / "report.json").read_text(encoding="utf-8"))
    assert payload["study"]["digest"] == study.study_digest

    html = (destination / "report.html").read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    # Self-contained: nothing is fetched when the page opens.
    for external in ("<script", "src=", "@import", "<link"):
        assert external not in html
    assert study.study_digest in html


def test_the_report_survives_a_study_that_never_ran(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    """An empty report is a report, and it says the tasks were never run."""
    state = StateDir(tmp_path).ensure()
    report = build_report(study, state=state, client=client).as_dict()

    assert report["evidence"]["trials"] == 0
    assert set(report["evidence"]["missing_tasks"]) == {"json-normalizer", "retry-backoff"}
    assert any("never run" in warning for warning in report["warnings"])
    write_report(build_report(study, state=state, client=client), tmp_path / "empty")


def test_extraction_ignores_another_studys_runs_against_the_same_task(
    study: Study, adp: FakeAdp, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    state, _ = executed
    intent = state.known_intents()["json-normalizer"]
    client.create_run(
        study.adp.owner,
        study.adp.repo,
        intent_id=intent,
        orchestrator="somebody-else",
        external_ref="other-study:x",
        labels={"study": "sha256:" + "9" * 64, "arm": "theirs", "task": "json-normalizer"},
    )

    outcomes = extract(study, client=client, state=state)
    assert all(trial.arm_id != "theirs" for trial in outcomes.trials)


# --- process metrics as rankable axes ---------------------------------------


def test_a_process_metric_is_ranked_like_an_axis(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    """Study A's primary metric is the hallucinated-call rate, so it has to be
    something the report ranks rather than a footnote under the grader axes."""
    state, _ = executed
    report = build_report(study, state=state, client=client).as_dict()

    block = report["axes"]["process:hallucinated_call_rate"]
    assert {row["arm"] for row in block["arms"]} == {"standard", "twin"}
    assert all(row["mean"] == pytest.approx(0.25) for row in block["arms"])
    assert "pooled_sd" in block["noise_floor"]


def test_a_rate_contrast_reports_an_interval_and_no_invented_p_value(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    """A rate has no pass/fail outcome, so there is no exact test to run."""
    state, _ = executed
    report = build_report(study, state=state, client=client).as_dict()

    contrast = report["axes"]["process:tool_error_rate"]["contrasts"]["arms"]["twin"]
    assert "delta" in contrast and "ci" in contrast
    assert "unavailable" in contrast["mcnemar"]
    assert "holm_p" not in contrast


def _with_foreign(study: Study, commands: dict[str, list[str]]) -> Study:
    """The same study with foreign commands declared per arm.

    Declaring them moves the arm digest and therefore the study digest, which is
    why every test here runs the amended study rather than re-reporting the
    original: extraction matches runs by the study label, so re-reading old runs
    under a new definition of "foreign" would find nothing. That is the
    "digest mismatch ⇒ no comparison" rule doing exactly what it is for — a
    retuned escape list is a different instrument.
    """
    payload = study.model_dump()
    for arm in payload["arms"]:
        arm["foreign_commands"] = commands.get(arm["id"], [])
    return Study.model_validate(payload)


def _report_with_foreign(
    study: Study, client: AdpClient, tmp_path: Path, commands: dict[str, list[str]]
) -> dict[str, Any]:
    amended = _with_foreign(study, commands)
    state = StateDir(tmp_path)
    _run(amended, client, state, SmokeExecutor())
    return build_report(amended, state=state, client=client).as_dict()


def test_the_escape_metric_is_computed_when_the_study_declares_what_is_foreign(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    """Study B's primary metric after the 2026-08-11 amendment, end to end.

    The fixture trial runs `python3 /app/normalize.py < /dev/null`, so declaring
    `python3` foreign gives an arm that reached outside its toolchain exactly
    once — which is what the wiring has to carry from the spec, through
    `compute`, to a per-arm block and a rankable axis.
    """
    report = _report_with_foreign(
        study, client, tmp_path, {"standard": ["python3"], "twin": ["python3"]}
    )

    escape = report["process"]["standard"]["escape"]
    assert escape["escaped_trials"] == escape["measured_trials"]
    assert escape["escaped_rate"] == pytest.approx(1.0)
    assert escape["escaped_commands"] == ["python3"]
    assert escape["probe_calls"] == 0

    assert report["axes"]["process:escaped"]["arms"][0]["mean"] == pytest.approx(1.0)


def test_the_escape_axis_carries_an_exact_test_and_the_rates_do_not(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    """`escaped` is a per-trial yes/no, so it is the one process metric with a 2×2.

    The others are rates, where the interval is the inference. Getting this
    wrong in either direction matters: a p-value on a rate is invented, and
    withholding one from a genuine binary throws away the test the design
    pre-registered.
    """
    report = _report_with_foreign(
        study, client, tmp_path, {"standard": ["python3"], "twin": ["cat"]}
    )

    escaped = report["axes"]["process:escaped"]["contrasts"]["arms"]["twin"]
    assert "p" in escaped["mcnemar"]
    assert "holm_p" in escaped

    rate = report["axes"]["process:escape_to_familiar_rate"]["contrasts"]["arms"]["twin"]
    assert "unavailable" in rate["mcnemar"]


def test_an_arm_declaring_nothing_foreign_reports_no_escape_rather_than_zero(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    """The same discipline as every other rate here: no vocabulary, no number.

    A confident 0.0 would read as "never reached outside its toolchain" when it
    means "nobody said what outside was" — and this metric is now primary, so
    that reading would be the headline.
    """
    state, _ = executed
    report = build_report(study, state=state, client=client).as_dict()

    assert "unavailable" in report["process"]["standard"]["escape"]
    assert report["axes"]["process:escaped"]["arms"][0]["mean"] is None


def test_the_instrument_floor_is_the_gap_between_two_arms_that_should_not_differ(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    """The floor `oss` cannot supply, because `oss` differs in something real.

    Here the two "twins" are the smoke study's own arms, which replay different
    fixtures — so the floor is deliberately non-zero and the assertions are
    about the shape of the reading rather than about a value.
    """
    payload = study.model_dump()
    payload["pre_registration"]["instrument_arms"] = ["standard", "twin"]
    amended = Study.model_validate(payload)

    state = StateDir(tmp_path)
    _run(amended, client, state, SmokeExecutor())
    report = build_report(amended, state=state, client=client).as_dict()

    floor = report["axes"]["acceptance"]["instrument_floor"]
    assert floor["arms"] == ["standard", "twin"]
    assert floor["magnitude"] == pytest.approx(abs(floor["delta"]))
    assert floor["ci"]["low"] <= floor["delta"] <= floor["ci"]["high"]


def test_without_a_declared_pair_the_instrument_floor_says_so_rather_than_reading_zero(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    """Same discipline as every other refusal here: absent is not zero.

    A floor of 0.0 would say "changing nothing but a name costs nothing", which
    is the study's most interesting possible finding and not something a missing
    config key gets to assert.
    """
    state, _ = executed
    report = build_report(study, state=state, client=client).as_dict()

    floor = report["axes"]["acceptance"]["instrument_floor"]
    assert "unavailable" in floor
    assert "magnitude" not in floor

    contrast = report["axes"]["acceptance"]["contrasts"]["arms"]["twin"]
    assert "no instrument floor" in contrast["beyond_instrument_floor"]


def test_a_contrast_involving_a_floor_arm_is_not_scored_against_the_floor(
    study: Study, client: AdpClient, tmp_path: Path
) -> None:
    """An instrument arm against the control is partly the floor itself.

    Reporting `twin vs oss` as "clears the instrument floor" when `twin` is one
    of the two arms the floor is measured between would be reporting the noise
    as the signal.
    """
    payload = study.model_dump()
    payload["pre_registration"]["instrument_arms"] = ["standard", "twin"]
    amended = Study.model_validate(payload)

    state = StateDir(tmp_path)
    _run(amended, client, state, SmokeExecutor())
    report = build_report(amended, state=state, client=client).as_dict()

    contrast = report["axes"]["acceptance"]["contrasts"]["arms"]["twin"]
    assert "is one of the arms the floor is measured between" in contrast["beyond_instrument_floor"]


def test_a_grader_axis_still_carries_its_exact_test(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    state, _ = executed
    report = build_report(study, state=state, client=client).as_dict()
    contrast = report["axes"]["robustness"]["contrasts"]["arms"]["twin"]
    assert "p" in contrast["mcnemar"]
    assert "holm_p" in contrast


def test_a_rate_that_is_undefined_stays_out_of_the_numbers(
    study: Study, client: AdpClient, executed: tuple[StateDir, Any]
) -> None:
    """A trial with no tool calls has no error rate, and is counted as unscored
    on that axis rather than entering it as a zero."""
    state, _ = executed
    report = build_report(study, state=state, client=client).as_dict()
    block = report["axes"]["process:retry_rate"]
    for cell in block["cells"].values():
        assert all(isinstance(value, float) for value in cell["values"])


def _outcomes_with_costs(costs: list[int | None], arms: list[str] | None = None) -> Any:
    """A minimal StudyOutcomes carrying just the cost fields under test.

    ``None`` means unpriced. It is written as ``0`` on the outcome because
    :class:`TrialOutcome` types ``cost_micro_usd`` as ``int`` — which is the
    residual half of this defect: ADP reporting a genuine zero and ADP
    reporting nothing are the same value here, so "unpriced" is currently
    inferred from falsiness. That is right for every case this project can
    produce today (a priced call is never exactly zero) and it is not right in
    principle. See the ledger.
    """
    from duva_bench.analysis.extract import StudyOutcomes, TrialOutcome

    names = arms or [f"arm-{i}" for i in range(len(costs))]
    trials = [
        TrialOutcome(
            run_id=f"run-{i}",
            external_ref=f"ref-{i}",
            task_id="t",
            arm_id=names[i],
            repetition=1,
            labels={},
            verdict="VERIFIED",
            failures=(),
            axes=(),
            tokens_in=0,
            tokens_out=0,
            cost_micro_usd=cost or 0,
            duration_ms=0,
            tool_calls=0,
            tool_failures=0,
        )
        for i, cost in enumerate(costs)
    ]
    return StudyOutcomes(trials=trials)


def test_an_unpriced_trial_leaves_the_total_unstated_rather_than_low(tmp_path: Path) -> None:
    """§0.6: unpriced is not zero, and a total is a claim.

    The cost block used to sum every trial and report `priced_trials` beside the
    result, which added an unpriced trial in as zero. The oracle rehearsal on
    2026-08-10 printed `total_usd: 0.0` next to `unpriced_trials: 8` — true for
    an oracle that calls no model, and for a model whose price nobody has it
    would understate a study's cost silently and by an unknown amount.

    A report may decline to state a total. It may not state a wrong one.
    """
    from duva_bench.report.build import _cost_block

    outcomes = _outcomes_with_costs([120_000, None, 80_000])

    block = _cost_block(outcomes)

    assert block["total_usd"] is None, "a total was stated over an unpriced trial"
    assert block["total_micro_usd"] is None
    # What is known stays available: refusing to answer is not withholding.
    assert block["priced_micro_usd"] == 200_000
    assert block["priced_trials"] == 2
    assert block["unpriced_trials"] == 1


def test_a_fully_priced_study_still_gets_a_total(tmp_path: Path) -> None:
    """The refusal is conditional, or every report would be useless."""
    from duva_bench.report.build import _cost_block

    block = _cost_block(_outcomes_with_costs([120_000, 80_000]))

    assert block["unpriced_trials"] == 0
    assert block["total_micro_usd"] == 200_000
    assert block["total_usd"] == pytest.approx(0.2)


def test_an_arm_with_an_unpriced_trial_reports_no_arm_cost(tmp_path: Path) -> None:
    """An arm is what gets compared, so a short column there is worse than none."""
    from duva_bench.report.build import _cost_block

    block = _cost_block(_outcomes_with_costs([120_000, None], arms=["a", "a"]))

    assert block["by_arm"]["a"]["cost_micro_usd"] is None
    assert block["by_arm"]["a"]["priced_micro_usd"] == 120_000
    assert block["by_arm"]["a"]["unpriced_trials"] == 1
