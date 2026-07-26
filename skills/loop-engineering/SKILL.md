---
name: loop-engineering
description: "Loop Engineering — design the system that drives an agent through a goal-bounded, verified ticket cycle (implement → review → fix → merge → close). Mechanical steps scripted; judgment delegated to loop-invoked doing-skills. Runtime-neutral discipline; instantiate in your harness."
version: 0.3.0
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
not free-form natural-language instructions handed off in prose.

This skill teaches the **discipline**. It is runtime-neutral: the scripted
steps are instantiated in your harness (the abstract primitives live in
[`ticket-workflow-core`](../ticket-workflow-core/SKILL.md); a Paseo worked
example in [`tickets-to-paseo`](../tickets-to-paseo/SKILL.md)). Doing-skills
(`/triage`, `/implement`, `/research`, …) stay **external** — the loop
*invokes* them; it never carries them.

> **Scope.** This is a knowledge artifact. A Python/Paseo reference
> implementation previously lived in this repo as `scripts/`; it has been
> retired (see [ADR-0011](../../docs/adr/0011-agent-skill-product-reframe.md)).
> The discipline survives in the three skills.

## The loop drives the agent; agents are leaves

The loop driver is a **script** in your harness. It reads a claimed ticket's
labels, gates readiness, dispatches by type, invokes the triage/implement/
review turns, derives the verdict, enables auto-merge, and closes the issue.
Nothing depends on an agent remembering to call a skill — **invocation is
structural**: the loop *is* the invocation. This is the faithful realization
of "script, not natural language."

## Two-axis routing

A claimed ticket is routed on two **orthogonal** label axes. The loop gates on
the first, then dispatches on the second. The decision is a pure function of
the labels, so it is unit-testable and immune to the natural-language
unreliability Loop Engineering exists to remove.

```
ticket claimed
 → readiness gate (triage state):  ready-for-agent?  else invoke /triage; loop back
 → type dispatch (type label):      which skill + ritual?
```

| Axis | Label set | Consulted |
| --- | --- | --- |
| Readiness state | `needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix` | **first** |
| Ticket type | `research` / `prototype` / `grilling` / `task` | second (only once ready) |

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
| `task` (code) | `/implement` + `/code-review` | PR → derived verdict → merge → close | AFK |

Only the AFK types (`research`, `task`) are fully automated; the HITL types
(`prototype`, `grilling`) invoke their skill and then **pause for the human
turn** — the loop never fakes the human's side of the exchange.

## Scripted vs. judgment boundary

Loop Engineering migrates only the **mechanical** operations out of
natural-language skills into unconditional script steps; the **judgment**
stays as loop-*invoked* agent turns under system-authored prompts.

| Scripted (deterministic) | Judgment (loop-invoked agent turn) |
| --- | --- |
| label reading, routing, turn planning | the triage *decision* |
| the implement prompt + the `Fixes #N` PR body | the *implementation* |
| PR creation scaffold, the review prompt template | the review *findings* |
| the derived verdict (computed from findings, never declared) | — |
| auto-merge enablement, issue close | — |

Because the loop authors every prompt and the close body, the implementer can
neither frame its own review nor author its own close text.

## Code-delivery branch (`task`)

For a `ready-for-agent` + `task` ticket, the loop:

1. Plans an implement turn whose PR body carries `Fixes #N` (auto-closes the
   issue on merge).
2. Invokes `/implement` in a worktree off the base branch with a
   system-authored prompt that instructs the agent to use that body verbatim.
3. Opens a PR whose body carries `Fixes #N`.

### Close-out loop

Once the PR is open, the close-out loop drives review → verdict → fix → merge
→ close:

4. **Invoke the independent reviewer** (loop-invoked, never the implementer):
   secondary model on a **different provider**, separate worktree, **diff +
   spec only** under a fixed, system-authored prompt — five independence axes
   (see [`ticket-workflow-core`](../ticket-workflow-core/SKILL.md#gate)).
5. **Derive the verdict** from the reviewer's sha-tagged findings — computed,
   never declared. `pass = no CRITICAL/HIGH AND every changed file has a
   finding or OK`.
6. **Fix loop.** On fail, hand the findings to the **same implementer**
   *verbatim* (no "resolve all issues" prose); it pushes; the loop re-reviews.
   A finding is "resolved" only when it disappears from the **next** review —
   never self-declared. The loop re-derives the verdict each round, so a
   finding that was not actually fixed reappears and the verdict stays fail.
7. **Cap.** After a bounded number of rounds (default 3) without a pass, the
   loop escalates **`STUCK_REVIEW`** (chat room + an issue comment), leaves
   the PR **unmerged**, and does **not** auto-close. It never silently passes.
8. **Merge + dual close.** On pass, the **loop** (never the implementer)
   enables auto-merge; the host merges when the required status checks are
   green. The issue closes via `Fixes #N`, and the loop posts a resolution
   comment (dual close).

## Scope and escalation

Per-ticket lifecycle only. The multi-ticket DAG (`DEPENDS_ON`, chat-room
handoff, supervisor) is unchanged — a dependent's loop simply does not start
until its blocker is merged-and-gated. On stuck (`STUCK_REVIEW` after the
round cap, unresolved triage, missing reviewer token), the loop posts to the
chat room *and* an issue comment, leaves the PR unmerged, and stops. It does
not auto-close on stuck (only `wontfix` / `ready-for-human` stop-and-leave).

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
- hand review findings to the fixer **verbatim**; "resolved" = disappears from the next review;
- escalate `STUCK_REVIEW` at the round cap — never silently pass;
- enable auto-merge only on a passing derived verdict, and only the loop (never the implementer) merges;
- dual-close: `Fixes #N` auto-close + a loop resolution comment;
- keep doing-skills external (invoked, never carried).

## Version Changes

0.3.0: Reframed as a runtime-neutral knowledge artifact
([ADR-0011](../../docs/adr/0011-agent-skill-product-reframe.md)). Removed all
references to the in-repo Python driver (`scripts/loop.py`, `routing.py`,
`closeout.py`, `verdict.py`), which has been retired. The discipline —
two-axis routing, the scripted-vs-judgment boundary, the close-out loop, the
`STUCK_REVIEW` cap, dual close — is now expressed as stack-agnostic discipline
the consumer instantiates. Primitive shapes live in `ticket-workflow-core`; a
Paseo example in `tickets-to-paseo`.

0.2.0: Close-out half wired (T5b). *(Historical — referenced the now-retired
driver.)*

0.1.0: Routing-half skeleton (T5a). *(Historical.)*
