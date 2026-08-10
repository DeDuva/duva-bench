"""Semantic twins: the instrument Study A is built on (M4).

A twin of a toolset is **isomorphic** to it — same shape, same parameters, same
behaviour, different names. Every tool and every parameter gets a new name that
is pronounceable, not a dictionary word, and about as long as the one it
replaces; the handlers are unchanged, and a rename map records the mapping in
both directions.

Why this exists at all: an agent that does better with `read_file` than with an
identically-behaved `veshanu` did not do better *at the task*. It did better at
a name it had seen a million times in training. That difference is the thing
Study A measures, and a twin is the only way to hold everything else still while
varying it.

Three properties this module is held to, all tested:

**Isomorphism.** For any arguments, the twin's handler returns what the
original's would. A twin that behaves differently is a confound, not an
instrument.

**Determinism.** ``(definition, seed)`` fixes the twin exactly. A twin that
varies per run makes the arm digest a lie, and the arm digest is what binds
results to what produced them.

**Length matching.** A name that is much longer than the one it replaces costs
the model more context and more tokens, which is a second variable arriving
uninvited. The match is on **characters**, as a proxy for tokens — see
:func:`syllabic_name`, which says what that proxy costs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from duva_bench.study.digest import digest_payload

# Consonant-vowel syllables. The vocabulary is chosen so every combination is
# pronounceable by an English speaker and none of them carries meaning: no `q`,
# `x`, `c` (which need a following letter to be pronounceable or duplicate `k`),
# and no `y` as a vowel (it changes syllable count depending on where it lands).
CONSONANTS = ("b", "d", "f", "g", "h", "j", "k", "l", "m", "n", "p", "r", "s", "t", "v", "z")
VOWELS = ("a", "e", "i", "o", "u")

# Short English words that fall out of a consonant-vowel generator and would
# defeat the point of a non-dictionary name. Not a dictionary — a dictionary
# would be a data dependency for a check that only has to catch the words this
# generator can actually produce, which is a small and enumerable set.
DICTIONARY = frozenset(
    {
        "be",
        "bed",
        "beg",
        "bet",
        "big",
        "bit",
        "bin",
        "bug",
        "bus",
        "but",
        "dad",
        "day",
        "did",
        "dig",
        "dim",
        "dip",
        "dog",
        "dot",
        "dub",
        "dug",
        "fad",
        "fan",
        "far",
        "fat",
        "fed",
        "fig",
        "fin",
        "fit",
        "fog",
        "fun",
        "gap",
        "gas",
        "get",
        "gig",
        "gum",
        "gun",
        "gut",
        "had",
        "ham",
        "has",
        "hat",
        "hen",
        "hid",
        "him",
        "hip",
        "his",
        "hit",
        "hog",
        "hot",
        "hub",
        "hug",
        "hum",
        "hut",
        "jam",
        "jar",
        "jet",
        "job",
        "jog",
        "jug",
        "keg",
        "kid",
        "kin",
        "kit",
        "lab",
        "lad",
        "lag",
        "lap",
        "led",
        "leg",
        "let",
        "lid",
        "lip",
        "lit",
        "log",
        "lot",
        "lug",
        "mad",
        "man",
        "map",
        "mat",
        "men",
        "met",
        "mob",
        "mop",
        "mud",
        "mug",
        "nab",
        "nag",
        "nap",
        "net",
        "nib",
        "nip",
        "nod",
        "not",
        "nun",
        "nut",
        "pad",
        "pan",
        "pat",
        "peg",
        "pen",
        "pet",
        "pig",
        "pin",
        "pit",
        "pod",
        "pop",
        "pot",
        "pub",
        "pug",
        "pun",
        "pup",
        "put",
        "rag",
        "ram",
        "ran",
        "rat",
        "red",
        "rib",
        "rid",
        "rig",
        "rim",
        "rip",
        "rob",
        "rod",
        "rot",
        "rub",
        "rug",
        "rum",
        "run",
        "rut",
        "sad",
        "sag",
        "sap",
        "sat",
        "set",
        "sin",
        "sip",
        "sit",
        "sob",
        "sun",
        "tab",
        "tag",
        "tan",
        "tap",
        "tar",
        "tin",
        "tip",
        "tog",
        "ton",
        "top",
        "tub",
        "tug",
        "van",
        "vat",
        "vet",
        "zap",
        "zip",
        "data",
        "file",
        "line",
        "name",
        "note",
        "page",
        "path",
        "read",
        "role",
        "save",
        "seed",
        "site",
        "size",
        "sort",
        "tone",
        "type",
        "unit",
        "user",
        "vote",
        "zone",
    }
)


class TwinError(ValueError):
    """A toolset that cannot be twinned."""


@dataclass(frozen=True)
class Twin:
    """A toolset's twin, and the map that relates the two."""

    definition: dict[str, Any]
    # {"tools": {original: twin}, "parameters": {original_tool: {param: twin}}}
    rename_map: dict[str, Any]
    seed: str
    original_digest: str

    @property
    def tool_names(self) -> dict[str, str]:
        names: dict[str, str] = self.rename_map["tools"]
        return names

    @property
    def inverse_tools(self) -> dict[str, str]:
        return {twin: original for original, twin in self.tool_names.items()}

    def parameters_for(self, original_tool: str) -> dict[str, str]:
        params: dict[str, dict[str, str]] = self.rename_map["parameters"]
        return params.get(original_tool, {})

    @property
    def digest(self) -> str:
        return digest_payload(self.definition)

    def rename_map_digest(self) -> str:
        return digest_payload(self.rename_map)


