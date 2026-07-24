---
name: loop-engineering
description: "Deterministic loop driver for ticket cycles — scripts the routing spine (readiness gate + type dispatch) and invokes external doing-skills as leaves (ADR-0008)."
version: 0.1.0
requires:
  - project
  - tickets
produces:
  - turns
  - prs
---

# Loop Engineering

Loop Engineering is the practice of designing the **system** that drives an
agent through a goal-bounded, verified cycle — implement, review, fix, merge,
close — rather than prompting it turn-by-turn. Routines are mechanical
operations encoded as scripted steps with a verification gate at each stage,
not free-form natural-language instructions handed off in prose (see
[`CONTEXT.md`](../../CONTEXT.md), [ADR-0008](../../docs/adr/0008-script-driven-loop-driver-and-type-aware-routing.md)).

This skill is the **migration home** for those routine mechanical operations.
It documents the loop's shape; the executable spine lives in
[`scripts/loop.py`](../../scripts/loop.py) and the pure two-axis router in
[`scripts/routing.py`](../../scripts/routing.py). Doing-skills (`/triage`,
`/implement`, `/research`, …) **stay external** — the loop *invokes* them; it
never carries them (ADR-0001 selective-fork principle).

> **Status.** This is the *routing half* (T5a, issue #28): readiness gate +
> type dispatch + the implement turn that opens a PR carrying `Fixes #N`. The
> close-out half — independent review → derived verdict → fix loop → merge →
> close — is T5b (issue #29) and is stubbed below, not yet wired.

## The loop drives the agent; agents are leaves

The loop driver is a **script** (`scripts/loop.py`). It reads a claimed
ticket's labels (`gh`), gates readiness, dispatches by type, invokes the
triage/implement/review turns (`paseo run --detach`), runs the verdict script
(`scripts/verdict.py`, ADR-0007), enables auto-merge, and closes the issue.
Nothing depends on an agent remembering to call a skill — **invocation is
structural**: the loop *is* the invocation. This is the faithful realization
of "script, not natural language."

## Two-axis routing

A claimed ticket is routed on two **orthogonal** label axes. The loop gates on
the first, then dispatches on the second. The decision is a pure function,
[`routing.route(labels)`](../../scripts/routing.py), so it is unit-testable and
immune to the natural-language unreliability Loop Engineering exists to remove.

```
ticket claimed
 → readiness gate (triage state):  ready-for-agent?  else invoke /triage; loop back
 → type dispatch (type label):      which skill + ritual?
```

| Axis | Label set | Consulted | Source |
| --- | --- | --- | --- |
| Readiness state | `needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix` | **first** | [triage-labels.md](../../docs/agents/triage-labels.md) |
| Ticket type | `research` / `prototype` / `grilling` / `task` | second (only once ready) | [ticket-types.md](../../docs/agents/ticket-types.md) |

### Readiness gate (enforced, not advisory)

The gate is structural — implement is **unreachable** from a triage status:

| State | Loop action |
| --- | --- |
| `needs-triage` / unlabeled | invoke `/triage` → re-route |
| `needs-info` | pause; re-triage on the next reporter update |
| `ready-for-agent` | proceed to type dispatch |
| `ready-for-human` | stop — leave for a human |
| `wontfix` | close / skip |

A `ready-for-agent` ticket with **no type label** is itself a triage gap (the
type was never assigned) → `/triage`. Dispatch stays deterministic, never
guessed from prose.

### Type dispatch

| Type | Skill (external, invoked) | Resolution ritual | AFK / HITL |
| --- | --- | --- | --- |
| `research` | `/research` subagent | findings comment → close | AFK (parallel) |
| `prototype` | `/prototype` | pause → link artifact → close | HITL |
| `grilling` | `/grilling` + `/domain-modeling` | pause → record decision → close | HITL |
| `task` (code) | `/implement` + `/code-review` | PR → derived verdict → merge → close (ADR-0007) | AFK |

Only the AFK types (`research`, `task`) are fully automated; the HITL types
(`prototype`, `grilling`) invoke their skill and then **pause for the human
turn** — the loop never fakes the human's side of the exchange.

## Scripted vs. judgment boundary

Loop Engineering migrates only the **mechanical** operations out of
natural-language skills into unconditional script steps; the **judgment**
stays as loop-*invoked* agent turns under system-authored prompts.

| Scripted (deterministic) | Judgment (loop-invoked agent turn) |
| --- | --- |
| label reading (`gh`), routing, turn planning | the triage *decision* |
| the implement prompt + the `Fixes #N` PR body | the *implementation* |
| PR creation scaffold, the review prompt template | the review *findings* |
| the derived verdict (`scripts/verdict.py`, ADR-0007) | — |
| auto-merge enablement, issue close | — |

Because the loop authors every prompt and the close body, the implementer can
neither frame its own review (ADR-0007) nor author its own close text.

## Code-delivery branch (`task`)

For a `ready-for-agent` + `task` ticket, the loop:

1. Plans an implement turn whose PR body is
   [`loop.implement_pr_body(N)`](../../scripts/loop.py) → `Fixes #N`.
2. Invokes `/implement` (`paseo run --detach`) in a worktree off the base
   branch with a system-authored prompt that instructs the agent to use that
   body verbatim.
3. **(this slice ends here — PR opened.)** The close-out half below is T5b.

### Close-out half (T5b, issue #29 — stubbed, not yet wired)

> 4. Invoke the **independent** reviewer (loop-invoked, secondary model on a
>    different provider, separate worktree, diff + spec only) under a fixed
>    system-authored prompt (ADR-0007).
> 5. Hand the reviewer's structured findings to the **same implementer**
>    verbatim (no "resolve all issues" prose); re-review until the derived
>    verdict passes or the **3-round cap** hits (`STUCK_REVIEW`: chat + issue
>    comment, PR unmerged, no auto-close).
> 6. On pass, the **loop** (never the implementer) enables auto-merge; GitHub
>    merges when both `validate-skills` and `review-verdict` are green.
> 7. The issue closes via `Fixes #N` plus a loop resolution comment.

## Scope and escalation

Per-ticket lifecycle only. The multi-ticket DAG (`DEPENDS_ON`, chat-room
handoff, supervisor) is unchanged (ADR-0006) — a dependent's loop simply does
not start until its blocker is merged-and-gated. On stuck
(`STUCK_REVIEW` after 3 rounds, unresolved triage, missing reviewer token), the
loop posts to the chat room *and* a `gh issue comment`, leaves the PR unmerged,
and stops. It does not auto-close on stuck (only `wontfix` / `ready-for-human`
stop-and-leave).

## Running the driver

```bash
# Plan a turn without side effects (CI-safe):
python3 scripts/loop.py 28 --dry-run

# Drive one routing turn for a claimed ticket:
python3 scripts/loop.py 28
```

The turn planner is pure and unit-tested:

```bash
python3 scripts/test_loop.py        # turn-planning (this slice)
python3 scripts/test_routing.py     # two-axis router
```

## Inputs

```json
{
  "project": "...",
  "tickets": [{ "number": 28, "labels": ["ready-for-agent", "task"] }]
}
```

## Outputs

```json
{
  "issue": 28,
  "turn": { "action": "dispatch", "skill": "/implement + /code-review", "mode": "AFK", "opens_pr": true, "pr_body": "Fixes #28\n…" },
  "status": "implement turn invoked; PR opened (Fixes #N)"
}
```

## Requirements

The loop must:

- enforce the readiness gate — implement unreachable from a triage status;
- dispatch by ticket type once readiness clears;
- for `task`, open a PR whose body carries `Fixes #N`;
- keep doing-skills external (invoked, never carried);
- escalate, not silently pass, when the fix loop exhausts its cap (T5b).

## Version Changes

0.1.0: Routing-half skeleton (T5a, issue #28). Documents the two-axis router,
per-type rituals, and the scripted-vs-judgment boundary. Executable spine in
`scripts/loop.py` (pure `plan_turn` + `implement_pr_body` + thin I/O driver
with `--dry-run`). Close-out half (review → verdict → merge → close) stubbed
for T5b.
