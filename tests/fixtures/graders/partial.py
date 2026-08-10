#!/usr/bin/env python3
"""A grader with one axis it could not measure. Unscored is not zero."""

import json

print(
    json.dumps(
        {
            "spec": {"grader": "partial", "version": "1.0.0"},
            "axes": {
                "acceptance": {"score": 0.5, "passed": False, "summary": "1/2 cases"},
                "latency": {"score": None, "passed": False, "summary": "the timer never started"},
            },
        },
        sort_keys=True,
    )
)
