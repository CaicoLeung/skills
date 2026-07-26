# CONTEXT

Glossary of the domain terms this repo's skills already use. When your output
names one of these concepts, use the term as defined here — don't drift to
synonyms. Architecture decisions live in [`docs/adr/`](docs/adr/).

## Glossary

- **Loop Engineering** — the practice of designing the *system* that drives an
  agent through a goal-bounded, verified cycle — implement, review, fix, merge,
  close — rather than prompting it turn-by-turn. Routines are mechanical
  operations encoded as scripted steps with a verification gate at each stage,
  not free-form natural-language instructions handed off in prose.
  _Avoid_: "automation", "workflow" (too generic — they elide the
  agent-in-the-loop and the per-stage verification that distinguishes a loop
  from a batch job).
- **Paseo daemon** — the local supervisor process that owns agent lifecycle,
  state, and the WebSocket the desktop/mobile clients consume. Agents are
  asynchronous (10–30+ minutes); do not poll, rely on completion notifications.
  Conventional defaults (confirm at runtime via `paseo daemon status`): listens
  on `127.0.0.1:6767`, home `~/.paseo`.

- **Worktree** — a git worktree branched off the project's base branch, created
  one per ticket as that agent's isolated workspace. Base branch resolved from
  `inputs.metadata.baseBranch`, else the repo default branch.
  _Avoid_: "main branch" — the base branch is configurable and may not be
  literally `main`; treat "main branch" as a loose synonym, never the literal
  merge target.

- **Agent / subagent** — a Paseo agent executing a skill prompt (e.g.
  `/implement`). Created with `relationship: { kind: "subagent" }` inside an
  existing workspace; one agent per ticket. `create_agent` is the submit — the
  daemon then owns the async lifecycle.

- **notifyOnFinish edge** — a per-edge dependency attribute that does two
  things: gates a dependent's start (the daemon holds it until all its blockers
  finish) **and** emits the completion notification clients consume. Ticket
  dependencies are preserved by declaring these edges up-front, not by delaying
  agent creation.

- **Ticket type** — the *kind of work* a ticket represents, set as a label at
  creation and read by the loop's dispatcher to route the ticket to its skill.
  Four values, mirroring `wayfinder`'s vocabulary: `research` (AFK — surface a
  fact), `prototype` (HITL — raise fidelity with an artifact), `grilling` (HITL
  — resolve a decision by interview), `task` (code-delivery, AFK — build and
  merge). Orthogonal to the triage readiness *state*: the loop gates on state,
  then dispatches on type.
  _Avoid_: "category" (reserved for bug/enhancement), "kind" (too vague).

- **Close-out gate** — the conditions that must all hold before a code-delivery
  ticket's PR may merge: the `/code-review` verdict is **pass** —
  *script-derived* from the reviewer's severity-tagged findings (no
  CRITICAL/HIGH + per-file coverage floor), never a self-declared token —
  **and** the required CI status checks (`validate-skills`, `review-verdict`)
  are green. Applies to code-delivery (`task`) tickets only; `research` /
  `prototype` / `grilling` tickets resolve a decision and close without a PR.
  Universal for code delivery — never optional, never bypassed. A human
  approving review is the only optional component, toggled per the merge
  setting; it stacks on the AI and CI gates, never replaces them.
  _Avoid_: quality gate (too vague), review (overloaded — means the AI
  `/code-review`, the CI check, or a human approving review depending on
  context)

- **Review round / fix loop** — one iteration of the close-out cycle for a
  `task` PR: an independent review (T4) of the current head, followed by the
  derived verdict (T1/T3). On fail, the loop hands the findings to the same
  implementer **verbatim** and re-reviews; a finding is "resolved" only when
  it disappears from the *next* review, never self-declared. The loop is
  bounded by a 3-round cap (`MAX_REVIEW_ROUNDS`): a third non-pass escalates
  `STUCK_REVIEW` (chat + issue comment, PR unmerged, no auto-close) rather
  than looping forever. The loop (never the implementer) enables auto-merge
  only on a pass, and closes via the PR's `Fixes #N` trailer plus a resolution
  comment. _Avoid_: "iteration" (too generic), "retry loop" (implies blind
  retry, not verdict-driven).

