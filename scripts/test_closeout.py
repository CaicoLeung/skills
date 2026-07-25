#!/usr/bin/env python3
"""Unit tests for the close-out loop planner (T5b / ADR-0008).

Zero-dependency: runnable directly as ``python3 scripts/test_closeout.py``.
Exits non-zero on any failure. Covers the **pure** close-out decision logic
and the system-authored prompts — the only non-trivial behavior in the
close-out half. The I/O driver (``loop.run_closeout``) is exercised safely
through ``--dry-run``, not here (issue #23 testing decisions).

Each assertion maps to an acceptance criterion of issue #29:

* AC1 — findings handed to the fixer **verbatim**; "resolved" = disappears
  from the next review (the loop never trusts a self-declaration).
* AC2 — the 3-round cap escalates ``STUCK_REVIEW`` without silently passing.
* AC3 — the loop (not the implementer) enables auto-merge, only on PASS.
* AC4 — dual close: ``Fixes #N`` auto-close + loop resolution comment.
* AC5 — end-to-end demonstration is covered by the dry-run driver + the
  demo procedure in ``docs/agents/closeout.md``; the *logic* those exercise
  is asserted here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _test_fakes import FakeGitHubReader  # noqa: E402
from github import GitHubReader  # noqa: E402
import closeout  # noqa: E402
import loop  # noqa: E402


def _check(condition: bool, label: str, failed: list[str]) -> None:
    if not condition:
        print(f"  FAIL {label}")
        failed.append(label)


def _verdict(status: str, findings: str = "", blocking: int = 0, gaps: int = 0) -> closeout.VerdictState:
    return closeout.VerdictState(
        status=status,
        findings_text=findings,
        blocking_count=blocking,
        coverage_gap_count=gaps,
    )


def main() -> int:
    failed: list[str] = []

    FINDINGS = (
        "### Standards\n[scripts/x.py:9]: HIGH: null deref\n"
        "### Spec\n[scripts/x.py:12]: CRITICAL: missing case\n"
    )

    # =========================================================================
    # AC2 + AC3: plan_closeout — the decision matrix
    # =========================================================================
    print("plan_closeout decision matrix:")

    # PASS at any round → PASS (merge). Pass short-circuits even at the cap.
    for rnd in (0, 1, 2, 3):
        d = closeout.plan_closeout(_verdict(closeout.VERDICT_PASS), round=rnd)
        _check(
            d.action == closeout.ACTION_PASS,
            f"pass at round {rnd} -> PASS (got {d.action})",
            failed,
        )
        _check(
            "auto-merge" in d.reason,
            f"PASS reason must mention auto-merge (round {rnd})",
            failed,
        )

    # MISSING below the cap → REVIEW (no current review; invoke reviewer).
    d = closeout.plan_closeout(_verdict(closeout.VERDICT_MISSING), round=0)
    _check(d.action == closeout.ACTION_REVIEW, "missing at round 0 -> REVIEW", failed)
    d = closeout.plan_closeout(_verdict(closeout.VERDICT_MISSING), round=2)
    _check(d.action == closeout.ACTION_REVIEW, "missing at round 2 -> REVIEW", failed)

    # FAIL below the cap → FIX, carrying the verbatim findings.
    d = closeout.plan_closeout(
        _verdict(closeout.VERDICT_FAIL, FINDINGS, blocking=2), round=1
    )
    _check(d.action == closeout.ACTION_FIX, "fail at round 1 -> FIX", failed)
    _check(
        d.findings_text == FINDINGS,
        "FIX decision must carry the findings verbatim",
        failed,
    )

    # =========================================================================
    # AC2: the 3-round cap escalates STUCK_REVIEW, never silently passes
    # =========================================================================
    print("3-round cap escalates STUCK_REVIEW (no silent pass):")

    # FAIL at the cap -> STUCK (not FIX, not PASS).
    d = closeout.plan_closeout(
        _verdict(closeout.VERDICT_FAIL, FINDINGS, blocking=1), round=closeout.MAX_REVIEW_ROUNDS
    )
    _check(
        d.action == closeout.ACTION_STUCK,
        f"fail at round {closeout.MAX_REVIEW_ROUNDS} -> STUCK (got {d.action})",
        failed,
    )
    _check(
        "STUCK_REVIEW" in d.reason,
        "STUCK reason must name STUCK_REVIEW",
        failed,
    )
    _check(d.action != closeout.ACTION_PASS, "cap must never silently pass", failed)

    # Beyond the cap too.
    d = closeout.plan_closeout(_verdict(closeout.VERDICT_FAIL), round=closeout.MAX_REVIEW_ROUNDS + 1)
    _check(d.action == closeout.ACTION_STUCK, "fail beyond cap -> STUCK", failed)

    # MISSING at the cap -> STUCK too (a review that keeps going stale escalates,
    # not loops forever). The cap guards every non-pass path.
    d = closeout.plan_closeout(
        _verdict(closeout.VERDICT_MISSING), round=closeout.MAX_REVIEW_ROUNDS
    )
    _check(
        d.action == closeout.ACTION_STUCK,
        "missing at cap -> STUCK (cap guards every non-pass path)",
        failed,
    )

    # The cap is exactly 3 (parent #23 story 26).
    _check(closeout.MAX_REVIEW_ROUNDS == 3, "MAX_REVIEW_ROUNDS must be 3", failed)

    # =========================================================================
    # AC1: fix_prompt hands the findings VERBATIM; no "resolve all" prose
    # =========================================================================
    print("fix_prompt verbatim handoff (no 'resolve all' prose):")
    pr_url = "https://github.com/CaicoLeung/skills/pull/42"
    fp = closeout.fix_prompt(FINDINGS, 42, pr_url)

    # The findings appear verbatim — byte-for-byte — in the fixer's prompt.
    _check(FINDINGS in fp, "fix_prompt must embed findings verbatim", failed)
    _check(
        "[scripts/x.py:9]: HIGH: null deref" in fp,
        "specific finding line survives into fix_prompt",
        failed,
    )

    # Forbidden handoff prose: a summary like "resolve all issues" is exactly
    # where a fixer could quietly drop a finding (parent #23 story 23).
    for forbidden in (
        "resolve all issues",
        "fix all issues",
        "fix everything",
        "address all the problems",
    ):
        _check(
            forbidden.lower() not in fp.lower(),
            f"fix_prompt must not carry paraphrase prose {forbidden!r}",
            failed,
        )

    # "resolved" is defined by the NEXT review, not by the fixer — the prompt
    # says so, and forbids self-declaration (parent #23 story 25).
    _check(
        "NEXT independent review" in fp and "do not self-declare" in fp,
        "fix_prompt must define 'resolved' as disappearing from the next review",
        failed,
    )

    # The fixer is told NOT to merge (merge authority is the loop's).
    _check(
        "do not merge" in fp.lower(),
        "fix_prompt must tell the fixer not to merge",
        failed,
    )

    # =========================================================================
    # AC1 (cont.): "resolved = disappears" is enforced structurally — the loop
    # re-derives the verdict from the NEXT review, so the same finding recurring
    # keeps the verdict failing. Model two rounds: round 1 fails on finding F;
    # round 2 still fails because F reappeared -> FIX again, then cap -> STUCK.
    # (No self-declaration is ever consulted.)
    # =========================================================================
    print("'resolved = disappears' (verdict re-derived, never self-declared):")
    r1 = closeout.plan_closeout(_verdict(closeout.VERDICT_FAIL, FINDINGS, blocking=1), round=1)
    _check(r1.action == closeout.ACTION_FIX, "round 1 fail -> FIX", failed)
    # Pretend the fixer pushed but F reappeared: the NEXT verdict is still fail.
    r2 = closeout.plan_closeout(_verdict(closeout.VERDICT_FAIL, FINDINGS, blocking=1), round=2)
    _check(r2.action == closeout.ACTION_FIX, "round 2 (finding recurred) -> FIX again", failed)
    r3 = closeout.plan_closeout(_verdict(closeout.VERDICT_FAIL, FINDINGS, blocking=1), round=3)
    _check(r3.action == closeout.ACTION_STUCK, "round 3 (still recurred) -> STUCK", failed)
    # But if the finding truly disappeared, round 2's verdict is pass -> PASS.
    r2_clean = closeout.plan_closeout(_verdict(closeout.VERDICT_PASS), round=2)
    _check(
        r2_clean.action == closeout.ACTION_PASS,
        "a finding that disappeared -> next verdict pass -> PASS",
        failed,
    )

    # =========================================================================
    # AC3: auto-merge is loop-only, only on PASS, --auto (queues behind the gate)
    # =========================================================================
    print("auto_merge_command (loop-only, PASS-only, --auto):")
    cmd = closeout.auto_merge_command("CaicoLeung/skills", 42)
    _check(cmd[:3] == ["gh", "pr", "merge"], "auto-merge is a gh pr merge command", failed)
    _check("42" in cmd, "auto-merge targets the PR number", failed)
    _check("--auto" in cmd, "auto-merge must use --auto (queues behind branch protection)", failed)
    _check("--squash" in cmd and "--delete-branch" in cmd, "squash + delete-branch adapter default", failed)
    _check("--repo" in cmd and "CaicoLeung/skills" in cmd, "auto-merge targets the repo", failed)
    # A direct merge (no --auto) would bypass the gate; the loop never emits one.
    _check(
        not any(c.startswith("--merge") or c == "--merge" for c in cmd),
        "loop must not emit a direct (non-auto) merge",
        failed,
    )

    # closeout_commands emits auto-merge ONLY on PASS; FIX/REVIEW emit paseo run,
    # STUCK emits a comment — never a merge.
    pass_cmds = closeout.closeout_commands(
        closeout.plan_closeout(_verdict(closeout.VERDICT_PASS), round=1),
        "CaicoLeung/skills", 29, 42, "https://x/pull/42", "main",
        reviewer_workspace="issue-42-review", implementer_workspace="issue-42-implement",
    )
    _check(
        any(c[:3] == ["gh", "pr", "merge"] and "--auto" in c for c in pass_cmds),
        "PASS -> closeout_commands must emit an auto-merge",
        failed,
    )

    fix_cmds = closeout.closeout_commands(
        closeout.plan_closeout(_verdict(closeout.VERDICT_FAIL, FINDINGS), round=1),
        "CaicoLeung/skills", 29, 42, "https://x/pull/42", "main",
        reviewer_workspace="issue-42-review", implementer_workspace="issue-42-implement",
    )
    _check(
        not any(c[:3] == ["gh", "pr", "merge"] for c in fix_cmds),
        "FIX must not emit any merge command (implementer never merges)",
        failed,
    )
    _check(
        any(c[0] == "paseo" and "--worktree" in c for c in fix_cmds),
        "FIX must emit a paseo run in the implementer's worktree",
        failed,
    )
    # And the FIX command's prompt carries the findings verbatim.
    fix_prompt_argv = [c for c in fix_cmds if c[0] == "paseo"]
    _check(
        fix_prompt_argv and FINDINGS in fix_prompt_argv[-1][-1],
        "FIX paseo run prompt must carry the findings verbatim",
        failed,
    )
    # The FIX run uses the IMPLEMENTER worktree (same agent — holds context).
    _check(
        any("issue-42-implement" in c for c in fix_cmds),
        "FIX must run in the implementer's worktree (same agent fixes)",
        failed,
    )

    stuck_cmds = closeout.closeout_commands(
        closeout.plan_closeout(_verdict(closeout.VERDICT_FAIL), round=closeout.MAX_REVIEW_ROUNDS),
        "CaicoLeung/skills", 29, 42, "https://x/pull/42", "main",
        reviewer_workspace="issue-42-review", implementer_workspace="issue-42-implement",
    )
    _check(
        not any(c[:3] == ["gh", "pr", "merge"] for c in stuck_cmds),
        "STUCK must not emit a merge command (PR left unmerged)",
        failed,
    )
    _check(
        any(c[:3] == ["gh", "issue", "comment"] for c in stuck_cmds),
        "STUCK must post an issue comment (escalation)",
        failed,
    )

    review_cmds = closeout.closeout_commands(
        closeout.plan_closeout(_verdict(closeout.VERDICT_MISSING), round=0),
        "CaicoLeung/skills", 29, 42, "https://x/pull/42", "main",
        reviewer_workspace="issue-42-review", implementer_workspace="issue-42-implement",
    )
    _check(
        not any(c[:3] == ["gh", "pr", "merge"] for c in review_cmds),
        "REVIEW must not emit a merge command",
        failed,
    )
    # The reviewer runs in a SEPARATE worktree (independence axis 4) — not the
    # implementer's.
    _check(
        any("issue-42-review" in c and "issue-42-implement" not in c for c in review_cmds),
        "REVIEW must run in the reviewer's separate worktree, not the implementer's",
        failed,
    )

    # =========================================================================
    # AC4: dual close — Fixes #N (PR body, T5a) + loop resolution comment
    # =========================================================================
    print("dual close: resolution comment (Fixes #N is in the PR body, T5a):")
    rc = closeout.resolution_comment(29, pr_url, rounds=2)
    _check("Resolved #29" in rc, "resolution comment names the issue", failed)
    _check(pr_url in rc, "resolution comment links the PR", failed)
    _check("2 review round" in rc, "resolution comment reports the review cost", failed)
    # The loop's close line — Fixes #N in the PR body auto-closes; the comment
    # also carries an explicit close for human-readable resolution.
    _check(f"Closes #29" in rc, "resolution comment carries an explicit close", failed)
    # The comment must NOT claim merge happened before CI is green.
    _check(
        "validate-skills" in rc and "review-verdict" in rc,
        "resolution comment must ground the merge in both required checks",
        failed,
    )
    # Optional merged SHA is surfaced when provided.
    rc_sha = closeout.resolution_comment(29, pr_url, rounds=1, merged_sha="abc1234")
    _check("abc1234" in rc_sha, "resolution comment surfaces merged SHA when given", failed)

    # =========================================================================
    # AC2 (cont.): STUCK_REVIEW — PR unmerged, no auto-close, posts to issue
    # =========================================================================
    print("STUCK_REVIEW escalation (PR unmerged, no auto-close):")
    sm = closeout.stuck_message(29, pr_url, round=closeout.MAX_REVIEW_ROUNDS)
    _check("STUCK_REVIEW" in sm, "stuck message names STUCK_REVIEW", failed)
    _check("#29" in sm and pr_url in sm, "stuck message names the issue + PR", failed)
    # The issue is NOT auto-closed on stuck (only wontfix / ready-for-human
    # stop-and-leave; ADR-0008 §5). The message must say so explicitly so a
    # consumer never mistakes stuck for resolved.
    _check(
        "not auto-closed" in sm.lower(),
        "stuck message must state the issue is not auto-closed",
        failed,
    )
    _check(
        "unmerged" in sm.lower(),
        "stuck message must state the PR is left unmerged",
        failed,
    )

    # =========================================================================
    # Determinism + JSON round-trip
    # =========================================================================
    print("determinism + JSON:")
    a = closeout.plan_closeout(_verdict(closeout.VERDICT_FAIL, FINDINGS, blocking=1), round=2)
    b = closeout.plan_closeout(_verdict(closeout.VERDICT_FAIL, FINDINGS, blocking=1), round=2)
    _check(a == b, "plan_closeout is deterministic for equal inputs", failed)
    js = a.to_dict()
    _check(
        js["action"] == closeout.ACTION_FIX and js["findings_text"] == FINDINGS,
        "CloseoutDecision.to_dict round-trips action + verbatim findings",
        failed,
    )

    # =========================================================================
    # Totality: every (status, round) resolves to exactly one action
    # =========================================================================
    print("totality (no (status, round) falls through):")
    for status in (closeout.VERDICT_PASS, closeout.VERDICT_FAIL, closeout.VERDICT_MISSING):
        for rnd in range(0, closeout.MAX_REVIEW_ROUNDS + 2):
            d = closeout.plan_closeout(_verdict(status), round=rnd)
            _check(
                d.action in (closeout.ACTION_PASS, closeout.ACTION_REVIEW, closeout.ACTION_FIX, closeout.ACTION_STUCK),
                f"({status}, {rnd}) unresolved -> {d.action}",
                failed,
            )
            # The four actions are mutually exclusive in meaning: only PASS merges.
            if d.action == closeout.ACTION_PASS:
                _check(status == closeout.VERDICT_PASS, "PASS only on a passing verdict", failed)

    # =========================================================================
    # Driver through the gateway: run_closeout_round composes T3+T1 from fake PR
    # comments. Previously exercised only via --dry-run with verdict_state/
    # round_number overrides; with the injected reader the verdict is DERIVED
    # from fake comments, not supplied — the real close-out path, testable.
    # =========================================================================
    print("run_closeout_round through the gateway (fake reader):")
    _check(
        isinstance(FakeGitHubReader(), GitHubReader),
        "FakeGitHubReader must satisfy the GitHubReader Protocol",
        failed,
    )

    sha = "deadbeef"
    cfg_co = loop.DriverConfig(
        repo="CaicoLeung/skills", reviewer_login="reviewer-bot",
    )

    # A passing review: every changed file covered, no blocking findings.
    fake_pass = FakeGitHubReader()
    fake_pass.head_shas[42] = sha
    fake_pass.changed_files[42] = ["scripts/x.py"]
    fake_pass.comments[42] = [{
        "id": 1,
        "user": {"login": "reviewer-bot"},
        "created_at": "2026-07-25T10:00:00Z",
        "body": (
            f"<!-- review-verdict-findings sha={sha} -->\n\n"
            "### Standards\nscripts/x.py: OK\n"
            "### Spec\nscripts/x.py: OK\n"
        ),
    }]
    rep = loop.run_closeout_round(29, 42, cfg_co, gh=fake_pass, dry_run=True)
    _check(rep["head_sha"] == sha, "run_closeout_round reads head via the fake", failed)
    _check(
        rep["verdict"]["status"] == "pass",
        f"derived verdict must be pass (got {rep['verdict']['status']})",
        failed,
    )
    _check(
        rep["decision"]["action"] == "pass",
        "pass verdict -> PASS decision (auto-merge path)",
        failed,
    )
    _check(
        any(c[:3] == ["gh", "pr", "merge"] and "--auto" in c for c in rep["commands"]),
        "PASS via the gateway must still emit the loop-owned auto-merge",
        failed,
    )

    # A failing review (HIGH finding) at round 1 -> FIX; the round count is
    # read from the fake's comments (one reviewer findings comment => round 1).
    fake_fail = FakeGitHubReader()
    fake_fail.head_shas[42] = sha
    fake_fail.changed_files[42] = ["scripts/x.py"]
    fake_fail.comments[42] = [{
        "id": 2,
        "user": {"login": "reviewer-bot"},
        "created_at": "2026-07-25T11:00:00Z",
        "body": (
            f"<!-- review-verdict-findings sha={sha} -->\n\n"
            "### Standards\n[scripts/x.py:9]: HIGH: null deref\n"
        ),
    }]
    rep_fail = loop.run_closeout_round(29, 42, cfg_co, gh=fake_fail, dry_run=True)
    _check(
        rep_fail["verdict"]["status"] == "fail",
        f"HIGH finding -> fail verdict (got {rep_fail['verdict']['status']})",
        failed,
    )
    _check(
        rep_fail["decision"]["action"] == "fix",
        "fail at round 1 -> FIX (findings handed to the implementer)",
        failed,
    )
    _check(
        rep_fail["round"] == 1,
        f"round count read from the fake's comments (got {rep_fail['round']})",
        failed,
    )

    # A PR with NO reviewer findings comment yet -> derived verdict MISSING at
    # round 0 -> REVIEW. run_closeout_round must drive the full REVIEW path:
    # plan_closeout -> _require_reviewer_independence -> build the fixed review
    # prompt from the fake's diff+spec -> emit a paseo run on the SECONDARY
    # provider in the reviewer's separate worktree. This is the one claimed
    # testable path that had no end-to-end coverage through the driver.
    print("run_closeout_round REVIEW path through the gateway (no review yet):")
    cfg_rev = loop.DriverConfig(
        repo="CaicoLeung/skills", reviewer_login="reviewer-bot",
        provider="anthropic", model="claude-impl",
        secondary_provider="openai", secondary_model="gpt-reviewer",
    )
    fake_rev = FakeGitHubReader()
    fake_rev.head_shas[42] = sha
    fake_rev.diffs[42] = "+diff line A\n-diff line B\n"
    fake_rev.bodies[29] = "## Acceptance\n- do the thing\n"
    fake_rev.changed_files[42] = ["scripts/x.py"]
    # No comments[42]: the reviewer has not posted yet.
    rep_rev = loop.run_closeout_round(29, 42, cfg_rev, gh=fake_rev, dry_run=True)
    _check(
        rep_rev["verdict"]["status"] == "missing",
        f"no review comment -> MISSING verdict (got {rep_rev['verdict']['status']})",
        failed,
    )
    _check(
        rep_rev["round"] == 0,
        f"no reviewer comments -> round 0 (got {rep_rev['round']})",
        failed,
    )
    _check(
        rep_rev["decision"]["action"] == "review",
        "MISSING at round 0 -> REVIEW (independent reviewer invoked)",
        failed,
    )
    rev_run = [c for c in rep_rev["commands"] if c[:1] == ["paseo"]]
    _check(
        len(rev_run) == 1,
        f"REVIEW must emit one paseo command (got {len(rev_run)})",
        failed,
    )
    if rev_run:
        cmd = rev_run[0]
        _check(
            "openai" in cmd and "gpt-reviewer" in cmd,
            "REVIEW must run on the SECONDARY provider/model",
            failed,
        )
        _check(
            "issue-29-review" in cmd,
            "REVIEW must run in the reviewer's separate worktree",
            failed,
        )
        _check(
            "+diff line A" in cmd[-1] and "## Acceptance" in cmd[-1],
            "REVIEW prompt must carry the fake's diff + spec verbatim",
            failed,
        )

    if failed:
        print(f"\n{len(failed)} close-out test(s) failed.", file=sys.stderr)
        return 1
    print("\nAll close-out planner tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
