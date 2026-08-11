"""M3: the trace bridge, against fixtures.

The fixture in `tests/fixtures/harbor/` was validated against Harbor 0.20.0's
own `Trajectory` model when it was written, so these assertions are about a
document Harbor would actually produce rather than one that only this bridge
would accept.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from duva_bench.exec.bridge import AdpEvent, bridge, bridge_trajectory, to_micro_usd
from duva_bench.exec.harbor import load_trial

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "harbor"


@pytest.fixture
def trajectory() -> dict[str, Any]:
    path = FIXTURES / "terminus-2-json-normalizer" / "agent" / "trajectory.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def results() -> dict[str, Any]:
    path = FIXTURES / "terminus-2-json-normalizer" / "result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def kinds(events: list[AdpEvent]) -> list[str]:
    return [event.kind for event in events]


# --- the mapping ------------------------------------------------------------


def test_every_tool_call_becomes_a_tool_call_event(trajectory: dict[str, Any]) -> None:
    events = bridge_trajectory(trajectory)
    calls = [event for event in events if event.kind == "tool_call"]
    assert [event.type for event in calls] == [
        "read_file",
        "write_file",
        "run_command",
        "read_lines",
    ]


def test_a_tool_name_lands_in_type_where_adp_groups_on_it(trajectory: dict[str, Any]) -> None:
    """`type` is what ADP's per-tool stats group by, and what the hallucinated-call
    rate is computed from. In the payload it would be invisible to both."""
    call = next(e for e in bridge_trajectory(trajectory) if e.kind == "tool_call")
    assert call.type == "read_file"
    assert call.payload["arguments"] == {"path": "/app/instruction.md"}


def test_a_nonzero_exit_code_is_a_failed_call(trajectory: dict[str, Any]) -> None:
    events = bridge_trajectory(trajectory)
    run_command = next(e for e in events if e.type == "run_command")
    assert run_command.status == "failure"


def test_an_is_error_flag_is_a_failed_call(trajectory: dict[str, Any]) -> None:
    events = bridge_trajectory(trajectory)
    assert next(e for e in events if e.type == "read_lines").status == "failure"


def test_a_call_with_no_observation_is_an_error_not_a_success() -> None:
    """Nobody recorded the outcome. That is not the same as it having worked."""
    events = bridge_trajectory(
        {
            "agent": {"name": "a", "version": "1"},
            "steps": [
                {
                    "step_id": 1,
                    "source": "agent",
                    "message": "",
                    "tool_calls": [{"tool_call_id": "c1", "function_name": "t", "arguments": {}}],
                }
            ],
        }
    )
    assert next(e for e in events if e.kind == "tool_call").status == "error"


def test_step_metrics_become_a_model_call_not_fields_on_the_message(
    trajectory: dict[str, Any],
) -> None:
    events = bridge_trajectory(trajectory)
    calls = [event for event in events if event.kind == "model_call"]
    assert len(calls) == 3
    first = calls[0]
    assert first.tokens_in == 1200
    assert first.tokens_out == 90
    assert first.model == "anthropic/claude-sonnet-4-5-20250929"
    # The message it came from carries no tokens: `byKind` must not report that
    # the messages cost the money.
    message = next(event for event in events if event.kind == "message")
    assert message.tokens_in is None and message.cost_micro_usd is None


def test_cost_is_carried_as_integer_micro_dollars(trajectory: dict[str, Any]) -> None:
    events = bridge_trajectory(trajectory)
    assert [e.cost_micro_usd for e in events if e.kind == "model_call"] == [4200, 13100, 900]


@pytest.mark.parametrize(
    ("dollars", "micro"),
    [
        (0.0042, 4200),
        (0.0000015, 2),  # half-up, deterministically — not float rounding
        (0, 0),
        (None, None),
        ("0.25", 250000),
        (True, None),  # a bool is not a cost
    ],
)
def test_micro_dollar_conversion(dollars: Any, micro: int | None) -> None:
    assert to_micro_usd(dollars) == micro


def test_messages_keep_their_source(trajectory: dict[str, Any]) -> None:
    events = bridge_trajectory(trajectory)
    messages = [event for event in events if event.kind == "message"]
    assert messages[0].type == "user"
    assert messages[1].type == "agent"


def test_an_observation_with_no_source_call_is_not_counted_as_a_tool_result(
    trajectory: dict[str, Any],
) -> None:
    events = bridge_trajectory(trajectory)
    stray = [e for e in events if e.type == "harbor.observation"]
    assert len(stray) == 1
    assert stray[0].kind == "custom"
    assert "memory limit" in stray[0].payload["content"]


def test_final_metrics_are_custom_not_a_second_model_call(trajectory: dict[str, Any]) -> None:
    """They are totals over events already recorded; recording them as a call
    would double every token count in ADP's own stats."""
    events = bridge_trajectory(trajectory)
    totals = next(e for e in events if e.type == "harbor.final_metrics")
    assert totals.kind == "custom"
    assert totals.tokens_in is None
    assert totals.payload["total_prompt_tokens"] == 6610


