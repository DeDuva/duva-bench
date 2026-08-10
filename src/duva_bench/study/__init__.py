"""Study specs, their canonical digest, and their pre-registration (M1)."""

from __future__ import annotations

from duva_bench.study.digest import digest_payload, short
from duva_bench.study.load import (
    StudyFileError,
    dump_study,
    load_study,
    parse_study,
    write_study,
)
from duva_bench.study.models import (
    AdpTarget,
    Amendment,
    Arm,
    DocsBundle,
    GitSource,
    HarnessSpec,
    ModelSpec,
    PreRegistration,
    Study,
    TaskRef,
    ToolsetSpec,
)

__all__ = [
    "AdpTarget",
    "Amendment",
    "Arm",
    "DocsBundle",
    "GitSource",
    "HarnessSpec",
    "ModelSpec",
    "PreRegistration",
    "Study",
    "StudyFileError",
    "TaskRef",
    "ToolsetSpec",
    "digest_payload",
    "dump_study",
    "load_study",
    "parse_study",
    "short",
    "write_study",
]
