#!/usr/bin/env python3
"""Validate every skill's frontmatter. Exits non-zero on any failure.

Implements the ADR-0002 contract. See scripts/skills.py for the implementation
and docs/agents/skills.md for authoring guidance.

Why this thin wrapper exists (issue #55 audit): ``validate`` is a subcommand of
``scripts/skills.py``, but this clone is a *stable, named* entry point referenced
by CI (``validate-skills.yml``), ``CLAUDE.md``, ``README.md``, the ADRs, the
``test_marketplace``/branch-protection guards, and the generated
``skills/INDEX.md`` header. Deleting it would touch ~a dozen call sites —
moving complexity, not concentrating it — so the deletion test keeps it. The
logic lives in ``scripts/skills.py``; this file is the named target only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skills  # noqa: E402

if __name__ == "__main__":
    sys.exit(skills.main(["validate", *sys.argv[1:]]))
