#!/usr/bin/env python3
"""Marketplace JSON generator — skill frontmatter → .claude-plugin/marketplace.json.

Renders the single-plugin Claude Code marketplace manifest from
``.claude-plugin/marketplace-config.json`` plus every conforming skill's
frontmatter (ADR-0002). Extracted from ``scripts/skills.py`` (issue #54) so
``skills.py`` is reduced to the deep frontmatter parser + schema validator, and
the renderer — plus its own JSON config schema — is testable through its own
interface instead of via a private ``_load_marketplace_config`` helper.

The renderer imports the deep core (:mod:`skills`) for discovery; it owns no
parsing of its own. Byte-stable output is part of the contract (the marketplace
drift gate, issue #46, fails CI on a stale committed file).

CLI:
    python3 scripts/marketplace.py [--root ROOT] [--output PATH] [--config PATH] [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow ``python3 scripts/marketplace.py`` and ``from scripts.marketplace import``
# (pytest) to both find the sibling ``skills`` module (the deep core).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import skills  # noqa: E402


def _fatal(msg: str) -> None:
    """Print error to stderr and exit with code 2."""
    print(msg, file=sys.stderr)
    sys.exit(2)


def load_config(config_path: Path) -> dict:
    """Load + validate the marketplace config, or exit with a clear error.

    Public entry (was ``skills._load_marketplace_config``): the marketplace
    module is testable through its own interface, not a private helper. The
    config schema (``name`` / ``owner.name`` / ``metadata.description``) lives
    here, not piggybacked on the validator's module.
    """
    if not config_path.exists():
        _fatal(f"error: marketplace config not found: {config_path}")
    try:
        with open(config_path, encoding="utf-8") as fh:
            config: dict = json.load(fh)
    except json.JSONDecodeError as exc:
        _fatal(f"error: invalid JSON in {config_path}: {exc}")
    for key in ("name", "owner", "metadata"):
        if key not in config:
            _fatal(f"error: {config_path} missing required key '{key}'")
    owner = config.get("owner", {})
    if not isinstance(owner, dict) or not owner.get("name"):
        _fatal(f"error: {config_path} owner.name is required")
    if "description" not in config.get("metadata", {}):
        _fatal(f"error: {config_path} metadata.description is required")
    return config


def render(skills_root: Path, config: dict) -> str:
    """Generate marketplace.json from config + conforming skills' frontmatter.

    Plugins are sorted by name for deterministic, byte-stable output (the
    drift gate fails CI on a stale file). Defaults come from the config's
    ``plugin_defaults`` (``strict`` + the per-plugin ``skills`` list).
    """
    conforming = [s for s in skills.discover(skills_root) if not s.errors]
    defaults = config.get("plugin_defaults", {})
    strict = defaults.get("strict", False)
    skills_val = defaults.get("skills", ["./"])
    plugins = []
    for s in conforming:
        m = s.meta
        plugins.append({
            "name": m["name"],
            "source": f"./skills/{m['name']}",
            "description": m["description"],
            "version": m["version"],
            "strict": strict,
            "skills": skills_val,
        })
    # Sort plugins by name for deterministic output.
    plugins.sort(key=lambda p: p["name"])
    marketplace = {
        "name": config["name"],
        "owner": config["owner"],
        "metadata": config["metadata"],
        "plugins": plugins,
    }
    return json.dumps(marketplace, indent=2, ensure_ascii=False) + "\n"


def cmd_marketplace(args: argparse.Namespace) -> int:
    """Generate or --check ``.claude-plugin/marketplace.json``.

    The repo root is derived from the skills root's parent (``--root skills``
    ⇒ repo root), so the default config/output paths resolve without extra
    flags.
    """
    repo_root = Path(args.root).resolve().parent
    config_path = (
        Path(args.config) if args.config
        else repo_root / ".claude-plugin" / "marketplace-config.json"
    )
    out = (
        Path(args.output) if args.output
        else repo_root / ".claude-plugin" / "marketplace.json"
    )
    config = load_config(config_path)
    skills_root = Path(args.root)
    generated = render(skills_root, config)
    if args.check:
        existing = out.read_text(encoding="utf-8") if out.exists() else ""
        if existing != generated:
            print(
                f"error: {out} is stale or missing — run "
                f"'python3 scripts/build-marketplace.py' to regenerate.",
                file=sys.stderr,
            )
            return 1
        print(f"ok   {out} is up to date.")
        return 0
    out.write_text(generated, encoding="utf-8")
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Marketplace generator CLI (generate or --check)."""
    p = argparse.ArgumentParser(
        description="Generate/check .claude-plugin/marketplace.json from skill frontmatter.",
    )
    p.add_argument("--root", default="skills", help="skills directory (default: skills)")
    p.add_argument("--output", help="output path (default: .claude-plugin/marketplace.json)")
    p.add_argument("--config", help="config path (default: .claude-plugin/marketplace-config.json)")
    p.add_argument("--check", action="store_true", help="fail if the marketplace is stale")
    args = p.parse_args(argv)
    return cmd_marketplace(args)


if __name__ == "__main__":
    sys.exit(main())
