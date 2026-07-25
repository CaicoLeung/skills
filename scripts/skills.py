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
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- Schema (ADR-0002, amended by ADR-0009) ----------------------------------
#
# Five required fields (ADR-0002) plus one OPTIONAL boolean field
# (``asks-user-questions``, ADR-0009): asserted ``true`` by any skill that
# interviews the user. When asserted, the skill body MUST reference the
# question-numbering convention (see :data:`CONVENTION_DOC_REF`). Absent means
# the skill does not interview and the convention does not bind it.

FIELDS_SCALAR = ("name", "description", "version")
FIELDS_LIST = ("requires", "produces")
FIELDS_BOOLEAN = ("asks-user-questions",)  # optional (ADR-0009)
REQUIRED = FIELDS_SCALAR + FIELDS_LIST
ALLOWED = REQUIRED + FIELDS_BOOLEAN  # schema is closed; this is the full set
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
DESCRIPTION_MAX = 300

# The convention doc a skill body must reference when it interviews the user
# (ADR-0009). Checked as a path substring so a relative link, a bare path, or a
# markdown link all satisfy it.
CONVENTION_DOC_REF = "docs/agents/question-numbering.md"


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


def _to_scalar(val: str) -> bool | str:
    """Coerce a parsed bare scalar into its Python value.

    Part of the restricted frontmatter subset: bare YAML core-schema booleans
    ``true`` / ``false`` become Python ``bool``; every other bare scalar stays a
    ``str``. Quoted values are always strings (handled by :func:`_unquote`), so
    ``description: "true"`` remains the string ``"true"``. Only top-level scalar
    assignments pass through here; list items and flow-sequence items stay
    strings.
    """
    if val == "true":
        return True
    if val == "false":
        return False
    return val


def _assign_scalar(val: str) -> bool | str:
    """Coerce a top-level scalar field value, respecting YAML quote semantics.

    A quoted value (matching single/double quotes) is always a string, so
    ``asks-user-questions: "true"`` stays the string ``"true"`` (and the
    validator then rejects it as non-boolean). A bare ``true`` / ``false``
    becomes a Python ``bool``; everything else stays a string.
    """
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return _unquote(val)  # quoted → string, never coerced
    return _to_scalar(val)
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


def _strip_bom_and_split(text: str) -> list[str]:
    """Strip a leading BOM and split into lines (shared frontmatter prep).

    Accepts CRLF and LF; the leading U+FEFF is removed defensively so an editor
    BOM does not hide the opening ``---`` fence.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.splitlines()


def _frontmatter_close_index(lines: list[str]) -> int | None:
    """Index of the closing ``---`` fence, or ``None`` when there is none.

    Expects BOM-stripped lines (see :func:`_strip_bom_and_split`). Returns
    ``None`` if there is no opening ``---`` or no closing ``---``. Shared by
    :func:`parse_frontmatter` (which maps the missing cases to specific errors)
    and :func:`_body_after_frontmatter` (which treats any failure as "no body").
    """
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i
    return None


def parse_frontmatter(text: str):
    """Return (meta_dict, error_or_None). meta is {} on a hard parse failure."""
    lines = _strip_bom_and_split(text)
    if not lines or lines[0].strip() != "---":
        return {}, "must start with a '---' frontmatter fence"
    end = _frontmatter_close_index(lines)
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
            meta[key] = _assign_scalar(val)
    return meta, None


def _body_after_frontmatter(text: str) -> str:
    """Return the text following the closing ``---`` frontmatter fence.

    Used by the interview-flag reference check (ADR-0009): when a skill asserts
    ``asks-user-questions: true`` its body must cite the convention doc. Returns
    an empty string when the frontmatter is missing or malformed (a hard parse
    failure already wins, so the body check is moot).
    """
    lines = _strip_bom_and_split(text)
    end = _frontmatter_close_index(lines)
    if end is None:
        return ""
    return "\n".join(lines[end + 1:])


# --- Validation --------------------------------------------------------------


def validate_meta(meta: dict, skill_dir: str, body: str = "") -> list:
    errors: list = []
    for k in REQUIRED:
        if k not in meta:
            errors.append(f"missing required field '{k}'")
    for k in meta:
        if k not in ALLOWED:
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

    # Interview-affordance flag (ADR-0009): optional boolean. When asserted
    # true, the skill body must reference the question-numbering convention so a
    # conforming interview skill cannot ship without pointing at the format.
    asks = meta.get("asks-user-questions")
    if asks is not None and not isinstance(asks, bool):
        errors.append(
            "'asks-user-questions' must be a boolean (true or false)"
        )
    if asks is True and CONVENTION_DOC_REF not in body:
        errors.append(
            "asks-user-questions: true is asserted, but the body does not "
            f"reference the question-numbering convention "
            f"({CONVENTION_DOC_REF})"
        )
    return errors


# --- Discovery ---------------------------------------------------------------


def discover(skills_root: Path) -> list:
    skills = []
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        skill_dir = skill_md.parent.name
        text = skill_md.read_text(encoding="utf-8")
        meta, err = parse_frontmatter(text)
        # The body (everything after the frontmatter fence) feeds the
        # interview-flag reference check (ADR-0009); only materialized when the
        # flag is asserted, but extracted unconditionally for a stable contract.
        body = "" if err else _body_after_frontmatter(text)
        errors = [err] if err else validate_meta(meta, skill_dir, body)
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
