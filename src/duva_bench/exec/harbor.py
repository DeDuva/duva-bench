"""The Harbor adapter (M3).

Harbor is the executor: a fresh container per trial, adapters for real agent
CLIs, trace collection. duva-bench does not reimplement any of that — the whole
architectural bet is that building a container-per-trial executor ourselves
would be recreating a maintained wheel.

What this module owns is the seam:

* build the invocation for one (task, arm) pair, including the arm's env pins
* run it
* find what it wrote, and read the two files the bridge needs

Harbor is driven through its **CLI** rather than its Python API. It is an
optional dependency (`pip install 'duva-bench[harbor]'`) that requires Python
≥ 3.12 while this package supports 3.11, and its Python surface is large and
young. A subprocess boundary means a Harbor upgrade cannot break `import
duva_bench`, and the command that was run is a string this project can record
in the trial record and a human can paste into a shell.

Output layout, as of Harbor 0.20.0 and **as observed from a real run** rather
than inferred: a job writes ``<jobs-dir>/<job-name>/`` and each trial lands in a
subdirectory holding ``result.json`` (a ``TrialResult``) and
``agent/trajectory.json`` (an ATIF trajectory). The trial directory is found by
searching for ``result.json`` rather than by rebuilding Harbor's naming, because
the naming is Harbor's business and the file is the contract.

``--jobs-dir`` is passed as an absolute path. Harbor resolves it against its own
working directory, and a relative one produced a doubly-nested output tree that
neither this adapter nor a human could find.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from duva_bench.env import stripped_environment
from duva_bench.study.models import Arm, TaskRef

# The version this adapter was written against and the only one it claims to
# work with. Harbor's CLI is young; a floating dependency would make a trial
# that failed to launch indistinguishable from an arm that failed the task.
PINNED_HARBOR_VERSION = "0.20.0"

# Harbor 0.20.0 writes `result.json`, singular, one per trial directory. The
# fixtures in this repository were built against `results.json` — a name Harbor
# does not use — so `find_trial_dir` matched nothing on the first real run and
# every trial reported "Harbor wrote no results". The fixtures agreed with the
# code because both were written from the same guess; only a real trial could
# say. See docs/blockers.md.
RESULTS_FILE = "result.json"
TRAJECTORY_FILE = Path("agent") / "trajectory.json"


def verifier_reward(verifier: dict[str, Any]) -> float | bool | None:
    """The reward out of a Harbor ``verifier_result``, whichever shape it is in.

    Harbor 0.20.0 nests it: ``{"rewards": {"reward": 1.0}}``. This repository's
    fixtures carried a flat ``{"reward": 1.0, "status": "passed"}`` that Harbor
    does not write, so every reader of the flat key answered ``None`` on real
    data — and there were two such readers, in different modules, disagreeing
    with reality in the same way. One function now, so the next shape change is
    one edit rather than a hunt.
    """
    rewards = verifier.get("rewards")
    if isinstance(rewards, dict) and "reward" in rewards:
        candidate = rewards["reward"]
    else:
        candidate = verifier.get("reward")
    if isinstance(candidate, bool | int | float):
        return candidate
    return None


class HarborUnavailable(RuntimeError):
    """Harbor is not installed, or not the pinned version."""


class HarborFailed(RuntimeError):
    """Harbor ran and did not produce a trial."""


@dataclass(frozen=True)
class HarborTrial:
    """What one Harbor trial left on disk."""

    trial_dir: Path
    results: dict[str, Any]
    trajectory: dict[str, Any] | None
    command: tuple[str, ...]
    exit_code: int

    @property
    def agent_name(self) -> str | None:
        info = self.results.get("agent_info")
        return info.get("name") if isinstance(info, dict) else None

    @property
    def failed_with_exception(self) -> bool:
        return isinstance(self.results.get("exception_info"), dict)

    @property
    def graded_dir(self) -> Path:
        """What the grader is pointed at.

        Harbor collects files out of the container into ``<trial>/artifacts/``;
        the workspace itself is gone by the time anything can be graded, because
        the container is. So the artifacts directory *is* the work product, and
        a task that wants something graded has to publish it there.

        Falls back to the trial directory when nothing was collected, so a
        grader reports "nothing was written" rather than crashing on a missing
        path — an unscored trial and a broken grader must stay distinguishable.

        **Where the files actually are is read from Harbor's own manifest, not
        assumed.** Harbor 0.20.0 collects the container's ``/logs/artifacts``
        into ``<trial>/artifacts/logs/artifacts`` — it mirrors the source path
        underneath the destination rather than flattening it. Pointing a grader
        at ``<trial>/artifacts`` therefore hands it a directory containing one
        subdirectory and ``manifest.json``, and every grader scores 0 "never
        written" while the task's own verifier reports a pass. The manifest maps
        source to destination, so it is the thing to believe.
        """
        artifacts = self.trial_dir / "artifacts"
        if not artifacts.is_dir():
            return self.trial_dir
        collected = self._collected_dir(artifacts)
        return collected if collected is not None else artifacts

    def _collected_dir(self, artifacts: Path) -> Path | None:
        """The destination Harbor recorded for the container's artifacts dir."""
        manifest = artifacts / "manifest.json"
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("source", "")).rstrip("/").endswith("/logs/artifacts"):
                destination = entry.get("destination")
                if not isinstance(destination, str):
                    continue
                # Recorded relative to the trial directory, not to `artifacts/`.
                candidate = self.trial_dir / destination
                if candidate.is_dir():
                    return candidate
        return None

    @property
    def verifier_passed(self) -> bool | None:
        """Harbor's own verdict, or None when it never ran.

        None is not False. A verifier that did not run says nothing about the
        work, and folding it into "did not pass" is the same mistake as scoring
        an unscored trial zero.
        """
        verifier = self.results.get("verifier_result")
        if not isinstance(verifier, dict):
            return None
        # Harbor 0.20.0 writes `{"rewards": {"reward": 1.0}}`. The fixtures in
        # this repository carried a flat `{"reward": 1.0, "status": "passed"}`,
        # which Harbor does not produce — so this property answered None for
        # every real trial, and "the verifier did not run" is a very different
        # claim from "the verifier passed". Both shapes are read, because the
        # flat one is what a future Harbor might go back to and neither costs
        # anything to support.
        reward = verifier_reward(verifier)
        if isinstance(reward, bool):
            return reward
        if isinstance(reward, int | float):
            return reward > 0
        return None


