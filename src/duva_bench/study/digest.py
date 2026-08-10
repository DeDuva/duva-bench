"""The canonical digest (M1).

Mirrors adp-replay's ``manifest/digest.py``. A study digest is what binds a
result to the definition that produced it: it rides on every ADP run as a label,
so a reader handed a report can recompute it from the study file alone and find
out whether the two are the same experiment.

Canonicalization rules, all load-bearing:

* keys sorted at every depth, so serialization order cannot change the digest
* no insignificant whitespace
* UTF-8 rather than ASCII escapes, so the digest does not depend on the
  encoder's escaping policy
* **floats rejected**, not normalized

The last one is where this departs from adp-replay, and it is deliberate. A
study's numbers are things a human wrote down — a temperature, a budget, a
top-p. Passing them through a binary float makes the digest depend on the YAML
parser's rounding, and a study whose digest changes when the parser is upgraded
certifies nothing. Write them as strings; the arm still records exactly what was
sent, and the digest still means what it says.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Paths removed before digesting, as explicit paths rather than by matching a
# field name wherever it appears. Excluding a field from the digest excludes it
# from what the digest attests, so this list is the whole of what a study does
# not certify — and at M1 it is empty, because a study spec holds no runtime
# identifiers. Entries arrive only with a written reason.
DIGEST_EXCLUDED_PATHS: tuple[tuple[str, ...], ...] = ()

DIGEST_PREFIX = "sha256:"


class NonCanonicalValue(TypeError):
    """A value that cannot be digested reproducibly."""


def _strip(value: Any, paths: tuple[tuple[str, ...], ...]) -> Any:
    """Return ``value`` with each of ``paths`` removed, without mutating it."""
    if not paths or not isinstance(value, dict):
        return value

    here = {path[0] for path in paths if len(path) == 1}
    deeper: dict[str, list[tuple[str, ...]]] = {}
    for path in paths:
        if len(path) > 1:
            deeper.setdefault(path[0], []).append(path[1:])

    out: dict[str, Any] = {}
    for key, item in value.items():
        if key in here:
            continue
        if key in deeper:
            item = _strip(item, tuple(deeper[key]))
        out[key] = item
    return out


def reject_floats(value: Any, path: str = "") -> None:
    """Raise if any float is reachable from ``value``, naming where it is.

    Called on the way into the digest rather than at the model boundary alone,
    so a dict that reached a spec through some path with no validator on it
    still cannot silently make a study's digest platform-dependent.
    """
    if isinstance(value, float):
        raise NonCanonicalValue(
            f"{path or '<root>'} is the float {value!r}. Study specs are digested, and a "
            "float's decimal form depends on the parser that read it; write it as a "
            f'string ("{value!r}") so the digest means the same thing everywhere.'
        )
    if isinstance(value, dict):
        for key, item in value.items():
            reject_floats(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            reject_floats(item, f"{path}[{index}]")


def canonical_form(payload: dict[str, Any]) -> dict[str, Any]:
    """The digested view of a payload: its JSON form minus the excluded paths."""
    stripped: dict[str, Any] = _strip(payload, DIGEST_EXCLUDED_PATHS)
    return stripped


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Canonical JSON encoding of ``payload``, as digested."""
    form = canonical_form(payload)
    reject_floats(form)
    return json.dumps(
        form,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest_payload(payload: dict[str, Any]) -> str:
    """SHA-256 of the canonical form, prefixed the way ADP prefixes digests."""
    return DIGEST_PREFIX + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def short(digest: str) -> str:
    """The first 12 hex characters, as used in ``external_ref`` and intent titles.

    Short enough to read in a run listing, long enough that a collision inside
    one experiment is not a thing that happens.
    """
    return digest.removeprefix(DIGEST_PREFIX)[:12]
