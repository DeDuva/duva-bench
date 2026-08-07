"""The duva-bench command line.

Stdlib ``argparse``, no CLI framework: execution-plan §2 lists three runtime
dependencies and a fourth would need a justification this does not have.

Every subcommand is a thin shell over a function in a package module, and the
JSON API (M7) serves *those functions*, not a subprocess call to this file. That
is what "the web UX is a client of the API, never a second path" costs: nothing
below this module may reach back up into it.

Subcommand handlers import their module inside the handler rather than at module
import, so `duva-bench --version` works in a checkout where Harbor or the server
extra is not installed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from duva_bench import __version__


def _print_json(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="duva-bench",
        description="Define, execute, and analyze controlled experiments over coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"duva-bench {__version__}")
    subcommands = parser.add_subparsers(dest="command", metavar="<command>")

    validate = subcommands.add_parser("validate", help="Validate a study file")
    validate.add_argument("study", type=Path)
    validate.set_defaults(handler=_validate)

    digest = subcommands.add_parser("digest", help="Print a study's canonical digest")
    digest.add_argument("study", type=Path)
    digest.add_argument(
        "--part",
        choices=("study", "pre-registration", "arms"),
        default="study",
        help="Which digest to print (default: the whole study)",
    )
    digest.set_defaults(handler=_digest)

    return parser


# --- handlers ---------------------------------------------------------------


def _validate(args: argparse.Namespace) -> int:
    from duva_bench.study.load import load_study

    study = load_study(args.study)
    _print_json(
        {
            "ok": True,
            "title": study.title,
            "study_digest": study.study_digest,
            "tasks": [task.id for task in study.tasks],
            "arms": [arm.id for arm in study.arms],
            "trials": study.trial_count,
        }
    )
    return 0


def _digest(args: argparse.Namespace) -> int:
    from duva_bench.study.load import load_study

    study = load_study(args.study)
    if args.part == "study":
        print(study.study_digest)
    elif args.part == "pre-registration":
        registration = study.pre_registration
        _print_json(
            {
                "pre_registration_digest": registration.pre_registration_digest,
                "original_digest": registration.original_digest,
                "amended": registration.amended,
            }
        )
    else:
        _print_json({arm.id: arm.arm_digest for arm in study.arms})
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    result: int = handler(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
