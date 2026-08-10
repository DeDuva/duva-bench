"""The trace bridge: Harbor's ATIF trajectory to ADP events (M3).

A pure function, `harbor_trace -> [AdpEvent]`, with no clock, no network and no
filesystem. That is not stylistic. The bridge is the one place where a
recorded experiment can quietly stop meaning what it says — a mis-mapped tool
call becomes a hallucinated-call rate that is wrong in a direction nobody
notices — so it has to be testable against fixtures, exactly, forever.

**What Harbor gives us.** Agents write an ATIF trajectory (Agent Trajectory
Interchange Format) to ``<trial>/agent/trajectory.json``: an ``agent`` block, a
list of ``steps``, and optional ``final_metrics``. A step carries a ``source``
(system/user/agent), a ``message``, optional ``tool_calls``, an optional
``observation`` holding one result per call, and optional per-step ``metrics``
(prompt/completion/cached tokens, ``cost_usd``). Harbor also writes
``<trial>/results.json`` — a ``TrialResult`` — whose ``verifier_result`` says
whether the task's own tests passed.

**What ADP takes.** Seven event kinds: ``message``, ``model_call``,
``tool_call``, ``handoff``, ``commit``, ``test_result``, ``custom``. Typed
columns for ``status``, ``model``, ``tokens_in``, ``tokens_out``,
``cost_micro_usd``, ``duration_ms``, ``git_sha``; everything else rides in an
opaque ``payload``.

**The mapping rule.** Map only what the trace supports, and make everything
unmapped a ``custom`` event rather than dropping it or guessing. A dropped
record is a trajectory that verifies perfectly and describes something that did
not happen.

Two decisions worth stating, because both could reasonably have gone the other
way:

* **A step's metrics become a separate ``model_call`` event**, not fields on the
  message. ADP counts tokens per event, and hanging them on a ``message`` would
  make ``byKind`` say the messages cost the money.
* **Tool status is inferred, and conservatively.** ATIF's observation result has
  no status field; producers put error information in ``extra`` (``is_error``,
  ``exit_code``, ``error``). When nothing says a call failed, it is recorded as
  ``success`` — but ``duva_bench.analysis`` computes the tool-error rate from
  ``status`` alone, so :data:`ERROR_KEYS` is the whole of what "failed" means
  here and it is deliberately explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# ADP's event kinds, from the contract's enum. Anything this bridge cannot place
# in one of the first six becomes `custom`.
ADP_KINDS = ("message", "model_call", "tool_call", "handoff", "commit", "test_result", "custom")

# Keys in an observation result's `extra` that mean the call did not succeed.
# ATIF has no status field, so this list *is* the definition of a failed tool
# call for every metric downstream.
ERROR_KEYS = ("is_error", "error", "failed", "exception")


@dataclass(frozen=True)
class AdpEvent:
    """One event, in the shape ``AdpClient.append_events`` wants.

    ``payload`` is always a dict — never None — because ADP's column is NOT NULL
    (execution-plan §3.1) and because a payload-less event is a row nobody can
    interpret later.
    """

    kind: str
    type: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    status: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_micro_usd: int | None = None
    duration_ms: int | None = None
    git_sha: str | None = None

    def as_fields(self) -> dict[str, Any]:
        """The keyword arguments for :meth:`Recorder.record`, minus the kind."""
        fields: dict[str, Any] = {"payload": self.payload}
        for name in (
            "type",
            "status",
            "model",
            "tokens_in",
            "tokens_out",
            "cost_micro_usd",
            "duration_ms",
            "git_sha",
        ):
            value = getattr(self, name)
            if value is not None:
                fields[name] = value
        return fields


def to_micro_usd(cost: Any) -> int | None:
    """Dollars to integer micro-dollars, or None.

    Through ``Decimal`` rather than ``int(cost * 1_000_000)``: the float path
    turns 0.0000015 into 1 on one machine and 2 on another, and a cost ledger
    that disagrees with itself across machines is not a ledger.
    """
    if cost is None or isinstance(cost, bool):
        return None
    try:
        amount = Decimal(str(cost))
    except (ValueError, ArithmeticError):
        return None
    return int((amount * 1_000_000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    return int(value) if isinstance(value, int | float) else None


def _text(message: Any) -> str:
    """ATIF messages are a string or a list of content parts."""
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return "".join(
            part.get("text", "")
            for part in message
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _tool_status(result: dict[str, Any] | None) -> str:
    """Whether a tool call failed, from whatever the producer said about it.

    ATIF has no status field. Producers record failure in the result's `extra`,
    and the keys vary by producer, so several are recognized. Absence of a
    result is not success: a call with no observation is a call whose outcome
    nobody recorded, and `error` is the honest reading of that.
    """
    if result is None:
        return "error"
    extra = result.get("extra")
    if isinstance(extra, dict):
        for key in ERROR_KEYS:
            value = extra.get(key)
            if value is True or (isinstance(value, str) and value):
                return "failure"
        exit_code = extra.get("exit_code")
        if isinstance(exit_code, int) and exit_code != 0:
            return "failure"
    return "success"


def bridge_trajectory(trajectory: dict[str, Any]) -> list[AdpEvent]:
    """Map one ATIF trajectory to ADP events, in trajectory order."""
    events: list[AdpEvent] = []
    agent = trajectory.get("agent") or {}
    default_model = agent.get("model_name")

    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        # A trajectory with no steps is not an empty trajectory; it is a
        # trajectory this bridge does not understand, and saying so in the
        # record is better than recording nothing and looking complete.
        return [
            AdpEvent(
                kind="custom",
                type="harbor.unreadable_trajectory",
                payload={"reason": "no `steps` array", "keys": sorted(trajectory)},
            )
        ]

    for step in steps:
        if not isinstance(step, dict):
            events.append(
                AdpEvent(kind="custom", type="harbor.unreadable_step", payload={"step": step})
            )
            continue
        events.extend(_bridge_step(step, default_model))

    metrics = trajectory.get("final_metrics")
    if isinstance(metrics, dict):
        # Recorded as `custom`, not as a second model_call: these are totals
        # over events already recorded, and adding them as a call would double
        # every token count in ADP's own stats.
        events.append(
            AdpEvent(
                kind="custom",
                type="harbor.final_metrics",
                payload=dict(metrics),
            )
        )

    return events


def _bridge_step(step: dict[str, Any], default_model: str | None) -> list[AdpEvent]:
    events: list[AdpEvent] = []
    step_id = step.get("step_id")
    source = step.get("source")
    message = _text(step.get("message"))

    if message or source in ("user", "system"):
        events.append(
            AdpEvent(
                kind="message",
                type=str(source) if source else None,
                payload={
                    "step_id": step_id,
                    "text": message,
                    **({"timestamp": step["timestamp"]} if step.get("timestamp") else {}),
                },
            )
        )

    metrics = step.get("metrics")
    if isinstance(metrics, dict):
        events.append(
            AdpEvent(
                kind="model_call",
                type="inference",
                model=step.get("model_name") or default_model,
                tokens_in=_int(metrics.get("prompt_tokens")),
                tokens_out=_int(metrics.get("completion_tokens")),
                cost_micro_usd=to_micro_usd(metrics.get("cost_usd")),
                payload={
                    "step_id": step_id,
                    "cached_tokens": metrics.get("cached_tokens"),
                    "llm_call_count": step.get("llm_call_count"),
                    **(
                        {"reasoning_effort": step["reasoning_effort"]}
                        if step.get("reasoning_effort") is not None
                        else {}
                    ),
                },
            )
        )

    observations = _observations_by_call(step.get("observation"))
    for call in step.get("tool_calls") or []:
        if not isinstance(call, dict):
            events.append(
                AdpEvent(kind="custom", type="harbor.unreadable_tool_call", payload={"call": call})
            )
            continue
        call_id = call.get("tool_call_id")
        result = observations.get(call_id)
        events.append(
            AdpEvent(
                kind="tool_call",
                # `type` is the tool's name, which is what ADP's per-tool stats
                # group by and what the hallucinated-call rate is computed from.
                type=str(call.get("function_name") or "unknown"),
                status=_tool_status(result),
                payload={
                    "step_id": step_id,
                    "tool_call_id": call_id,
                    "arguments": call.get("arguments") or {},
                    **({"result": _text(result.get("content"))} if result else {}),
                },
            )
        )

    unattributed = [result for key, result in observations.items() if key is None]
    for result in unattributed:
        # An observation with no source_call_id is environment feedback that did
        # not come from a call — a system event. It is not a tool result and
        # must not be counted as one.
        events.append(
            AdpEvent(
                kind="custom",
                type="harbor.observation",
                payload={"step_id": step_id, "content": _text(result.get("content"))},
            )
        )

    return events


def _observations_by_call(observation: Any) -> dict[str | None, dict[str, Any]]:
    if not isinstance(observation, dict):
        return {}
    mapped: dict[str | None, dict[str, Any]] = {}
    for result in observation.get("results") or []:
        if isinstance(result, dict):
            mapped[result.get("source_call_id")] = result
    return mapped


def bridge_verifier(results: dict[str, Any]) -> list[AdpEvent]:
    """Harbor's own verifier outcome, as a ``test_result`` event.

    Harbor's verifier is not duva-bench's grader and does not score anything:
    it answers "did the environment end up in the state the task asked for".
    Recording it as a `test_result` keeps that answer in the trajectory, where a
    reader can see it next to the separately-authorized eval rather than
    instead of it.
    """
    verifier = results.get("verifier_result")
    if not isinstance(verifier, dict):
        return []

    reward = verifier.get("reward")
    passed = _passed(verifier)
    return [
        AdpEvent(
            kind="test_result",
            type="harbor.verifier",
            status="success" if passed else "failure",
            payload={
                "reward": reward,
                "verifier": {
                    key: value
                    for key, value in verifier.items()
                    if key in ("reward", "status", "error", "metadata")
                },
            },
        )
    ]


def _passed(verifier: dict[str, Any]) -> bool:
    reward = verifier.get("reward")
    if isinstance(reward, bool):
        return reward
    if isinstance(reward, int | float):
        return reward > 0
    status = verifier.get("status")
    return isinstance(status, str) and status.lower() in ("pass", "passed", "success")


def bridge_exception(results: dict[str, Any]) -> list[AdpEvent]:
    """Whatever Harbor recorded about a trial that blew up.

    Kept as `custom` rather than silently dropped: a trial that failed for an
    infrastructure reason has to be distinguishable from an arm that failed the
    task, and the difference lives in this record.
    """
    info = results.get("exception_info")
    if not isinstance(info, dict):
        return []
    return [
        AdpEvent(
            kind="custom",
            type="harbor.exception",
            status="error",
            payload={
                "exception_type": info.get("exception_type"),
                "exception_message": info.get("exception_message"),
            },
        )
    ]


def bridge(
    trajectory: dict[str, Any] | None,
    results: dict[str, Any] | None = None,
    *,
    final_git_sha: str | None = None,
) -> list[AdpEvent]:
    """The whole bridge: trajectory, verifier outcome, exception, commit.

    Pure. Given the same inputs it returns the same events, which is what makes
    ``tests/fixtures/`` a meaningful check rather than a smoke test.
    """
    events: list[AdpEvent] = []
    if trajectory:
        events.extend(bridge_trajectory(trajectory))
    if results:
        events.extend(bridge_verifier(results))
        events.extend(bridge_exception(results))
    if final_git_sha:
        events.append(
            AdpEvent(
                kind="commit",
                type="harbor.final_state",
                git_sha=final_git_sha,
                payload={"source": "duva-bench"},
            )
        )
    return events
