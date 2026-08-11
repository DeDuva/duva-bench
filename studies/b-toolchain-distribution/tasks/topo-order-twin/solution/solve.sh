#!/usr/bin/env bash
set -euo pipefail
python3 - <<'ORACLE'
from pathlib import Path
p = Path('/workspace/kelvra/graph/__init__.py')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('"""Dependency resolution."""\n\n\nclass Cycle(Exception):\n    """Raised when a graph cannot be ordered. `members` holds who is involved."""\n\n    def __init__(self, members):\n        super().__init__(f"cycle among {sorted(members)}")\n        self.members = sorted(members)\n\n\ndef resolve(graph):\n    """Return the names of `graph` in dependency order."""\n    names = set(graph)\n    for needs in graph.values():\n        names.update(needs)\n    remaining = {name: set(graph.get(name, ())) for name in names}\n\n    ordered = []\n    while remaining:\n        ready = sorted(name for name, needs in remaining.items() if not needs)\n        if not ready:\n            raise Cycle(remaining)\n        for name in ready:\n            ordered.append(name)\n            del remaining[name]\n        for needs in remaining.values():\n            needs.difference_update(ready)\n    return ordered\n')
p = Path('/workspace/kelvra/report/__init__.py')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('"""Build planning."""\n\nfrom graph import resolve\n\n\ndef plan_build(graph):\n    """The order this build should run in."""\n    return resolve(graph)\n')
p = Path('/workspace/brivols/test_report.py')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('import pytest\n\nfrom graph import Cycle\nfrom report import plan_build\n\n\ndef test_plan_build_orders_a_simple_chain():\n    assert plan_build({"a": ["b"], "b": []}) == ["b", "a"]\n\n\ndef test_plan_build_breaks_ties_alphabetically():\n    assert plan_build({"b": [], "a": [], "c": []}) == ["a", "b", "c"]\n\n\ndef test_plan_build_rejects_a_cycle():\n    with pytest.raises(Cycle) as raised:\n        plan_build({"a": ["b"], "b": ["a"]})\n    assert raised.value.members == ["a", "b"]\n')
ORACLE