- **Quota failover** — switching execution to the secondary provider when the
  primary's quota is exhausted, and back again when a quota probe confirms
  restoration. Driven off **real quota signals**, never a fixed calendar
  schedule. Armed only when primary and secondary are on **different providers**
  (quota is tracked per provider, so a shared provider means failover is
  impossible and stays `disabled`).

- **modeId / thinkingOptionId** — model-descriptor fields resolved from the live
  Paseo enumeration (`paseo provider ls` → `paseo provider models <p> --thinking`).
  `modeId` is the access mode of a `provider/model`; `thinkingOptionId` maps a
  reasoning-depth choice to a thinking option (omitted when the model has none).
  The canonical descriptor used everywhere is `{ provider, model, modeId }`.

- **Supervisor** — the role that closes the gap between **agent-finished**
  (work submitted, leaf idle) and **merged-and-gated** (work verified). For
  each task's PR the supervisor observes gate state — PR merge state via
  `gh pr view`, the required check's status via `gh api commits/$sha/status`
  — never agent internals — and applies the triage state machine below.
  Runtime-neutral core is `scripts/supervise.py: plan_supervise`; the thin
  I/O driver is `loop.py supervise` (`run_supervise_round`,
  `run_supervise_trajectory`). In Paseo 0.1.110 the supervisor surface is a
  `paseo loop` / `paseo schedule` re-invoking the stateless planner once per
  interval (no daemon supervisor exists).
  _Avoid_: "watcher" (implies idle polling of agents — supervisor polls gate
  state, not agents), "monitor" (same), "cron job" (the `paseo loop` is the
  cron-like surface; the supervisor is the decision logic).

- **Merged-and-gated completion** — a task is complete only when **both** hold:
  the PR's state is `MERGED` **and** the required CI check (`validate-skills`,
  `review-verdict`) reported `success`. A merged PR with no check is **NOT**
  complete (the `wf-skills-1` stall pattern). The supervisor posts the
  completion signal (`DONE task_$id pr=$url merged_at=$ts`) only at this
  point; dependents filter on `DONE task_$id pr=` so they unblock on the
  verified signal, not the leaf's agent-finished `DONE task_$id`.
  _Avoid_: "merged" (necessary but insufficient — elides the check), "done"
  (overloaded — also means agent-finished).

- **Triage state machine** — the supervisor's per-observation decision logic.
  Every deviation maps to exactly one bucket, and the bucket picks the action:
  `mechanical` (`check_missing`, `merge_dirty`, `merge_behind`) and
  `transient` (`check_failing`) → re-dispatch the SAME leaf via `paseo send`
  with the specific failure (bounded); `genuine` (`merge_blocked`,
  unsatisfiable branch protection) and `ambiguous` (`unknown`) → escalate at
  any retry. Ambiguity defaults to escalate, never silent pass. Implemented
  by `scripts/supervise.py: classify_deviation`, `detect_deviation`,
  `plan_supervise`.
  _Avoid_: "policy" (too generic), "rules engine" (no dynamic registration).

- **Bounded retry budget** — `MAX_GATE_RETRIES = 2`. A mechanical/transient
  deviation that does not converge after two redispatches auto-escalates —
  the never-wait-forever guarantee. Genuine/ambiguous deviations skip the
  budget (the leaf cannot fix them; no amount of redispatch unblocks an
  unsatisfiable protection rule). The driver advances `retries_used` per
  executed REDISPATCH, mirroring `closeout.MAX_REVIEW_ROUNDS = 3` for the
  review fix-loop.
  _Avoid_: "retry count" (a count is not a budget; the budget has a fixed
  cap and exhausts).

- **Absence-of-signal** — a first-class supervisor deviation, distinct from
  "still waiting". A required check that has not appeared in the commit's
  status contexts within `signal_deadline_sec` (default 300s) is
  `check_missing` (mechanical) — the supervisor re-dispatches the leaf within
  bounded time rather than waiting a full hour. This is the exact
  `wf-skills-1` stall: a renamed workflow meant the required check never
  appeared, the leaf went idle, and nothing watched. Detection is a
  per-observation test on `check_seen` + `signal_elapsed_sec`, not a
  wall-clock timeout.
  _Avoid_: "timeout" (a wall clock; absence-of-signal is a test on observed
  state, and is much faster than the wall-clock `max_wait_sec`).
