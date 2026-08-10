"""Documentation bundles: the second variable in Study A (M4).

Three grades, and the distance between them is the treatment:

``none``
    Nothing. The agent has the tool definitions the harness passes it and
    whatever it knows already. For a twinned toolset that is close to nothing,
    which is the point.

``reference``
    One section per tool: signature, parameters, types, required-ness, and the
    description from the definition. What an API reference gives you.

``rich``
    ``reference`` plus a worked example per tool — a call with plausible
    arguments and the shape of what comes back.

The grades are cumulative on purpose. If ``rich`` were written independently it
could differ from ``reference`` in wording, length or emphasis, and a difference
between the two arms would be "some prose changed" rather than "examples were
added".

The bundle is content-digested and the digest rides in the arm's
``DocsBundle.content_digest``, so two runs claiming the same docs grade can be
checked rather than believed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from duva_bench.study.digest import digest_payload
from duva_bench.study.models import DocsGrade

INDEX = "TOOLS.md"


@dataclass(frozen=True)
class DocsBundleContent:
    """Rendered documentation for one toolset at one grade."""

    grade: DocsGrade
    files: dict[str, str]

    @property
    def content_digest(self) -> str:
        """Digest of the rendered bytes, not of the request that produced them."""
        return digest_payload({"grade": self.grade, "files": self.files})

    def write_into(self, directory: Any) -> list[str]:
        from pathlib import Path

        root = Path(directory)
        written: list[str] = []
        for name, text in sorted(self.files.items()):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written.append(name)
        return written


def render_docs(definition: dict[str, Any], grade: DocsGrade) -> DocsBundleContent:
    """Render a toolset's documentation at ``grade``.

    Deterministic in ``(definition, grade)``: same input, same bytes, same
    digest. Examples are generated from the parameter schema rather than
    invented per call, so ``rich`` is reproducible and its content is a function
    of the toolset rather than of whoever ran it.
    """
    if grade == "none":
        return DocsBundleContent(grade=grade, files={})

    tools = [tool for tool in definition.get("tools", []) if isinstance(tool, dict)]
    sections = [_section(tool, grade) for tool in sorted(tools, key=lambda t: str(t.get("name")))]
    body = "\n\n".join(sections)

    header = "# Tools\n\nReference for the tools available in this environment." + (
        " Each entry ends with a worked example.\n" if grade == "rich" else "\n"
    )
    return DocsBundleContent(grade=grade, files={INDEX: f"{header}\n{body}\n"})


def _section(tool: dict[str, Any], grade: DocsGrade) -> str:
    name = str(tool.get("name", "unknown"))
    description = str(tool.get("description", "")).strip()
    properties, required = _schema(tool)

    lines = [f"## `{name}`", ""]
    if description:
        lines += [description, ""]

    if properties:
        lines += ["| parameter | type | required | description |", "|---|---|---|---|"]
        for parameter in sorted(properties):
            schema = properties[parameter] if isinstance(properties[parameter], dict) else {}
            lines.append(
                f"| `{parameter}` | {schema.get('type', 'any')} | "
                f"{'yes' if parameter in required else 'no'} | "
                f"{str(schema.get('description', '')).strip()} |"
            )
        lines.append("")
    else:
        lines += ["Takes no parameters.", ""]

    if grade == "rich":
        lines += ["Example:", "", "```json", _example(name, properties, required), "```", ""]

    return "\n".join(lines).rstrip()


def _schema(tool: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    parameters = tool.get("parameters")
    if not isinstance(parameters, dict):
        return {}, set()
    properties = parameters.get("properties")
    required = parameters.get("required")
    return (
        properties if isinstance(properties, dict) else {},
        {str(name) for name in required} if isinstance(required, list) else set(),
    )


def _example(name: str, properties: dict[str, Any], required: set[str]) -> str:
    """A worked call, generated from the schema.

    Required parameters only: an example that fills in every optional argument
    teaches the model that they are expected, which is a lesson the reference
    grade does not teach and would be a second difference between the arms.
    """
    arguments = {
        parameter: _placeholder(parameter, properties.get(parameter))
        for parameter in sorted(required or properties)
    }
    return json.dumps({"tool": name, "arguments": arguments}, indent=2, sort_keys=True)


def _placeholder(parameter: str, schema: Any) -> Any:
    kind = schema.get("type") if isinstance(schema, dict) else None
    if isinstance(schema, dict) and isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.5
    if kind == "boolean":
        return True
    if kind == "array":
        return []
    if kind == "object":
        return {}
    # A string placeholder that names its own parameter: an example argument
    # that looks like real content ("/etc/passwd") teaches the model something
    # about the environment, which is not what this grade is varying.
    return f"<{parameter}>"
