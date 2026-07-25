#!/usr/bin/env python3
"""Generate (or --check) .claude-plugin/marketplace.json from every conforming skill.

    python3 scripts/build-marketplace.py           # regenerate marketplace.json
    python3 scripts/build-marketplace.py --check   # fail if the committed file is stale

See scripts/marketplace.py for the implementation and docs/agents/skills.md for usage.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import marketplace  # noqa: E402

if __name__ == "__main__":
    sys.exit(marketplace.main(sys.argv[1:]))
