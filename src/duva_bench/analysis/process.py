"""Process metrics: what the arm did, not just how it scored (M6).

An outcome score says whether the task got done. These say *how*, and they are
where a controlled experiment earns its keep — two arms can pass at the same
rate and differ completely in how many tool calls they got wrong on the way.

Five metrics, computed from ADP trajectories:

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

``escape_to_familiar_rate`` and ``escaped``
    Calls that invoke a toolchain the arm was **not** given — running `pytest`
    in a project whose test runner is called something else, or `make` in a
    depot that builds with `dbuild`.

    This is not the hallucinated-call rate under another name. That one asks
    whether a *tool the agent was handed* was used correctly; this asks whether
    the agent reached past the tools it was handed for the one it has read a
    million times. The first is about a vocabulary, the second about a habit.

    It exists because of the 2026-08-11 pilot, where it was the only measure
    that separated the arms at n=20 while the outcome axis showed nothing:

    ==============  =================  =====================
    arm             used its runner    ran `pytest` directly
    ==============  =================  =====================
    oss             20/20              0/20
    twin            14/20              6/20
    proprietary     19/20              3/20
    ==============  =================  =====================

    Note which arm escapes most. The *twin* — identical to `oss` in behaviour
    and different only in names — abandons its own runner far more often than
    the wholly foreign depot does. The depot is obviously alien, so the agent
    reads the instructions; the twin looks like an ordinary project with odd
    names, so habit fires and misfires. **Partial unfamiliarity may cost more
    than total unfamiliarity**, which is a sharper claim than "unfamiliar is
    worse" and the one worth testing.

    That observation was made *after* looking at the data and is therefore a
    hypothesis, not a result. It is pre-registered in the Study B design
    document and must be tested on trials that did not generate it.

    ``escaped`` — whether a trial reached out *at all* — is usually the better
    unit than the per-call rate, which is diluted by however much other work a
    trial happened to do.

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
    # Commands invoking a toolchain this arm was not given. `None` where the arm
    # declares no foreign commands — the rate is then not computed at all rather
    # than reported as a flattering zero.
    escape_calls: int | None = None
    escaped_commands: tuple[str, ...] = ()

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
    def escape_to_familiar_rate(self) -> float | None:
        """Share of this trial's calls that reached outside its own toolchain.

        See the module docstring for what this measures and why it is not the
        hallucinated-call rate under another name.
        """
        if self.escape_calls is None or not self.tool_calls:
            return None
        return self.escape_calls / self.tool_calls

    @property
    def escaped(self) -> bool | None:
        """Whether this trial reached outside its toolchain *at all*.

        The per-call rate is diluted by however much other work a trial happened
        to do; whether an agent abandoned its toolchain even once is the cleaner
        unit, and it is the one that separated arms in the 2026-08-11 pilot.
        """
        return None if self.escape_calls is None else self.escape_calls > 0

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
            "escape_calls": self.escape_calls,
            "escape_to_familiar_rate": self.escape_to_familiar_rate,
            "escaped": self.escaped,
            "escaped_commands": list(self.escaped_commands),
        }


def compute(
    events: tuple[TrajectoryEvent, ...] | list[TrajectoryEvent],
    *,
    toolset: frozenset[str] | set[str] | None = None,
    foreign_commands: tuple[str, ...] | frozenset[str] | None = None,
) -> ProcessMetrics:
    """Process metrics for one trial's trajectory.

    ``toolset`` is the arm's *effective* tool names — the twin's, for a twinned
    arm. Without it the hallucinated-call rate is not computed at all rather
    than computed against an assumption.

    ``foreign_commands`` are the command words that belong to a toolchain this
    arm was **not** given. Same discipline: absent, the escape rate is `None`
    rather than zero.
    """
    calls = [event for event in events if event.kind == "tool_call"]
    failures = sum(1 for call in calls if (call.status or "") in FAILED_STATUSES)

    retries = 0
    previous: tuple[str, str] | None = None
    hallucinated = 0
    unknown: list[str] = []
    metaprogramming = 0
    escapes = 0 if foreign_commands is not None else None
    escaped: list[str] = []

    for call in calls:
        name = call.type or "unknown"
        signature = (name, _arguments_key(call))
        if previous is not None and signature == previous:
            retries += 1
        previous = signature

        if toolset is not None and name not in toolset:
            hallucinated += 1
            unknown.append(name)

        if foreign_commands is not None:
            found = _foreign_in(call, foreign_commands)
            if found:
                escapes = (escapes or 0) + 1
                escaped.extend(found)

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
        escape_calls=escapes,
        escaped_commands=tuple(sorted(set(escaped))),
    )


def _foreign_in(call: TrajectoryEvent, foreign: tuple[str, ...] | frozenset[str]) -> list[str]:
    """Which foreign commands this call invoked, if any.

    Matched on whole words at the start of a command or after a shell separator,
    so `make test` counts and a path like `/usr/bin/makefile-lint` does not. The
    point is to catch *invoking* a tool the arm was not given, not mentioning it.
    """
    text = _command_text(call)
    if not text:
        return []
    found = []
    for command in foreign:
        if re.search(rf"(?:^|[|&;()\s]){re.escape(command)}(?=[\s;|&]|$)", text):
            found.append(command)
    return found


def _command_text(call: TrajectoryEvent) -> str:
    """The shell text a call ran, across the argument names agents use for it."""
    payload = call.payload if isinstance(call.payload, dict) else {}
    arguments = payload.get("arguments")
    if not isinstance(arguments, dict):
        return ""
    for key in ("keystrokes", "command", "cmd", "input"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return ""


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
