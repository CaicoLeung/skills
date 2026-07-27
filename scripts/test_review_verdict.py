#!/usr/bin/env python3
"""Unit tests for the review-verdict CI check (T3 / ADR-0007 enforcement).

Zero-dependency: runnable directly as ``python3 scripts/test_review_verdict.py``.
Exits non-zero on any failure. Covers the **pure** selection logic plus
``main()``'s exit-code contract (via an injected fake reader — no ``gh`` or
network). ``main()``'s live GitHub I/O is also exercised end-to-end by the
demo.

The tested contract (ADR-0007 enforcement):

* Only the reviewer identity's findings count.
* Only a review whose reviewed-SHA equals the PR head is *current*.
* The latest current review wins; any stale (sha-mismatch) review is ignored.
* No current review → ``None`` → the check fails as "no current review".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_verdict as rv  # noqa: E402


def _comment(body: str, login: str = "reviewer-bot", cid: int = 1, at: str = "2024-01-01T00:00:00Z"):
    """Build a REST-shaped PR issue comment dict."""
    return {"id": cid, "user": {"login": login}, "body": body, "created_at": at}


def _findings(sha: str, body: str = "[f.py]: OK", login: str = "reviewer-bot", cid: int = 1, at: str = "2024-01-01T00:00:00Z"):
    """Build a reviewer findings comment with the marker."""
    return _comment(
        f"<!-- review-verdict-findings sha={sha} -->\n{body}", login, cid, at
    )


def _run(label: str, fn) -> int:
    """Run a check fn returning (ok, detail); print result; return failure count."""
    ok, detail = fn()
    if ok:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        print(f"       {detail}")
    return 0 if ok else 1


def main() -> int:
    failed = 0
    HEAD = "deadbeefcafebabe" * 2  # 32 hex, full-ish SHA
    HEAD_SHORT = "deadbeef"  # short SHA must also match a full head
    OTHER = "1111111122222222" * 2

    # --- extract_reviewed_sha ----------------------------------------------
    print("extract_reviewed_sha:")

    def t_marker():
        got = rv.extract_reviewed_sha(
            f"<!-- review-verdict-findings sha={HEAD} -->\n[f.py]: OK"
        )
        return (got == HEAD, f"got {got!r}, want {HEAD!r}")

    def t_short():
        got = rv.extract_reviewed_sha(
            f"<!-- review-verdict-findings sha={HEAD_SHORT} -->"
        )
        return (got == HEAD_SHORT, f"got {got!r}")

    def t_none():
        return (rv.extract_reviewed_sha("not a findings comment") is None, "prose parsed")

    def t_empty():
        return (rv.extract_reviewed_sha("") is None, "empty parsed")

    def t_case_insensitive():
        # Marker SHA is lowercased; a mixed-case sha still matches head_sha.
        got = rv.extract_reviewed_sha(
            "<!-- review-verdict-findings sha=DEADBEEF -->"
        )
        return (got == "deadbeef", f"got {got!r}")

    failed += _run("marker present", t_marker)
    failed += _run("short sha accepted", t_short)
    failed += _run("non-findings prose -> None", t_none)
    failed += _run("empty -> None", t_empty)
    failed += _run("marker sha lowercased", t_case_insensitive)

    # --- select_current_findings: identity + sha matching -------------------
    print("select_current_findings (identity + sha):")

    def t_selects_current():
        comments = [
            _findings(OTHER, "[f.py:1]: HIGH: stale", cid=10, at="2024-01-01T00:00:00Z"),
            _findings(HEAD, "[f.py]: OK", cid=11, at="2024-01-02T00:00:00Z"),
        ]
        sel = rv.select_current_findings(comments, HEAD, "reviewer-bot")
        return (
            sel is not None and sel.sha == HEAD and sel.comment_id == 11,
            f"got {sel}",
        )

    def t_ignores_other_login():
        # A findings comment from the implementer's own login does not count.
        comments = [_findings(HEAD, "[f.py]: OK", login="implementer-bot")]
        sel = rv.select_current_findings(comments, HEAD, "reviewer-bot")
        return (sel is None, f"got {sel}")

    def t_stale_only_returns_none():
        # Every review is for a different SHA -> no current review.
        comments = [_findings(OTHER, "[f.py]: OK")]
        sel = rv.select_current_findings(comments, HEAD, "reviewer-bot")
        return (sel is None, f"got {sel}")

    def t_no_findings_returns_none():
        # PR with no findings comments at all.
        comments = [_comment("looks good!", login="reviewer-bot")]
        sel = rv.select_current_findings(comments, HEAD, "reviewer-bot")
        return (sel is None, f"got {sel}")

    def t_latest_of_multiple():
        # Two current reviews -> latest (by created_at) wins.
        comments = [
            _findings(HEAD, "[f.py:1]: HIGH: earlier", cid=1, at="2024-01-01T00:00:00Z"),
            _findings(HEAD, "[f.py]: OK", cid=2, at="2024-01-03T00:00:00Z"),
        ]
        sel = rv.select_current_findings(comments, HEAD, "reviewer-bot")
        return (sel is not None and sel.comment_id == 2, f"got {sel}")

    def t_short_sha_matches_head():
        # git treats a >=7-hex prefix as the same commit: a reviewer posting
        # GitHub's short SHA is still current against a full head.
        short = HEAD_SHORT  # 8 hex
        head = short + "a" * (40 - len(short))  # full head that short prefixes
        comments = [_findings(short, "[scripts/f.py]: OK")]
        sel = rv.select_current_findings(comments, head, "reviewer-bot")
        return (sel is not None, f"short-sha review should match full head; got {sel}")

    def t_marker_stripped_from_body():
        comments = [_findings(HEAD, "[f.py]: OK")]
        sel = rv.select_current_findings(comments, HEAD, "reviewer-bot")
        return (
            sel is not None and "review-verdict-findings" not in sel.body,
            f"body still has marker: {sel.body if sel else None!r}",
        )

    failed += _run("selects sha-matched review", t_selects_current)
    failed += _run("ignores non-reviewer login", t_ignores_other_login)
    failed += _run("all-stale -> None (no current review)", t_stale_only_returns_none)
    failed += _run("no findings -> None", t_no_findings_returns_none)
    failed += _run("latest current review wins", t_latest_of_multiple)
    failed += _run("short sha prefix-matches full head", t_short_sha_matches_head)
    failed += _run("marker stripped from findings body", t_marker_stripped_from_body)

    # --- end-to-end: selection feeds derive_verdict ------------------------
    # Proves the gate's two failure modes surface via the same selection seam:
    # blocking finding -> fail; coverage gap -> fail; clean -> pass. This wires
    # the pure selection to the pure verdict without any network.
    print("selection -> derive_verdict (gate behavior):")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from verdict import derive_verdict  # noqa: E402

    CHANGED = ["scripts/f.py"]

    def t_blocking_fails():
        comments = [
            _findings(HEAD, "[scripts/f.py:9]: HIGH: null deref", login="reviewer-bot")
        ]
        sel = rv.select_current_findings(comments, HEAD, "reviewer-bot")
        assert sel is not None
        res = derive_verdict(sel.body, CHANGED)
        return (not res.passed and len(res.blocking_issues) == 1, f"passed={res.passed}")

    def t_coverage_gap_fails():
        # Review acks a different file -> changed file lacks coverage.
        # (OK form is plain `file: OK`, per ADR-0007.)
        comments = [
            _findings(HEAD, "scripts/other.py: OK", login="reviewer-bot")
        ]
        sel = rv.select_current_findings(comments, HEAD, "reviewer-bot")
        assert sel is not None
        res = derive_verdict(sel.body, CHANGED)
        return (
            not res.passed and "scripts/f.py" in res.coverage_gaps,
            f"passed={res.passed} gaps={res.coverage_gaps}",
        )

    def t_clean_passes():
        comments = [_findings(HEAD, "scripts/f.py: OK", login="reviewer-bot")]
        sel = rv.select_current_findings(comments, HEAD, "reviewer-bot")
        assert sel is not None
        res = derive_verdict(sel.body, CHANGED)
        return (res.passed, f"passed={res.passed}")

    def t_nonblocking_warning_passes():
        comments = [
            _findings(HEAD, "[scripts/f.py:3]: MEDIUM: nit", login="reviewer-bot")
        ]
        sel = rv.select_current_findings(comments, HEAD, "reviewer-bot")
        assert sel is not None
        res = derive_verdict(sel.body, CHANGED)
        return (res.passed and len(res.findings) == 1, f"passed={res.passed}")

    failed += _run("blocking finding -> fail", t_blocking_fails)
    failed += _run("coverage gap -> fail", t_coverage_gap_fails)
    failed += _run("clean -> pass", t_clean_passes)
    failed += _run("non-blocking warning -> pass", t_nonblocking_warning_passes)

    # --- main(): exit-code contract (CI gate behavior) ---------------------
    # main() is the consumer-side CI entry point (ADR-0013 §4). Its contract
    # is its exit code: 2 = bad input / gh read fail, 1 = no current review or
    # verdict fail, 0 = pass. The injected reader (twin of every other driver)
    # makes the branches unit-testable without gh/network — so main() is now
    # tested, not just the pure selection core.
    print("main() exit-code contract:")
    from _test_fakes import FakeGitHubReader  # noqa: E402

    REPO = "owner/repo"
    PR = 1

    def _argv(sha: str = HEAD) -> list[str]:
        return ["--repo", REPO, "--pr", str(PR), "--sha", sha,
                "--reviewer-login", "reviewer-bot"]

    class _RaisingReader:
        def issue_comments(self, repo, pr):
            raise RuntimeError("gh boom")
        def pr_changed_files(self, repo, pr):
            return []

    def t_missing_args_exit_2():
        code = rv.main(argv=[], reader=FakeGitHubReader())
        return (code == 2, f"got {code}")

    def t_gh_read_fail_exit_2():
        code = rv.main(argv=_argv(), reader=_RaisingReader())
        return (code == 2, f"got {code}")

    def t_no_current_review_exit_1():
        fake = FakeGitHubReader()
        fake.comments[PR] = [_findings(OTHER, "[scripts/f.py]: OK")]  # stale sha
        fake.changed_files[PR] = ["scripts/f.py"]
        code = rv.main(argv=_argv(), reader=fake)
        return (code == 1, f"got {code}")

    def t_blocking_finding_exit_1():
        fake = FakeGitHubReader()
        fake.comments[PR] = [
            _findings(HEAD, "[scripts/f.py:9]: HIGH: null deref", login="reviewer-bot")
        ]
        fake.changed_files[PR] = ["scripts/f.py"]
        code = rv.main(argv=_argv(), reader=fake)
        return (code == 1, f"got {code}")

    def t_clean_review_exit_0():
        fake = FakeGitHubReader()
        fake.comments[PR] = [_findings(HEAD, "scripts/f.py: OK", login="reviewer-bot")]
        fake.changed_files[PR] = ["scripts/f.py"]
        code = rv.main(argv=_argv(), reader=fake)
        return (code == 0, f"got {code}")

    failed += _run("missing args -> exit 2", t_missing_args_exit_2)
    failed += _run("gh read fail -> exit 2", t_gh_read_fail_exit_2)
    failed += _run("no current review -> exit 1", t_no_current_review_exit_1)
    failed += _run("blocking finding -> exit 1", t_blocking_finding_exit_1)
    failed += _run("clean review -> exit 0", t_clean_review_exit_0)

    # --- summary -----------------------------------------------------------
    total = 19  # 5 + 7 + 4 + ... keep in sync with _run calls above
    # (Recount robustly below.)
    total = 5 + 7 + 4 + 5
    if failed:
        print(
            f"\n{failed} review-verdict test(s) failed (of {total}).",
            file=sys.stderr,
        )
        return 1
    print(f"\nAll {total} review-verdict cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
