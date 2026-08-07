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
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


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
