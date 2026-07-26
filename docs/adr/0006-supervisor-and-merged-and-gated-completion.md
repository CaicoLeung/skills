# ADR-0006: Supervisor and merged-and-gated completion

- **Status:** Accepted
- **Date:** 2026-07-24
- **Supersedes:** —
- **Related:** [ADR-0003](./0003-branch-protection-quality-gate.md), [ADR-0005](./0005-auto-merge-via-branch-protection.md), [ADR-0004](./0004-runtime-neutral-core-plus-adapter.md), Issue #10

## Context

The `wf-skills-1` execution exposed a structural gap: the skill fired dependent tasks on **agent-finished** (`DONE` posted at agent turn-end), not on **merged-and-gated** (the PR merged to main AND the close-out gate genuinely passed). Nothing owned the gap between those two states. A stuck gate produced an *absence of signal* that nothing detected — the process stalled until human intervention.

Two states:
- **agent-finished**: Agent posted `DONE` to chat room at turn-end. PR might not exist; gate might not run; PR might not merge.
- **merged-and-gated**: PR merged to base branch AND branch protection gate passed (`validate-skills` CI check green).

The gap is real: agent can finish hours before merge happens. CI may fail; auto-merge may stall; branch protection may block. Dependents unblocking on agent-finished proceed on unverified work.

## Decision

**Supervisor actor observes gate/merge state, declares completion only on merged-and-gated, escalates within bounded window on stuck gates.**

### 1. SUPERVISE primitive (core)

Add to `ticket-workflow-core`:

```
SUPERVISE workflow:
  tasks: [task_ids...]
  base_branch: string
  bounded_window:
    interval_sec: 60
    max_wait_sec: 3600
    escalation_target: workflow_chat_room
  completion_condition:
    type: "merged-and-gated"
    required_check: "validate-skills"
  escalation_action:
    type: "post_stuck_gate_alert"
    format: "STUCK_GATE task=$taskId pr=$pr_url reason=$reason"
```

**Semantics:**
- Supervisor polls PR and CI state (via adapter API) — NOT agent state.
- Completes only when all tasks' PRs are merged AND required CI checks passed.
- Stuck gate detection: after `max_wait_sec`, escalate to chat room.
- Honest reconciliation: polling *gate state* is NOT the "don't poll agents" anti-pattern. That guidance warned against polling agent internals; gates are platform state you MUST observe because stuck = absence of notification.

### 2. DEPENDS_ON fires on merged-and-gated

Update `DEPENDS_ON` semantics:
- Pre-T1: `notifyOnFinish` edge = agent posts `DONE` at turn-end.
- Post-T1: `notifyOnMerge` edge = supervisor posts `DONE task_$taskId pr=$pr_url` only after merged-and-gated.

Adapters map to available primitives:
- Paseo 0.1.110 has no `notifyOnMerge` edge → supervisor posts to chat room.
- Future runtimes with daemon edges → wire to `notifyOnMerge`.

### 3. Bounded triage window

Supervisor checks every `interval_sec` (default 60s). If task not merged-and-gated within `max_wait_sec` (default 3600s = 1 hour), escalate:
```
paseo chat post "wf-$workflowId" "STUCK_GATE task=$taskId pr=$pr_url reason=timeout_after_${max_wait_sec}s"
```

Human sees alert, investigates:
- PR blocked by failing CI?
- Auto-merge disabled unexpectedly?
- Branch protection misconfigured?

Supervisor continues polling; does NOT abandon. Human fix allows gate to proceed; supervisor detects merge and posts completion.

### 4. Honest reconciliation with "don't poll agents"

Original guidance (CONTEXT.md): *"Agents are asynchronous (10–30+ minutes); do not poll, rely on completion notifications."*

This referred to **agent internals** — polling agent CPU/turn state is wrong. But **gate state** (PR merge status, CI checks) MUST be observed because:
- A stuck gate is by definition an *absence of notification*.
- Platform state is external, not agent internals.
- You cannot receive "merge didn't happen" notification — you must observe and timeout.