def syllabic_name(source: str, seed: str, *, length: int, taken: set[str]) -> str:
    """A pronounceable, non-dictionary name of about ``length`` characters.

    Deterministic in ``(source, seed)``: the bytes come from a hash, not from a
    random number generator, so a twin can be recomputed from the study spec on
    any machine years later without anybody having stored it.

    **Length is matched in characters, not tokens.** Matching tokens would need
    a tokenizer, and a tokenizer is a per-model dependency this package does not
    take — the twin has to be the same twin for every arm in a study, and a
    model-specific twin would confound the very comparison it is built for.
    Characters are a proxy: a 9-character invented name is usually 2-4 BPE
    tokens where a 9-character English word is 1-2, so twin names cost *more*
    tokens, not fewer, and the direction of that bias is stated in the report
    rather than hidden.
    """
    if length < 2:
        raise TwinError(f"cannot build a name of length {length} for {source!r}")

    for attempt in range(1000):
        digest = hashlib.sha256(f"{seed}\x00{source}\x00{attempt}".encode()).digest()
        letters: list[str] = []
        index = 0
        while len(letters) < length:
            # Alternate consonant and vowel so the result is pronounceable by
            # construction rather than by rejection sampling.
            table = CONSONANTS if len(letters) % 2 == 0 else VOWELS
            letters.append(table[digest[index % len(digest)] % len(table)])
            index += 1
        candidate = "".join(letters)
        if candidate not in DICTIONARY and candidate not in taken:
            return candidate

    raise TwinError(f"could not find an unused name for {source!r} after 1000 attempts")


def twin_toolset(definition: dict[str, Any], *, seed: str) -> Twin:
    """Build the twin of an OpenAI-style toolset definition.

    ``definition`` is ``{"tools": [{"name": ..., "description": ...,
    "parameters": {"properties": {...}, "required": [...]}}, ...]}`` — the shape
    every agent CLI in scope accepts, whether it calls it a tool, a function or
    a command.

    Descriptions are carried across **unchanged except for name substitutions**.
    Rewriting them would change how much the model is told, which is the docs
    bundle's variable (:mod:`duva_bench.arms.docs`), not this one.
    """
    tools = definition.get("tools")
    if not isinstance(tools, list) or not tools:
        raise TwinError("a toolset definition needs a non-empty `tools` list")

    taken: set[str] = set()
    tool_names: dict[str, str] = {}
    parameter_names: dict[str, dict[str, str]] = {}

    # Sorted, so the twin does not depend on the order the tools happened to be
    # written in — the same reason the digest sorts keys.
    for tool in sorted(tools, key=lambda item: str(item.get("name", ""))):
        original = str(tool.get("name") or "")
        if not original:
            raise TwinError(f"a tool has no name: {tool!r}")
        if original in tool_names:
            raise TwinError(f"two tools are called {original!r}")
        renamed = syllabic_name(original, seed, length=len(original), taken=taken)
        taken.add(renamed)
        tool_names[original] = renamed

        properties = _properties(tool)
        renames: dict[str, str] = {}
        for parameter in sorted(properties):
            # Parameter names are scoped to their tool, so two tools may reuse a
            # parameter name and get different twins for it. That is deliberate:
            # a shared name across tools is a hint the agent could learn from.
            new_name = syllabic_name(
                f"{original}.{parameter}", seed, length=len(parameter), taken=taken
            )
            taken.add(new_name)
            renames[parameter] = new_name
        parameter_names[original] = renames

    rename_map = {"tools": tool_names, "parameters": parameter_names}
    twinned = {
        **{key: value for key, value in definition.items() if key != "tools"},
        "tools": [_twin_tool(tool, rename_map) for tool in tools],
    }
    return Twin(
        definition=twinned,
        rename_map=rename_map,
        seed=seed,
        original_digest=digest_payload(definition),
    )


