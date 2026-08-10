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

Output layout, as of Harbor 0.20.0: a job writes ``<jobs-dir>/<job-name>/`` and
each trial lands in a subdirectory holding ``results.json`` (a ``TrialResult``)
and ``agent/trajectory.json`` (an ATIF trajectory). The trial directory is found
by searching for ``results.json`` rather than by rebuilding Harbor's naming,
because the naming is Harbor's business and the file is the contract.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from duva_bench.env import stripped_environment
from duva_bench.study.models import Arm, TaskRef

# The version this adapter was written against and the only one it claims to
# work with. Harbor's CLI is young; a floating dependency would make a trial
# that failed to launch indistinguishable from an arm that failed the task.
PINNED_HARBOR_VERSION = "0.20.0"

RESULTS_FILE = "results.json"
TRAJECTORY_FILE = Path("agent") / "trajectory.json"


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
    def verifier_passed(self) -> bool | None:
        """Harbor's own verdict, or None when it never ran.

        None is not False. A verifier that did not run says nothing about the
        work, and folding it into "did not pass" is the same mistake as scoring
        an unscored trial zero.
        """
        verifier = self.results.get("verifier_result")
        if not isinstance(verifier, dict):
            return None
        reward = verifier.get("reward")
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

    def preflight(self) -> str:
        """Fail before a study starts rather than on its first trial."""
        if shutil.which(self.harbor) is None:
            raise HarborUnavailable(
                f"{self.harbor!r} is not on PATH. Install the extra with "
                "`pip install 'duva-bench[harbor]'` (Harbor requires Python >= 3.12), "
                "and note that it needs a container runtime as well."
            )
        completed = subprocess.run(
            [self.harbor, "--version"], capture_output=True, text=True, timeout=120
        )
        version = (completed.stdout or completed.stderr).strip()
        if PINNED_HARBOR_VERSION not in version:
            raise HarborUnavailable(
                f"this adapter is written against Harbor {PINNED_HARBOR_VERSION}; the "
                f"installed one reports {version!r}. Pin it, or update the adapter and "
                "the [harbor] extra together."
            )
        return version

    def command(self, task_dir: Path, arm: Arm, *, jobs_dir: Path, label: str) -> list[str]:
        """The argv for one trial. Pure, so a test can read it.

        One task, one attempt, one concurrent trial: duva-bench schedules the
        factorial itself (M5) because the budget cap and the per-provider rate
        limits are study-level facts Harbor does not have.
        """
        argv = [
            self.harbor,
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
            argv += ["--env", f"{name}={value}"]
        for name, value in sorted(arm.model.parameters.items()):
            # Model parameters ride as agent kwargs. They are strings in the
            # study spec (floats are refused at the digest boundary), and this
            # is where they become the agent's problem rather than ours.
            argv += ["--agent-kwarg", f"{name}={value}"]
        return argv + list(self.extra_args)

    def execute(
        self, task: TaskRef, arm: Arm, *, task_dir: Path, work_dir: Path, label: str
    ) -> HarborTrial:
        jobs_dir = work_dir / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        argv = self.command(task_dir, arm, jobs_dir=jobs_dir, label=label)

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


def find_trial_dir(job_dir: Path) -> Path | None:
    """The trial directory under ``job_dir``, found by its results file.

    Harbor's directory naming is Harbor's business and has changed between
    releases; ``results.json`` is the contract. When a job wrote several (it
    should not, at one attempt and one task), the newest wins and the caller
    gets a directory rather than an exception, because a trial that ran is
    worth recording even when the layout surprised us.
    """
    if not job_dir.exists():
        return None
    candidates = sorted(job_dir.rglob(RESULTS_FILE), key=lambda path: path.stat().st_mtime)
    return candidates[-1].parent if candidates else None


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