**Clarified guidance:**
- DON'T poll agents (use `notifyOnFinish` / chat-room signals).
- DO poll gate state (PR/CI) via platform API — supervisor's job.
- Stuck = absence of signal; bounded window is the only way to detect it.

### 5. Tracer bullet (T1) — concretized (issue #11)

The original T1 slice (supervisor role + SUPERVISE primitive + bounded-window
escalation) shipped as documentation. **Issue #11** concretized it into a
runnable tracer bullet that closes the loop and catches the
`wf-skills-1` stall. The concretization adds three things the doc-only T1
lacked:

1. **A triage state machine** (§6 below) — the supervisor classifies each
   deviation into mechanical/transient (re-dispatch the leaf) vs.
   genuine/ambiguous (escalate). The doc-only T1 had only a wall-clock
   timeout; it could not tell a flaky rebase from an unsatisfiable protection
   rule, and it had no re-dispatch path at all.
2. **A bounded retry budget** (`MAX_GATE_RETRIES`) that auto-escalates on
   exhaustion — the never-wait-forever guarantee. The doc-only T1's
   `max_wait_sec` was an informational wall clock, not a per-deviation cap.
3. **Absence-of-signal as a first-class deviation** (`check_missing`) — a
   required check that has not reported within `signal_deadline_sec` is a
   deviation, not a silent wait. This is the exact `wf-skills-1` stall:
   renamed workflow → required check never appeared → leaf idle → nothing
   watching. The doc-only T1's wall clock would eventually fire, but only
   after a full hour of nothing; the signal deadline fires in minutes and
   names the deviation.

The pure planner is `scripts/supervise.py` (`plan_supervise`,
:class:`GateState`, :class:`SuperviseDecision`); the thin I/O driver is
`scripts/loop.py` (`run_supervise_round`, `run_supervise_trajectory`, the
`supervise` CLI subcommand). The supervisor surface is a `paseo loop` /
`paseo schedule` re-invoking the stateless planner once per interval — no
daemon supervisor exists in Paseo 0.1.110.

T2 (DEPENDS_ON on merged-and-gated) and T3 (subgraph scoping) build on T1.

### 6. Triage state machine (T1 concretization — issue #11)

Every observed deviation maps to exactly one triage bucket, and the bucket
decides the action:

| Bucket | Deviations | Action | Bounded? |
| --- | --- | --- | --- |
| **mechanical** | `check_missing`, `merge_dirty`, `merge_behind` | re-dispatch the SAME leaf via `paseo send` with the specific failure | yes — `MAX_GATE_RETRIES` |
| **transient** | `check_failing` (currently red — could be flaky or real) | re-dispatch the leaf | yes — `MAX_GATE_RETRIES` |
| **genuine** | `merge_blocked` (unsatisfiable branch protection) | `ESCALATE` signal | no — escalate at any retry |
| **ambiguous** | `unknown` (unrecognized state) | `ESCALATE` signal | no — escalate at any retry |

**Bounded retry budget.** `MAX_GATE_RETRIES = 2`. A mechanical/transient
deviation that does not converge after two redispatches auto-escalates — the
cap is the never-wait-forever guarantee. Genuine/ambiguous deviations skip
the budget entirely (the leaf cannot fix them; no amount of redispatch will
unblock an unsatisfiable protection rule). The driver advances
`retries_used` per executed REDISPATCH.

**Absence-of-signal detection.** A required check that has not appeared in
the commit's status contexts within `signal_deadline_sec` (default 300s) is
`check_missing`. This is NOT the wall-clock `max_wait_sec` — it is a
per-observation test on `check_seen` + `signal_elapsed_sec`. Detection is
what makes the `wf-skills-1` stall surface: the planner's `WAIT` action
becomes `REDISPATCH` (then `ESCALATE`) instead of looping forever.

**Ambiguity defaults to escalate.** The original sin (an agent read a
blocked-but-passing PR as success) is structural now: `unknown` deviations
and `BLOCKED` merge states escalate immediately, never silently pass. A
merged PR with no check is likewise NOT complete (`merged_and_gated` requires
both `pr_state=MERGED` AND `check_state=success`).

