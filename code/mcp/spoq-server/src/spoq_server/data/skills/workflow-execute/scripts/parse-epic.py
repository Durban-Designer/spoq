#!/usr/bin/env python3
"""
Parse an epic directory and output JSON with metadata and tasks.

Usage:
    python3 parse-epic.py spoq/epics/epic-name
    python3 parse-epic.py spoq/epics/epic-name --validate
"""

import sys
import json
from pathlib import Path

# Add lib directory to path for imports
lib_path = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_path))

from epic_utils import parse_epic


def main():
    if len(sys.argv) < 2:
        print("Usage: parse-epic.py <epic-path> [--validate]", file=sys.stderr)
        sys.exit(1)

    epic_path = Path(sys.argv[1])
    validate = "--validate" in sys.argv

    result = parse_epic(epic_path, validate=validate)

    # Output JSON
    print(json.dumps(result, indent=2))

    # Exit with error code if there were errors
    if "errors" in result or "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
