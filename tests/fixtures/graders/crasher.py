#!/usr/bin/env python3
"""A grader that dies. The trial it was scoring is unscored, never zero."""

import sys

print("about to fail", file=sys.stderr)
raise SystemExit(3)
