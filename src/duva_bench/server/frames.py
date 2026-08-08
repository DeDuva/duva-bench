"""The SSE frame log (M7).

A study runs for hours. A browser tab watching it will lose its connection —
a laptop sleeps, a proxy times out, a phone changes network — and when it comes
back it must not have a hole in the middle of the trial grid.

So the stream is a **log with ids**, not a firehose. Every frame carries the
byte offset it ends at, the client sends its last id back as ``Last-Event-ID``
on reconnect, and the server replays from there. That is the whole design, and
it is squad-lab's, including the part that is easy to get wrong:

**the frame cache is keyed by file path, not by study id.**

Keying by study id looks equivalent and is not. Two studies can share an id
across a server restart (a digest is a study's id, and re-uploading the same
file gives the same digest), while a *file* is where the bytes actually are —
so a cache keyed on the id can hand a reconnecting client frames from a
different run of the same study, which is a hole that reads like data.

The offset is the id because ``progress.jsonl`` is append-only: a byte offset is
a resume point that survives a restart, needs no state on the server, and cannot
be invalidated by anything except the file being rewritten — which nothing does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Frame:
    """One line of progress, and the offset a client resumes from after it."""

    id: int
    event: str
    data: dict[str, Any]

    def as_sse(self) -> str:
        payload = json.dumps(self.data, sort_keys=True, separators=(",", ":"))
        return f"id: {self.id}\nevent: {self.event}\ndata: {payload}\n\n"


def read_frames(path: Path, *, after: int = 0) -> list[Frame]:
    """Frames from ``progress.jsonl`` after byte offset ``after``.

    A torn final line — what a kill mid-write leaves — is left in the file and
    not emitted. The next read picks it up once it is complete, which is why the
    offset advances only past lines that parsed.
    """
    path = Path(path)
    if not path.exists():
        return []

    raw = path.read_bytes()
    if after >= len(raw):
        return []

    frames: list[Frame] = []
    offset = after
    remainder = raw[after:]
    for line in remainder.split(b"\n"):
        end = offset + len(line) + 1
        if end > len(raw):
            # No trailing newline yet: the writer is mid-line. Stop here rather
            # than emitting half a record.
            break
        offset = end
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        frames.append(Frame(id=offset, event="trial", data=data))
    return frames


def resume_point(last_event_id: str | None) -> int:
    """The offset a reconnecting client asked to resume from.

    A malformed or missing header replays from the beginning. Replaying too much
    is a client seeing a row twice, which it can dedupe by ``external_ref``;
    replaying too little is a row nobody ever sees.
    """
    if not last_event_id:
        return 0
    try:
        value = int(last_event_id)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


class FrameCache:
    """Frames per progress file, keyed by path.

    See the module docstring for why the key is the path. The cache exists so a
    reconnect does not re-read a large file from disk for every client; it is
    not authoritative, and a miss simply reads again.
    """

    def __init__(self) -> None:
        self._frames: dict[str, list[Frame]] = {}
        self._sizes: dict[str, int] = {}

    def frames(self, path: Path, *, after: int = 0) -> list[Frame]:
        key = str(Path(path).resolve())
        size = Path(path).stat().st_size if Path(path).exists() else 0

        if self._sizes.get(key) != size:
            # The file grew (or was replaced). Re-read from the last frame we
            # hold, and drop everything if it shrank — a shrinking append-only
            # file is a different file.
            cached = self._frames.get(key, [])
            if size < self._sizes.get(key, 0):
                cached = []
            start = cached[-1].id if cached else 0
            cached = cached + read_frames(path, after=start)
            self._frames[key] = cached
            self._sizes[key] = size

        return [frame for frame in self._frames.get(key, []) if frame.id > after]

    def forget(self, path: Path) -> None:
        key = str(Path(path).resolve())
        self._frames.pop(key, None)
        self._sizes.pop(key, None)
