"""duva-bench — controlled factorial experiments over coding-agent arms.

The package is deliberately importable with only the three core dependencies
installed (pydantic, httpx, pyyaml). Execution needs Harbor and analysis needs a
reachable ADP, but *reading* a published study — validating its spec,
recomputing its digest, reconciling its report — must work on any machine, and
that property is enforced by keeping the heavy imports inside the modules that
need them rather than at package import time.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("duva-bench")
except PackageNotFoundError:  # pragma: no cover - only when running from a source tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
