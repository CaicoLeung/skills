# Flows

How the skills in this repo compose into end-to-end workflows. Pick your starting
point, follow the arrows. Each step names the skill that owns it, what it
produces, and what feeds the next step.

This repo has three skills, and they layer:

- **[`ticket-workflow-core`](../skills/ticket-workflow-core/SKILL.md)** — the
  *what*. Turns ticket data into a runtime-neutral workflow plan (abstract
  primitives: `EXECUTE`, `DEPENDS_ON`, `GATE`, `SUPERVISE`, …).
- **[`tickets-to-paseo`](../skills/tickets-to-paseo/SKILL.md)** — the *how*.
  Adapter that maps the core's plan onto the Paseo 0.1.110 surface (`paseo run`,
  chat rooms, supervisor).
- **[`loop-engineering`](../skills/loop-engineering/SKILL.md)** — the *driver*.
  Scripts the per-ticket lifecycle deterministically (routing spine + close-out
  loop) and invokes external doing-skills (`/triage`, `/implement`,
  `/code-review`, …) as leaves.

External doing-skills are **not** in this repo. The loop invokes them; it never
carries them ([ADR-0001](./adr/0001-fork-with-selective-sync.md)).

## Start here: pick your starting point

| If you have… | Start at | Ends at |
| --- | --- | --- |
| A code-delivery ticket (`task`) ready to build | [Flow A](#flow-a-code-delivery-task) | merged PR + auto-closed issue |
| A question to investigate (`research`) | [Flow B](#flow-b-research) | findings comment + closed issue |
| A decision to resolve (`grilling`) | [Flow C](#flow-c-grilling) | recorded decision + closed issue |
| Fidelity to raise (`prototype`) | [Flow D](#flow-d-prototype) | linked artifact + closed issue |
| A multi-ticket epic with dependencies | [Flow E](#flow-e-multi-ticket-epic) | DAG executed, every PR merged-and-gated |

Every flow presupposes the ticket is `ready-for-agent`. If it isn't, the loop
routes it through `/triage` first — see [The readiness gate](#the-readiness-gate).

## Flow A: code delivery (`task`)

The happy path — the only flow that produces a PR.

```
ready-for-agent + task
  │
  ▼  loop-engineering (routing half)
/implement  →  PR opened, body carries `Fixes #N`
  │
  ▼  loop-engineering (close-out half)
independent /code-review (secondary model, separate worktree, diff + spec only)
  │
  ▼  scripts/verdict.py — derived verdict (computed, never declared)
pass?  ──yes──▶  loop enables auto-merge  →  GitHub merges (CI green)  →  Fixes #N closes the issue
  │
  no
  ▼
findings handed to the SAME implementer verbatim  →  push  →  re-review
  │
  └─ after 3 non-passing rounds: STUCK_REVIEW (PR unmerged, no auto-close)
```

| Step | Skill | Produces | Feeds next |
| --- | --- | --- | --- |
| Route | `loop-engineering` | a dispatch decision (readiness gate + type) | the implement turn |
| Implement | `/implement` (external) | a PR with `Fixes #N` | the close-out loop |
| Review | `/code-review` (external, independent) | sha-tagged findings | the derived verdict |
| Verdict | `scripts/verdict.py` | pass / fail | merge, or the fix loop |
| Merge + close | `loop-engineering` | merged PR, closed issue | — |

Commands (CI-safe — no agents, no network):

```bash
python3 scripts/loop.py 28 --dry-run                                       # plan the implement turn
python3 scripts/loop.py closeout 29 --pr 99 --outcomes fail,fail,pass      # simulate the close-out
python3 scripts/loop.py closeout 29 --pr 99 --outcomes fail,fail,fail      # → STUCK_REVIEW
```

See [`docs/agents/closeout.md`](./agents/closeout.md) for the close-out shape,
invariants, and demo procedure.

## Flow B: research

```
ready-for-agent + research
  │
  ▼  loop-engineering (type dispatch)
/research subagent (AFK, parallel-safe)
  │
  ▼
findings comment on the issue  →  issue closed (no PR)
```

No PR, no merge, no review gate. The ticket resolves a *fact*, not a change.

## Flow C: grilling

```
ready-for-agent + grilling
  │
  ▼  loop-engineering (type dispatch)
/grilling + /domain-modeling   ←  HITL: the loop PAUSES for the human turn
  │
  ▼  (human answers the interview)
decision recorded  →  issue closed (no PR)
```

The loop never fakes the human's side. It invokes the skill and pauses.

## Flow D: prototype

```
ready-for-agent + prototype
  │
  ▼  loop-engineering (type dispatch)
/prototype   ←  HITL: the loop PAUSES
  │
  ▼
artifact linked on the issue  →  issue closed (no PR)
```

## Flow E: multi-ticket epic

When tickets depend on each other, `ticket-workflow-core` plans the DAG and
`tickets-to-paseo` executes it with verified handoff.

```
epic tickets + DEPENDS_ON edges
  │
  ▼  ticket-workflow-core
workflow plan (EXECUTE / DEPENDS_ON / GATE / SUPERVISE primitives)
  │
  ▼  tickets-to-paseo
Paseo surface: a chat room + one agent per ticket + a supervisor
  │
  ▼  each ticket runs its own flow (A–D above)
  │
  ▼  supervisor posts `DONE task_$id pr=$url` only on merged-and-gated
dependents unblock on VERIFIED work, not agent-finished
```

A dependent's loop does not start until its blocker is **merged-and-gated** (PR
merged AND `validate-skills` green). A stuck blocker freezes only its transitive
dependents — independent tickets proceed. See
[ADR-0006](./adr/0006-supervisor-and-merged-and-gated-completion.md).

## The readiness gate

Every flow above presupposes `ready-for-agent`. The gate is structural —
implement is *unreachable* from any other triage state:

| State | Loop action |
| --- | --- |
| `needs-triage` / unlabeled | invoke `/triage` → re-route |
| `needs-info` | pause; re-triage on the next reporter update |
| `ready-for-agent` | proceed to type dispatch |
| `ready-for-human` | stop — leave for a human |
| `wontfix` | close / skip |

A `ready-for-agent` ticket with **no type label** is itself a triage gap →
`/triage`. Type is never guessed from prose. The two label axes are orthogonal;
see [`docs/agents/ticket-types.md`](./agents/ticket-types.md) and
[`docs/agents/triage-labels.md`](./agents/triage-labels.md).

## One-line summary

> Tickets carry two labels (readiness + type). The loop gates on readiness,
> dispatches on type, and for code delivery drives an independent review to a
> derived verdict before it merges and closes. The core + adapter extend that to
> multi-ticket DAGs with verified handoff.
