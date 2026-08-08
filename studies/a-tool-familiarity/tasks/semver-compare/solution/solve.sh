#!/usr/bin/env bash
# Harbor's oracle: proves the task and its verifier agree, so a failing
# arm is a failing arm rather than a broken task.
set -euo pipefail

cat > /app/semver.py <<'PY'
import re

PATTERN = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


def _parse(text):
    matched = PATTERN.match(text.strip())
    if not matched:
        raise ValueError(f"not a semantic version: {text!r}")
    major, minor, patch, pre = matched.groups()
    return (int(major), int(minor), int(patch), pre)


def _pre_key(part):
    return (0, int(part), "") if part.isdigit() else (1, 0, part)


def compare(left, right):
    a = _parse(left)
    b = _parse(right)
    if a[:3] != b[:3]:
        return -1 if a[:3] < b[:3] else 1
    if a[3] == b[3]:
        return 0
    if a[3] is None:
        return 1
    if b[3] is None:
        return -1
    first = [_pre_key(p) for p in a[3].split(".")]
    second = [_pre_key(p) for p in b[3].split(".")]
    if first == second:
        return 0
    return -1 if first < second else 1
PY
