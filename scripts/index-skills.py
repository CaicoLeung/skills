#!/usr/bin/env python3
"""Generate (or --check) skills/INDEX.md from every conforming skill.

    python3 scripts/index-skills.py           # regenerate skills/INDEX.md
    python3 scripts/index-skills.py --check   # fail if the committed index is stale

See scripts/skills.py for the implementation and docs/agents/skills.md for usage.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skills  # noqa: E402

if __name__ == "__main__":
    sys.exit(skills.main(["index", *sys.argv[1:]]))
