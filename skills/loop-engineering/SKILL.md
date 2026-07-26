---
name: loop-engineering
description: "Deterministic loop driver for ticket cycles — scripts the routing spine (readiness gate + type dispatch), the close-out loop (review → derived verdict → fix → merge → close), and the supervisor (triage → redispatch/escalate → merged-and-gated) and invokes external doing-skills as leaves (ADR-0008)."
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
not free-form natural-language instructions handed off in prose (see
[`CONTEXT.md`](../../CONTEXT.md), [ADR-0008](../../docs/adr/0008-script-driven-loop-driver-and-type-aware-routing.md)).

This skill is the **migration home** for those routine mechanical operations.
It documents the loop's shape; the executable spine lives in
[`scripts/loop.py`](../../scripts/loop.py) and the pure two-axis router in
[`scripts/routing.py`](../../scripts/routing.py). Doing-skills (`/triage`,
`/implement`, `/research`, …) **stay external** — the loop *invokes* them; it
never carries them (ADR-0001 selective-fork principle).

> **Status.** Routing half (T5a, issue #28), close-out half (T5b, issue #29),
> **and** supervisor half (T5c, issue #11) are wired: readiness gate + type
> dispatch open a PR carrying `Fixes #N`, the close-out loop drives
> independent review → derived verdict → fix → merge → close, and the
> supervisor drives triage (mechanical/transient → redispatch;
> genuine/ambiguous → escalate) → merged-and-gated completion. The pure
> planners are [`scripts/closeout.py`](../../scripts/closeout.py),
> [`scripts/supervise.py`](../../scripts/supervise.py); the I/O driver lives
> in [`scripts/loop.py`](../../scripts/loop.py) (`run_closeout_*`,
> `run_supervise_*`).

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
| supervisor gate observation, the triage classification (`scripts/supervise.py`) | the leaf's *re-dispatch* fix (specific deviation, system-authored) |
| the redispatch prompt + the completion/escalation signal | — |
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
3. Opens a PR whose body carries `Fixes #N` (auto-closes the issue on merge).

### Close-out half (T5b, issue #29)

Once the PR is open, the close-out loop
([`scripts/closeout.py`](../../scripts/closeout.py) planner +
[`scripts/loop.py`](../../scripts/loop.py) driver) drives review → verdict →
fix → merge → close. The decision is a pure function,
[`closeout.plan_closeout(verdict, round)`](../../scripts/closeout.py):

4. **Invoke the independent reviewer** (loop-invoked, never the implementer):
   secondary model on a **different provider**, separate worktree, **diff +
   spec only** under the fixed
   [`review-prompt.md`](../ticket-workflow-core/review-prompt.md) (ADR-0007 §2 —
   five independence axes).
5. **Derive the verdict** from the reviewer's sha-tagged findings
   ([`scripts/verdict.py`](../../scripts/verdict.py), ADR-0007) — computed,
   never declared. `pass = no CRITICAL/HIGH AND every changed file has a
   finding or OK`.
6. **Fix loop.** On fail, hand the findings to the **same implementer**
   *verbatim* ([`closeout.fix_prompt`](../../scripts/closeout.py) — no
   "resolve all issues" prose); it pushes; the loop re-reviews. A finding is
   "resolved" only when it disappears from the **next** review — never
   self-declared. The loop re-derives the verdict each round, so a finding
   that was not actually fixed reappears and the verdict stays fail.
7. **Cap.** After [`closeout.MAX_REVIEW_ROUNDS`](../../scripts/closeout.py) (3)
   rounds without a pass, the loop escalates **`STUCK_REVIEW`** (chat room + a
   `gh issue comment`), leaves the PR **unmerged**, and does **not**
   auto-close. It never silently passes.
8. **Merge + dual close.** On pass, the **loop** (never the implementer)
   enables GitHub auto-merge (`gh pr merge --auto`); GitHub merges when both
   `validate-skills` and `review-verdict` are green. The issue closes via
   `Fixes #N`, and the loop posts a
   [`closeout.resolution_comment`](../../scripts/closeout.py) (dual close).

### Supervisor half (T5c, issue #11)

The close-out loop ends at merge — but merge is necessary, not sufficient.
A merged PR with no check is **not** complete (`wf-skills-1` stall pattern).
The supervisor
([`scripts/supervise.py`](../../scripts/supervise.py) planner +
[`scripts/loop.py`](../../scripts/loop.py) driver) drives the gap between
**agent-finished** (PR open or merged, leaf idle) and **merged-and-gated**
(PR merged AND required check `success`). The decision is a pure function,
[`supervise.plan_supervise(state, retries_used, retry_budget)`](../../scripts/supervise.py).

Each interval the supervisor observes the gate (`gh pr view --json
mergeStateStatus` + `gh api commits/$sha/status`), composes a
`supervise.GateState`, and triages:

| Bucket | Deviations | Action | Bounded? |
| --- | --- | --- | --- |
| **mechanical** | `check_missing`, `merge_dirty`, `merge_behind` | re-dispatch the SAME leaf via `paseo send` with the specific failure | yes |
| **transient** | `check_failing` | re-dispatch the leaf | yes |
| **genuine** | `merge_blocked` (unsatisfiable branch protection) | `ESCALATE` signal (chat + issue) | no |
| **ambiguous** | `unknown` | `ESCALATE` signal | no |

9. **Bounded retry budget.** `supervise.MAX_GATE_RETRIES` (2). A
   mechanical/transient deviation that does not converge after two
   redispatches auto-escalates — the never-wait-forever guarantee (mirrors
   `closeout.MAX_REVIEW_ROUNDS` for the review fix-loop). Genuine/ambiguous
   deviations skip the budget; ambiguity defaults to escalate, never silent
   pass.
10. **Absence-of-signal.** A required check that has not appeared in the
    commit's status contexts within `signal_deadline_sec` (default 300s) is
    `check_missing` (mechanical) — the supervisor redispatches the leaf in
    minutes, not hours. This is the exact `wf-skills-1` stall: renamed
    workflow → required check never appeared → leaf idle → nothing watching.
    Detection is a per-observation test on `check_seen` +
    `signal_elapsed_sec`, not a wall-clock timeout.
11. **Redispatch handoff.** The leaf is re-dispatched with the deviation
    detail verbatim
    ([`supervise.redispatch_prompt`](../../scripts/supervise.py) — no "fix
    all issues" prose, mirroring the GATE fix-loop). The leaf pushes to the
    same branch; the supervisor re-observes the gate on its next interval.
    A deviation is "resolved" only when it disappears from the NEXT
    observation, never by self-declaration.
12. **Completion signal.** Only when the gate is merged-and-gated does the
    supervisor post `DONE task_$id pr=$url merged_at=$ts`. Dependents filter
    on `DONE task_$id pr=` (so `task_1` does not substring-match `task_10`)
    and unblock on this verified signal, not the leaf's agent-finished
    `DONE task_$id`.

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
# Routing half — plan a turn without side effects (CI-safe):
python3 scripts/loop.py 28 --dry-run

# Close-out half — simulate a full trajectory (no agents, no network):
python3 scripts/loop.py closeout 29 --pr 99 --outcomes fail,fail,pass --dry-run
python3 scripts/loop.py closeout 29 --pr 99 --outcomes fail,fail,fail --dry-run  # → STUCK_REVIEW

# Close-out half — drive one live round for a PR (reviewer on a 2nd provider):
python3 scripts/loop.py closeout 29 --pr 99 \
  --secondary-provider openai --secondary-model gpt-4o \
  --reviewer-login "$REVIEWER_LOGIN" --dry-run

# Supervisor half — simulate a trajectory of gate states (no agents, no network):
python3 scripts/loop.py supervise 11 --pr 99 --sequence missing,missing,missing --dry-run  # → REDISPATCH×2 → ESCALATE (wf-skills-1 stall)
python3 scripts/loop.py supervise 11 --pr 99 --sequence failing,failing,merge --dry-run     # → REDISPATCH×2 → COMPLETE (flaky check recovers)
python3 scripts/loop.py supervise 11 --pr 99 --sequence missing,merge --dry-run             # → REDISPATCH → COMPLETE (single redispatch converges)
python3 scripts/loop.py supervise 11 --pr 99 --sequence blocked --dry-run                   # → ESCALATE (genuine, any retry)

# Supervisor half — drive one live round for a PR (re-dispatches via `paseo send`):
python3 scripts/loop.py supervise 11 --pr 99 \
  --chat-room wf-skills-1 --leaf-agent agent-abc --task-id task_11 \
  --retries-used 0 --signal-elapsed-sec 320 --dry-run
```

The planners are pure and unit-tested:

```bash
python3 scripts/test_routing.py     # two-axis router
python3 scripts/test_loop.py        # routing turn-planning (T5a)
python3 scripts/test_closeout.py    # close-out planner (T5b)
python3 scripts/test_supervise.py   # supervisor planner (T5c)
```

See [`docs/agents/closeout.md`](../../docs/agents/closeout.md) for the
close-out demo (claim → triage → implement → review → merge → close), and
[`docs/agents/supervise.md`](../../docs/agents/supervise.md) for the
supervisor demo (gate observation → triage → redispatch / escalate →
merged-and-gated), including the `wf-skills-1` stall replay.

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
- escalate `STUCK_REVIEW` at the 3-round cap — never silently pass;
- enable auto-merge only on a passing derived verdict, and only the loop (never the implementer) merges;
- dual-close: `Fixes #N` auto-close + a loop resolution comment;
- keep doing-skills external (invoked, never carried);
- observe gate state (PR + required check) per interval, never agent internals;
- triage every deviation (mechanical/transient → redispatch the leaf; genuine/ambiguous → escalate);
- bound the retry budget (`MAX_GATE_RETRIES`) and auto-escalate on exhaustion;
- treat absence-of-signal as a deviation (`check_missing` after `signal_deadline_sec`);
- declare completion only on merged-and-gated (PR merged AND check `success`), never on a merged PR with no check;
- re-dispatch the leaf via the adapter's "send to existing agent" verb, not by spawning a new agent.

## Version Changes

0.3.0: Supervisor half wired (T5c, issue #11). Pure planner
`scripts/supervise.py` (`plan_supervise`, `classify_deviation`,
`detect_deviation`, `GateState`, `SuperviseDecision`, `redispatch_prompt`,
`completion_signal`, `escalate_signal`; triage state machine: mechanical/
transient → redispatch leaf, genuine/ambiguous → escalate; bounded retry
budget `MAX_GATE_RETRIES` auto-escalates on exhaustion; absence-of-signal as
first-class deviation `check_missing` after `signal_deadline_sec`). Driver in
`scripts/loop.py` (`run_supervise_round`, `run_supervise_trajectory`,
`supervise` CLI subcommand with `--sequence` for CI-safe replay). Tests in
`scripts/test_supervise.py`; demo in `docs/agents/supervise.md`. ADR-0006 §T1
concretized.

0.2.0: Close-out half wired (T5b, issue #29). Pure planner
`scripts/closeout.py` (`plan_closeout`, `fix_prompt`, `resolution_comment`,
`stuck_message`, `auto_merge_command`, `closeout_plan`; 3-round cap →
`STUCK_REVIEW`; loop-only auto-merge on PASS; dual close). Driver stages in
`scripts/loop.py` (`run_closeout_round`, `run_closeout_trajectory`) invoke the
independent reviewer, hand findings verbatim to the same implementer,
re-derive the verdict each round, and merge + close. Tests in
`scripts/test_closeout.py`; demo in `docs/agents/closeout.md`.

0.1.0: Routing-half skeleton (T5a, issue #28). Documents the two-axis router,
per-type rituals, and the scripted-vs-judgment boundary. Executable spine in
`scripts/loop.py` (pure `plan_turn` + `implement_pr_body` + thin I/O driver
with `--dry-run`). Close-out half (review → verdict → merge → close) stubbed
for T5b.
