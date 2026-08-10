"""Re-vendor ADP's OpenAPI document as JSON.

Two stages, and only this one needs a YAML parser. The vendored artifact is
JSON so that the generator — and anyone auditing what the client was built
against — needs nothing but the standard library, and so that the digest the
generator stamps into the generated module is a digest of bytes this repository
holds rather than of a file on somebody's laptop.

    make sync-spec ADP_SPEC=../adp/spec/openapi.yaml

The output is written with sorted keys and a fixed indent, so re-vendoring an
unchanged document is a no-op in the diff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
VENDORED = ROOT / "spec" / "adp-openapi.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="ADP's spec/openapi.yaml")
    parser.add_argument("--out", type=Path, default=VENDORED)
    args = parser.parse_args(argv)

    document: Any = yaml.safe_load(args.source.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or "paths" not in document:
        raise SystemExit(f"{args.source} does not look like an OpenAPI document")

    rendered = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")

    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    version = document.get("info", {}).get("version", "?")
    print(f"{args.out.relative_to(ROOT)}: contract {version}, sha256:{digest}")
    print("Now run: make generate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