def _properties(tool: dict[str, Any]) -> dict[str, Any]:
    parameters = tool.get("parameters")
    if not isinstance(parameters, dict):
        return {}
    properties = parameters.get("properties")
    return properties if isinstance(properties, dict) else {}


def _twin_tool(tool: dict[str, Any], rename_map: dict[str, Any]) -> dict[str, Any]:
    original = str(tool.get("name"))
    renames: dict[str, str] = rename_map["parameters"].get(original, {})
    twinned: dict[str, Any] = dict(tool)
    twinned["name"] = rename_map["tools"][original]

    if isinstance(tool.get("description"), str):
        twinned["description"] = _substitute(tool["description"], rename_map, original)

    parameters = tool.get("parameters")
    if isinstance(parameters, dict):
        new_parameters = dict(parameters)
        properties = parameters.get("properties")
        if isinstance(properties, dict):
            new_parameters["properties"] = {
                renames.get(name, name): _twin_property(schema, rename_map, original)
                for name, schema in properties.items()
            }
        required = parameters.get("required")
        if isinstance(required, list):
            new_parameters["required"] = [renames.get(str(name), name) for name in required]
        twinned["parameters"] = new_parameters

    return twinned


def _twin_property(schema: Any, rename_map: dict[str, Any], tool: str) -> Any:
    if not isinstance(schema, dict):
        return schema
    twinned = dict(schema)
    if isinstance(schema.get("description"), str):
        twinned["description"] = _substitute(schema["description"], rename_map, tool)
    return twinned


def _substitute(text: str, rename_map: dict[str, Any], tool: str) -> str:
    """Replace original names inside prose with their twins.

    Longest first, so `read_file_lines` is not half-rewritten by the rule for
    `read_file`. Substring replacement rather than word-boundary matching,
    because tool names appear inside code fences and snake_case identifiers
    where a word boundary is not where one would hope.
    """
    renames: dict[str, str] = dict(rename_map["parameters"].get(tool, {}))
    renames.update(rename_map["tools"])
    for original in sorted(renames, key=len, reverse=True):
        text = text.replace(original, renames[original])
    return text


# --- the runtime side: handlers, and what isomorphism means ------------------


@dataclass
class Toolset:
    """A definition plus the handlers that implement it.

    Handlers live here rather than in the study spec because a study spec is
    data that travels and a handler is code that runs. What the spec carries is
    the digest of the definition; what a trial needs is this.
    """

    definition: dict[str, Any]
    handlers: dict[str, Any] = field(default_factory=dict)

    def invoke(self, name: str, arguments: dict[str, Any]) -> Any:
        handler = self.handlers.get(name)
        if handler is None:
            raise KeyError(f"no tool {name!r} in this toolset")
        return handler(**arguments)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(
            str(tool.get("name")) for tool in self.definition.get("tools", []) if tool.get("name")
        )


def twin_handlers(toolset: Toolset, twin: Twin) -> Toolset:
    """The twin's handlers: the originals, reached through the rename map.

    This is what "identical handlers" means operationally — there is exactly one
    implementation, and the twin is a naming shim over it. A copied handler
    could drift; this one cannot.
    """
    handlers: dict[str, Any] = {}
    for original, renamed in twin.tool_names.items():
        parameter_names = twin.parameters_for(original)
        inverse = {new: old for old, new in parameter_names.items()}
        handler = toolset.handlers.get(original)
        if handler is None:
            continue

        def call(_handler: Any = handler, _inverse: dict[str, str] = inverse, **kwargs: Any) -> Any:
            return _handler(**{_inverse.get(key, key): value for key, value in kwargs.items()})

        handlers[renamed] = call
    return Toolset(definition=twin.definition, handlers=handlers)


def load_definition(path: Any) -> dict[str, Any]:
    from pathlib import Path

    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TwinError(f"{path} is not a toolset definition")
    return document
