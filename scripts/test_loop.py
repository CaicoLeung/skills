#!/usr/bin/env python3
"""Unit tests for the deterministic loop driver's turn planner (T5a / ADR-0008).

Zero-dependency: runnable directly as ``python3 scripts/test_loop.py``.
Exits non-zero on any failure.

Scope (this slice): the loop's *routing half* — the readiness gate and type
dispatch that decide which turn runs, and the implement turn's PR-body
(issue #29); its network-free enrichment path is covered below — the
provider/model + verbatim handoff in :func:`loop.closeout_decision_commands`
for FIX, and the loop-owned PASS commands. The REVIEW enrichment needs ``gh``
for the live diff, so it stays on ``--dry-run``.

Behavior, not plumbing: no ``gh``, no ``paseo run``. The pure turn-planning
function (:func:`loop.plan_turn`) is the testable seam; the I/O driver that
actually invokes ``paseo run --detach`` is deliberately not covered (per the
testing decisions in issue #23).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _test_fakes import FakeGitHubReader  # noqa: E402
from github import GitHubReader  # noqa: E402
import loop  # noqa: E402
import routing  # noqa: E402


def _check(condition: bool, label: str, failed: list) -> None:
    if not condition:
        print(f"  FAIL {label}")
        failed.append(label)


def main() -> int:
    failed: list[str] = []

    # --- Acceptance: implement is unreachable from a triage status ----------
    # Whatever triage state a claimed ticket is in, the loop must never select
    # an implement (PR-opening) turn. The readiness gate fires first.
    print("readiness gate: implement unreachable from triage statuses:")
    triage_states = [
        ([], "unlabeled"),
        (["needs-triage"], "needs-triage"),
        (["needs-info"], "needs-info"),
        (["ready-for-human"], "ready-for-human"),
        (["wontfix"], "wontfix"),
    ]
    for labels, name in triage_states:
        turn = loop.plan_turn(labels, issue_number=42)
        _check(
            not turn.opens_pr,
            f"{name}: implement turn must not open a PR (got {turn})",
            failed,
        )
        # A task label present but not ready must still not implement.
        if name in ("unlabeled", "needs-triage", "needs-info"):
            turn_with_task = loop.plan_turn([*labels, "task"], issue_number=42)
            _check(
                not turn_with_task.opens_pr,
                f"{name}+task: must not implement until ready-for-agent",
                failed,
            )

    # --- Acceptance: orchestrator dispatches by type label ------------------
    # ready-for-agent + each type routes to that type's external skill.
    print("type dispatch: ready-for-agent dispatches each type's skill:")
    for ttype in routing.TICKET_TYPES:
        expected_skill = routing.TYPE_DISPATCH[ttype].skill
        expected_mode = routing.TYPE_DISPATCH[ttype].mode
        turn = loop.plan_turn(["ready-for-agent", ttype], issue_number=42)
        _check(
            turn.skill == expected_skill,
            f"{ttype}: skill {turn.skill!r} != {expected_skill!r}",
            failed,
        )
        _check(
            turn.mode == expected_mode,
            f"{ttype}: mode {turn.mode!r} != {expected_mode!r}",
            failed,
        )
        _check(
            turn.action == loop.ACTION_DISPATCH,
            f"{ttype}: action should be dispatch, got {turn.action!r}",
            failed,
        )

    # --- Acceptance: for `task`, an implement turn opens a PR w/ Fixes #N ----
    print("task implement turn: opens PR carrying 'Fixes #N':")
    turn = loop.plan_turn(["ready-for-agent", "task"], issue_number=28)
    _check(turn.opens_pr, "task turn must open a PR", failed)
    _check(turn.pr_body is not None, "task turn must carry a PR body", failed)
    _check(
        turn.pr_body is not None and "Fixes #28" in turn.pr_body,
        f"PR body must contain 'Fixes #28' (got {turn.pr_body!r})",
        failed,
    )

    # Only `task` opens a PR; the non-code types resolve decisions and close.
    for ttype in ("research", "prototype", "grilling"):
        t = loop.plan_turn(["ready-for-agent", ttype], issue_number=28)
        _check(
            not t.opens_pr,
            f"{ttype} must not open a PR (only task does)",
            failed,
        )

    # --- implement_pr_body: the canonical close body is deterministic -------
    print("implement_pr_body: deterministic 'Fixes #N' body:")
    for n in (1, 28, 1234):
        body = loop.implement_pr_body(n)
        _check(
            f"Fixes #{n}" in body,
            f"implement_pr_body({n}) missing 'Fixes #{n}': {body!r}",
            failed,
        )

    # --- Non-dispatch turns carry no skill and open no PR -------------------
    print("non-dispatch turns carry no skill / PR:")
    cases = [
        ([], loop.ACTION_TRIAGE),
        (["needs-triage"], loop.ACTION_TRIAGE),
        (["needs-info"], loop.ACTION_PAUSE),
        (["ready-for-human"], loop.ACTION_STOP),
        (["wontfix"], loop.ACTION_CLOSE),
    ]
    for labels, expected_action in cases:
        turn = loop.plan_turn(labels, issue_number=7)
        _check(
            turn.action == expected_action,
            f"{sorted(labels)}: action {turn.action!r} != {expected_action!r}",
            failed,
        )
        _check(not turn.opens_pr, f"{expected_action} must not open a PR", failed)

    # The triage turn invokes /triage; the pause/stop/close turns invoke no
    # doing-skill (they are pure loop actions).
    _check(
        loop.plan_turn([], issue_number=7).skill == "/triage",
        "triage turn must invoke /triage",
        failed,
    )
    for labels, _ in cases[2:]:
        turn = loop.plan_turn(labels, issue_number=7)
        _check(
            turn.skill is None,
            f"{turn.action} must carry no skill (got {turn.skill!r})",
            failed,
        )

    # --- Determinism: turn planning never depends on label order ------------
    print("determinism (order-independent):")
    left = loop.plan_turn(["ready-for-agent", "task", "bug"], issue_number=5)
    right = loop.plan_turn(["bug", "task", "ready-for-agent"], issue_number=5)
    _check(left == right, "plan_turn is order-sensitive", failed)

    # --- Ambiguity surfaces as the routing error, not a silent turn ---------
    print("ambiguity propagates:")
    raised = False
    try:
        loop.plan_turn(["ready-for-agent", "research", "task"], issue_number=1)
    except ValueError:
        raised = True
    _check(raised, "ambiguous type labels must raise, not pick silently", failed)

    # --- workspace_name: clean slug; no stray '+' or leading dash ---------
    # A `task` turn's skill packs "/implement + /code-review"; the worktree
    # must be named after the primary skill, not the whole packed string.
    print("workspace_name: readable slug (primary skill only):")
    _check(
        loop.workspace_name(28, loop.plan_turn(["ready-for-agent", "task"], 28))
        == "issue-28-implement",
        "task worktree must name the primary skill (/implement), "
        "not the packed '/implement + /code-review' string",
        failed,
    )
    _check(
        loop.workspace_name(7, loop.plan_turn(["ready-for-agent", "grilling"], 7))
        == "issue-7-grilling",
        "grilling worktree must slug to 'grilling'",
        failed,
    )
    _check(
        loop.workspace_name(7, loop.plan_turn([], 7)) == "issue-7-triage",
        "triage worktree must slug to 'triage'",
        failed,
    )

    # --- turn_status: HITL pauses; AFK does not (mode is not metadata) ----
    # The ADR-0008 §3 invariant: a HITL turn's outcome must be visibly
    # distinct from an AFK turn so no consumer fakes the human's side.
    print("turn_status: HITL pauses for the human turn, AFK does not:")
    task_turn = loop.plan_turn(["ready-for-agent", "task"], 28)
    _check(
        "PR opened (Fixes #28)" in loop.turn_status(task_turn, 28),
        "task status must report the PR with 'Fixes #N'",
        failed,
    )
    proto = loop.plan_turn(["ready-for-agent", "prototype"], 9)
    proto_status = loop.turn_status(proto, 9)
    _check(
        "paused for human turn (HITL)" in proto_status and "AFK" not in proto_status,
        "prototype (HITL) status must signal a pause for the human turn",
        failed,
    )
    research = loop.plan_turn(["ready-for-agent", "research"], 9)
    research_status = loop.turn_status(research, 9)
    _check(
        "(AFK)" in research_status and "paused" not in research_status,
        "research (AFK) status must not claim a human pause",
        failed,
    )

    # Pure motions carry their own status — turn_status is total over actions.
    _check(
        "paused" in loop.turn_status(loop.plan_turn(["needs-info"], 3), 3),
        "needs-info status must report the pause",
        failed,
    )
    _check(
        "stopped" in loop.turn_status(loop.plan_turn(["ready-for-human"], 3), 3),
        "ready-for-human status must report the stop",
        failed,
    )
    _check(
        loop.turn_status(loop.plan_turn(["wontfix"], 3), 3) == "closed (wontfix)",
        "wontfix status must report the close",
        failed,
    )

    # --- Close-out driver enrichment (T5b): provider/model + verbatim handoff --
    # The live closeout_decision_commands refines the pure planner's placeholder
    # commands. FIX runs on the PRIMARY provider with the verbatim findings; PASS
    # emits loop-owned gh commands. REVIEW needs gh for the live diff (covered by
    # --dry-run, not here). Network-free: no gh, no paseo.
    print("close-out driver enrichment (FIX primary, PASS loop-owned):")
    import closeout

    cfg_fix = loop.DriverConfig(
        repo="CaicoLeung/skills", provider="anthropic", model="claude-x",
    )
    FINDINGS = "### Standards\n[s/x.py:9]: HIGH: null deref\n"
    fix_dec = closeout.plan_closeout(
        closeout.VerdictState(closeout.VERDICT_FAIL, FINDINGS, 1, 0), round=1
    )
    fix_cmds = loop.closeout_decision_commands(
        cfg_fix, fix_dec, 29, 42, head_sha="deadbeef"
    )
    fix_run = [c for c in fix_cmds if c[0] == "paseo"][0]
    _check(
        "--provider" in fix_run and "anthropic" in fix_run,
        "FIX enrichment runs on cfg.provider",
        failed,
    )
    _check(
        "--model" in fix_run and "claude-x" in fix_run,
        "FIX enrichment runs on cfg.model (not the planner default)",
        failed,
    )
    _check(
        FINDINGS in fix_run[-1],
        "FIX enrichment prompt carries the findings verbatim",
        failed,
    )
    _check(
        not any(c[:3] == ["gh", "pr", "merge"] for c in fix_cmds),
        "FIX enrichment must not emit a merge (implementer never merges)",
        failed,
    )

    cfg_pass = loop.DriverConfig(repo="CaicoLeung/skills")
    pass_dec = closeout.plan_closeout(
        closeout.VerdictState(closeout.VERDICT_PASS, "", 0, 0), round=1
    )
    pass_cmds = loop.closeout_decision_commands(
        cfg_pass, pass_dec, 29, 42, head_sha="deadbeef"
    )
    _check(
        any(c[:3] == ["gh", "pr", "merge"] and "--auto" in c for c in pass_cmds),
        "PASS enrichment emits the loop-owned auto-merge",
        failed,
    )
    _check(
        any(c[:3] == ["gh", "issue", "comment"] for c in pass_cmds),
        "PASS enrichment emits the dual-close resolution comment",
        failed,
    )

    # --- Driver through the gateway: run_ticket_loop reads labels via the fake --
    # Previously disclaimed as untestable (issue #23: it hit real ``gh``). The
    # ``gh`` param twins ``runner`` — inject a fake and the routing driver is
    # exercised end to end through its own interface, no network.
    print("run_ticket_loop through the gateway (fake reader):")
    _check(
        isinstance(FakeGitHubReader(), GitHubReader),
        "FakeGitHubReader must satisfy the GitHubReader Protocol",
        failed,
    )
    fake = FakeGitHubReader()
    fake.labels[28] = ["ready-for-agent", "task"]
    cfg_loop = loop.DriverConfig(repo="CaicoLeung/skills")
    report = loop.run_ticket_loop(28, cfg_loop, dry_run=True, gh=fake)
    _check(
        report["labels"] == ["ready-for-agent", "task"],
        f"run_ticket_loop must read labels via the fake (got {report['labels']})",
        failed,
    )
    _check(
        report["turn"]["opens_pr"] is True,
        "ready-for-agent+task via the fake must open a PR",
        failed,
    )
    _check(
        isinstance(report["command"], list) and report["command"][0] == "paseo",
        "run_ticket_loop must build the paseo command from the fake-read labels",
        failed,
    )

    # --- REVIEW enrichment through the gateway: diff+spec reach the prompt ------
    # The case this suite explicitly skipped ("needs gh for the live diff").
    # The fake supplies diff/spec/changed-files; REVIEW must run on the SECONDARY
    # provider in the review worktree, and the fake's diff+spec must survive into
    # the rendered review prompt (proving the gateway feeds reviewer.build_review_prompt).
    print("REVIEW enrichment through the gateway (diff+spec via fake):")
    fake_r = FakeGitHubReader()
    fake_r.diffs[42] = "+diff line A\n-diff line B\n"
    fake_r.bodies[29] = "## Acceptance\n- do the thing\n"
    fake_r.changed_files[42] = ["scripts/x.py"]
    cfg_rev = loop.DriverConfig(
        repo="CaicoLeung/skills",
        provider="anthropic", model="claude-impl",
        secondary_provider="openai", secondary_model="gpt-reviewer",
    )
    review_dec = closeout.plan_closeout(
        closeout.VerdictState(closeout.VERDICT_MISSING, "", 0, 0), round=0
    )
    _check(
        review_dec.action == closeout.ACTION_REVIEW,
        "VERDICT_MISSING at round 0 -> REVIEW",
        failed,
    )
    rev_cmds = loop.closeout_decision_commands(
        cfg_rev, review_dec, 29, 42, head_sha="deadbeef", gh=fake_r
    )
    rev_run = [c for c in rev_cmds if c[0] == "paseo"][0]
    _check(
        "openai" in rev_run and "gpt-reviewer" in rev_run,
        "REVIEW must run on the SECONDARY provider/model",
        failed,
    )
    _check(
        "issue-29-review" in rev_run,
        "REVIEW must run in the reviewer's separate worktree",
        failed,
    )
    _check(
        "+diff line A" in rev_run[-1] and "## Acceptance" in rev_run[-1],
        "REVIEW prompt must carry the fake's diff + spec verbatim",
        failed,
    )

    if failed:
        print(f"\n{len(failed)} loop test(s) failed.", file=sys.stderr)
        return 1
    print("\nAll loop turn-planning tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
