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

### 5. Tracer bullet scope (T1)

T1 implements the thinnest slice:
- Supervisor role defined (ADR-0006).
- SUPERVISE primitive added to core.
- Paseo adapter implements supervisor via `gh pr view` and `gh api` calls.
- Bounded window: 60s interval, 3600s timeout.
- Escalation: chat-room post.

T2 (DEPENDS_ON on merged-and-gated) and T3 (subgraph scoping) build on T1. T4 (verdict protocol) and T5 (status-check drift guard) run in parallel.

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

- `ticket-workflow-core` v0.3.0 — adds SUPERVISE primitive, updates DEPENDS_ON semantics
- `tickets-to-paseo` v0.4.0 — implements supervisor via gh CLI, bounded triage
