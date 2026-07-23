#!/usr/bin/env python3
"""Skill frontmatter parser, validator, and index generator.

Implements the contract in docs/adr/0002-skill-frontmatter-contract.md.
Zero third-party dependencies: parses a *restricted* YAML frontmatter subset
(top-level ``key: scalar`` pairs and indented ``- item`` block sequences) pinned
to the five required fields. Anything outside that subset is rejected.

Subcommands:
    python3 scripts/skills.py validate [--root ROOT]
    python3 scripts/skills.py index    [--root ROOT] [--output PATH] [--check]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# --- Schema (ADR-0002) -------------------------------------------------------

FIELDS_SCALAR = ("name", "description", "version")
FIELDS_LIST = ("requires", "produces")
REQUIRED = FIELDS_SCALAR + FIELDS_LIST
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
DESCRIPTION_MAX = 300


# --- Branch protection drift guard ------------------------------------------


def _extract_workflow_job_names(workflows_dir: Path) -> set[str]:
    """Extract top-level job names from all workflow YAML files."""
    jobs: set[str] = set()
    if not workflows_dir.exists():
        return jobs

    for wf_file in workflows_dir.glob("*.yml"):
        content = wf_file.read_text(encoding="utf-8")
        lines = content.splitlines()

        in_jobs = False
        jobs_indent = None
        for raw in lines:
            stripped = raw.strip()
            if stripped == "jobs:":
                in_jobs = True
                jobs_indent = len(raw) - len(raw.lstrip())
                continue

            if in_jobs and raw.strip():
                current_indent = len(raw) - len(raw.lstrip())
                # Exit jobs section on same-level or less-indented top-level key
                if current_indent <= jobs_indent and ":" in raw:
                    in_jobs = False
                    continue

                # Job name: exactly one level deeper than jobs:
                if in_jobs and ":" in raw:
                    # Must be directly under jobs: (one level of indentation)
                    line_indent = len(raw) - len(raw.lstrip())
                    if line_indent == jobs_indent + 2:
                        potential = raw.strip().split(":", 1)[0].strip()
                        if potential and not potential.startswith("#"):
                            jobs.add(potential)

    return jobs


def _get_branch_protection_contexts(repo: str = "CaicoLeung/skills") -> list[str]:
    """Fetch required status check contexts from branch protection via GitHub REST API.

    Uses GITHUB_TOKEN for auth. Falls back gracefully if unavailable.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return []

    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/branches/main/protection",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            contexts = data.get("required_status_checks", {}).get("contexts", [])
            return contexts
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as e:
        # 404 = no protection configured, 403/401 = insufficient permissions
        if isinstance(e, urllib.error.HTTPError) and e.code in (404, 403, 401):
            return []  # No/unknown protection or no access = no contexts to check
        # In CI, fail loudly; locally, skip gracefully
        if os.environ.get("CI"):
            raise RuntimeError(f"Failed to fetch branch protection: {e}") from e
        return []


def _validate_branch_protection(repo_root: Path) -> list[str]:
    """Validate that each branch protection context has a matching workflow job name."""
    errors: list[str] = []
    workflows_dir = repo_root / ".github" / "workflows"

    job_names = _extract_workflow_job_names(workflows_dir)
    if not job_names:
        errors.append("no workflow job names found in .github/workflows/*.yml")

    contexts = _get_branch_protection_contexts()
    if not contexts:
        # In CI, empty contexts means the API call failed (already raised above)
        # Locally, might not be authenticated — skip this check gracefully
        return errors

    for ctx in contexts:
        if ctx not in job_names:
            errors.append(
                f"branch protection requires context '{ctx}' "
                f"but no workflow job has that name (found: {sorted(job_names)})"
            )

    return errors


def _validate_branch_protection_info(repo_root: Path) -> list[str]:
    """Return informational messages about branch protection (non-failing)."""
    info: list[str] = []
    workflows_dir = repo_root / ".github" / "workflows"
    job_names = _extract_workflow_job_names(workflows_dir)

    contexts = _get_branch_protection_contexts()
    if contexts:
        orphan_jobs = job_names - set(contexts)
        if orphan_jobs:
            info.append(
                f"note: workflow job(s) {sorted(orphan_jobs)} not required by branch protection"
            )

    return info


