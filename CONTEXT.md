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
