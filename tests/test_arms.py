"""M4: twins, documentation bundles, and materialization.

The isomorphism test is property-based in the sense the plan asks for — sampled
inputs, not hand-picked ones — driven by a seeded ``random.Random`` rather than
by Hypothesis. That is a deliberate trade: a study's results have to be
reproducible from the spec, and a test suite whose failures depend on a
generator's database is one more thing that behaves differently on the machine
that has run it before. The seed is in the source; a failure here reproduces
anywhere.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from duva_bench.arms.docs import render_docs
from duva_bench.arms.materialize import TOOLSET_FILE, materialize, toolset_digests
from duva_bench.arms.twin import (
    CONSONANTS,
    DICTIONARY,
    VOWELS,
    Toolset,
    TwinError,
    twin_handlers,
    twin_toolset,
)
from duva_bench.study.load import load_study
from duva_bench.study.models import Study

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "smoke" / "study.yaml"

DEFINITION: dict[str, Any] = {
    "tools": [
        {
            "name": "read_file",
            "description": "Read a file. Use read_file before write_file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to read."},
                    "max_bytes": {"type": "integer", "description": "Truncate after this many."},
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "contents": {"type": "string"},
                    "mode": {"type": "string", "enum": ["overwrite", "append"]},
                },
                "required": ["path", "contents"],
            },
        },
        {
            "name": "run_command",
            "description": "Run a shell command and return its output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}, "timeout_s": {"type": "integer"}},
                "required": ["command"],
            },
        },
    ]
}


@pytest.fixture
def study() -> Study:
    return load_study(EXAMPLE)


def _handlers() -> Toolset:
    """A toolset whose handlers are observable functions of their arguments."""

    def read_file(path: str, max_bytes: int | None = None) -> dict[str, Any]:
        return {"read": path, "limit": max_bytes}

    def write_file(path: str, contents: str, mode: str = "overwrite") -> dict[str, Any]:
        return {"wrote": path, "bytes": len(contents), "mode": mode}

    def run_command(command: str, timeout_s: int | None = None) -> dict[str, Any]:
        return {"ran": command, "timeout": timeout_s}

    return Toolset(
        definition=DEFINITION,
        handlers={"read_file": read_file, "write_file": write_file, "run_command": run_command},
    )


# --- the names --------------------------------------------------------------


def test_every_tool_and_parameter_is_renamed() -> None:
    twin = twin_toolset(DEFINITION, seed="s1")
    assert set(twin.tool_names) == {"read_file", "write_file", "run_command"}
    assert all(new != old for old, new in twin.tool_names.items())
    for tool, renames in twin.rename_map["parameters"].items():
        assert renames, f"{tool} has no renamed parameters"
        assert all(new != old for old, new in renames.items())


def test_names_are_length_matched_to_what_they_replace() -> None:
    """A longer name costs more context, which is a second variable."""
    twin = twin_toolset(DEFINITION, seed="s1")
    for original, renamed in twin.tool_names.items():
        assert len(renamed) == len(original)
    for tool, renames in twin.rename_map["parameters"].items():
        for original, renamed in renames.items():
            assert len(renamed) == len(original), f"{tool}.{original}"


def test_names_are_pronounceable_by_construction() -> None:
    twin = twin_toolset(DEFINITION, seed="s1")
    for renamed in twin.tool_names.values():
        for index, letter in enumerate(renamed):
            expected = CONSONANTS if index % 2 == 0 else VOWELS
            assert letter in expected, f"{renamed} is not alternating consonant-vowel"


def test_names_are_not_dictionary_words() -> None:
    twin = twin_toolset(DEFINITION, seed="s1")
    for renamed in twin.tool_names.values():
        assert renamed not in DICTIONARY


def test_no_two_names_collide_anywhere_in_the_toolset() -> None:
    twin = twin_toolset(DEFINITION, seed="s1")
    every = list(twin.tool_names.values()) + [
        name for renames in twin.rename_map["parameters"].values() for name in renames.values()
    ]
    assert len(every) == len(set(every))


def test_the_same_parameter_name_in_two_tools_gets_two_twins() -> None:
    """A name shared across tools is a hint an agent could learn from."""
    twin = twin_toolset(DEFINITION, seed="s1")
    assert twin.parameters_for("read_file")["path"] != twin.parameters_for("write_file")["path"]


# --- determinism ------------------------------------------------------------


def test_a_twin_is_a_function_of_the_definition_and_the_seed() -> None:
    first = twin_toolset(DEFINITION, seed="s1")
    second = twin_toolset(DEFINITION, seed="s1")
    assert first.rename_map == second.rename_map
    assert first.digest == second.digest


def test_a_different_seed_is_a_different_twin() -> None:
    assert twin_toolset(DEFINITION, seed="s1").digest != twin_toolset(DEFINITION, seed="s2").digest


def test_the_twin_does_not_depend_on_the_order_tools_were_written_in() -> None:
    reordered = {"tools": list(reversed(DEFINITION["tools"]))}
    assert (
        twin_toolset(DEFINITION, seed="s1").rename_map
        == twin_toolset(reordered, seed="s1").rename_map
    )


# --- isomorphism ------------------------------------------------------------


def _sample(rng: random.Random) -> tuple[str, dict[str, Any]]:
    tool = rng.choice(["read_file", "write_file", "run_command"])
    if tool == "read_file":
        arguments: dict[str, Any] = {"path": f"/tmp/{rng.randrange(10_000)}"}
        if rng.random() < 0.5:
            arguments["max_bytes"] = rng.randrange(1, 4096)
    elif tool == "write_file":
        arguments = {
            "path": f"/tmp/{rng.randrange(10_000)}",
            "contents": "x" * rng.randrange(0, 50),
        }
        if rng.random() < 0.5:
            arguments["mode"] = rng.choice(["overwrite", "append"])
    else:
        arguments = {"command": f"echo {rng.randrange(10_000)}"}
        if rng.random() < 0.5:
            arguments["timeout_s"] = rng.randrange(1, 60)
    return tool, arguments


def test_the_twin_returns_what_the_original_would_for_sampled_inputs() -> None:
    """The property the instrument stands on: same behaviour, different names."""
    original = _handlers()
    twin = twin_toolset(DEFINITION, seed="iso")
    twinned = twin_handlers(original, twin)
    rng = random.Random(20260807)

    for _ in range(400):
        tool, arguments = _sample(rng)
        renames = twin.parameters_for(tool)
        twin_arguments = {renames[name]: value for name, value in arguments.items()}
        assert twinned.invoke(twin.tool_names[tool], twin_arguments) == original.invoke(
            tool, arguments
        )


def test_the_twin_exposes_exactly_the_twin_names() -> None:
    twin = twin_toolset(DEFINITION, seed="iso")
    twinned = twin_handlers(_handlers(), twin)
    assert set(twinned.names) == set(twin.tool_names.values())
    with pytest.raises(KeyError):
        twinned.invoke("read_file", {"path": "/tmp/x"})


def test_the_rename_map_round_trips() -> None:
    twin = twin_toolset(DEFINITION, seed="iso")
    for original, renamed in twin.tool_names.items():
        assert twin.inverse_tools[renamed] == original
    reloaded = json.loads(json.dumps(twin.rename_map))
    assert reloaded == twin.rename_map


def test_the_twins_schema_is_the_same_shape() -> None:
    twin = twin_toolset(DEFINITION, seed="iso")
    for tool in twin.definition["tools"]:
        original = twin.inverse_tools[tool["name"]]
        source = next(t for t in DEFINITION["tools"] if t["name"] == original)
        assert set(tool["parameters"]["properties"]) == {
            twin.parameters_for(original)[name] for name in source["parameters"]["properties"]
        }
        assert len(tool["parameters"]["required"]) == len(source["parameters"]["required"])


def test_prose_references_are_renamed_too() -> None:
    """A description that still says `read_file` hands the original name back."""
    twin = twin_toolset(DEFINITION, seed="iso")
    described = next(
        t for t in twin.definition["tools"] if t["name"] == twin.tool_names["read_file"]
    )
    assert "read_file" not in described["description"]
    assert "write_file" not in described["description"]
    assert twin.tool_names["write_file"] in described["description"]


def test_a_toolset_with_no_tools_is_refused() -> None:
    with pytest.raises(TwinError, match="non-empty"):
        twin_toolset({"tools": []}, seed="s")


# --- documentation bundles --------------------------------------------------


def test_grade_none_is_no_files_rather_than_an_empty_file() -> None:
    assert render_docs(DEFINITION, "none").files == {}


def test_reference_documents_every_tool_and_parameter() -> None:
    text = render_docs(DEFINITION, "reference").files["TOOLS.md"]
    for tool in DEFINITION["tools"]:
        assert f"`{tool['name']}`" in text
        for parameter in tool["parameters"]["properties"]:
            assert f"`{parameter}`" in text


def test_rich_is_reference_plus_examples_not_a_rewrite() -> None:
    """If rich were written independently, the arms would differ in prose too."""
    reference = render_docs(DEFINITION, "reference").files["TOOLS.md"]
    rich = render_docs(DEFINITION, "rich").files["TOOLS.md"]
    for line in reference.splitlines():
        if line.startswith(("## ", "| `")):
            assert line in rich
    assert rich.count("Example:") == len(DEFINITION["tools"])


def test_examples_only_fill_in_required_parameters() -> None:
    rich = render_docs(DEFINITION, "rich").files["TOOLS.md"]
    assert '"max_bytes"' not in rich, "an optional parameter in an example teaches it is expected"


def test_each_grade_has_its_own_content_digest() -> None:
    digests = {
        grade: render_docs(DEFINITION, grade).content_digest
        for grade in ("none", "reference", "rich")
    }
    assert len(set(digests.values())) == 3


def test_documentation_is_deterministic() -> None:
    assert render_docs(DEFINITION, "rich").files == render_docs(DEFINITION, "rich").files


# --- materialization --------------------------------------------------------


def test_materializing_copies_the_task_rather_than_editing_it(study: Study, tmp_path: Path) -> None:
    source = EXAMPLE.parent / "tasks" / "json-normalizer"
    before = (source / "instruction.md").read_text(encoding="utf-8")

    materialize(
        study.task("json-normalizer"),
        study.arm("standard"),
        source=source,
        destination=tmp_path / "standard",
        toolset_definition=DEFINITION,
    )

    assert (source / "instruction.md").read_text(encoding="utf-8") == before
    assert (tmp_path / "standard" / "task.toml").exists()


def test_a_twinned_arm_gets_the_twin_and_never_the_map(study: Study, tmp_path: Path) -> None:
    """An agent that could read the rename map would be handed the answer."""
    materialized = materialize(
        study.task("json-normalizer"),
        study.arm("twin"),
        source=EXAMPLE.parent / "tasks" / "json-normalizer",
        destination=tmp_path / "twin",
        toolset_definition=DEFINITION,
    )

    written = json.loads((materialized.path / TOOLSET_FILE).read_text(encoding="utf-8"))
    assert {tool["name"] for tool in written["tools"]} == set(
        materialized.rename_map["tools"].values()  # type: ignore[union-attr]
    )
    assert not list(materialized.path.rglob("rename_map.json"))

    # It is written where analysis can reach it, outside the task tree.
    destination = materialized.write_rename_map(tmp_path / "records" / "rename_map.json")
    assert destination is not None and destination.exists()


def test_a_docs_grade_of_none_leaves_no_documentation(study: Study, tmp_path: Path) -> None:
    materialized = materialize(
        study.task("json-normalizer"),
        study.arm("standard"),
        source=EXAMPLE.parent / "tasks" / "json-normalizer",
        destination=tmp_path / "standard",
        toolset_definition=DEFINITION,
    )
    assert not (materialized.path / "docs").exists()
    assert "docs/TOOLS.md" not in (materialized.path / "instruction.md").read_text(encoding="utf-8")


def test_a_docs_grade_writes_the_bundle_and_says_where_it_is(study: Study, tmp_path: Path) -> None:
    """Documentation the agent cannot find is a directory, not a grade."""
    arm = study.arm("standard").model_copy(
        update={
            "toolset": study.arm("standard").toolset.model_copy(
                update={
                    "docs_bundle": study.arm("standard").toolset.docs_bundle.model_copy(
                        update={"grade": "rich"}
                    )
                }
            )
        }
    )
    materialized = materialize(
        study.task("json-normalizer"),
        arm,
        source=EXAMPLE.parent / "tasks" / "json-normalizer",
        destination=tmp_path / "rich",
        toolset_definition=DEFINITION,
    )
    assert (materialized.path / "docs" / "TOOLS.md").exists()
    assert "docs/TOOLS.md" in (materialized.path / "instruction.md").read_text(encoding="utf-8")


def test_the_materialization_digest_covers_what_was_applied(study: Study, tmp_path: Path) -> None:
    standard = materialize(
        study.task("json-normalizer"),
        study.arm("standard"),
        source=EXAMPLE.parent / "tasks" / "json-normalizer",
        destination=tmp_path / "a",
        toolset_definition=DEFINITION,
    )
    twinned = materialize(
        study.task("json-normalizer"),
        study.arm("twin"),
        source=EXAMPLE.parent / "tasks" / "json-normalizer",
        destination=tmp_path / "b",
        toolset_definition=DEFINITION,
    )
    assert standard.digest != twinned.digest


def test_per_tool_digests_change_only_for_the_tool_that_changed() -> None:
    before = toolset_digests(DEFINITION)
    edited = json.loads(json.dumps(DEFINITION))
    edited["tools"][0]["description"] = "Read a file, carefully."
    after = toolset_digests(edited)

    assert after["read_file"] != before["read_file"]
    assert after["write_file"] == before["write_file"]
    assert after["run_command"] == before["run_command"]


# --- materialization has to reach the container ------------------------------


def _servable_definition() -> dict[str, object]:
    return {
        "name": "standard",
        "tools": [
            {
                "name": "read_file",
                "capability": "fs.read",
                "description": "Read a file from the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            {
                "name": "run_command",
                "capability": "proc.run",
                "description": "Run a shell command.",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        ],
    }


def test_a_materialized_task_declares_its_toolset_where_harbor_reads_it(tmp_path: Path) -> None:
    """The defect this redesign exists to fix.

    Materialization used to write `duva/toolset.json` and stop. Harbor
    configures an agent's tools from `task.toml` and from nowhere else, so that
    file was inert and arms differing only in their toolset differed only in
    their labels — which gate G2 demonstrated by reporting one arm beating
    another when the two were the same arm.
    """
    study = load_study(EXAMPLE)
    materialized = materialize(
        study.task("json-normalizer"),
        study.arm("standard"),
        source=EXAMPLE.parent / "tasks" / "json-normalizer",
        destination=tmp_path / "variant",
        toolset_definition=_servable_definition(),
    )

    config = (materialized.path / "task.toml").read_text(encoding="utf-8")
    assert "[[environment.mcp_servers]]" in config, "Harbor is never told the toolset exists"
    assert "DUVA_TOOLSET" in config, "the server is never told what to serve"

    dockerfile = (materialized.path / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert "duva_mcp_server.py" in dockerfile, "the server never reaches the image"
    assert (materialized.path / "environment" / "duva_toolset.json").is_file()
    assert (materialized.path / "environment" / "duva_mcp_server.py").is_file()


def test_a_twin_variant_carries_no_word_of_the_vocabulary_it_replaces(tmp_path: Path) -> None:
    """The container must not contain the answer.

    A twin arm is being tested on names it has never seen. If the original names
    were anywhere inside the task — the toolset file, the Dockerfile, the
    instruction — an agent with a shell could read them, and the arm would be
    measuring whether the model can grep.
    """
    study = load_study(EXAMPLE)
    materialized = materialize(
        study.task("json-normalizer"),
        study.arm("twin"),
        source=EXAMPLE.parent / "tasks" / "json-normalizer",
        destination=tmp_path / "twin",
        toolset_definition=_servable_definition(),
    )

    leaked = []
    for path in materialized.path.rglob("*"):
        if not path.is_file():
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for original in ("read_file", "run_command"):
            if original in body:
                leaked.append(f"{path.relative_to(materialized.path)} contains {original!r}")
    assert not leaked, leaked

    # The map that would reveal it exists, and is handed back rather than written in.
    assert materialized.rename_map is not None
    assert set(materialized.rename_map["tools"]) == {"read_file", "run_command"}


def test_the_served_twin_dispatches_to_the_same_implementations(tmp_path: Path) -> None:
    """Isomorphism, checked by calling the twin and the original.

    A twin whose tools do something different is not a twin, and the study built
    on it would be measuring two toolsets rather than two names for one.
    """
    from duva_bench.arms.mcp_server import handle
    from duva_bench.arms.twin import twin_toolset

    original = _servable_definition()
    twin = twin_toolset(original, seed="isomorphism").definition

    target = tmp_path / "subject.txt"
    target.write_text("first\nsecond\n", encoding="utf-8")

    def call(definition: dict[str, object], name: str, arguments: dict[str, object]) -> str:
        reply = handle(
            definition,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        assert reply is not None
        return str(reply["result"]["content"][0]["text"])

    from_original = call(original, "read_file", {"path": str(target)})

    twin_read = next(t for t in twin["tools"] if t["capability"] == "fs.read")
    twin_path_arg = next(k for k, v in twin_read["parameter_roles"].items() if v == "path")
    from_twin = call(twin, str(twin_read["name"]), {twin_path_arg: str(target)})

    assert from_original == from_twin == "first\nsecond"


def test_an_arm_that_manipulates_nothing_runs_the_task_as_written(tmp_path: Path) -> None:
    """Copying a task that does not need copying only adds failure modes."""
    from duva_bench.exec.trial import _arm_task_dir
    from duva_bench.state import StateDir

    study = load_study(EXAMPLE)
    arm = study.arm("standard")
    assert arm.toolset.definition_path is None
    assert arm.toolset.docs_bundle.grade == "none"

    resolved = _arm_task_dir(
        study,
        study.task("json-normalizer"),
        arm,
        root=EXAMPLE.parent,
        state=StateDir(tmp_path),
    )
    assert resolved == (EXAMPLE.parent / "tasks" / "json-normalizer").resolve()
