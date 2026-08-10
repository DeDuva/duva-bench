#!/usr/bin/env python3
"""A grader that grades nothing and reports its own environment.

Its whole job is to make the environment-stripping rule checkable: whatever
duva-bench handed this process is what an untrusted grader would have had.
"""

import json
import os
import sys

print(
    json.dumps(
        {
            "spec": {"grader": "env-printer", "version": "1.0.0"},
            "axes": {
                "environment": {
                    "score": 1.0,
                    "passed": True,
                    "summary": "reported the environment it was given",
                }
            },
            "environment": sorted(os.environ),
            "cwd": os.getcwd(),
            "argv": sys.argv[1:],
        },
        sort_keys=True,
    )
)