@dataclass
class Skill:
    dir: str
    path: Path
    meta: dict
    errors: list = field(default_factory=list)


# --- Restricted frontmatter parser ------------------------------------------


def _unquote(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        inner = val[1:-1]
        if val[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return val
def _parse_flow(val: str) -> list:
    """Parse an inline flow sequence ``[a, b, "c d"]`` into a list.

    Part of the restricted frontmatter subset (ADR-0002): only flow sequences
    are supported for list fields, alongside indented ``- item`` blocks.
    """
    inner = val[1:-1]
    if inner.strip() == "":
        return []
    items, cur, quote = [], "", None
    for ch in inner:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            cur += ch
        elif ch == ",":
            items.append(_unquote(cur.strip()))
            cur = ""
        else:
            cur += ch
    items.append(_unquote(cur.strip()))
    return items


def parse_frontmatter(text: str):
    """Return (meta_dict, error_or_None). meta is {} on a hard parse failure."""
    # Accept CRLF and LF; treat leading BOM defensively.
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "must start with a '---' frontmatter fence"
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, "frontmatter is not closed with a '---' fence"
    if end == 1:
        return {}, "frontmatter is empty"

    meta: dict = {}
    cur_key = None
    for n, raw in enumerate(lines[1:end], start=2):
        stripped = raw.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        # Block sequence item.
        if stripped == "-" or stripped.startswith("- "):
            if cur_key is None:
                return {}, f"line {n}: sequence item with no preceding key"
            if not isinstance(meta.get(cur_key), list):
                return {}, f"line {n}: sequence under scalar key '{cur_key}'"
            item = "" if stripped == "-" else stripped[2:].strip()
            meta[cur_key].append(_unquote(item))
            continue
        # A top-level key must not be indented.
        if raw[:1] in (" ", "\t"):
            return {}, f"line {n}: unexpected indented line {raw!r}"
        if ":" not in stripped:
            return {}, f"line {n}: expected 'key: value', got {raw!r}"
        key, _, val = stripped.partition(":")
        key = key.strip()
        if not key:
            return {}, f"line {n}: empty key"
        if key in meta:
            return {}, f"line {n}: duplicate key '{key}'"
        val = val.strip()
        if val == "":
            cur_key = key
            meta[key] = []
        elif val.startswith("[") and val.endswith("]"):
            cur_key = key
            meta[key] = _parse_flow(val)
        else:
            cur_key = key
            meta[key] = _unquote(val)
    return meta, None


# --- Validation --------------------------------------------------------------


def validate_meta(meta: dict, skill_dir: str) -> list:
    errors: list = []
    for k in REQUIRED:
        if k not in meta:
            errors.append(f"missing required field '{k}'")
    for k in meta:
        if k not in REQUIRED:
            errors.append(f"unknown field '{k}' (schema is closed)")

    if "name" in meta:
        name = meta["name"]
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            errors.append(f"name '{name}' must be kebab-case matching [a-z0-9][a-z0-9-]*")
        elif name != skill_dir:
            errors.append(f"name '{name}' must equal skill directory '{skill_dir}'")

    if "description" in meta:
        desc = meta["description"]
        if not isinstance(desc, str) or not desc.strip():
            errors.append("description must be a non-empty string")
        elif len(desc) > DESCRIPTION_MAX:
            errors.append(f"description is {len(desc)} chars (max {DESCRIPTION_MAX})")

    if "version" in meta:
        ver = meta["version"]
        if not isinstance(ver, str) or not VERSION_RE.fullmatch(ver):
            errors.append(f"version '{ver}' must be semver MAJOR.MINOR.PATCH")

    for k in FIELDS_LIST:
        if k not in meta:
            continue
        v = meta[k]
        if not isinstance(v, list):
            errors.append(f"'{k}' must be a list")
            continue
        for item in v:
            if not isinstance(item, str) or not item.strip():
                errors.append(f"'{k}' contains an empty / non-string item")
            elif not NAME_RE.fullmatch(item):
                errors.append(f"'{k}' item '{item}' must be kebab-case")
    return errors


# --- Discovery ---------------------------------------------------------------


def discover(skills_root: Path) -> list:
    skills = []
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        skill_dir = skill_md.parent.name
        text = skill_md.read_text(encoding="utf-8")
        meta, err = parse_frontmatter(text)
        errors = [err] if err else validate_meta(meta, skill_dir)
        skills.append(Skill(dir=skill_dir, path=skill_md, meta=meta, errors=errors))
    return skills


# --- Commands ----------------------------------------------------------------


def cmd_validate(args) -> int:
    skills_root = Path(args.root)
    if not skills_root.is_dir():
        print(f"error: skills root not found: {skills_root}", file=sys.stderr)
        return 2
    skills = discover(skills_root)
    if not skills:
        print(f"error: no skills found under {skills_root}", file=sys.stderr)
        return 2
    failed = [s for s in skills if s.errors]
    for s in skills:
        rel = s.path.relative_to(skills_root.parent)
        if s.errors:
            print(f"FAIL {rel}")
            for e in s.errors:
                print(f"      - {e}")
        else:
            print(f"ok   {rel}")
    if failed:
        print(f"\n{len(failed)} skill(s) failed validation.", file=sys.stderr)
        return 1
    print(f"\n{len(skills)} skill(s) valid.")

    # Branch protection drift guard
    repo_root = skills_root.parent
    protection_errors = _validate_branch_protection(repo_root)
    if protection_errors:
        print("\nBranch protection guard:", file=sys.stderr)
        for e in protection_errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    # Info-only messages (don't fail)
    for msg in _validate_branch_protection_info(repo_root):
        print(f"  {msg}")

    return 0


INDEX_HEADER = "<!-- AUTO-GENERATED by scripts/index-skills.py — do not edit. -->\n"


def render_index(skills_root: Path) -> str:
    skills = [s for s in discover(skills_root) if not s.errors]
    lines = [INDEX_HEADER, "# Skills", ""]
    if not skills:
        lines += ["_No conforming skills found._", ""]
        return "\n".join(lines)
    lines += [
        "| Skill | Version | Description | Requires | Produces |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in skills:
        m = s.meta
        req = ", ".join(m.get("requires", [])) or "—"
        prod = ", ".join(m.get("produces", [])) or "—"
        desc = m.get("description", "").replace("|", "\\|")
        lines.append(
            f"| [`{m['name']}`](skills/{s.dir}/SKILL.md) | `{m['version']}` "
            f"| {desc} | {req} | {prod} |"
        )
    lines.append("")
    return "\n".join(lines)


def cmd_index(args) -> int:
    skills_root = Path(args.root)
    out = Path(args.output) if args.output else skills_root.parent / "skills" / "INDEX.md"
    generated = render_index(skills_root)
    if args.check:
        existing = out.read_text(encoding="utf-8") if out.exists() else ""
        if existing != generated:
            print(
                f"error: {out} is stale or missing — run "
                f"'python3 scripts/index-skills.py' to regenerate.",
                file=sys.stderr,
            )
            return 1
        print(f"ok   {out} is up to date.")
        return 0
    out.write_text(generated, encoding="utf-8")
    print(f"wrote {out}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("validate", help="validate all skills' frontmatter")
    pv.add_argument("--root", default="skills", help="skills directory (default: skills)")
    pv.set_defaults(func=cmd_validate)

    pi = sub.add_parser("index", help="generate or check skills/INDEX.md")
    pi.add_argument("--root", default="skills", help="skills directory (default: skills)")
    pi.add_argument("--output", help="output path (default: skills/INDEX.md)")
    pi.add_argument("--check", action="store_true", help="fail if the index is stale")
    pi.set_defaults(func=cmd_index)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