**Re-dispatch handoff.** The leaf is re-dispatched via the adapter's
"send to existing agent" verb (`paseo send --agent $leaf`) carrying the
specific deviation detail verbatim — no "fix all issues" prose (mirrors the
GATE fix-loop contract, ADR-0007). The leaf pushes; the supervisor
re-observes the gate on its next interval. A deviation is "resolved" only
when it disappears from the NEXT observation, never by the leaf's
self-declaration.

## Consequences

- **Completion is verified, not assumed.** Dependents unblock only after merged-and-gated.
- **Stuck gates surface, not stall.** Bounded window ensures human sees alerts.
- **Platform state IS observable.** Supervisor polls PR/CI via API; this is correct pattern.
- **Two-phase completion:** agent-finished (work submitted) → merged-and-gated (work verified). Supervisor owns the second phase.
- **Adapter maps to platform APIs.** Paseo adapter uses `gh` CLI; future adapters use their git host's API.

## Acceptance Criteria (from issue #10 T1)

- ✅ Supervisor role defined in ADR-0006.
- ✅ SUPERVISE primitive added to `ticket-workflow-core`.
- ✅ `tickets-to-paseo` implements supervisor via `gh pr view` + `gh api`.
- ✅ Bounded triage: 60s interval, 3600s timeout, escalate to chat room.
- ✅ Honest reconciliation documented: polling gate state ≠ polling agents.
- ✅ Completion declared only on merged-and-gated (PR merged + CI green).

## Acceptance Criteria (from issue #11 — T1 concretization)

- ✅ Triage state machine implemented (`scripts/supervise.py: classify_deviation`, `plan_supervise`): mechanical/transient → redispatch, genuine/ambiguous → escalate.
- ✅ Bounded retry budget (`MAX_GATE_RETRIES=2`) that auto-escalates on exhaustion.
- ✅ Absence-of-signal as a first-class deviation (`check_missing`, `signal_deadline_sec` default 300s).
- ✅ Re-dispatch via `paseo send` to the existing leaf (not `paseo run`).
- ✅ Distinct completion vs escalation signals (`DONE task_$id pr=… merged_at=…` / `ESCALATE task=… pr=… deviation=…`).
- ✅ `wf-skills-1` check-name-drift stall replayable and detected (`loop.py supervise --sequence … --dry-run`).
- ✅ Runtime-neutral pure planner + thin I/O driver (ADR-0004 boundary preserved).
- ✅ "Don't poll" reconciliation documented in §4 (polling *gate state* ≠ polling *agent internals*).

## Adapter Implementation Notes (Paseo)

Paseo adapter supervisor implementation:
```bash
# Poll PR state
gh pr view "$pr_number" --json state,mergeable,mergedAt,headRefOid -q '.state'

# Poll CI status
gh api "repos/OWNER/REPO/commits/$headRefOid/status" \
  --jq '.statuses[] | select(.context=="validate-skills") | .state'

# Completion condition:
# - PR state = "MERGED"
# - CI check = "success"
# - mergedAt timestamp included for completion signal

# Escalation on stuck gate:
paseo chat post "wf-$workflowId" \
  "STUCK_GATE task=$taskId pr=$pr_url reason=$reason"
```

## Version Implications

- `ticket-workflow-core` v0.3.0 (original T1) — adds SUPERVISE primitive, updates DEPENDS_ON semantics. **v0.7.0** (issue #11) — SUPERVISE primitive concretized (triage state machine, bounded retries, absence-of-signal); pure planner in `scripts/supervise.py`.
- `tickets-to-paseo` v0.4.0 (original T1) — implements supervisor via gh CLI, bounded triage. **v0.7.0** (issue #11) — SUPERVISE mapping concretized (`paseo loop` drives `loop.py supervise`; `paseo send` redispatch; `ESCALATE` signal to chat + issue).
- `loop-engineering` v0.3.0 (issue #11) — supervisor half documented (planner/driver split, token vocabulary, bounded retries, replay harness).
