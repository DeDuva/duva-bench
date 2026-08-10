"""M0: the package imports, and the CLI answers before anything else is built."""

from __future__ import annotations

import argparse
import subprocess
import sys

import pytest

import duva_bench
from duva_bench.cli import build_parser, main


def test_the_package_reports_a_version() -> None:
    assert duva_bench.__version__


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert duva_bench.__version__ in capsys.readouterr().out


def test_no_subcommand_prints_help_and_fails() -> None:
    assert main([]) == 2


def test_the_installed_entry_point_runs() -> None:
    """`pip install -e .` then `duva-bench --version`, via the module path.

    Spawned rather than called so this covers the console script's own import
    path: a module that only imports under the test session's already-warm
    interpreter is not a module a user can run.
    """
    result = subprocess.run(
        [sys.executable, "-m", "duva_bench.cli", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert duva_bench.__version__ in result.stdout


def test_every_subcommand_has_a_handler() -> None:
    """A subcommand parsed but not dispatched would exit 2 with no explanation.

    Vacuous at M0, on purpose: each milestone adds subcommands and this is what
    stops one from arriving without a dispatch entry.
    """
    parser = build_parser()
    actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert actions, "the CLI declares no subcommand group"
    for name, subparser in actions[0].choices.items():
        assert subparser.get_default("handler") is not None, f"{name} has no handler"
