#!/usr/bin/env python3
"""Unit tests for marketplace.json generation (ADR-0002 → plugin entries).

Zero-dependency: runnable directly as ``python3 scripts/test_marketplace.py``.
Exits non-zero on any failure. Covers the derive path (config + frontmatter →
plugin), drift detection (--check), and byte-stable regeneration.
"""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skills  # noqa: E402


@contextlib.contextmanager
def _setup_tmp():
    """Create a temporary directory with an empty skills/ subdirectory."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        skills_root = tmp / "skills"
        skills_root.mkdir()
        yield tmp, skills_root


def _make_skill(dir_path: Path, name: str, description: str, version: str) -> Path:
    """Write a minimal conforming SKILL.md with frontmatter into dir_path/name/."""
    skill_dir = dir_path / name
    skill_dir.mkdir(parents=True)
    md = skill_dir / "SKILL.md"
    md.write_text(f"""---
name: {name}
description: "{description}"
version: {version}
requires: []
produces: []
---
""", encoding="utf-8")
    return md


def _write_config(path: Path, name="test-marketplace", owner_name="tester",
                  desc="Test marketplace.") -> None:
    path.write_text(json.dumps({
        "name": name,
        "owner": {"name": owner_name},
        "metadata": {"description": desc},
        "plugin_defaults": {"strict": False, "skills": ["./"]},
    }, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    failed = 0

    # --- Derive path: config + frontmatter → plugin entries -------------------
    print("derive path:")
    with _setup_tmp() as (tmp, skills_root):
        _make_skill(skills_root, "alpha-skill", "First skill.", "1.0.0")
        _make_skill(skills_root, "beta-skill", "Second skill.", "2.0.0")

        config_path = tmp / "config.json"
        _write_config(config_path)

        config = skills._load_marketplace_config(config_path)
        rendered = skills.render_marketplace(skills_root, config)
        mp = json.loads(rendered)

        # Top-level fields from config.
        if mp["name"] != "test-marketplace":
            print(f"  FAIL marketplace.name = {mp['name']!r}, expected 'test-marketplace'")
            failed += 1
        if mp["owner"]["name"] != "tester":
            print(f"  FAIL owner.name = {mp['owner']['name']!r}, expected 'tester'")
            failed += 1
        if mp["metadata"]["description"] != "Test marketplace.":
            print(f"  FAIL metadata.description mismatch")
            failed += 1

        # Plugins sorted alphabetically by name.
        plugins = mp["plugins"]
        if len(plugins) != 2:
            print(f"  FAIL expected 2 plugins, got {len(plugins)}")
            failed += 1
        else:
            if plugins[0]["name"] != "alpha-skill":
                print(f"  FAIL first plugin should be alpha-skill, got {plugins[0]['name']!r}")
                failed += 1
            if plugins[1]["name"] != "beta-skill":
                print(f"  FAIL second plugin should be beta-skill, got {plugins[1]['name']!r}")
                failed += 1
            # Check derive fields.
            for p in plugins:
                name = p["name"]
                if p["source"] != f"./skills/{name}":
                    print(f"  FAIL {name} source = {p['source']!r}, expected './skills/{name}'")
                    failed += 1
                if p["version"] not in ("1.0.0", "2.0.0"):
                    print(f"  FAIL {name} version = {p['version']!r}")
                    failed += 1
                if p["strict"] is not False:
                    print(f"  FAIL {name} strict should be False, got {p['strict']!r}")
                    failed += 1
                if p["skills"] != ["./"]:
                    print(f"  FAIL {name} skills should be ['./'], got {p['skills']!r}")
                    failed += 1

    # --- Drift detection: --check fails when committed differs ----------------
    print("drift detection (--check):")
    with _setup_tmp() as (tmp, skills_root):
        _make_skill(skills_root, "alpha-skill", "First skill.", "1.0.0")

        config_path = tmp / "config.json"
        _write_config(config_path)

        out_path = tmp / "marketplace.json"

        # Simulate args for cmd_marketplace.
        class Args:
            root = str(skills_root)
            output = str(out_path)
            config = str(config_path)
            check = False

        # First, generate the file.
        rc = skills.cmd_marketplace(Args)
        if rc != 0:
            print(f"  FAIL generate returned {rc}")
            failed += 1

        # --check against the just-generated file should pass.
        Args.check = True
        rc = skills.cmd_marketplace(Args)
        if rc != 0:
            print(f"  FAIL --check against fresh file returned {rc}")
            failed += 1

        # Corrupt the file — add a trailing newline or extra field.
        corrupted = out_path.read_text(encoding="utf-8") + "\n"
        out_path.write_text(corrupted, encoding="utf-8")
        rc = skills.cmd_marketplace(Args)
        if rc == 0:
            print("  FAIL --check should fail on corrupted marketplace")
            failed += 1

        # Missing file.
        out_path.unlink()
        rc = skills.cmd_marketplace(Args)
        if rc == 0:
            print("  FAIL --check should fail when marketplace file is missing")
            failed += 1

    # --- Stable regeneration: byte-identical output --------------------------
    print("stable regeneration:")
    with _setup_tmp() as (tmp, skills_root):
        _make_skill(skills_root, "alpha-skill", "First skill.", "1.0.0")

        config_path = tmp / "config.json"
        _write_config(config_path)

        config = skills._load_marketplace_config(config_path)
        first = skills.render_marketplace(skills_root, config)
        second = skills.render_marketplace(skills_root, config)
        if first != second:
            print("  FAIL regeneration is not byte-stable")
            # Show the diff.
            for i, (a, b) in enumerate(zip(first, second)):
                if a != b:
                    print(f"       diff at byte {i}: {a!r} vs {b!r}")
                    break
            failed += 1

        # Trailing newline present (JSON lines end with \n).
        if not first.endswith("\n"):
            print("  FAIL output does not end with newline")
            failed += 1

    # --- Config validation: missing required keys ----------------------------
    print("config validation:")
    with _setup_tmp() as (tmp, skills_root):
        _make_skill(skills_root, "alpha-skill", "First skill.", "1.0.0")

        for missing_key, test_config in [
            ("name", {"owner": {"name": "t"}, "metadata": {"description": "d"}}),
            ("owner", {"name": "n", "metadata": {"description": "d"}}),
            ("metadata", {"name": "n", "owner": {"name": "t"}}),
        ]:
            config_path = tmp / "config.json"
            config_path.write_text(json.dumps(test_config), encoding="utf-8")
            try:
                skills._load_marketplace_config(config_path)
                print(f"  FAIL _load_marketplace_config should exit on missing '{missing_key}'")
                failed += 1
            except SystemExit as exc:
                if exc.code != 2:
                    print(f"  FAIL missing '{missing_key}' exited {exc.code}, expected 2")
                    failed += 1

        # Missing metadata.description.
        config_path.write_text(json.dumps({
            "name": "n", "owner": {"name": "t"}, "metadata": {},
        }), encoding="utf-8")
        try:
            skills._load_marketplace_config(config_path)
            print("  FAIL should exit on missing metadata.description")
            failed += 1
        except SystemExit as exc:
            if exc.code != 2:
                print(f"  FAIL missing metadata.description exited {exc.code}, expected 2")
                failed += 1

        # Missing owner.name.
        config_path.write_text(json.dumps({
            "name": "n", "owner": {}, "metadata": {"description": "d"},
        }), encoding="utf-8")
        try:
            skills._load_marketplace_config(config_path)
            print("  FAIL should exit on missing owner.name")
            failed += 1
        except SystemExit as exc:
            if exc.code != 2:
                print(f"  FAIL missing owner.name exited {exc.code}, expected 2")
                failed += 1

        # Missing config file.
        try:
            skills._load_marketplace_config(tmp / "nonexistent.json")
            print("  FAIL should exit on missing config file")
            failed += 1
        except SystemExit as exc:
            if exc.code != 2:
                print(f"  FAIL missing config file exited {exc.code}, expected 2")
                failed += 1

    # --- Empty skills → empty plugins list (still valid marketplace) ----------
    print("empty skills:")
    with _setup_tmp() as (tmp, skills_root):
        # No skills created — empty directory.

        config_path = tmp / "config.json"
        _write_config(config_path)

        config = skills._load_marketplace_config(config_path)
        rendered = skills.render_marketplace(skills_root, config)
        mp = json.loads(rendered)
        if mp["plugins"] != []:
            print(f"  FAIL expected empty plugins list, got {mp['plugins']!r}")
            failed += 1

    # --- Summary -------------------------------------------------------------
    if failed:
        print(f"\n{failed} marketplace test(s) failed.", file=sys.stderr)
        return 1
    print("\nAll marketplace tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
