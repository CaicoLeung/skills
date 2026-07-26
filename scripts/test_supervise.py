#!/usr/bin/env python3
"""Unit tests for the supervisor planner (SUPERVISE / ADR-0006 §T1 tracer bullet).

Zero-dependency: runnable directly as ``python3 scripts/test_supervise.py``.
Exits non-zero on any failure.

Scope: the **pure** supervisor planner — the triage state machine (fix /
escalate), the bounded retry budget (auto-escalate on exhaustion), and
absence-of-signal detection (a required check that never reports within a
deadline is a deviation, not a silent wait). The I/O driver
(``loop.run_supervise_round``) is exercised safely through ``--dry-run`` /
the trajectory simulator — not here (issue #23 testing decisions).

Each assertion maps to an acceptance criterion of issue #11:

* AC1 — triage state machine (fix / escalate) + bounded retry budget that
  auto-escalates on exhaustion.
* AC2 — completion is merged-and-gated (PR merged AND gate passed), distinct
  from agent-finished.
* AC3 — adapter commands: redispatch leaf via ``paseo send`` with the specific
  failure, OR post an ``ESCALATE`` signal a human consumes.
* AC4 — absence-of-signal is detected: a check that never reports within a
  deadline is classified as a deviation, not silently waited on.
* AC5 — replay of the check-name-drift stall (``wf-skills-1``): old behavior
  is silent stall forever; new behavior escalates within bounded time.
* AC6 — the "don't poll" reconciliation: polling gate state ≠ polling agents.
  (Enforced structurally: the planner takes GateState, never agent state.)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _test_fakes import FakeGitHubReader  # noqa: E402
from github import GitHubReader, _normalize_check_run  # noqa: E402
import loop  # noqa: E402
import supervise  # noqa: E402


def _check(condition: bool, label: str, failed: list[str]) -> None:
    if not condition:
        print(f"  FAIL {label}")
        failed.append(label)


def _gate(
    *,
    pr_state: str = "OPEN",
    merge_state_status: str = "UNKNOWN",
    merged_at: str = "",
    required_check: str = "validate-skills",
    check_state: str = "",
    check_seen: bool = False,
    signal_elapsed_sec: int = 0,
    signal_deadline_sec: int = supervise.DEFAULT_SIGNAL_DEADLINE_SEC,
) -> supervise.GateState:
    """Build a GateState with the absence-of-signal defaults."""
    return supervise.GateState(
        pr_state=pr_state,
        merge_state_status=merge_state_status,
        merged_at=merged_at,
        required_check=required_check,
        check_state=check_state,
        check_seen=check_seen,
        signal_elapsed_sec=signal_elapsed_sec,
        signal_deadline_sec=signal_deadline_sec,
    )


def main() -> int:
    failed: list[str] = []

    # =========================================================================
    # AC2: completion is merged-and-gated (NOT agent-finished)
    # =========================================================================
    print("merged-and-gated completion (distinct from agent-finished):")

    # Only MERGED + check success → COMPLETE. Anything else is not complete.
    complete = _gate(pr_state="MERGED", check_state="success", check_seen=True,
                     merged_at="2026-07-26T10:00:00Z")
    d = supervise.plan_supervise(complete, retries_used=0)
    _check(d.action == supervise.ACTION_COMPLETE, "merged + green -> COMPLETE", failed)
    _check(
        "merged-and-gated" in d.reason,
        "COMPLETE reason must name merged-and-gated",
        failed,
    )

    # Merged but check never reported → NOT complete (still escalated — gate did
    # not genuinely pass). This is the original sin in reverse: a merged PR with
    # no check must NOT be read as success.
    merged_no_check = _gate(pr_state="MERGED", check_state="", check_seen=False,
                            signal_elapsed_sec=10_000)
    d = supervise.plan_supervise(merged_no_check, retries_used=0)
    _check(
        d.action != supervise.ACTION_COMPLETE,
        "merged WITHOUT check -> NOT complete (gate did not genuinely pass)",
        failed,
    )

    # Check green but PR not merged → NOT complete (agent-finished ≠ merged).
    green_no_merge = _gate(pr_state="OPEN", merge_state_status="CLEAN",
                           check_state="success", check_seen=True)
    d = supervise.plan_supervise(green_no_merge, retries_used=0)
    _check(
        d.action != supervise.ACTION_COMPLETE,
        "green check WITHOUT merge -> NOT complete (distinct from agent-finished)",
        failed,
    )

    # =========================================================================
    # AC1: triage state machine — fix (redispatch) vs escalate
    # =========================================================================
    print("triage state machine (mechanical/transient -> fix, genuine -> escalate):")

    # Mechanical: mergeStateStatus DIRTY (needs rebase) → REDISPATCH at retry 0.
    dirty = _gate(merge_state_status="DIRTY", check_state="success", check_seen=True)
    d = supervise.plan_supervise(dirty, retries_used=0)
    _check(
        d.action == supervise.ACTION_REDISPATCH,
        f"DIRTY at retry 0 -> REDISPATCH (got {d.action})",
        failed,
    )
    _check(d.deviation == supervise.DEVIATION_MERGE_DIRTY, "deviation is MERGE_DIRTY", failed)
    _check(
        d.classification == supervise.CLASS_MECHANICAL,
        "DIRTY classifies as MECHANICAL (re-dispatchable)",
        failed,
    )

    # Mechanical: mergeStateStatus BEHIND (needs rebase) → REDISPATCH.
    behind = _gate(merge_state_status="BEHIND", check_state="success", check_seen=True)
    d = supervise.plan_supervise(behind, retries_used=0)
    _check(d.action == supervise.ACTION_REDISPATCH, "BEHIND -> REDISPATCH", failed)
    _check(d.classification == supervise.CLASS_MECHANICAL, "BEHIND is MECHANICAL", failed)

    # Transient: required check currently failing → REDISPATCH (could be flaky).
    failing = _gate(check_state="failure", check_seen=True)
    d = supervise.plan_supervise(failing, retries_used=0)
    _check(d.action == supervise.ACTION_REDISPATCH, "check failing -> REDISPATCH", failed)
    _check(d.deviation == supervise.DEVIATION_CHECK_FAILING, "deviation is CHECK_FAILING", failed)
    _check(d.classification == supervise.CLASS_TRANSIENT, "failing check is TRANSIENT", failed)

    # Genuine: mergeStateStatus BLOCKED (unsatisfiable protection) → ESCALATE
    # at ANY retry count. Bounded retries do not apply — this is not fixable by
    # re-dispatching the leaf.
    blocked = _gate(merge_state_status="BLOCKED", check_state="success", check_seen=True)
    for rnd in (0, 1, 2, 99):
        d = supervise.plan_supervise(blocked, retries_used=rnd)
        _check(
            d.action == supervise.ACTION_ESCALATE,
            f"BLOCKED at retry {rnd} -> ESCALATE (unsatisfiable; never redispatch)",
            failed,
        )
        _check(d.classification == supervise.CLASS_GENUINE, "BLOCKED is GENUINE", failed)

    # Ambiguous: unknown merge state → ESCALATE (defaults to safe, never pass).
    unknown = _gate(merge_state_status="UNRECOGNIZED_TOKEN")
    d = supervise.plan_supervise(unknown, retries_used=0)
    _check(
        d.action == supervise.ACTION_ESCALATE,
        "unknown merge state -> ESCALATE (ambiguity defaults to escalate)",
        failed,
    )
    _check(d.classification == supervise.CLASS_AMBIGUOUS, "unknown is AMBIGUOUS", failed)

    # =========================================================================
    # AC1 (cont.): bounded retry budget auto-escalates on exhaustion
    # =========================================================================
    print("bounded retry budget (auto-escalate on exhaustion, never wait-forever):")
    _check(
        supervise.MAX_GATE_RETRIES == 2,
        f"MAX_GATE_RETRIES must be 2 (got {supervise.MAX_GATE_RETRIES})",
        failed,
    )

    # Mechanical deviation at the cap → ESCALATE (cap guards every redispatchable path).
    for deviation_state in (
        _gate(merge_state_status="DIRTY", check_state="success", check_seen=True),
        _gate(merge_state_status="BEHIND", check_state="success", check_seen=True),
        _gate(check_state="failure", check_seen=True),
    ):
        d = supervise.plan_supervise(deviation_state, retries_used=supervise.MAX_GATE_RETRIES)
        _check(
            d.action == supervise.ACTION_ESCALATE,
            f"{deviation_state.merge_state_status or deviation_state.check_state!r} at cap -> ESCALATE",
            failed,
        )
        _check(
            "exhausted" in d.reason.lower() or "cap" in d.reason.lower(),
            "cap escalation reason must name exhaustion",
            failed,
        )

    # Beyond the cap too.
    d = supervise.plan_supervise(
        _gate(check_state="failure", check_seen=True),
        retries_used=supervise.MAX_GATE_RETRIES + 3,
    )
    _check(d.action == supervise.ACTION_ESCALATE, "beyond cap -> ESCALATE", failed)

    # Just below the cap still redispatches (the boundary is exact).
    d = supervise.plan_supervise(
        _gate(merge_state_status="DIRTY", check_state="success", check_seen=True),
        retries_used=supervise.MAX_GATE_RETRIES - 1,
    )
    _check(
        d.action == supervise.ACTION_REDISPATCH,
        "one below cap -> REDISPATCH (boundary exact)",
        failed,
    )

    # =========================================================================
    # AC4: absence-of-signal — a missing check past the deadline is a deviation
    # =========================================================================
    print("absence-of-signal (missing check past deadline = deviation, not silent wait):")

    # Within the deadline, check unseen, no other deviation → WAIT. The
    # supervisor is patient while the check may simply not have reported yet.
    patient = _gate(check_state="", check_seen=False, signal_elapsed_sec=60,
                    signal_deadline_sec=300)
    _check(
        not patient.signal_deadline_exceeded,
        "signal_deadline_exceeded is False within the deadline",
        failed,
    )
    d = supervise.plan_supervise(patient, retries_used=0)
    _check(d.action == supervise.ACTION_WAIT, "within deadline + check unseen -> WAIT", failed)
    _check(d.deviation == supervise.DEVIATION_NONE, "no deviation while patient", failed)

    # Past the deadline, check still unseen → DEVIATION_CHECK_MISSING (absence
    # of signal). This is the wf-skills-1 stall: today nothing detects this.
    stalled = _gate(check_state="", check_seen=False, signal_elapsed_sec=600,
                    signal_deadline_sec=300)
    _check(stalled.signal_deadline_exceeded, "deadline exceeded after 600s/300s", failed)
    d = supervise.plan_supervise(stalled, retries_used=0)
    _check(
        d.action == supervise.ACTION_REDISPATCH,
        "check missing past deadline -> REDISPATCH (not silent wait)",
        failed,
    )
    _check(
        d.deviation == supervise.DEVIATION_CHECK_MISSING,
        "deviation is CHECK_MISSING (absence-of-signal)",
        failed,
    )
    _check(
        d.classification == supervise.CLASS_MECHANICAL,
        "check missing is MECHANICAL (could be name drift; leaf investigates)",
        failed,
    )

    # Past the deadline, retries exhausted → ESCALATE.
    d = supervise.plan_supervise(stalled, retries_used=supervise.MAX_GATE_RETRIES)
    _check(
        d.action == supervise.ACTION_ESCALATE,
        "check missing past deadline + exhausted -> ESCALATE",
        failed,
    )

    # =========================================================================
    # AC5: replay of the wf-skills-1 check-name-drift stall
    # =========================================================================
    # Scenario: the workflow was renamed, so the required check
    # `validate-skills` never appears. The leaf agent has long since finished
    # and gone idle. Today: silent stall (the gap the supervisor fills).
    # New behavior: within bounded time the supervisor (a) redispatches the
    # leaf with "check never reported" up to MAX_GATE_RETRIES, then (b)
    # escalates to a human. The trajectory simulator proves the loop closes.
    # =========================================================================
    print("wf-skills-1 replay (check-name-drift stall):")
    NameDriftScene = supervise.run_supervise_trajectory(
        gate_states=[
            # Poll 1: agent finished 60s ago, check not seen yet, patient.
            _gate(check_seen=False, signal_elapsed_sec=60, signal_deadline_sec=300),
            # Poll 2: 600s elapsed, deadline crossed → REDISPATCH (retry 1).
            _gate(check_seen=False, signal_elapsed_sec=600, signal_deadline_sec=300),
            # Poll 3: leaf redispatched; still no check → REDISPATCH (retry 2).
            _gate(check_seen=False, signal_elapsed_sec=1200, signal_deadline_sec=300),
            # Poll 4: still no check, cap exhausted → ESCALATE (terminal).
            _gate(check_seen=False, signal_elapsed_sec=1800, signal_deadline_sec=300),
        ],
        retry_budget=supervise.MAX_GATE_RETRIES,
    )
    actions = [s["action"] for s in NameDriftScene["decisions"]]
    _check(
        actions == ["wait", "redispatch", "redispatch", "escalate"],
        f"replay actions must be [wait, redispatch, redispatch, escalate] (got {actions})",
        failed,
    )
    _check(NameDriftScene["terminal"], "replay must terminate (never silent-stall)", failed)
    _check(
        NameDriftScene["retries_used"] == supervise.MAX_GATE_RETRIES,
        f"replay exhausts the retry budget (got {NameDriftScene['retries_used']})",
        failed,
    )

    # Contrast: today's behavior is WAIT forever — the supervisor's planner
    # would never terminate if absence-of-signal went undetected. Prove that
    # detection drives termination by replaying the SAME scene but with an
    # infinite deadline (the old behavior): the planner never escalates because
    # the deadline never crosses. This shows the deadline is the mechanism.
    NoDeadlineScene = supervise.run_supervise_trajectory(
        gate_states=[
            _gate(check_seen=False, signal_elapsed_sec=60, signal_deadline_sec=10**9),
            _gate(check_seen=False, signal_elapsed_sec=600, signal_deadline_sec=10**9),
            _gate(check_seen=False, signal_elapsed_sec=1200, signal_deadline_sec=10**9),
        ],
        retry_budget=supervise.MAX_GATE_RETRIES,
    )
    _check(
        all(s["action"] == "wait" for s in NoDeadlineScene["decisions"]),
        "without the deadline the planner would WAIT forever (proving the deadline is the mechanism)",
        failed,
    )
    _check(
        not NoDeadlineScene["terminal"],
        "without the deadline the replay does NOT terminate (the stall the supervisor fixes)",
        failed,
    )

    # Happy-path replay: agent finishes, check pending → success → merge.
    HappyScene = supervise.run_supervise_trajectory(
        gate_states=[
            _gate(check_state="pending", check_seen=True, signal_elapsed_sec=30),
            _gate(check_state="success", check_seen=True, signal_elapsed_sec=120,
                  merge_state_status="CLEAN"),
            _gate(pr_state="MERGED", check_state="success", check_seen=True,
                  merged_at="2026-07-26T10:00:00Z"),
        ],
        retry_budget=supervise.MAX_GATE_RETRIES,
    )
    happy_actions = [s["action"] for s in HappyScene["decisions"]]
    _check(
        happy_actions == ["wait", "wait", "complete"],
        f"happy-path actions must be [wait, wait, complete] (got {happy_actions})",
        failed,
    )
    _check(HappyScene["terminal"], "happy-path terminates on COMPLETE", failed)
    _check(HappyScene["retries_used"] == 0, "happy-path uses zero retries", failed)

    # =========================================================================
    # AC3: adapter commands — paseo send (REDISPATCH) + ESCALATE signal
    # =========================================================================
    print("supervise_commands (paseo send + ESCALATE signal):")
    cfg = supervise.SuperviseConfig(
        repo="CaicoLeung/skills", chat_room="wf-demo",
        agent_id="agent-11", workspace="issue-11-implement", base_branch="main",
    )

    # COMPLETE → chat post DONE signal (dependents unblock on this).
    complete_cmds = supervise.supervise_commands(
        supervise.plan_supervise(complete, retries_used=0), cfg, task_id="task_11",
        pr_url="https://github.com/CaicoLeung/skills/pull/99",
    )
    _check(
        any(c[:3] == ["paseo", "chat", "post"] for c in complete_cmds),
        "COMPLETE -> chat post (DONE signal)",
        failed,
    )
    sig = supervise.completion_signal("task_11", "https://github.com/CaicoLeung/skills/pull/99",
                                      "2026-07-26T10:00:00Z")
    _check(
        sig.startswith("DONE task_11 pr=") and "merged_at=" in sig,
        f"completion signal shape DONE task_<id> pr=<url> merged_at=<ts> (got {sig!r})",
        failed,
    )
    _check(
        any(sig in c for c in complete_cmds if c[:3] == ["paseo", "chat", "post"]),
        "COMPLETE command must carry the completion signal verbatim",
        failed,
    )

    # WAIT → no command (the supervisor observes again next interval).
    wait_cmds = supervise.supervise_commands(
        supervise.plan_supervise(patient, retries_used=0), cfg, task_id="task_11",
        pr_url="https://github.com/CaicoLeung/skills/pull/99",
    )
    _check(wait_cmds == [], "WAIT -> no command (observe again next interval)", failed)

    # REDISPATCH → paseo send with the specific failure detail.
    dirty_decision = supervise.plan_supervise(dirty, retries_used=0)
    redispatch_cmds = supervise.supervise_commands(
        dirty_decision, cfg, task_id="task_11",
        pr_url="https://github.com/CaicoLeung/skills/pull/99",
    )
    _check(
        any(c[:2] == ["paseo", "send"] for c in redispatch_cmds),
        "REDISPATCH -> paseo send (re-dispatch the leaf)",
        failed,
    )
    send_cmd = next(c for c in redispatch_cmds if c[:2] == ["paseo", "send"])
    _check("agent-11" in send_cmd, "paseo send targets the leaf agent_id", failed)
    _check("issue-11-implement" in send_cmd, "paseo send uses the leaf workspace", failed)
    # The prompt carries the deviation detail VERBATIM (no "fix all" prose).
    prompt_text = send_cmd[-1]
    _check(
        "DIRTY" in prompt_text and "rebase" in prompt_text.lower(),
        "redispatch prompt must carry the specific deviation (DIRTY / rebase)",
        failed,
    )
    for forbidden in ("fix all", "resolve all", "address all"):
        _check(
            forbidden.lower() not in prompt_text.lower(),
            f"redispatch prompt must not carry paraphrase prose {forbidden!r}",
            failed,
        )

    # ESCALATE → paseo chat post (ESCALATE signal) + gh issue comment.
    blocked_decision = supervise.plan_supervise(blocked, retries_used=0)
    escalate_cmds = supervise.supervise_commands(
        blocked_decision, cfg, task_id="task_11", issue_number=11,
        pr_url="https://github.com/CaicoLeung/skills/pull/99",
    )
    _check(
        any(c[:3] == ["paseo", "chat", "post"] for c in escalate_cmds),
        "ESCALATE -> chat post (ESCALATE signal a human consumes)",
        failed,
    )
    _check(
        any(c[:3] == ["gh", "issue", "comment"] for c in escalate_cmds),
        "ESCALATE -> gh issue comment (durable human signal)",
        failed,
    )
    esc_sig = supervise.escalate_signal(
        "task_11", "https://github.com/CaicoLeung/skills/pull/99",
        deviation=supervise.DEVIATION_MERGE_BLOCKED,
        reason="unsatisfiable branch protection",
    )
    _check(
        esc_sig.startswith("ESCALATE task_11 pr="),
        f"escalate signal shape ESCALATE task=<id> pr=<url> ... (got {esc_sig!r})",
        failed,
    )
    _check(
        "merge_blocked" in esc_sig,
        "escalate signal must name the deviation",
        failed,
    )

    # ESCALATE on exhaustion carries the same shape (the cap is in the reason).
    cap_decision = supervise.plan_supervise(
        _gate(check_state="failure", check_seen=True),
        retries_used=supervise.MAX_GATE_RETRIES,
    )
    cap_cmds = supervise.supervise_commands(
        cap_decision, cfg, task_id="task_11", issue_number=11,
        pr_url="https://github.com/CaicoLeung/skills/pull/99",
    )
    _check(
        any(c[:3] == ["gh", "issue", "comment"] for c in cap_cmds),
        "cap-exhaustion ESCALATE also posts a gh issue comment",
        failed,
    )

    # =========================================================================
    # AC6: the planner takes GateState, never agent state. Polling gate state
    # is mandatory; polling agents is not. (Reconciliation is structural —
    # there is no agent-state parameter to poll.)
    # =========================================================================
    print("don't-poll reconciliation (GateState only, no agent state):")
    import inspect
    params = inspect.signature(supervise.plan_supervise).parameters
    _check(
        list(params) == ["state", "retries_used", "retry_budget"],
        f"plan_supervise must take GateState + retry counts only (got {list(params)})",
        failed,
    )
    _check(
        str(params["state"].annotation) == "GateState",
        "state parameter must be annotated GateState (no agent state)",
        failed,
    )

    # =========================================================================
    # Determinism + JSON round-trip + totality
    # =========================================================================
    print("determinism + JSON + totality:")
    a = supervise.plan_supervise(dirty, retries_used=1)
    b = supervise.plan_supervise(dirty, retries_used=1)
    _check(a == b, "plan_supervise is deterministic for equal inputs", failed)
    js = a.to_dict()
    _check(
        js["action"] == supervise.ACTION_REDISPATCH and js["deviation"] == supervise.DEVIATION_MERGE_DIRTY,
        "SuperviseDecision.to_dict round-trips action + deviation",
        failed,
    )

    # Totality: every (mergeStateStatus, check_state, check_seen, elapsed, retries)
    # combination resolves to exactly one action — no fall-through.
    print("totality (no gate state falls through):")
    for pr_state in ("OPEN", "MERGED", "CLOSED"):
        for mss in ("UNKNOWN", "BEHIND", "BLOCKED", "CLEAN", "DIRTY", "HAS_HOOKS", "ODDBALL"):
            for chk in ("", "pending", "success", "failure", "error"):
                for seen in (True, False):
                    for elapsed in (0, 60, 600):
                        state = _gate(
                            pr_state=pr_state, merge_state_status=mss,
                            check_state=chk, check_seen=seen,
                            signal_elapsed_sec=elapsed,
                        )
                        for retries in (0, 1, 2, 5):
                            d = supervise.plan_supervise(state, retries_used=retries)
                            _check(
                                d.action in (
                                    supervise.ACTION_COMPLETE,
                                    supervise.ACTION_WAIT,
                                    supervise.ACTION_REDISPATCH,
                                    supervise.ACTION_ESCALATE,
                                ),
                                f"({pr_state},{mss},{chk!r},seen={seen},t={elapsed},r={retries}) unresolved -> {d.action}",
                                failed,
                            )
                            # Mutual exclusion: only COMPLETE implies merged-and-gated.
                            if d.action == supervise.ACTION_COMPLETE:
                                _check(
                                    state.merged_and_gated,
                                    "COMPLETE only on a genuinely merged-and-gated state",
                                    failed,
                                )

    # =========================================================================
    # Driver through the gateway: run_supervise_round composes gate-state
    # reads via the injected FakeGitHubReader. Mirrors the close-out driver
    # test pattern: the verdict/gate state is DERIVED from fake reads, not
    # supplied — the real supervisor path, testable.
    # =========================================================================
    print("run_supervise_round through the gateway (fake reader):")
    _check(
        isinstance(FakeGitHubReader(), GitHubReader),
        "FakeGitHubReader must satisfy the GitHubReader Protocol",
        failed,
    )

    cfg_sup = loop.DriverConfig(
        repo="CaicoLeung/skills", chat_room="wf-demo",
        leaf_agent_id="agent-11", required_check="validate-skills",
    )

    # MERGED + required check success → COMPLETE; the driver reads
    # pr_merge_state + commit_status_contexts via the fake.
    sha_ok = "deadbeef"
    fake_complete = FakeGitHubReader()
    fake_complete.merge_states[99] = {
        "state": "MERGED", "mergeStateStatus": "CLEAN",
        "mergedAt": "2026-07-26T10:00:00Z", "headRefOid": sha_ok,
    }
    fake_complete.statuses[sha_ok] = [
        {"context": "validate-skills", "state": "success"},
    ]
    rep = loop.run_supervise_round(11, 99, "task_11", cfg_sup, dry_run=True, gh=fake_complete)
    _check(rep["decision"]["action"] == "complete", "fake MERGED + green -> COMPLETE", failed)
    _check(
        rep["gate_state"]["merged_and_gated"] is True,
        "driver reports merged_and_gated=True on COMPLETE",
        failed,
    )
    _check(
        any(c[:3] == ["paseo", "chat", "post"] for c in rep["commands"]),
        "COMPLETE via the gateway posts the DONE signal to chat",
        failed,
    )
    _check(
        any(
            c[:3] == ["paseo", "chat", "post"]
            and "task_11" in c[-1] and "merged_at=" in c[-1]
            for c in rep["commands"]
        ),
        "COMPLETE chat post carries DONE task_11 ... merged_at=...",
        failed,
    )

    # Required check never reported + past the deadline → REDISPATCH (the
    # wf-skills-1 stall, detected). The driver composes the absence-of-signal
    # state from the fake's empty statuses list + the supplied elapsed time.
    sha_missing = "cafef00d"
    fake_missing = FakeGitHubReader()
    fake_missing.merge_states[99] = {
        "state": "OPEN", "mergeStateStatus": "CLEAN", "headRefOid": sha_missing,
    }
    # No statuses[sha_missing]: the check never reported.
    rep_miss = loop.run_supervise_round(
        11, 99, "task_11", cfg_sup,
        signal_elapsed_sec=600, signal_deadline_sec=300,
        retries_used=0, dry_run=True, gh=fake_missing,
    )
    _check(
        rep_miss["decision"]["action"] == "redispatch",
        "absence-of-signal via fake -> REDISPATCH (not silent stall)",
        failed,
    )
    _check(
        rep_miss["decision"]["deviation"] == "check_missing",
        "deviation detected as check_missing",
        failed,
    )
    _check(
        rep_miss["gate_state"]["signal_deadline_exceeded"] is True,
        "driver surfaces signal_deadline_exceeded=True in the report",
        failed,
    )
    _check(
        any(c[:2] == ["paseo", "send"] and "agent-11" in c for c in rep_miss["commands"]),
        "REDISPATCH via the gateway targets the leaf agent (paseo send)",
        failed,
    )
    send_prompt = next(
        c[-1] for c in rep_miss["commands"] if c[:2] == ["paseo", "send"]
    )
    _check(
        "validate-skills" in send_prompt and "check-name-drift" in send_prompt,
        "REDISPATCH prompt names the required check + the check-name-drift pattern",
        failed,
    )

    # BLOCKED mergeStateStatus → ESCALATE at any retry count (genuine deviation).
    sha_blocked = "b10ce0de"
    fake_blocked = FakeGitHubReader()
    fake_blocked.merge_states[99] = {
        "state": "OPEN", "mergeStateStatus": "BLOCKED", "headRefOid": sha_blocked,
    }
    fake_blocked.statuses[sha_blocked] = [
        {"context": "validate-skills", "state": "success"},
    ]
    rep_blk = loop.run_supervise_round(11, 99, "task_11", cfg_sup, dry_run=True, gh=fake_blocked)
    _check(
        rep_blk["decision"]["action"] == "escalate",
        "BLOCKED via fake -> ESCALATE (genuine; never redispatch)",
        failed,
    )
    _check(
        any(c[:3] == ["paseo", "chat", "post"] for c in rep_blk["commands"]),
        "ESCALATE posts an ESCALATE signal to the chat room",
        failed,
    )
    _check(
        any(c[:3] == ["gh", "issue", "comment"] and "11" in c for c in rep_blk["commands"]),
        "ESCALATE posts a durable gh issue comment on the backing issue",
        failed,
    )

    # CLI trajectory replay (the canonical demo path). The check-name-drift
    # scenario from wf-skills-1: three missing observations → redispatch,
    # redispatch, escalate (terminal).
    print("run_supervise_trajectory CLI replay (check-name-drift stall):")
    traj = loop.run_supervise_trajectory(["missing", "missing", "missing"], cfg_sup)
    actions = [s["action"] for s in traj["decisions"]]
    _check(
        actions == ["redispatch", "redispatch", "escalate"],
        f"CLI replay actions must be [redispatch, redispatch, escalate] (got {actions})",
        failed,
    )
    _check(traj["terminal"], "CLI replay terminates (no silent stall)", failed)
    _check(
        traj["retries_used"] == supervise.MAX_GATE_RETRIES,
        f"CLI replay exhausts the retry budget (got {traj['retries_used']})",
        failed,
    )

    # --- github._normalize_check_run: Actions check-runs → unified state -----
    # The supervisor's absence-of-signal detector depends on Actions checks
    # (review-verdict / validate-skills) being "seen". They report as
    # check-runs, NOT legacy status contexts, so the gateway must normalize
    # them into the {context, state} shape loop's gate-build reads.
    print("check-run normalization (Actions → unified state):")
    _check(
        _normalize_check_run(
            {"name": "validate-skills", "status": "completed", "conclusion": "success"}
        ) == {"context": "validate-skills", "state": "success"},
        "completed/success check-run normalizes to state=success (gate passes)",
        failed,
    )
    _check(
        _normalize_check_run(
            {"name": "review-verdict", "status": "completed", "conclusion": "failure"}
        ) == {"context": "review-verdict", "state": "failure"},
        "completed/failure check-run normalizes to state=failure (check_failing)",
        failed,
    )
    _check(
        _normalize_check_run(
            {"name": "ci", "status": "in_progress", "conclusion": None}
        ) == {"context": "ci", "state": "pending"},
        "in_progress check-run normalizes to state=pending (gate converging)",
        failed,
    )
    _check(
        _normalize_check_run(
            {"name": "ci", "status": "completed", "conclusion": "stale"}
        ) == {"context": "ci", "state": "error"},
        "completed/stale check-run normalizes to state=error",
        failed,
    )
    stale_neutral = _normalize_check_run(
        {"name": "ci", "status": "completed", "conclusion": "neutral"}
    )
    _check(
        stale_neutral == {"context": "ci", "state": ""},
        "neutral check-run → state='' (seen but NOT success; WAIT, never pass)",
        failed,
    )
    _check(
        _normalize_check_run({"name": "ci", "status": "queued"})["state"] == "pending",
        "queued check-run normalizes to state=pending",
        failed,
    )
    _check(
        _normalize_check_run({}) == {"context": "", "state": ""},
        "empty check-run payload does not crash (defensive)",
        failed,
    )

    # End-to-end contract: a gate observation over a fake reader whose statuses
    # carry the unified shape (the shape GhCliReader.commit_status_contexts now
    # emits for Actions checks) yields check_seen=True. This pins the contract
    # between the gateway's normalized output and loop's gate-build.
    sha_actions = "feedface"
    fake_actions = FakeGitHubReader()
    fake_actions.merge_states[99] = {
        "state": "OPEN", "mergeStateStatus": "CLEAN", "headRefOid": sha_actions,
    }
    fake_actions.statuses[sha_actions] = [
        _normalize_check_run(
            {"name": "validate-skills", "status": "completed", "conclusion": "success"}
        )
    ]
    rep_act = loop.run_supervise_round(
        11, 99, "task_11", cfg_sup, dry_run=True, gh=fake_actions,
    )
    _check(
        rep_act["gate_state"]["check_seen"] is True,
        "Actions check-run (unified shape) → check_seen=True (no false absence)",
        failed,
    )
    _check(
        rep_act["gate_state"]["check_state"] == "success",
        "Actions check-run success → check_state=success",
        failed,
    )
    if failed:
        print(f"\n{len(failed)} supervisor test(s) failed.", file=sys.stderr)
        return 1
    print("\nAll supervisor planner tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