def test_the_verifier_result_becomes_a_test_result(
    trajectory: dict[str, Any], results: dict[str, Any]
) -> None:
    events = bridge(trajectory, results)
    verifier = next(e for e in events if e.kind == "test_result")
    assert verifier.status == "success"
    assert verifier.payload["reward"] == 1.0


def test_a_failing_verifier_is_a_failure_not_an_absence(trajectory: dict[str, Any]) -> None:
    events = bridge(trajectory, {"verifier_result": {"reward": 0.0}})
    assert next(e for e in events if e.kind == "test_result").status == "failure"


def test_a_crashed_trial_records_the_exception_rather_than_nothing() -> None:
    trial = load_trial(FIXTURES / "terminus-2-crashed")
    events = bridge(trial.trajectory, trial.results)
    exception = next(e for e in events if e.type == "harbor.exception")
    assert exception.kind == "custom"
    assert exception.status == "error"
    assert exception.payload["exception_type"] == "AgentTimeoutError"
    # And no test_result at all: the verifier never ran, which is not a failure.
    assert "test_result" not in kinds(events)


def test_a_final_git_sha_becomes_a_commit_event(trajectory: dict[str, Any]) -> None:
    events = bridge(trajectory, None, final_git_sha="a" * 40)
    commit = next(e for e in events if e.kind == "commit")
    assert commit.git_sha == "a" * 40


# --- the rules the bridge is held to ----------------------------------------


def test_every_event_has_one_of_adps_kinds(
    trajectory: dict[str, Any], results: dict[str, Any]
) -> None:
    from duva_bench.exec.bridge import ADP_KINDS

    assert set(kinds(bridge(trajectory, results))) <= set(ADP_KINDS)


def test_every_event_carries_a_payload(trajectory: dict[str, Any], results: dict[str, Any]) -> None:
    """ADP's payload column is NOT NULL, and a payload-less row is unreadable."""
    for event in bridge(trajectory, results):
        assert isinstance(event.payload, dict)
        assert isinstance(event.as_fields()["payload"], dict)


def test_nothing_in_the_trace_is_dropped_silently() -> None:
    """An unmapped record becomes `custom`, never nothing."""
    events = bridge_trajectory(
        {
            "agent": {"name": "a", "version": "1"},
            "steps": [{"step_id": 1, "source": "agent", "message": "", "tool_calls": ["nonsense"]}],
        }
    )
    assert any(event.type == "harbor.unreadable_tool_call" for event in events)


def test_a_trajectory_with_no_steps_says_so_rather_than_looking_complete() -> None:
    events = bridge_trajectory({"agent": {"name": "a", "version": "1"}})
    assert kinds(events) == ["custom"]
    assert events[0].type == "harbor.unreadable_trajectory"


def test_the_bridge_is_pure(trajectory: dict[str, Any], results: dict[str, Any]) -> None:
    """Same inputs, same events — which is what makes the fixture a check."""
    before = json.dumps(trajectory, sort_keys=True)
    first = [event.as_fields() for event in bridge(trajectory, results)]
    second = [event.as_fields() for event in bridge(trajectory, results)]
    assert first == second
    assert json.dumps(trajectory, sort_keys=True) == before, "the bridge mutated its input"


def test_the_whole_bridged_trace_is_stable(
    trajectory: dict[str, Any], results: dict[str, Any]
) -> None:
    """One assertion over the whole mapping, so a silent change shows up here."""
    events = bridge(trajectory, results, final_git_sha="b" * 40)
    assert kinds(events) == [
        "message",  # step 1, user
        "message",  # step 2, agent
        "model_call",
        "tool_call",  # read_file
        "message",  # step 3
        "model_call",
        "tool_call",  # write_file
        "tool_call",  # run_command (failed)
        "tool_call",  # read_lines (failed, not in the toolset)
        "custom",  # the unattributed observation
        "message",  # step 4
        "model_call",
        "custom",  # final_metrics
        "test_result",
        "commit",
    ]


# --- against a trajectory a real agent actually wrote ------------------------


REAL = FIXTURES / "real-terminus-2-json-normalizer"


