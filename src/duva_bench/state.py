"""Local state, and the rule about what may live in it.

A result is a record reconstructible from ADP, not from local state. So what is
on disk here is **pointers and progress**: which ADP run a trial became, whether
its evidence verified, and how far the study got. No scores, no statistics, no
trajectories.

That rule is what makes the report trustworthy. If a number could come from a
local file, then re-deriving the report on another machine could produce a
different one, and nobody could tell which was the experiment. Everything M6
prints is read back from ADP, and this directory only says where to look.

Layout, under ``.duva-bench/<study-digest[:12]>/``:

``trials/<external-ref>.json``
    One :class:`~duva_bench.exec.trial.TrialRecord` per trial.

``spools/<external-ref>/``
    The recorder's spool, kept until the trial's events are acknowledged.

``progress.jsonl``
    Append-only, one line per completed trial. What makes a study resumable.

``intents.json``
    Task id to ADP intent id. Minting is idempotent per task per study, and
    this is the cache that makes it so without an extra round trip.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from duva_bench.study.models import Study

DEFAULT_ROOT = Path(".duva-bench")

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(value: str) -> str:
    """A filename-safe form of an ``external_ref``.

    ``external_ref``s are colon-separated by convention, which is legal in a
    POSIX filename and awkward everywhere else. The mapping is not reversed
    anywhere — the record carries the real ref — so collapsing runs of unsafe
    characters is enough.
    """
    return _UNSAFE.sub("_", value).strip("_") or "unnamed"


@dataclass(frozen=True)
class StateDir:
    """Where one study's local state lives."""

    root: Path

    @classmethod
    def for_study(cls, study: Study, root: Path | None = None) -> StateDir:
        """The state directory for ``study``, keyed by its digest.

        Keyed by digest rather than by title or file path: two files with the
        same title are two studies if their digests differ, and mixing their
        progress would make a resume complete the wrong trials.
        """
        base = Path(root) if root is not None else DEFAULT_ROOT
        return cls(base / study.slug)

    # --- paths ----------------------------------------------------------------

    @property
    def trials(self) -> Path:
        return self.root / "trials"

    @property
    def spools(self) -> Path:
        return self.root / "spools"

    @property
    def progress(self) -> Path:
        return self.root / "progress.jsonl"

    @property
    def intents(self) -> Path:
        return self.root / "intents.json"

    def trial_record(self, external_ref: str) -> Path:
        return self.trials / f"{safe_name(external_ref)}.json"

    def spool(self, external_ref: str) -> Path:
        return self.spools / safe_name(external_ref)

    def ensure(self) -> StateDir:
        self.trials.mkdir(parents=True, exist_ok=True)
        self.spools.mkdir(parents=True, exist_ok=True)
        return self

    # --- reads and writes -----------------------------------------------------

    def write_json(self, path: Path, payload: Any) -> Path:
        """Write JSON atomically.

        Atomic because a half-written trial record read by a resume is a resume
        that either crashes or, worse, decides the trial is missing and runs it
        again.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(payload, out, indent=2, sort_keys=True)
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return path

    def read_json(self, path: Path) -> Any | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def append_progress(self, entry: dict[str, Any]) -> None:
        """Append one completed trial to the progress log.

        Append-only and flushed per line: the log is read by a rerun to decide
        what is left to do, and a line that was buffered when the process died
        is a trial that gets run twice.
        """
        self.progress.parent.mkdir(parents=True, exist_ok=True)
        with self.progress.open("a", encoding="utf-8") as out:
            out.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
            out.flush()
            os.fsync(out.fileno())

    def progress_entries(self) -> list[dict[str, Any]]:
        """Every completed-trial line, oldest first, ignoring a torn last line."""
        if not self.progress.exists():
            return []
        entries: list[dict[str, Any]] = []
        lines = self.progress.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                if number == len(lines):
                    break  # torn by a kill; the trial simply looks unfinished
                raise
            entries.append(entry)
        return entries

    def known_intents(self) -> dict[str, str]:
        cached = self.read_json(self.intents)
        return dict(cached) if isinstance(cached, dict) else {}

    def remember_intent(self, task_id: str, intent_id: str) -> None:
        intents = self.known_intents()
        intents[task_id] = intent_id
        self.write_json(self.intents, intents)
