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

    **Only invocations count.** The detector reads a call's shell text as a
    shell would: :mod:`shlex` with quoting respected, split into commands at
    the separators, environment assignments and wrapper prefixes dropped, and
    the *head* of each command judged. `grep -rn pytest .`,
    `echo "do not use pytest"` and `cat Makefile` name a foreign tool without
    running it and are not escapes; `python3 -m pytest` and
    `bash -c "pytest -q"` are. A bare word match caught all five, which is what
    the first version of this did — and the pilot separated the arms by six
    events out of twenty, so a single miscounted `grep` would have moved it.

``probe_calls`` and ``probed_commands``
    `which pytest`, `command -v make`, `type dbuild` — checking whether a
    foreign tool *exists*. Behaviourally interesting and not an escape: an
    agent that looks and then uses its own runner did not reach past it.
    Counted separately so the distinction survives, rather than being folded
    into a metric that is now primary.

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
import shlex
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

# Where one command ends and the next begins, for the fallback path only.
SEGMENTS = re.compile(r"[\n;&|()`]")

# Separator tokens as `shlex` emits them: `;`, `|`, `||`, `&`, `&&`, and the
# parentheses that bound a subshell or a `$(…)` substitution.
SEPARATOR_CHARACTERS = frozenset(";|&()")

# `FOO=bar cmd` — an assignment is not the command.
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Prefixes that run another command: the tool being invoked is what follows.
PREFIX_COMMANDS = frozenset({"env", "time", "nohup", "stdbuf", "nice", "sudo", "exec", "xargs"})

# Interpreters whose `-m <module>` form invokes a tool without naming it in
# command position. `python3 -m pytest` is the escape the 2026-08-11 pilot
# actually saw, four times in one trial, and a head-of-segment rule alone would
# score it as no escape at all.
MODULE_RUNNERS = frozenset({"python", "python3", "py", "uv", "pipx", "poetry"})

# Shells that take a command as a string argument.
SHELL_RUNNERS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})

# Asking whether a tool exists is not using it.
PROBE_COMMANDS = frozenset({"which", "command", "type", "hash", "whereis", "whatis"})


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
    # Calls that asked whether a foreign tool exists without running it. Kept
    # apart from `escape_calls` because a probe is a different behaviour, and
    # folding it in would inflate the metric this study now leads with.
    probe_calls: int | None = None
    probed_commands: tuple[str, ...] = ()

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
            "probe_calls": self.probe_calls,
            "probed_commands": list(self.probed_commands),
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
    probes = 0 if foreign_commands is not None else None
    probed: list[str] = []

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
            invoked, looked_up = _foreign_in(call, foreign_commands)
            if invoked:
                escapes = (escapes or 0) + 1
                escaped.extend(invoked)
            if looked_up:
                probes = (probes or 0) + 1
                probed.extend(looked_up)

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
        probe_calls=probes,
        probed_commands=tuple(sorted(set(probed))),
    )


def _foreign_in(
    call: TrajectoryEvent, foreign: tuple[str, ...] | frozenset[str]
) -> tuple[list[str], list[str]]:
    """Which foreign commands this call *invoked*, and which it merely probed.

    Read as a shell reads: split the text into segments at separators, drop
    leading environment assignments and wrapper prefixes, and judge the head of
    each segment. Naming a tool is not running it — `grep -rn pytest .` and
    `echo "no pytest here"` are not escapes — and running one without naming it
    in command position still is, which is why `python3 -m pytest` and
    `bash -c "pytest -q"` are followed through.

    Returns ``(invoked, probed)``, both deduplicated by the caller.
    """
    text = _command_text(call)
    if not text:
        return [], []
    return _scan(text, frozenset(foreign), depth=0)


def _scan(text: str, foreign: frozenset[str], *, depth: int) -> tuple[list[str], list[str]]:
    """The recursive half of :func:`_foreign_in`. ``depth`` bounds `sh -c` nesting."""
    invoked: list[str] = []
    probed: list[str] = []
    for tokens in _segments(text):
        while tokens and (
            _basename(tokens[0]) in PREFIX_COMMANDS or ASSIGNMENT.match(tokens[0]) is not None
        ):
            tokens = tokens[1:]
        if not tokens:
            continue

        head = _basename(tokens[0])
        rest = tokens[1:]

        if head in foreign:
            invoked.append(head)
            continue

        if head in PROBE_COMMANDS:
            # `command -v pytest` — the flag is not the thing being asked about.
            probed.extend(_basename(token) for token in rest if _basename(token) in foreign)
            continue

        if head in MODULE_RUNNERS and "-m" in rest:
            index = rest.index("-m")
            if index + 1 < len(rest):
                module = _basename(rest[index + 1])
                if module in foreign:
                    invoked.append(module)
            continue

        if head in SHELL_RUNNERS and depth < 2:
            inner = _shell_command_argument(rest)
            if inner:
                deeper_invoked, deeper_probed = _scan(inner, foreign, depth=depth + 1)
                invoked.extend(deeper_invoked)
                probed.extend(deeper_probed)
    return invoked, probed


def _segments(text: str) -> list[list[str]]:
    """One shell line as a list of commands, each a list of tokens.

    Tokenized by :mod:`shlex` rather than by splitting on separator characters,
    because quoting is the whole difficulty: `sh -c "cd x && pytest"` is one
    command whose argument happens to contain a separator, and a character split
    tears it in half. Redirections and their targets are dropped, so
    `cat notes > make` writes a file and does not run one.

    Unbalanced quotes — which an agent does type — make :mod:`shlex` raise. The
    fallback is the naive split, which under-reads a quoted inner command rather
    than inventing one.
    """
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return [segment.split() for segment in SEGMENTS.split(text)]

    segments: list[list[str]] = [[]]
    skip = False
    for token in tokens:
        if skip:
            skip = False
            continue
        if "<" in token or ">" in token:
            skip = True  # the redirection's target is not a command
            continue
        if token and set(token) <= SEPARATOR_CHARACTERS:
            segments.append([])
            continue
        segments[-1].append(token)
    return segments


def _shell_command_argument(tokens: list[str]) -> str:
    """The string `sh -c` was asked to run.

    Quoting has already been resolved by :func:`_segments`, so the command
    arrives as a single token; the flag before it is `-c` or one of the bundled
    forms an agent actually types (`-lc`, `-euc`).
    """
    for index, token in enumerate(tokens[:-1]):
        if token.startswith("-") and token.endswith("c"):
            return tokens[index + 1]
    return ""


def _basename(token: str) -> str:
    """`/usr/local/bin/dbuild` is `dbuild`; an absolute path is still an invocation."""
    return token.rsplit("/", 1)[-1]


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
