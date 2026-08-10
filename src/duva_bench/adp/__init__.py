"""ADP: the system of record duva-bench writes every trial to (M2)."""

from __future__ import annotations

from duva_bench.adp.client import AdpClient, AdpError, AppendRejected
from duva_bench.adp.gate import Verdict, verdict_from, verify_gate
from duva_bench.adp.models import (
    AppendReceipt,
    ComparisonEval,
    EvalRecord,
    Run,
    RunComparison,
    RunStats,
    Trajectory,
    TrajectoryEvent,
    VerifyResult,
)
from duva_bench.adp.preflight import PreflightFailed, PreflightResult, preflight
from duva_bench.adp.recorder import Recorder, RecorderStats, RecorderStopped
from duva_bench.adp.spool import Spool, SpoolCorrupt
from duva_bench.adp.version import EXPECTED_API_VERSION, ApiVersionMismatch, assert_api_version

__all__ = [
    "EXPECTED_API_VERSION",
    "AdpClient",
    "AdpError",
    "ApiVersionMismatch",
    "AppendReceipt",
    "AppendRejected",
    "ComparisonEval",
    "EvalRecord",
    "PreflightFailed",
    "PreflightResult",
    "Recorder",
    "RecorderStats",
    "RecorderStopped",
    "Run",
    "RunComparison",
    "RunStats",
    "Spool",
    "SpoolCorrupt",
    "Trajectory",
    "TrajectoryEvent",
    "Verdict",
    "VerifyResult",
    "assert_api_version",
    "preflight",
    "verdict_from",
    "verify_gate",
]
