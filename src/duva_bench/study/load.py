"""Reading and writing study files (M1).

YAML in, YAML out, and the digest is the same on both sides. That round trip is
not a convenience: an amended study is written back out by tooling, and a
serializer that reorders a mapping or reformats a number would give the amended
file a different digest for reasons that have nothing to do with the experiment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from duva_bench.study.models import Study


class StudyFileError(ValueError):
    """A study file that cannot be read as a study."""


def parse_study(source: str | bytes, *, origin: str = "<string>") -> Study:
    """Parse YAML (or JSON, which is YAML) into a :class:`Study`."""
    try:
        document = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise StudyFileError(f"{origin} is not valid YAML: {error}") from None

    if not isinstance(document, dict):
        raise StudyFileError(f"{origin} is not a study: the document is not a mapping")

    try:
        return Study.model_validate(document)
    except ValidationError as error:
        raise StudyFileError(f"{origin} is not a valid study:\n{error}") from None


def load_study(path: Path) -> Study:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise StudyFileError(f"cannot read {path}: {error}") from None
    return parse_study(text, origin=str(path))


def study_document(study: Study) -> dict[str, Any]:
    """The plain-data form of a study — what gets digested and written."""
    return study.model_dump(mode="json")


def dump_study(study: Study) -> str:
    """Serialize a study to YAML.

    ``sort_keys=True`` matches the digest's canonical ordering, so the file on
    disk reads in the same order the digest was computed in. ``default_flow_style
    =False`` keeps it block-formatted and reviewable in a diff.
    """
    return yaml.safe_dump(
        study_document(study),
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )


def write_study(study: Study, path: Path) -> Path:
    path = Path(path)
    path.write_text(dump_study(study), encoding="utf-8")
    return path


def grader_source(study_path: Path, task_id: str, study: Study) -> Path:
    """Where a task's grader actually lives on disk.

    Grader paths in a study file are relative to the study file, not to the
    process's working directory: a study is a document that travels, and a
    relative path resolved against the caller's cwd resolves differently
    depending on where the caller was standing.
    """
    task = study.task(task_id)
    return (Path(study_path).parent / task.grader_path).resolve()
