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

    preflight = subcommands.add_parser(
        "preflight", help="Check the ADP contract and the identity separation"
    )
    preflight.add_argument("study", type=Path)
    preflight.set_defaults(handler=_preflight)

    trial = subcommands.add_parser("trial", help="Run a single trial")
    trial.add_argument("study", type=Path)
    trial.add_argument("--task", required=True)
    trial.add_argument("--arm", required=True)
    trial.add_argument("--repetition", type=int, default=1)
    trial.add_argument("--state-dir", type=Path, default=None)
    trial.set_defaults(handler=_trial)

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


def _preflight(args: argparse.Namespace) -> int:
    from duva_bench.adp.preflight import preflight
    from duva_bench.env import adp_credentials
    from duva_bench.study.load import load_study

    study = load_study(args.study)
    with adp_credentials().client() as client:
        result = preflight(client, study.adp.owner, study.adp.repo, strict=False)
    _print_json(
        {
            "ok": result.ok,
            "contract_version": result.contract_version,
            "reporter_principal": result.reporter_principal,
            "separately_authorized": result.separately_authorized,
        }
    )
    return 0 if result.ok else 1


def _trial(args: argparse.Namespace) -> int:
    from duva_bench.exec.trial import Trial, run_trial
    from duva_bench.state import StateDir
    from duva_bench.study.load import load_study

    study = load_study(args.study)
    record = run_trial(
        study,
        Trial(task_id=args.task, arm_id=args.arm, repetition=args.repetition),
        state=StateDir.for_study(study, args.state_dir),
        study_dir=args.study.parent,
    )
    _print_json(record.model_dump(mode="json"))
    return 0 if record.ok else 1


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
