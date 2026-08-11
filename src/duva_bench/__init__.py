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

# The identity of *this* project as an instrument, recorded on every run.
#
# `__version__` cannot do this job: it is `0.0.0` and would not move when the
# Harbor invocation or the trace mapping changes, which is exactly when two runs
# stop being comparable. Gate G1 is the proof — seven defects were fixed in the
# adapter and the bridge in one day, and runs from before and after were
# indistinguishable in ADP because the only harness identity recorded was
# Harbor's own agent and version.
#
# This is deliberately **not** part of the study spec. A study is data, its
# digest is pre-registered before execution, and a digest that moved when this
# project was edited would make pre-registration meaningless. It rides on the
# run as a label instead, where analysis bands on it: two trials of one arm
# produced by different adapter versions are not comparable, and
# `digest_bands` says so rather than ranking them.
#
# **Bump this when the meaning of a recorded trial changes** — the Harbor
# command, the trial-directory contract, the trace-to-event mapping, or what
# gets published as the attested subject. Not for refactors, docs or tests.
ADAPTER_VERSION = "2"

__all__ = ["ADAPTER_VERSION", "__version__"]
