"""The Harbor seam, checked against a real Harbor (M3).

Everything else about the adapter is tested against recorded fixtures, which is
right for the trace bridge — a trajectory is a document, and a document is
exactly what a fixture is. It is *not* right for the command line. An argv is a
claim about another program's interface, and a fixture of our own argv can only
tell us we still build the string we used to build.

The `harbor` marker existed from M0 and was used by **zero** tests, so excluding
it from `make check` excluded nothing, and the adapter shipped calling `--env`
when it meant `--agent-env` — a flag Harbor does have, for choosing the
container backend, so the mistake reads as plausible right up until every trial
dies before building anything.

These run only where Harbor is installed. `make test` excludes them; run them
with `pytest -m harbor` on a machine with the `[harbor]` extra.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from duva_bench.exec.harbor import PINNED_HARBOR_VERSION, HarborExecutor
from duva_bench.study.load import load_study

pytestmark = pytest.mark.harbor

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "smoke"


@pytest.fixture(scope="module")
def harbor_help() -> str:
    try:
        harbor = HarborExecutor().resolve()
    except Exception as missing:  # HarborUnavailable, imported lazily below
        pytest.fail(
            f"{missing} These tests are marked `harbor` and are excluded from `make test`; "
            "if you selected them, install the extra: pip install 'duva-bench[harbor]' "
            "(needs Python >= 3.12)."
        )
    completed = subprocess.run(
        [harbor, "run", "--help"], capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr
    # Harbor renders help in a box-drawing table and wraps long flag names with a
    # trailing ellipsis, so a flag can appear as `--agent-timeout-multip…`. Strip
    # the decoration; membership is tested against whole words below.
    return completed.stdout


def _flags(text: str) -> set[str]:
    """Every long flag the help text offers, ignoring truncated ones."""
    return {m.group(0) for m in re.finditer(r"--[a-z][a-z0-9-]+", text)}


def test_the_installed_harbor_is_the_pinned_one() -> None:
    """A floating Harbor makes a launch failure look like a failing arm."""
    assert HarborExecutor().preflight().strip() == PINNED_HARBOR_VERSION


def test_every_flag_the_adapter_emits_exists_in_harbors_cli(harbor_help: str) -> None:
    """The test that would have caught `--env`.

    Not "does the adapter still produce the argv it produced yesterday" but
    "does Harbor accept every flag in it". The two questions look alike and only
    the second one can fail when Harbor changes underneath us.
    """
    study = load_study(EXAMPLES / "study.yaml")
    argv = HarborExecutor().command(
        EXAMPLES / "tasks" / "json-normalizer",
        study.arm("standard"),
        jobs_dir=Path("/tmp/jobs"),
        label="flags",
    )
    available = _flags(harbor_help)
    emitted = {token for token in argv if token.startswith("--")}
    missing = emitted - available
    assert not missing, (
        f"the adapter passes flags Harbor 0.20.0 does not accept: {sorted(missing)}. "
        "Check `harbor run --help` and fix HarborExecutor.command()."
    )


def test_env_pins_do_not_go_to_the_environment_type_flag(harbor_help: str) -> None:
    """`--env` and `--agent-env` both exist and mean different things.

    Asserted against Harbor's own help rather than against a belief about it, so
    that the day Harbor renames either one, this says so.
    """
    assert "--agent-env" in _flags(harbor_help)
    assert "--env" in _flags(harbor_help)

    study = load_study(EXAMPLES / "study.yaml")
    arm = study.arm("standard")
    assert arm.env, "this test is vacuous unless the arm pins an environment variable"
    argv = HarborExecutor().command(
        EXAMPLES / "tasks" / "json-normalizer", arm, jobs_dir=Path("/tmp/jobs"), label="flags"
    )
    for name, value in arm.env.items():
        assert f"{name}={value}" in argv
        assert argv[argv.index(f"{name}={value}") - 1] == "--agent-env"


def test_the_agent_the_smoke_study_names_is_one_harbor_offers(harbor_help: str) -> None:
    """A study naming an agent Harbor does not have fails at the first trial.

    Harbor prints the agent enum inside a box-drawing table and wraps it mid-name,
    so `terminus-2` really appears as `t` at the end of one line and `erminus-2`
    at the start of the next. Matching has to happen after the decoration comes
    out, or this test fails on every agent whose name is unlucky.
    """
    flat = re.sub(r"[\s│┃|]+", "", harbor_help)
    study = load_study(EXAMPLES / "study.yaml")
    for arm in study.arms:
        assert arm.harness.agent in flat, (
            f"arm {arm.id!r} names agent {arm.harness.agent!r}, which does not appear in "
            "`harbor run --help`. Harbor names many agents; this machine offers these."
        )


def test_the_task_directories_the_study_points_at_are_harbor_tasks() -> None:
    """Harbor identifies a task by its `task.toml`; a missing one is a 404 late."""
    study = load_study(EXAMPLES / "study.yaml")
    for task in study.tasks:
        assert task.path is not None
        directory = EXAMPLES / task.path
        assert (directory / "task.toml").is_file(), f"{task.id}: no task.toml in {directory}"
        assert (directory / "environment" / "Dockerfile").is_file(), f"{task.id}: no Dockerfile"


def test_the_graders_the_study_pins_still_hash_to_their_pin() -> None:
    """An instrument that changed without its digest changing is not the instrument."""
    import hashlib

    raw = yaml.safe_load((EXAMPLES / "study.yaml").read_text(encoding="utf-8"))
    for entry in raw["tasks"]:
        grader = EXAMPLES / entry["grader_path"]
        digest = hashlib.sha256(grader.read_bytes()).hexdigest()
        assert digest == entry["grader_sha256"], (
            f"{entry['id']}: {grader} hashes to {digest}, study.yaml pins {entry['grader_sha256']}"
        )
