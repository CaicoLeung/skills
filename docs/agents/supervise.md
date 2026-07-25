# Supervisor (triage → redispatch / escalate → merged-and-gated)

The supervisor half of the loop driver (T5c, issue #11; ADR-0006 §T1). Once a
`task` ticket's PR is open and the close-out loop has reached merge, the
supervisor closes the last gap — between **agent-finished** (work submitted,
leaf idle) and **merged-and-gated** (work verified: PR merged **and** the
required check `success`). It observes the gate per interval, triages any
deviation, and either **re-dispatches the leaf** (`paseo send`) or **posts an
`ESCALATE` signal** a human consumes. Completion is merged-and-gated only — a
merged PR with no check is **not** complete.

This doc specifies the supervisor's shape, the CLI, the `wf-skills-1` stall
replay, and how to demo it without a live agent or network. See
[ADR-0006](../adr/0006-supervisor-and-merged-and-gated-completion.md) for the
decision (triage state machine, bounded retries, absence-of-signal,
"don't poll" reconciliation), [closeout.md](closeout.md) for the review half
the supervisor follows, and [CONTEXT.md](../../CONTEXT.md) for the glossary
(supervisor, merged-and-gated, absence-of-signal, triage state machine,
bounded retry budget).

## Shape

```
PR merged (close-out half, T5b)               ← OR: PR open but check missing
  │
  ▼
interval k:  loop observes the gate (gh pr view + gh api commits/$sha/status)
             → compose supervise.GateState
             → supervise.plan_supervise(state, retries_used, retry_budget)
                   COMPLETE    (merged AND check=success)
                              → DONE task_$id pr=$url merged_at=$ts
                                dependents unblock on DONE task_$id pr=   (terminal)
                   WAIT        (no deviation, signal deadline not crossed)
                              → no command; observe again next interval
                   REDISPATCH  (mechanical/transient, retries remain)
                              → paseo send leaf with deviation detail
                                leaf pushes → re-observe next interval (k+1)
                                retries_used += 1
                   ESCALATE    (genuine/ambiguous, OR retries exhausted)
                              → paseo chat post ESCALATE + gh issue comment
                                human intervenes; supervisor does NOT auto-close
                                                                                  (terminal)
```

* **Pure planner** — [`scripts/supervise.py`](../../scripts/supervise.py):
  `plan_supervise(state, retries_used, retry_budget)` is total over
  `(deviation, retries_used)` and is the only thing that decides
  complete / wait / redispatch / escalate. Also authors `redispatch_prompt`
  (specific deviation, no "fix all issues" prose), `completion_signal`
  (`DONE task_$id pr=… merged_at=…`), `escalate_signal`
  (`ESCALATE task=… pr=… deviation=…`), and classifies deviations via
  `classify_deviation` (mechanical / transient / genuine / ambiguous).
* **Thin driver** — [`scripts/loop.py`](../../scripts/loop.py):
  `run_supervise_round` (one live observation) and `run_supervise_trajectory`
  (a pure sim over a gate-state sequence). They read PR + check state via
  `gh` (through `GitHubReader`), compose a `GateState`, and translate the
  planner's decision into `paseo send` / `paseo chat post` / `gh issue
  comment` commands.

## Invariants (acceptance criteria of #11)

| AC | Where enforced |
| --- | --- |
| Triage state machine: mechanical/transient → redispatch; genuine/ambiguous → escalate | `supervise.classify_deviation` + `plan_supervise`. `merge_blocked` and `unknown` escalate at any retry count. |
| Bounded retry budget auto-escalates on exhaustion | `supervise.MAX_GATE_RETRIES = 2`; `plan_supervise` returns ESCALATE for mechanical/transient at `retries_used >= retry_budget`. |
| Absence-of-signal is a first-class deviation | `GateState.signal_deadline_exceeded` (`not check_seen and signal_elapsed_sec >= signal_deadline_sec`) → `check_missing`. Not a silent wait. |
| Completion only on merged-and-gated | `GateState.merged_and_gated` requires `pr_state=MERGED` AND `check_state=success`. A merged PR with no check is `check_missing`, not COMPLETE. |
| Re-dispatch via the adapter's "send to existing agent" verb | `supervise_decision_commands` builds `paseo send --agent $leaf` (NOT `paseo run`, which spawns a new agent). `--detach` keeps the supervisor non-blocking. |
| Distinct completion vs escalation signals | `completion_signal` posts `DONE task_$id pr=… merged_at=…`; `escalate_signal` posts `ESCALATE task=… pr=… deviation=…` to chat AND a `gh issue comment`. |
| Ambiguity defaults to escalate, never silent pass | `classify_deviation` returns AMBIGUOUS for any unrecognized state; `plan_supervise` escalates. |
| `wf-skills-1` stall detected within bounded time | The trajectory replay below — `missing,missing,missing` escalates after `MAX_GATE_RETRIES`. |
| Runtime-neutral planner (ADR-0004) | `supervise.py` imports no `paseo`, no `gh`, no agent. All I/O is in `loop.py` via `GitHubReader` + command builders. |

## CLI

```bash
# Simulate a trajectory of gate states (CI-safe — no agents, no network):
python3 scripts/loop.py supervise 11 --pr 99 --sequence missing,missing,missing --dry-run   # → REDISPATCH×2 → ESCALATE (wf-skills-1 stall)
python3 scripts/loop.py supervise 11 --pr 99 --sequence failing,failing,merge --dry-run      # → REDISPATCH×2 → COMPLETE (flaky check recovers)
python3 scripts/loop.py supervise 11 --pr 99 --sequence missing,merge --dry-run              # → REDISPATCH → COMPLETE (single redispatch converges)
python3 scripts/loop.py supervise 11 --pr 99 --sequence dirty,merge --dry-run                # → REDISPATCH → COMPLETE (needs rebase)
python3 scripts/loop.py supervise 11 --pr 99 --sequence blocked --dry-run                    # → ESCALATE (genuine, any retry)

# "Merged PR with no check is NOT complete" is a GateState(pr_state=MERGED,
# check_seen=False) combination — it classifies as check_missing, not COMPLETE.
# Not exposed as a CLI token (the deviation == the `missing` token's); asserted
# directly in scripts/test_supervise.py.

# Drive one live observation for a real PR (re-dispatches via `paseo send`):
python3 scripts/loop.py supervise 11 --pr 99 \
  --chat-room wf-skills-1 --leaf-agent agent-abc --task-id task_11 \
  --retries-used 0 --signal-elapsed-sec 320 --dry-run
```

Each token in `--sequence` is one interval's observed gate state:
`merge` (PR merged, check success — COMPLETE), `wait` (no deviation, deadline
not crossed — WAIT), `missing` (required check has not appeared and the
signal deadline is crossed — `check_missing`), `failing` (check is currently
red — `check_failing`), `dirty` (mergeStateStatus=DIRTY — `merge_dirty`),
`behind` (mergeStateStatus=BEHIND — `merge_behind`), `blocked`
(mergeStateStatus=BLOCKED — `merge_blocked`, genuine). The sim advances
`retries_used` only on REDISPATCH (mirrors closeout counting review rounds,
not polls) and stops at the first terminal decision (COMPLETE or ESCALATE).

## The `wf-skills-1` stall, and how the supervisor catches it

**The stall (real).** A `wf-skills-1` task renamed a GitHub Actions workflow
file. The branch protection rule still required `validate-skills`, but the
renamed workflow no longer emitted that check name — so the check **never
appeared** on the PR's commit. The leaf agent finished and went idle. Nothing
was watching the gap between agent-finished and merged-and-gated, so the PR
sat unmerged indefinitely. There was no signal to wait on; the absence itself
was the failure.

**Why the doc-only T1 did not catch it.** ADR-0006's original T1 had a
wall-clock `max_wait_sec` (default 3600s) — it would eventually fire, but
only after an hour of nothing, and the escalation would name "timeout" rather
than the actual deviation. Worse, it had no re-dispatch path: there was
nothing the supervisor could do but wait for a human.

**The concretization (this issue).** The supervisor now treats
absence-of-signal as a first-class deviation. Each interval it composes a
`GateState` from `commit_status_contexts` (does the required check appear?)
and `signal_elapsed_sec` vs `signal_deadline_sec` (default 300s). If the
check has not appeared within the deadline, the deviation is `check_missing`
(mechanical), and the supervisor re-dispatches the leaf within minutes
carrying the specific failure verbatim:

> Required check `validate-skills` has not reported within the 300s deadline;
> confirm the workflow that emits that context still exists.

After `MAX_GATE_RETRIES = 2` redispatches without convergence, the supervisor
escalates — names `check_missing` as the deviation, posts to chat + issue,
does not auto-close.

## Demo procedure (no live agent)

The supervisor is demoed with the trajectory simulator — no agent, no
network, no `paseo` daemon — exactly as `closeout.md` demos the review loop
with `--outcomes`. The *logic* those live runs would exercise is the pure
planner, asserted in `scripts/test_supervise.py`.

1. **The `wf-skills-1` stall.** `--sequence missing,missing,missing`.
   Expect: `REDISPATCH` (retries=0 → 1), `REDISPATCH` (retries=1 → 2),
   `ESCALATE` (retries=2, budget exhausted). `terminal: true`,
   `retries_used: 2`. The first two decisions carry `paseo send` commands
   with the `check_missing` detail; the third carries `paseo chat post
   ESCALATE …` + `gh issue comment …`. **This is the proof the stall is now
   caught within bounded time.**
2. **Flaky check recovers.** `--sequence failing,failing,merge`. Expect:
   `REDISPATCH` (check_failing), `REDISPATCH` (check_failing), `COMPLETE`
   (merged-and-gated). `terminal: true`, `retries_used: 2`. The COMPLETE
   decision carries `paseo chat post DONE task_11 pr=… merged_at=…`.
3. **Single redispatch converges.** `--sequence missing,merge`. Expect:
   `REDISPATCH` (check_missing, retries 0 → 1), `COMPLETE`. `terminal: true`,
   `retries_used: 1`.
4. **Needs rebase.** `--sequence dirty,merge`. Expect: `REDISPATCH`
   (merge_dirty), `COMPLETE`. `terminal: true`, `retries_used: 1`.
5. **Genuine block escalates immediately.** `--sequence blocked`. Expect:
   `ESCALATE` at `retries_used: 0` — genuine deviations skip the budget.
6. **Merged PR with no check is NOT complete.** Not a CLI token — the
   planner classifies `GateState(pr_state=MERGED, check_seen=False)` as
   `check_missing`, identical to the `missing` token's deviation. Asserted
   in `scripts/test_supervise.py`; the original sin (an agent read a
   blocked-but-passing PR as success) is structural now: `merged_and_gated`
   requires both `pr_state=MERGED` AND `check_state=success`, so a merged
   PR with no check cannot pass.

For example:

```console
$ python3 scripts/loop.py supervise 11 --pr 99 --sequence missing,missing,missing --dry-run
{
  "issue": 11,
  "pr": 99,
  "retries_used": 2,
  "terminal": true,
  "decisions": [
    { "action": "redispatch", "retries_used": 0, "deviation": "check_missing",
      "commands": [["paseo", "send", "--agent", "…", "--worktree", "…", …]], … },
    { "action": "redispatch", "retries_used": 1, "deviation": "check_missing",
      "commands": [["paseo", "send", "--agent", "…", …]], … },
    { "action": "escalate", "retries_used": 2, "deviation": "check_missing",
      "commands": [["paseo", "chat", "post", "wf-…", "ESCALATE task=11 …"],
                   ["gh", "issue", "comment", "11", …]], … }
  ]
}
```

## Honest reconciliation of "don't poll"

The supervisor re-invokes once per interval (`paseo loop` / `paseo schedule`).
That is a poll on **calendar time**, but what it polls is **gate state**
(PR merge state, commit status contexts) — never agent internals (no
`paseo agent inspect`, no chat-room reads of the leaf's working messages).
The distinction is load-bearing (ADR-0006 §4):

* **DON'T poll agents** — the leaf's turn boundaries are surfaced via
  `notifyOnFinish` / the `DONE task_$id` chat-room signal. The supervisor
  does not read agent state.
* **DO poll gate state** — PR merge state and CI status are platform state,
  not agent state. There is no `notifyOnMergedAndGated` edge in Paseo 0.1.110
  (or in GitHub), so observing it requires a read. The interval is the cost
  of that missing edge; bounded retries + signal deadline are the guardrails
  that keep the poll from ever waiting forever.
* **Stuck = absence of signal.** A gate that never reports is itself the
  failure mode (the `wf-skills-1` stall). The signal deadline detects it;
  the doc-only T1's wall clock could not name it.

## Operational notes

* **State storage.** Per-task `retries_used` and `signal_elapsed_sec` live in
  the workflow chat room's history or a workflow-state file — not in the
  daemon. Each supervisor invocation is a thin, idempotent I/O step.
* **Subgraph isolation.** The supervisor computes the blocked subgraph from
  the dependency graph passed at workflow generation and includes it in the
  `ESCALATE` signal's `blocked=[…]`. Dependent tasks filter for their
  blocker; independent tasks proceed.
* **No daemon supervisor.** Paseo 0.1.110 has no `notifyOnMerge` edge and no
  daemon-level supervisor. The adapter implements the supervisor as a
  `paseo loop` re-invoking the stateless planner. A future Paseo edge
  (`notifyOnMergeAndGated`) would let the supervisor subscribe instead of
  poll; the planner and triage logic would be unchanged.
