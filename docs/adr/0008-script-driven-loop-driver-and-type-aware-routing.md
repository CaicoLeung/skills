# ADR-0008: Script-driven loop driver and type-aware routing

- **Status:** Accepted
- **Date:** 2026-07-24
- **Supersedes:** —
- **Related:** [ADR-0001](./0001-fork-with-selective-sync.md), [ADR-0004](./0004-runtime-neutral-core-plus-adapter.md), [ADR-0006](./0006-supervisor-and-merged-and-gated-completion.md), [ADR-0007](./0007-derived-verdict-and-reviewer-independence.md)

## Context

Two failures recurred in practice:

1. **Skills weren't invoked.** `/triage` was skipped on triage-status tickets;
   `/implement` and `/code-review` fired only when an agent remembered — because
   invocation was the *agent's* responsibility (an optional behavior), not the
   system's.
2. **Orchestration was natural-language.** An agent improvising a sequence from
   a skill is the same unreliable, paraphrase-prone approach Loop Engineering
   exists to replace.

`mattpocock/skills` also routes tickets by **type** (`wayfinder`'s
`research` / `prototype` / `grilling` / `task`) as well as by the triage
readiness **state** — two axes this fork's routing never modeled. This fork
carries only the two orchestration skills (`ticket-workflow-core`,
`tickets-to-paseo`); the doing-skills and routers are upstream-only, and no
type labels exist.

## Decision

**A deterministic orchestrator script is the loop driver; agents are leaves.
The loop routes on two axes — readiness state, then ticket type — dispatching
each type to its (external) skill with a scripted scaffold.** Five parts.

### 1. The loop driver is a script

`scripts/loop.py` executes the state machine: reads labels (`gh`), gates
readiness, dispatches by type, invokes the triage/implement/review turns
(`paseo run --detach`), runs `scripts/verdict.py`, enables auto-merge, closes
the issue. It sleeps/polls between the 10–30 min agent turns — the ADR-0006
supervisor's merged-and-gated polling folds *into* this driver. The **system
drives the agent**; no agent improvises the sequence. This is the faithful
realization of "script, not natural language."

### 2. Two-axis routing

```
ticket claimed
 → readiness gate (triage state):  ready-for-agent?  else invoke /triage; loop back
 → type dispatch (type label):      which skill + ritual?
```

Readiness (the triage state machine) and type are orthogonal label axes; the
loop gates on the first, then dispatches on the second.

### 3. Type dispatch

| Type | Skill (external, invoked) | Resolution ritual | AFK / HITL |
|---|---|---|---|
| `research` | `/research` subagent | findings comment → close | AFK (parallel) |
| `prototype` | `/prototype` | pause → link artifact → close | HITL |
| `grilling` | `/grilling`+`/domain-modeling` | pause → record decision → close | HITL |
| `task` (code) | `/implement`+`/code-review` | PR → derived verdict → merge → close (ADR-0007) | AFK |

Only the AFK types are fully automated; HITL types invoke the skill and **pause
for the human turn** — never faking the human's side (a grilling agent that
answers its own questions has broken HITL).

### 4. Explicit type labels; doing-skills stay external

Type is an **explicit label** (mirroring `wayfinder`'s vocabulary; documented in
`docs/agents/ticket-types.md`), set at ticket creation and read deterministically
— not inferred from prose, since inference is the unreliability being removed.
The doing-skills (`implement`, `/research`, `/prototype`, `/grilling`) **stay
external** in the agent's installed skill library; the loop *invokes* them. This
repo carries only the **dispatcher + mechanical scaffold**, consistent with
ADR-0001's selective-fork principle and with "migrate the routine mechanical
operations" (not the judgment).

### 5. Scope and escalation

Per-ticket lifecycle only; the multi-ticket DAG (`DEPENDS_ON`, chat-room
handoff, supervisor) is unchanged — a dependent's loop simply doesn't start
until its blocker is merged-and-gated. On stuck (`STUCK_REVIEW` after 3 review
rounds, unresolved triage, missing reviewer token), the loop posts to the chat
room *and* a `gh issue comment`, leaves the PR unmerged, and stops — following
the ADR-0006 pattern. It does not auto-close on stuck (only `wontfix` /
`ready-for-human` stop-and-leave).

## Consequences

- **Invocation is structural.** `/triage` cannot be skipped (implement is
  unreachable from a triage-status state); every skill fires because the
  orchestrator invokes it as a leaf.
- **Mechanical ops are scripted; judgment stays as agent turns.** Routing, PR
  creation, verdict, merge, close, and prompt authoring are deterministic; the
  triage *decision*, the *implementation*, and the *review findings* are
  loop-invoked agent work.
- **`loop-engineering` skill is the migration home** for the routine mechanical
  operations — they stop being ad-hoc invocations an agent might skip and become
  stages of this canonical loop.
- **Selective migration.** Only mechanical operations migrate; judgment skills
  stay external and invoked.
- **The fix loop converges or escalates, never loops forever.** A 3-round cap
  with `STUCK_REVIEW` prevents cheating-by-exhaustion.

## Version Implications

- New: `skills/loop-engineering/SKILL.md`, `scripts/loop.py`,
  `docs/agents/ticket-types.md`.
- The `ticket-workflow-core` `GATE` change is recorded in ADR-0007.
- ADR-0006 supervisor semantics fold into the loop driver (no separate
  supervisor agent).
