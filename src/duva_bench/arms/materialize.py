"""Arm materialization: one task, prepared for one arm (M4).

A Harbor task directory is the same for every arm; what differs is the toolset
the agent is handed, the documentation in the environment, and the environment
pins. Materializing produces a per-arm copy of the task with those three applied,
and a digest over exactly what was applied.

The copy is deliberate. Editing the task in place would make the second arm's
trial depend on the first arm's leftovers, which is the kind of contamination
that produces a real-looking effect and no explanation for it.

What is written into the copy:

``environment/duva_toolset.json`` and ``environment/duva_mcp_server.py``
    The toolset definition the arm gets — the twin's, when the arm twins one —
    and the server that serves it. Both go under ``environment/`` because that
    is the Docker build context, and both are copied into the image by lines
    appended to the task's Dockerfile.

``task.toml``
    Rewritten to declare the server under ``[[environment.mcp_servers]]`` and to
    point it at the definition. **This is the part that makes a toolset real.**
    Until 2026-08-10 materialization wrote a definition file and stopped, and
    nothing read it: Harbor configures an agent's tools from ``task.toml`` and
    from nowhere else, so arms that differed only in their toolset differed only
    in their labels.

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

# Under `environment/`, because that directory is the Docker build context and a
# COPY cannot reach outside it — the first attempt at this put the server beside
# the task and the image build failed on the COPY.
ENVIRONMENT_DIR = Path("environment")
TOOLSET_FILE = ENVIRONMENT_DIR / "duva_toolset.json"
SERVER_FILE = ENVIRONMENT_DIR / "duva_mcp_server.py"
DOCKERFILE = ENVIRONMENT_DIR / "Dockerfile"
TASK_CONFIG = "task.toml"
DOCS_DIR = Path("docs")
INSTRUCTION = "instruction.md"

#: Where the two files land inside the container.
CONTAINER_DIR = "/opt/duva"
CONTAINER_TOOLSET = f"{CONTAINER_DIR}/toolset.json"
CONTAINER_SERVER = f"{CONTAINER_DIR}/mcp_server.py"

#: The MCP server's name. It prefixes every tool the agent sees as
#: `mcp__<name>__<tool>`, so analysis has to normalise it before computing a
#: hallucinated-call rate — see `analysis/process.py`.
SERVER_NAME = "duva"

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

    served = _install_toolset(destination, effective)

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
            "served": served,
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


def _install_toolset(destination: Path, definition: dict[str, Any]) -> bool:
    """Put the toolset in the image and declare it in ``task.toml``.

    Returns whether anything was installed. A definition with no tools installs
    nothing: a task whose arms do not manipulate tools should be handed to Harbor
    exactly as its author wrote it, rather than carrying an empty server that
    could only add failure modes.
    """
    if not definition.get("tools"):
        return False

    (destination / ENVIRONMENT_DIR).mkdir(parents=True, exist_ok=True)
    (destination / TOOLSET_FILE).write_text(
        json.dumps(definition, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (destination / SERVER_FILE).write_text(
        Path(__file__).with_name("mcp_server.py").read_text(encoding="utf-8"), encoding="utf-8"
    )

    dockerfile = destination / DOCKERFILE
    if not dockerfile.exists():
        raise FileNotFoundError(
            f"{destination} has no {DOCKERFILE}; a task whose arms manipulate tools has to be "
            "built from a Dockerfile so the tool server can be installed into the image"
        )
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8").rstrip()
        + "\n\n"
        + "# Added by duva-bench arm materialization: the arm's toolset, and the\n"
        + "# server that serves it to the agent over MCP.\n"
        + f"RUN mkdir -p {CONTAINER_DIR}\n"
        + f"COPY duva_toolset.json {CONTAINER_TOOLSET}\n"
        + f"COPY duva_mcp_server.py {CONTAINER_SERVER}\n",
        encoding="utf-8",
    )

    _declare_server(destination / TASK_CONFIG)
    return True


def _declare_server(path: Path) -> None:
    """Append the MCP server declaration to a task's ``task.toml``.

    Appended as text rather than parsed and re-emitted: this package's runtime
    dependencies are pydantic, httpx and pyyaml (execution-plan §2), and taking
    a TOML *writer* to rewrite one table would be a new dependency for a job that
    three lines of string do correctly. Reading TOML is stdlib; writing it is not.
    """
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist; Harbor identifies a task by its task.toml")
    existing = path.read_text(encoding="utf-8")
    if "duva-bench arm materialization" in existing:
        return
    path.write_text(
        existing.rstrip()
        + "\n\n"
        + "# Added by duva-bench arm materialization. Harbor passes this to the agent,\n"
        + "# which registers it as callable tools under the names this arm chose.\n"
        + "[[environment.mcp_servers]]\n"
        + f'name = "{SERVER_NAME}"\n'
        + 'transport = "stdio"\n'
        + 'command = "python3"\n'
        + f'args = ["{CONTAINER_SERVER}"]\n\n'
        + "[environment.env]\n"
        + f'DUVA_TOOLSET = "{CONTAINER_TOOLSET}"\n',
        encoding="utf-8",
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
