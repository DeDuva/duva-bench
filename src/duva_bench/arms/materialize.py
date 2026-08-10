"""Arm materialization: one task, prepared for one arm (M4).

A Harbor task directory is the same for every arm; what differs is the toolset
the agent is handed, the documentation in the environment, and the environment
pins. Materializing produces a per-arm copy of the task with those three applied,
and a digest over exactly what was applied.

The copy is deliberate. Editing the task in place would make the second arm's
trial depend on the first arm's leftovers, which is the kind of contamination
that produces a real-looking effect and no explanation for it.

What is written into the copy:

``duva/toolset.json``
    The toolset definition the arm gets — the twin's, when the arm twins one.

``duva/rename_map.json``
    Only for a twinned arm, and only inside the *materialization record*, never
    inside the container. An agent that could read the rename map would be an
    agent handed the answer; the map exists so analysis can compute the
    hallucinated-call rate afterwards.

``docs/TOOLS.md``
    The documentation bundle, at the arm's grade. Absent at grade ``none``.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from duva_bench.arms.docs import DocsBundleContent, render_docs
from duva_bench.arms.twin import Twin, twin_toolset
from duva_bench.study.digest import digest_payload
from duva_bench.study.models import Arm, TaskRef

TOOLSET_FILE = Path("duva") / "toolset.json"
DOCS_DIR = Path("docs")
INSTRUCTION = "instruction.md"

DOCS_POINTER = "\n\n---\n\nDocumentation for the tools in this environment is in `docs/TOOLS.md`.\n"


@dataclass(frozen=True)
class MaterializedTask:
    """A task directory prepared for one arm."""

    task_id: str
    arm_id: str
    path: Path
    toolset: dict[str, Any]
    docs: DocsBundleContent
    # None for an arm whose toolset is the original. Kept out of the task
    # directory on purpose — see the module docstring.
    rename_map: dict[str, Any] | None
    digest: str

    def write_rename_map(self, destination: Path) -> Path | None:
        """Persist the rename map *outside* the container's reach.

        Analysis needs it: a call to a name in the original vocabulary, made by
        an arm that was given the twin, is a hallucinated call, and that is only
        computable with this map. The trial needs it not at all.
        """
        if self.rename_map is None:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.rename_map, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return destination


def materialize(
    task: TaskRef,
    arm: Arm,
    *,
    source: Path,
    destination: Path,
    toolset_definition: dict[str, Any],
) -> MaterializedTask:
    """Copy ``source`` to ``destination`` and apply the arm to the copy."""
    source = Path(source)
    destination = Path(destination)
    if not (source / INSTRUCTION).exists():
        raise FileNotFoundError(f"{source} does not look like a Harbor task: no {INSTRUCTION}")

    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)

    twin: Twin | None = None
    if arm.toolset.twin_of is not None:
        assert arm.toolset.twin_seed is not None  # the spec refuses one without the other
        twin = twin_toolset(toolset_definition, seed=arm.toolset.twin_seed)
        effective = twin.definition
    else:
        effective = toolset_definition

    toolset_path = destination / TOOLSET_FILE
    toolset_path.parent.mkdir(parents=True, exist_ok=True)
    toolset_path.write_text(
        json.dumps(effective, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    docs = render_docs(effective, arm.toolset.docs_bundle.grade)
    if docs.files:
        docs.write_into(destination / DOCS_DIR)
        instruction = destination / INSTRUCTION
        # The agent is told the documentation exists. Docs it cannot find are
        # not a documentation grade; they are a directory.
        instruction.write_text(
            instruction.read_text(encoding="utf-8").rstrip() + DOCS_POINTER, encoding="utf-8"
        )

    digest = digest_payload(
        {
            "task": task.id,
            "arm": arm.id,
            "toolset": effective,
            "docs_grade": docs.grade,
            "docs_digest": docs.content_digest,
            "env": dict(arm.env),
        }
    )

    return MaterializedTask(
        task_id=task.id,
        arm_id=arm.id,
        path=destination,
        toolset=effective,
        docs=docs,
        rename_map=twin.rename_map if twin is not None else None,
        digest=digest,
    )


def toolset_digests(definition: dict[str, Any]) -> dict[str, str]:
    """Per-tool definition digests, for ``ToolsetSpec.tools``.

    Per tool rather than over the whole toolset: a study that changed one tool's
    schema and nothing else should show exactly that in the diff of two arms,
    and a single digest over the bundle would only say "something moved".
    """
    digests: dict[str, str] = {}
    for tool in definition.get("tools", []):
        if isinstance(tool, dict) and tool.get("name"):
            digests[str(tool["name"])] = digest_payload(tool)
    return digests
