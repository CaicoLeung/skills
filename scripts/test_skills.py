#!/usr/bin/env python3
"""Unit tests for the skill frontmatter validator's interview-flag rule.

Zero-dependency: runnable directly as ``python3 scripts/test_skills.py``.
Exits non-zero on any failure. Table-driven, public-surface-only style.

Scope (ADR-0009): the one new test seam — the validator's external accept/reject
behavior for the optional ``asks-user-questions`` boolean field, plus the
parser coercion that enables it, exercised through the public surface
(:func:`skills.validate_meta`, :func:`skills.parse_frontmatter`). Prose
formatting quality is deliberately not asserted (those are review concerns,
per the ADR's testing decisions). Internal helpers (body extraction, scalar
coercion) are covered indirectly through that public surface, never imported.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skills  # noqa: E402


def _base_meta(**overrides) -> dict:
    """A minimal conforming meta dict (all five required fields present)."""
    meta = {
        "name": "demo-skill",
        "description": "A demo skill.",
        "version": "0.1.0",
        "requires": [],
        "produces": [],
    }
    meta.update(overrides)
    return meta


def _has_interview_error(errors: list) -> bool:
    return any("asks-user-questions" in e for e in errors)


def _full_skill(flag_line: str, body: str) -> str:
    """Render a complete SKILL.md text with a given flag line and body."""
    return (
        "---\n"
        "name: demo-skill\n"
        'description: "A demo skill."\n'
        "version: 0.1.0\n"
        "requires: []\n"
        "produces: []\n"
        f"{flag_line}\n"
        "---\n"
        f"{body}\n"
    )


def main() -> int:
    failed = 0
    convention = skills.CONVENTION_DOC_REF

    # --- The one test seam: (label, meta, body, expected_pass) --------------
    # Accept/reject only. Prose quality is out of scope (ADR-0009 testing).
    print("interview-flag accept/reject:")
    cases = [
        # Flag absent → never binds, body irrelevant.
        (
            "flag absent passes (convention does not bind)",
            _base_meta(),
            "body does not mention the convention at all",
            True,
        ),
        # Flag explicitly false → also does not bind.
        (
            "flag false passes (convention does not bind)",
            _base_meta(**{"asks-user-questions": False}),
            "body does not mention the convention at all",
            True,
        ),
        # Flag true + body references the convention → pass.
        (
            "flag true + body references convention passes",
            _base_meta(**{"asks-user-questions": True}),
            f"See {convention} for the interview format.",
            True,
        ),
        # Flag true + body silent → FAIL (the rule's whole point).
        (
            "flag true + body silent fails",
            _base_meta(**{"asks-user-questions": True}),
            "body never mentions the convention",
            False,
        ),
        # Flag true + body references only a near-miss path → FAIL (substring
        # must be the real doc path, not a coincidental word).
        (
            "flag true + body has near-miss path fails",
            _base_meta(**{"asks-user-questions": True}),
            "see docs/agents/question-style.md instead",
            False,
        ),
        # Flag is a non-boolean scalar → FAIL (must be true/false).
        (
            "flag as non-boolean string fails",
            _base_meta(**{"asks-user-questions": "yes"}),
            f"see {convention}",
            False,
        ),
        # Flag is a number → FAIL.
        (
            "flag as number fails",
            _base_meta(**{"asks-user-questions": 1}),
            f"see {convention}",
            False,
        ),
        # Closed schema still rejects truly unknown fields (regression guard).
        (
            "unknown field still rejected (schema stays closed)",
            _base_meta(bogus="x"),
            "",
            False,
        ),
    ]
    for label, meta, body, expected_pass in cases:
        errors = skills.validate_meta(meta, meta["name"], body)
        passed = not errors
        if passed != expected_pass:
            print(f"  FAIL {label}")
            print(f"       got errors = {errors}")
            print(f"       expected_pass = {expected_pass}")
            failed += 1
            continue
        # When it fails, the interview flag must be the cited reason iff the
        # case is about the flag (not the closed-schema regression guard).
        if not expected_pass and "unknown field" not in label:
            if not _has_interview_error(errors):
                print(f"  FAIL {label}: rejection did not cite asks-user-questions")
                print(f"       errors = {errors}")
                failed += 1

    # --- Parser coercion end-to-end (public surface: parse_frontmatter) -----
    # A bare ``true``/``false`` parses to a Python bool and satisfies the rule
    # when the body references the convention; a quoted ``"true"`` stays a
    # string and is then rejected as non-boolean (YAML quote semantics).
    print("parser coercion (bare vs quoted):")
    parse_cases = [
        # bare true → bool True → passes when body cites the convention
        ("asks-user-questions: true", f"see {convention}", True, True),
        # bare false → bool False → does not bind, passes regardless of body
        ("asks-user-questions: false", "no convention mention", True, False),
        # quoted "true" → str → validator rejects as non-boolean
        ('asks-user-questions: "true"', f"see {convention}", False, "true"),
        # absent flag → not in meta → does not bind
        ("# (no flag)", "no convention mention", True, None),
    ]
    for flag_line, body, expected_pass, expected_value in parse_cases:
        text = _full_skill(flag_line, body)
        meta, err = skills.parse_frontmatter(text)
        if err is not None:
            print(f"  FAIL parse ({flag_line!r}): parse error {err}")
            failed += 1
            continue
        val = meta.get("asks-user-questions")
        # bool is a subclass of int; guard the type explicitly.
        if expected_value is True:
            val_ok = val is True
        elif expected_value is False:
            val_ok = val is False
        elif expected_value is None:
            val_ok = val is None
        else:
            val_ok = val == expected_value and not isinstance(val, bool)
        if not val_ok:
            print(f"  FAIL parse ({flag_line!r}): value {val!r} (expected {expected_value!r})")
            failed += 1
        errors = skills.validate_meta(meta, meta["name"], body)
        if (not errors) != expected_pass:
            print(f"  FAIL validate ({flag_line!r}): errors {errors} (expected_pass={expected_pass})")
            failed += 1

    total = len(cases) + len(parse_cases)
    if failed:
        print(f"\n{failed} skills test(s) failed (of {total} cases).", file=sys.stderr)
        return 1
    print(f"\nAll {total} skills cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
