import json
import sys

document = json.load(sys.stdin)
json.dump(document, sys.stdout, sort_keys=True, indent=2, ensure_ascii=False)
sys.stdout.write("\n")
