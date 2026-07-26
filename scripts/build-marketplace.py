#!/usr/bin/env python3
"""Generate (or --check) .claude-plugin/marketplace.json from every conforming skill.

    python3 scripts/build-marketplace.py           # regenerate marketplace.json
    python3 scripts/build-marketplace.py --check   # fail if the committed file is stale

See scripts/marketplace.py for the implementation and docs/agents/skills.md for usage.

Why this thin wrapper exists (issue #55 audit): ``scripts/marketplace.py`` is
its own CLI now (issue #54), but this clone remains a *stable, named* entry
point referenced by CI (``validate-skills.yml``), the
``test_marketplace.py`` drift guard (issue #46), ADR-0003, and this file's own
error message. Deleting it would move those references rather than concentrate
complexity, so the deletion test keeps it. The logic lives in
``scripts/marketplace.py``; this file is the named target only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import marketplace  # noqa: E402

if __name__ == "__main__":
    sys.exit(marketplace.main(sys.argv[1:]))
