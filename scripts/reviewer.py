#!/usr/bin/env python3
"""Independent code-reviewer core: fixed prompt + findings producer (T4 / ADR-0007).

The reviewer is the *findings producer*, structurally separated from the
implementer on five axes (ADR-0007 §2):

    axis       | guarantee
    -----------|-------------------------------------------------------------
    invoker    | the loop driver invokes it, never the implementer
    prompt     | a FIXED, system-authored template the implementer never edits
    model      | the secondary model on a DIFFERENT provider than the implementer
    workspace  | a SEPARATE isolated worktree
    input      | diff + ticket spec ONLY — never the author's prose

This module is the runtime-neutral reviewer core (ADR-0004: the rule lives in
the core; the loop + adapter supply the mechanism). It is **pure** — no agent,
network, or GitHub calls:

  * :func:`build_review_prompt` renders the fixed template from diff + spec
    only. There is **no parameter for author prose**, so it can never reach the
    reviewer.
  * :func:`strip_verdict_line` removes any self-declared verdict line — defense
    in depth (the prompt already forbids it).
  * :func:`extract_findings` parses reviewer output via :mod:`verdict` (single
    source of truth for the findings format), checks the coverage floor, and
    reports whether a verdict line was present.
  * :func:`format_findings_comment` renders the sha-tagged comment body the
    reviewer's GitHub-App identity posts.

The loop driver (``scripts/loop.py``, T5b) calls this module's CLI to build the
prompt, runs the secondary model on it in a separate worktree, then formats and
posts the findings. The ``review-verdict`` CI check (T3) reads the posted
comment and runs :mod:`verdict`.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# verdict.py is a sibling (same scripts/ dir). Importing it keeps the findings
# format defined in exactly one place (T1) — reviewer never re-parses it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verdict  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = REPO_ROOT / "skills" / "ticket-workflow-core" / "review-prompt.md"

# The two /code-review axes (ADR-0007). Findings are produced for both; the
# verdict aggregates them — a CRITICAL/HIGH in either axis fails.
REVIEW_AXES = ("Standards", "Spec")

# Template slots, filled by build_review_prompt via single-pass substitution.
SLOT_SHA = "{{SHA}}"
SLOT_SPEC = "{{TICKET_SPEC}}"
SLOT_DIFF = "{{DIFF}}"
SLOT_CHANGED_FILES = "{{CHANGED_FILES}}"

# Slots a reviewer prompt MUST NOT carry — the implementer's prose never
# reaches the reviewer (ADR-0007 §2, input axis). The tests assert their
# absence in the committed template.
FORBIDDEN_SLOTS = ("{{COMMIT_MESSAGE}}", "{{PR_DESCRIPTION}}", "{{AUTHOR_PROSE}}")

# A self-declared verdict line, in any common spelling. The prompt forbids it;
# this regex is defense in depth so it can never reach verdict.py. Matches only
# lines that *start* with VERDICT (after optional whitespace/markdown-bold), so
# a finding summary that merely mentions "the verdict script" is preserved.
VERDICT_LINE_RE = re.compile(r"^\s*\**\s*VERDICT\b[\s:*-]*(pass|fail)\b", re.IGNORECASE)

# The machine-readable SHA marker prefixing every findings comment the reviewer
# App posts. The review-verdict CI (T3) greps this to select the latest findings
# whose reviewed-sha == PR head.
COMMENT_SHA_RE = re.compile(r"<!-- review-verdict sha=([0-9a-f]+) -->")


@dataclass(frozen=True)
class ExtractedFindings:
    """Parsed reviewer output, ready to validate and post."""

    cleaned_text: str
    findings: tuple[verdict.Finding, ...]
    coverage_gaps: tuple[str, ...]
    blocking_issues: tuple[verdict.Finding, ...]
    had_verdict_line: bool

    @property
    def well_formed(self) -> bool:
        """True iff the output carries no verdict line and covers every file.

        ``coverage_gaps`` is a *reviewer* quality signal (a file it went silent
        on); the gate-time coverage check in :func:`verdict.derive_verdict`
        makes the final ruling. ``had_verdict_line`` is always a contract
        violation worth a re-prompt.
        """
        return not self.had_verdict_line and not self.coverage_gaps

    def to_dict(self) -> dict:
        """JSON-serializable validation summary (no cleaned_text — that is posted)."""
        return {
            "well_formed": self.well_formed,
            "had_verdict_line": self.had_verdict_line,
            "findings_count": len(self.findings),
            "blocking_count": len(self.blocking_issues),
            "coverage_gaps": list(self.coverage_gaps),
            "findings": [f.to_dict() for f in self.findings],
        }


def build_review_prompt(
    diff: str,
    spec: str,
    sha: str,
    changed_files: list[str],
    template: str | None = None,
) -> str:
    """Render the FIXED review prompt from diff + spec ONLY.

    The implementer's commit messages and PR description are **not parameters**
    — by construction they can never reach the reviewer (ADR-0007 §2, input
    axis). Substitution is single-pass, so a slot token appearing inside the
    diff or spec is inserted literally and never re-interpreted (a diff cannot
    inject a fake spec, and vice versa).
    """
    text = (
        template
        if template is not None
        else DEFAULT_TEMPLATE.read_text(encoding="utf-8")
    )
    changed_block = (
        "\n".join(f"- {path}" for path in changed_files)
        or "- (no changed files)"
    )
    slots = {
        SLOT_SHA: sha,
        SLOT_SPEC: spec,
        SLOT_CHANGED_FILES: changed_block,
        SLOT_DIFF: diff,
    }
    # Single pass: replacement text is never re-scanned, so slot tokens inside
    # the diff/spec survive verbatim.
    pattern = re.compile("|".join(re.escape(k) for k in slots))
    return pattern.sub(lambda m: slots[m.group(0)], text)


def strip_verdict_line(raw: str) -> tuple[str, bool]:
    """Remove any self-declared verdict line.

    Returns ``(cleaned_text, had_verdict_line)``. Lines are matched
    individually and only at line start, so prose that merely *mentions* a
    verdict (e.g. a finding summary, or the template's own instructions) is
    preserved.
    """
    had = False
    kept: list[str] = []
    for line in raw.splitlines():
        if VERDICT_LINE_RE.match(line):
            had = True
            continue
        kept.append(line)
    return "\n".join(kept).strip(), had


def extract_findings(
    raw_output: str, changed_files: list[str]
) -> ExtractedFindings:
    """Parse reviewer output: strip any verdict, parse findings, check coverage.

    Finding/OK parsing delegates to :func:`verdict.derive_verdict`, so the
    findings format has exactly one source of truth (T1). The coverage floor
    (every changed file has a finding or OK) is surfaced so the loop can
    re-prompt a reviewer that went silent on a file.
    """
    cleaned, had_verdict = strip_verdict_line(raw_output)
    result = verdict.derive_verdict(cleaned, list(changed_files))
    return ExtractedFindings(
        cleaned_text=cleaned,
        findings=tuple(result.findings),
        coverage_gaps=result.coverage_gaps,
        blocking_issues=result.blocking_issues,
        had_verdict_line=had_verdict,
    )


def format_findings_comment(cleaned_text: str, sha: str) -> str:
    """Render the sha-tagged comment body the reviewer App identity posts.

    The leading marker is grepped by the ``review-verdict`` CI (T3) to select
    the latest findings whose reviewed-sha == PR head; a stale review (sha ≠ PR
    head) reads as "no current review." ``cleaned_text`` is the reviewer's
    output verbatim, minus any stripped verdict line — the reviewer's voice is
    preserved, only the forged verdict is excised.
    """
    return f"<!-- review-verdict sha={sha} -->\n\n{cleaned_text.strip()}\n"


def comment_sha(comment_body: str) -> str | None:
    """Return the reviewed-sha embedded in a findings comment, or ``None``.

    Used by the review-verdict CI (T3) and by tests asserting a comment is
    current for a given PR head.
    """
    match = COMMENT_SHA_RE.search(comment_body)
    return match.group(1) if match else None


# --- CLI (the loop driver calls this) ----------------------------------------


def _read_arg(value: str) -> str:
    """Read a CLI arg that is either ``-`` (stdin) or a file path."""
    if value == "-":
        return sys.stdin.read()
    return Path(value).read_text(encoding="utf-8")


def _read_lines(value: str) -> list[str]:
    return [line.strip() for line in _read_arg(value).splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Subcommands the loop driver (T5b) uses:

        build-prompt    render the fixed prompt (diff + spec only) to stdout;
                        the loop feeds it to ``paseo run --provider <secondary>``
                        in a separate worktree
        format-findings strip any verdict, check coverage, and render the
                        sha-tagged comment to stdout (postable via
                        ``gh pr comment`` from the App identity); a JSON
                        validation summary goes to stderr

    Both subcommands are pure I/O over the functions above — no policy. The
    loop decides when to re-prompt or post.
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=(
            "Independent reviewer core (ADR-0007): fixed prompt + findings "
            "producer. Pure — no agent, network, or GitHub calls."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser(
        "build-prompt",
        help="Render the fixed review prompt from diff + ticket spec only.",
    )
    build.add_argument("--diff", required=True, help="diff file (or '-' for stdin)")
    build.add_argument("--spec", required=True, help="ticket-spec file (or '-')")
    build.add_argument("--sha", required=True, help="commit SHA being reviewed")
    build.add_argument(
        "--changed-files",
        required=True,
        help="changed-files list, one per line (or '-')",
    )
    build.add_argument("--template", help="override the fixed template path")

    fmt = sub.add_parser(
        "format-findings",
        help="Strip any verdict, check coverage, render the sha-tagged findings comment.",
    )
    fmt.add_argument("--findings", required=True, help="reviewer raw output (or '-')")
    fmt.add_argument("--sha", required=True, help="commit SHA that was reviewed")
    fmt.add_argument(
        "--changed-files",
        required=True,
        help="changed-files list for the coverage floor (or '-')",
    )

    args = parser.parse_args(argv)

    if args.cmd == "build-prompt":
        template = None
        if args.template:
            template = Path(args.template).read_text(encoding="utf-8")
        prompt = build_review_prompt(
            diff=_read_arg(args.diff),
            spec=_read_arg(args.spec),
            sha=args.sha,
            changed_files=_read_lines(args.changed_files),
            template=template,
        )
        sys.stdout.write(prompt)
        return 0

    if args.cmd == "format-findings":
        extracted = extract_findings(
            raw_output=_read_arg(args.findings),
            changed_files=_read_lines(args.changed_files),
        )
        comment = format_findings_comment(extracted.cleaned_text, args.sha)
        # Comment body to stdout (postable directly); validation to stderr.
        sys.stdout.write(comment)
        sys.stderr.write(json.dumps(extracted.to_dict(), indent=2) + "\n")
        return 0

    return 2  # unreachable: argparse requires a subcommand


if __name__ == "__main__":
    sys.exit(main())
