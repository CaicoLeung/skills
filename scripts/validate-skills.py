#!/usr/bin/env python3
"""Validate every skill's frontmatter. Exits non-zero on any failure.

Implements the ADR-0002 contract. See scripts/skills.py for the implementation
and docs/agents/skills.md for authoring guidance.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skills  # noqa: E402

if __name__ == "__main__":
    sys.exit(skills.main(["validate", *sys.argv[1:]]))