class TrialExecutor(Protocol):
    """What :func:`duva_bench.exec.trial.run_trial` needs from an executor.

    A protocol rather than a class so tests can supply a recorded trial without
    a container runtime, and so a second executor (a different harness, a remote
    runner) is a new implementation rather than a fork of the trial runner.
    """

    def execute(
        self, task: TaskRef, arm: Arm, *, task_dir: Path, work_dir: Path, label: str
    ) -> HarborTrial: ...


@dataclass
class HarborExecutor:
    """Runs one trial through the Harbor CLI."""

    harbor: str = "harbor"
    timeout_seconds: float = 3600.0
    extra_args: tuple[str, ...] = ()
    # Environment for the Harbor process. Provider keys have to survive — the
    # agent inside the container needs them — so this is *not* the stripped
    # environment the grader gets. What is stripped is ADP: Harbor has no
    # business holding the runner token, and an agent that could reach ADP could
    # write its own trajectory.
    env: dict[str, str] = field(default_factory=dict)

    def resolve(self) -> str:
        """Where Harbor actually is.

        `shutil.which` first, then the directory holding the running
        interpreter. The second lookup is not a nicety: Harbor is installed as a
        console script into the same virtualenv as duva-bench, and running
        `.venv/bin/duva-bench` without activating that virtualenv leaves
        `.venv/bin` off PATH — so the executor would report Harbor missing while
        standing next to it. Invoking the package by absolute path is the
        documented way to run it, so it has to work.
        """
        found = shutil.which(self.harbor)
        if found:
            return found
        sibling = Path(sys.executable).parent / self.harbor
        if sibling.is_file():
            return str(sibling)
        raise HarborUnavailable(
            f"{self.harbor!r} is not on PATH and is not next to {sys.executable}. "
            "Install the extra with `pip install 'duva-bench[harbor]'` (Harbor requires "
            "Python >= 3.12), and note that it needs a container runtime as well."
        )

    def preflight(self) -> str:
        """Fail before a study starts rather than on its first trial."""
        completed = subprocess.run(
            [self.resolve(), "--version"], capture_output=True, text=True, timeout=120
        )
        version = (completed.stdout or completed.stderr).strip()
        if PINNED_HARBOR_VERSION not in version:
            raise HarborUnavailable(
                f"this adapter is written against Harbor {PINNED_HARBOR_VERSION}; the "
                f"installed one reports {version!r}. Pin it, or update the adapter and "
                "the [harbor] extra together."
            )
        return version

    def command(
        self,
        task_dir: Path,
        arm: Arm,
        *,
        jobs_dir: Path,
        label: str,
        harbor: str | None = None,
    ) -> list[str]:
        """The argv for one trial. Pure, so a test can read it.

        "Pure" is load-bearing and was briefly lost: resolving the Harbor binary
        in here made building an argv require Harbor to be *installed*, so two
        unit tests that only wanted to read the flags failed on any machine
        without it. `execute` passes the resolved path in; everyone else gets
        the configured name and no filesystem lookup.

        One task, one attempt, one concurrent trial: duva-bench schedules the
        factorial itself (M5) because the budget cap and the per-provider rate
        limits are study-level facts Harbor does not have.
        """
        argv = [
            harbor or self.harbor,
            "run",
            "--path",
            str(task_dir),
            "--agent",
            arm.harness.agent,
            "--model",
            f"{arm.model.provider}/{arm.model.model}",
            "--jobs-dir",
            str(jobs_dir),
            "--job-name",
            label,
            "--n-attempts",
            "1",
            "--n-concurrent",
            "1",
            "--quiet",
        ]
        for name, value in sorted(arm.env.items()):
            # The arm's environment pins, passed to the container rather than
            # inherited from whatever the operator happened to have exported.
            #
            # `--agent-env`, emphatically not `--env`: in Harbor 0.20.0 `--env`
            # chooses the *environment type* (`docker`, `modal`, `e2b`, …) and
            # would reject `LANG=C.UTF-8` as an unknown backend before building
            # anything. The two flags read alike and fail nothing alike.
            argv += ["--agent-env", f"{name}={value}"]
        for name, value in sorted(arm.model.parameters.items()):
            # Model parameters ride as agent kwargs. They are strings in the
            # study spec (floats are refused at the digest boundary), and this
            # is where they become the agent's problem rather than ours.
            argv += ["--agent-kwarg", f"{name}={value}"]
        return argv + list(self.extra_args)

    def execute(
        self, task: TaskRef, arm: Arm, *, task_dir: Path, work_dir: Path, label: str
    ) -> HarborTrial:
        # Absolute, and that matters: Harbor resolves `--jobs-dir` against its
        # own working directory, so a relative path lands somewhere neither this
        # process nor a human looking for the output would think to check. The
        # first real trial wrote its results to
        # `<work_dir>/<work_dir>/jobs/...` for exactly this reason.
        jobs_dir = (work_dir / "jobs").resolve()
        jobs_dir.mkdir(parents=True, exist_ok=True)
        argv = self.command(task_dir, arm, jobs_dir=jobs_dir, label=label, harbor=self.resolve())

        environment = {
            # ADP credentials are stripped and provider keys are kept: see the
            # comment on `env`. `keep` is empty on purpose.
            **stripped_environment(keep=()),
            **{name: value for name, value in os.environ.items() if _is_provider_key(name)},
            **self.env,
            **arm.env,
        }

        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            env=environment,
            cwd=work_dir,
        )

        trial_dir = find_trial_dir(jobs_dir / label)
        if trial_dir is None:
            raise HarborFailed(
                f"Harbor exited {completed.returncode} and wrote no {RESULTS_FILE} under "
                f"{jobs_dir / label}. Last stderr:\n{(completed.stderr or '')[-2000:]}"
            )
        return load_trial(trial_dir, command=tuple(argv), exit_code=completed.returncode)


