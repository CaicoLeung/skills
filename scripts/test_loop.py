#!/usr/bin/env python3
"""Unit tests for the deterministic loop driver's turn planner (T5a / ADR-0008).

Zero-dependency: runnable directly as ``python3 scripts/test_loop.py``.
Exits non-zero on any failure.

Scope (this slice): the loop's *routing half* — the readiness gate and type
dispatch that decide which turn runs, and the implement turn's PR-body
contract. The close-out half (review → verdict → fix → merge → close) is T5b
(issue #29) and is not exercised here.

Behavior, not plumbing: no ``gh``, no ``paseo run``. The pure turn-planning
function (:func:`loop.plan_turn`) is the testable seam; the I/O driver that
actually invokes ``paseo run --detach`` is deliberately not covered (per the
testing decisions in issue #23).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
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

    if failed:
        print(f"\n{len(failed)} loop test(s) failed.", file=sys.stderr)
        return 1
    print("\nAll loop turn-planning tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