def test_a_real_terminus_2_trajectory_bridges_without_inventing_failures() -> None:
    """The fixture that closed gate G1, and the defect it caught.

    Every other fixture in this directory was written by this project from
    Harbor's documentation. This one was produced by Harbor 0.20.0 running
    `terminus-2` against a real model, on the trial recorded in
    `docs/blockers.md` — and it disagrees with the hand-written ones in a way
    that mattered: its observation results carry only `content`, with no
    `source_call_id` and no `tool_call_id`.

    Correlating results to calls by id therefore found nothing, "no result
    recorded" reads as `error`, and the first real trial reported **16 tool
    calls and 16 tool failures** for a task whose own verifier passed. The
    tool-error rate is a primary process metric for Study A, so a bridge that
    marks every call failed does not produce a slightly wrong number — it
    produces a study that cannot be read at all.
    """
    trajectory = json.loads((REAL / "agent" / "trajectory.json").read_text(encoding="utf-8"))
    results = json.loads((REAL / "result.json").read_text(encoding="utf-8"))

    events = bridge(trajectory, results, final_git_sha=None)
    tool_calls = [event for event in events if event.kind == "tool_call"]

    assert tool_calls, "a real trajectory that used tools bridged no tool_call events"
    failed = [event for event in tool_calls if event.status != "success"]
    assert not failed, (
        f"{len(failed)} of {len(tool_calls)} tool calls bridged as failures from a "
        "trajectory whose task passed its verifier"
    )

    # And the results really were correlated, not merely defaulted to success.
    assert all("result" in (event.payload or {}) for event in tool_calls)


def test_the_real_trajectory_carries_the_usage_harbor_summaries_lose() -> None:
    """The 2026-08-08 probe found `claude-code` reporting zero tokens.

    `terminus-2` does not: the per-step metrics carry usage, so `model_call`
    events reach ADP with tokens and cost on them. Pinned because every cost
    figure on this track depends on it, and because the failure mode is a
    plausible-looking zero rather than an error.
    """
    trajectory = json.loads((REAL / "agent" / "trajectory.json").read_text(encoding="utf-8"))
    results = json.loads((REAL / "result.json").read_text(encoding="utf-8"))

    calls = [e for e in bridge(trajectory, results, final_git_sha=None) if e.kind == "model_call"]
    assert calls, "no model_call events bridged from a real trajectory"
    assert sum(c.tokens_in or 0 for c in calls) > 0, "every model_call reported zero input tokens"
    assert sum(c.tokens_out or 0 for c in calls) > 0, "every model_call reported zero output tokens"


def test_bridged_usage_reconciles_with_the_agents_own_totals() -> None:
    """Every cost figure on this track descends from these five events.

    The 2026-08-08 probe found Harbor's `results.json` reporting
    `total_input_tokens: 0` for `claude-code` while the agent's own log carried
    full usage — a plausible-looking zero rather than an error, which is the
    worst shape a wrong number can take. M2 was written to take usage from the
    agent log for that reason, and this asserts the arithmetic actually holds
    for `terminus-2`.

    The trajectory states its own totals in `final_metrics`, independently of
    the per-step `metrics` the bridge reads. Summing one and comparing it to the
    other is a real cross-check: they are two different fields, written by the
    producer, that have to agree. If a future agent reports per-step usage that
    does not add up to what it claims overall, a study's cost ledger is wrong
    and nothing else would say so.
    """
    trajectory = json.loads((REAL / "agent" / "trajectory.json").read_text(encoding="utf-8"))
    results = json.loads((REAL / "result.json").read_text(encoding="utf-8"))
    totals = trajectory["final_metrics"]

    calls = [e for e in bridge(trajectory, results, final_git_sha=None) if e.kind == "model_call"]

    assert sum(c.tokens_in or 0 for c in calls) == totals["total_prompt_tokens"]
    assert sum(c.tokens_out or 0 for c in calls) == totals["total_completion_tokens"]

    # Cost is carried in micro-USD integers, so the comparison is to the nearest
    # micro-dollar rather than exact: floats are refused at the digest boundary
    # for the same reason they are not trusted here.
    bridged_micro = sum(c.cost_micro_usd or 0 for c in calls)
    stated_micro = round(totals["total_cost_usd"] * 1_000_000)
    assert abs(bridged_micro - stated_micro) <= len(calls), (
        f"bridged {bridged_micro} micro-USD against a stated {stated_micro}; "
        "per-step costs do not add up to the trajectory's own total"
    )


def test_cached_tokens_are_not_silently_dropped_from_the_prompt_count() -> None:
    """Cache reads are most of the prompt, and they are not free.

    This trajectory reports 8,384 cached of 13,297 prompt tokens. `prompt_tokens`
    already includes them, so the bridge must not add `cached_tokens` on top —
    doing so would inflate the input count by 60% here, and the error would grow
    with exactly the caching that makes long studies affordable.
    """
    trajectory = json.loads((REAL / "agent" / "trajectory.json").read_text(encoding="utf-8"))
    results = json.loads((REAL / "result.json").read_text(encoding="utf-8"))
    totals = trajectory["final_metrics"]
    assert totals.get("total_cached_tokens", 0) > 0, "this fixture no longer exercises caching"

    calls = [e for e in bridge(trajectory, results, final_git_sha=None) if e.kind == "model_call"]
    bridged_in = sum(c.tokens_in or 0 for c in calls)

    assert bridged_in == totals["total_prompt_tokens"]
    assert bridged_in != totals["total_prompt_tokens"] + totals["total_cached_tokens"]