def _is_provider_key(name: str) -> bool:
    """Provider credentials the agent inside the container needs.

    Named positively rather than by un-stripping: the default is that a secret
    does not travel, and every exception is one an operator can read.
    """
    upper = name.upper()
    return upper.startswith(
        (
            "ANTHROPIC_",
            "OPENAI_",
            "GOOGLE_",
            "GEMINI_",
            "AZURE_",
            "XAI_",
            "MISTRAL_",
            "COHERE_",
            "DEEPSEEK_",
            "TOGETHER_",
            "GROQ_",
            "OPENROUTER_",
        )
    )


# A trial's `result.json` carries these; a *job*'s does not. Harbor writes both
# files under the same name, one per job and one per trial, so "the newest
# result.json" picks the job summary — which has no `agent/trajectory.json`
# beside it, so the bridge silently produced zero events while everything else
# about the trial succeeded. Identify the file by what is in it, not by where it
# sits: the layout is Harbor's business, but these keys are the contract.
TRIAL_RESULT_KEYS = ("trial_name", "task_name")


def _is_trial_result(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and any(key in payload for key in TRIAL_RESULT_KEYS)


def find_trial_dir(job_dir: Path) -> Path | None:
    """The trial directory under ``job_dir``, found by its result file.

    Harbor's directory naming is Harbor's business and has changed between
    releases; ``result.json`` is the contract — but only the *trial* one. A job
    writes its own summary under the same name, and picking that one yields a
    directory with no trajectory in it.

    When a job wrote several trial results (it should not, at one attempt and
    one task), the newest wins and the caller gets a directory rather than an
    exception, because a trial that ran is worth recording even when the layout
    surprised us.
    """
    if not job_dir.exists():
        return None
    candidates = [path for path in job_dir.rglob(RESULTS_FILE) if _is_trial_result(path)]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime).parent


def load_trial(
    trial_dir: Path, *, command: tuple[str, ...] = (), exit_code: int = 0
) -> HarborTrial:
    """Read one finished trial directory. Also how fixtures are loaded."""
    results_path = trial_dir / RESULTS_FILE
    if not results_path.exists():
        raise HarborFailed(f"{results_path} does not exist")
    results = json.loads(results_path.read_text(encoding="utf-8"))

    trajectory: dict[str, Any] | None = None
    trajectory_path = trial_dir / TRAJECTORY_FILE
    if trajectory_path.exists():
        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))

    return HarborTrial(
        trial_dir=trial_dir,
        results=results,
        trajectory=trajectory,
        command=command,
        exit_code=exit_code,
    )
