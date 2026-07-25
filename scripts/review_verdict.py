#!/usr/bin/env python3
"""CI check for the derived verdict (T3 / ADR-0007 enforcement).

The ``review-verdict`` job runs this on every PR. It finds the reviewer
identity's **latest** findings comment whose reviewed-SHA equals the PR head,
hands the comment body + the PR's changed files to ``derive_verdict``
(``scripts/verdict.py``), and exits with the verdict's exit code. The job's own
pass/fail *is* the ``review-verdict`` status check — nothing self-declares a
verdict and nothing appends a token.

Stale review handling: a review whose reviewed-SHA does not match the PR head
is treated as **no current review**, and the check fails. This forces a fresh
review round on every push and makes a stale review unable to merge (ADR-0007).

Identity: findings are filtered to the reviewer's login (``REVIEWER_LOGIN``),
the GitHub App's bot login in production. The App is an operational
prerequisite (out of scope per the parent epic); the mechanism — filter by
login + sha — is what this ticket delivers. While the App is absent, the login
is the maintainer, and the demo posts findings manually under it.

This module follows the repo's "behavior validated by a zero-dep script"
pattern: the selection logic is a set of **pure** functions (no ``gh``, no
network), unit-tested in ``scripts/test_review_verdict.py``. ``main()`` holds
the GitHub I/O.

Findings comment format (see docs/agents/review-verdict.md)::

    <!-- review-verdict-findings sha=<7..40 hex> -->
    ## Code review findings (ADR-0007) — reviewed SHA `<sha>`

    [scripts/foo.py:12]: HIGH: null deref on None input
    [scripts/bar.py]: OK

The marker line is the machine anchor; everything else is the findings body fed
to ``derive_verdict`` (which ignores non-matching prose lines).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

# The machine anchor inside a reviewer's findings comment. The SHA is what the
# reviewer actually reviewed; the CI compares it to the PR head. 7..40 hex
# accepts both short and full SHAs so a reviewer may post either.
FINDINGS_MARKER_RE = re.compile(
    r"<!--\s*review-verdict-findings\s+sha=([0-9a-f]{7,40})\s*-->",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class SelectedFindings:
    """The reviewer's current findings for a PR head.

    ``body`` is the comment body with the marker stripped, ready for
    ``derive_verdict``; ``sha`` is the reviewed SHA (guaranteed == head_sha);
    ``comment_id`` is the REST id, surfaced in the check log for traceability.
    """

    body: str
    sha: str
    comment_id: int


def extract_reviewed_sha(body: str) -> Optional[str]:
    """Return the reviewed SHA from a comment's marker, or ``None``.

    A reviewer posts exactly one ``<!-- review-verdict-findings sha=... -->``
    marker per comment. ``None`` means the comment is not a findings comment
    (or carries no sha) and is skipped.
    """
    if not body:
        return None
    match = FINDINGS_MARKER_RE.search(body)
    return match.group(1).lower() if match else None


def _strip_marker(body: str) -> str:
    """Remove the findings marker line so ``derive_verdict`` never sees it.

    The marker cannot parse as a finding (no uppercase severity token), so
    ``derive_verdict`` would ignore it anyway — stripping is belt-and-braces.
    """
    return FINDINGS_MARKER_RE.sub("", body, count=1).strip("\n")


def _same_commit(sha_a: str, sha_b: str) -> bool:
    """True if two lowercase hex SHAs identify the same git commit.

    A reviewer may post the full 40-char SHA or the short form GitHub shows
    (≥7 hex). git treats a ≥7-hex prefix as uniquely identifying a commit, so
    a prefix match means the same commit — a review is *current* when its SHA
    equals or is a prefix of the PR head (either direction, for symmetry).
    """
    if not sha_a or not sha_b:
        return False
    return sha_a == sha_b or sha_a.startswith(sha_b) or sha_b.startswith(sha_a)


def select_current_findings(
    comments: Iterable[dict[str, Any]],
    head_sha: str,
    reviewer_login: str,
) -> Optional[SelectedFindings]:
    """Pick the reviewer's latest sha-matched findings comment, or ``None``.

    Args:
        comments: PR issue-comment dicts from the GitHub REST API, each shaped
            like ``{"id": int, "user": {"login": str}, "body": str,
            "created_at": str}``. Ordering does not matter; entries are sorted
            by ``created_at``.
        head_sha: the PR head SHA the check must be current against.
        reviewer_login: the reviewer identity whose findings count. In
            production this is the GitHub App's bot login.

    Returns:
        The latest :class:`SelectedFindings` whose author is ``reviewer_login``
        and whose reviewed SHA identifies the same commit as ``head_sha``
        (case-insensitive; a reviewer may post the full or short SHA — a
        ≥7-hex prefix identifies the same commit, per git), or ``None`` when
        none match — i.e. **no current review** (stale or missing). The caller
        treats ``None`` as a hard fail.
    """
    head = head_sha.lower()
    matches: list[SelectedFindings] = []
    # Track created_at alongside each match so ordering is stable regardless of
    # API page order.
    timestamps: list[str] = []
    for c in comments:
        user = (c.get("user") or {})
        if (user.get("login") or "") != reviewer_login:
            continue
        body = c.get("body") or ""
        sha = extract_reviewed_sha(body)
        if sha is None or not _same_commit(sha, head):
            continue
        matches.append(
            SelectedFindings(
                body=_strip_marker(body),
                sha=sha,
                comment_id=int(c.get("id", 0)),
            )
        )
        timestamps.append(c.get("created_at") or "")
    if not matches:
        return None
    # Latest first by created_at (ISO-8601 sorts lexically).
    ordered = [m for _, m in sorted(zip(timestamps, matches), key=lambda p: p[0])]
    return ordered[-1]


# --- GitHub I/O (main only) --------------------------------------------------
# main() reads through the shared gateway (scripts/github.py) — the same
# transport the loop driver uses — so the ``gh`` command shape lives in one
# place. The pure selection core above never touches the network.


def main(argv: Optional[list[str]] = None) -> int:
    """CI entry point: fetch findings, derive verdict, exit with its code."""
    import argparse
    import json

    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    from github import GhCliReader  # noqa: E402  (shared gh gateway)
    from verdict import derive_verdict  # noqa: E402  (local zero-dep import)

    p = argparse.ArgumentParser(
        description="review-verdict CI check (ADR-0007 enforcement)"
    )
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    p.add_argument("--pr", type=int, default=int(os.environ.get("PR_NUMBER", "0") or 0))
    p.add_argument(
        "--sha",
        default=os.environ.get("PR_HEAD_SHA", ""),
        help="PR head SHA the review must be current against",
    )
    p.add_argument(
        "--reviewer-login",
        default=os.environ.get("REVIEWER_LOGIN", ""),
        help="Reviewer identity (GitHub App bot login in production)",
    )
    args = p.parse_args(argv)

    missing = [
        name
        for name, val in (
            ("--repo / GITHUB_REPOSITORY", args.repo),
            ("--pr / PR_NUMBER", str(args.pr)),
            ("--sha / PR_HEAD_SHA", args.sha),
            ("--reviewer-login / REVIEWER_LOGIN", args.reviewer_login),
        )
        if not val
    ]
    if missing:
        print(f"::error::review-verdict missing required input: {', '.join(missing)}")
        return 2

    reader = GhCliReader()
    try:
        comments = reader.issue_comments(args.repo, args.pr)
        selected = select_current_findings(comments, args.sha, args.reviewer_login)
        if selected is None:
            print(
                f"::error::No current review: no findings comment from "
                f"'{args.reviewer_login}' for SHA {args.sha} (stale or missing). "
                f"A fresh review is required before merge."
            )
            return 1

        changed = reader.pr_changed_files(args.repo, args.pr)

        result = derive_verdict(selected.body, changed)
    except RuntimeError as exc:
        # Single CLI catch (twin of the loop driver's): every gh failure surfaces
        # as one RuntimeError shape; report it as a CI error and exit non-zero.
        print(f"::error::review-verdict GitHub read failed: {exc}")
        return 2

    print(
        f"review-verdict: reviewed-SHA={selected.sha} "
        f"comment={selected.comment_id} changed-files={len(changed)} "
        f"findings={len(result.findings)} blocking={len(result.blocking_issues)} "
        f"gaps={len(result.coverage_gaps)}"
    )
    print(json.dumps(result.to_dict(), indent=2))

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
