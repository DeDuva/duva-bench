import json
import sys

try:
    document = json.load(sys.stdin)
except json.JSONDecodeError:
    print("invalid json", file=sys.stderr)
    raise SystemExit(2)

json.dump(document, sys.stdout, sort_keys=True, indent=2, ensure_ascii=False)
sys.stdout.write("\n")
