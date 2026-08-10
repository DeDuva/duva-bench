"""Process metrics: what the arm did, not just how it scored (M6).

An outcome score says whether the task got done. These say *how*, and they are
where a controlled experiment earns its keep — two arms can pass at the same
rate and differ completely in how many tool calls they got wrong on the way.

Four metrics, computed from ADP trajectories:

``tool_error_rate``
    Tool calls whose recorded status is a failure, over all tool calls. The
    status comes from the trace bridge, which infers it from the harness's
    observation record — so this metric is exactly as good as
    :data:`duva_bench.exec.bridge.ERROR_KEYS`, and that is stated rather than
    implied.

``retry_rate``
    Consecutive repeats of the same tool with the same arguments. Not a
    measure of persistence: a measure of an agent going round the same loop.

``hallucinated_call_rate``
    **The primary metric of Study A.** Calls to a tool name that is not in the
    arm's toolset. Computable only because the twin's rename map is kept: for a
    twinned arm, a call to the *original* vocabulary is a call to a tool that
    does not exist, and the map is what says so.

``metaprogramming_rate``
    Calls that escape the toolset into general execution — writing a script and
    running it rather than using the tool provided. Study B's variable, and a
    confound for Study A if it is not measured: an agent that cannot use an
    unfamiliar tool may simply route around it, which looks like success and is
    a different behaviour.

Every rate is ``None`` rather than ``0.0`` when its denominator is zero. A trial
with no tool calls has no tool-error rate; recording one as zero would put "did
not use tools" and "used tools perfectly" in the same column.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from duva_bench.adp.models import TrajectoryEvent

# Commands that run code the agent wrote, rather than doing the task through the
# tools it was given. Matched against the *command* argument of a shell-style
# tool call. Deliberately narrow: `python -c`, `bash script.sh` and friends are
# metaprogramming; `ls` and `cat` are just using a terminal.
METAPROGRAMMING = re.compile(
    r"\b(python3?|node|deno|bun|ruby|perl|php)\b\s+(-c\b|-e\b|[\w./-]+\.(py|js|mjs|ts|rb|pl|php))"
    r"|\b(bash|sh|zsh)\b\s+([\w./-]+\.(sh|bash))"
    r"|\bchmod\s+\+x\b",
    re.IGNORECASE,
)

FAILED_STATUSES = frozenset({"failure", "error", "rejected"})


@dataclass(frozen=True)
class ProcessMetrics:
    """Per-trial process metrics. Rates are None when undefined, never zero."""

    tool_calls: int = 0
    tool_failures: int = 0
    retries: int = 0
    hallucinated_calls: int = 0
    metaprogramming_calls: int = 0
    unknown_names: tuple[str, ...] = ()

    @property
    def tool_error_rate(self) -> float | None:
        return self.tool_failures / self.tool_calls if self.tool_calls else None

    @property
    def retry_rate(self) -> float | None:
        return self.retries / self.tool_calls if self.tool_calls else None

    @property
    def hallucinated_call_rate(self) -> float | None:
        return self.hallucinated_calls / self.tool_calls if self.tool_calls else None

    @property
    def metaprogramming_rate(self) -> float | None:
        return self.metaprogramming_calls / self.tool_calls if self.tool_calls else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_calls": self.tool_calls,
            "tool_failures": self.tool_failures,
            "tool_error_rate": self.tool_error_rate,
            "retries": self.retries,
            "retry_rate": self.retry_rate,
            "hallucinated_calls": self.hallucinated_calls,
            "hallucinated_call_rate": self.hallucinated_call_rate,
            "metaprogramming_calls": self.metaprogramming_calls,
            "metaprogramming_rate": self.metaprogramming_rate,
            "unknown_names": list(self.unknown_names),
        }


def compute(
    events: tuple[TrajectoryEvent, ...] | list[TrajectoryEvent],
    *,
    toolset: frozenset[str] | set[str] | None = None,
) -> ProcessMetrics:
    """Process metrics for one trial's trajectory.

    ``toolset`` is the arm's *effective* tool names — the twin's, for a twinned
    arm. Without it the hallucinated-call rate is not computed at all rather
    than computed against an assumption.
    """
    calls = [event for event in events if event.kind == "tool_call"]
    failures = sum(1 for call in calls if (call.status or "") in FAILED_STATUSES)

    retries = 0
    previous: tuple[str, str] | None = None
    hallucinated = 0
    unknown: list[str] = []
    metaprogramming = 0

    for call in calls:
        name = call.type or "unknown"
        signature = (name, _arguments_key(call))
        if previous is not None and signature == previous:
            retries += 1
        previous = signature

        if toolset is not None and name not in toolset:
            hallucinated += 1
            unknown.append(name)

        if _is_metaprogramming(call):
            metaprogramming += 1

    return ProcessMetrics(
        tool_calls=len(calls),
        tool_failures=failures,
        retries=retries,
        hallucinated_calls=hallucinated,
        metaprogramming_calls=metaprogramming,
        # Sorted and deduplicated: this is evidence for a reader, and a bag of
        # repeats would bury the one name that matters.
        unknown_names=tuple(sorted(set(unknown))),
    )


def _arguments_key(call: TrajectoryEvent) -> str:
    payload = call.payload if isinstance(call.payload, dict) else {}
    arguments = payload.get("arguments")
    try:
        return json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(arguments)


def _is_metaprogramming(call: TrajectoryEvent) -> bool:
    payload = call.payload if isinstance(call.payload, dict) else {}
    arguments = payload.get("arguments")
    if not isinstance(arguments, dict):
        return False
    for key in ("command", "cmd", "script", "code"):
        value = arguments.get(key)
        if isinstance(value, str) and METAPROGRAMMING.search(value):
            return True
    return False


def effective_toolset(
    labels: dict[str, str], toolsets: dict[str, frozenset[str]]
) -> frozenset[str] | None:
    """The tool names an arm actually had, from its run labels.

    Returns None when the study did not record a toolset for this arm, so the
    hallucinated-call rate goes uncomputed rather than being computed against
    the wrong vocabulary — which would report every legitimate call as a
    hallucination and look like a spectacular finding.
    """
    return toolsets.get(labels.get("toolset", ""))
