# CONTEXT

This repo publishes **Loop Engineering** as installable Agent Skills —
stack-agnostic discipline for driving an agent through a verified ticket cycle.
The skills teach the discipline; consumers instantiate it in their own harness.
Architecture decisions live in [`docs/adr/`](docs/adr/).

## Glossary

When your output names one of these concepts, use the term as defined here —
don't drift to synonyms.

- **Skill** — an installable knowledge artifact: a `SKILL.md` plus any sibling
  content (e.g. a prompt template) that an agent consumes. A skill is
  *discipline + contracts*, not a script and not repo-coupled documentation.
  Installed via `npx skills add` (or the host's skill installer); read directly
  from the committed source — no build step.
  _Avoid_: conflating "skill" with the repo's scripts or CI (those are
  infrastructure for *producing* skills, not skills themselves).

- **Adapter** — a skill that maps the runtime-neutral core primitives
  ([`ticket-workflow-core`](skills/ticket-workflow-core/SKILL.md)) to a specific
  runtime surface (e.g. [`tickets-to-paseo`](skills/tickets-to-paseo/SKILL.md)
  maps them to Paseo 0.1.110). A second runtime is a new adapter file, not a
  core change.

- **Loop Engineering** — the practice of designing the *system* that drives an
  agent through a goal-bounded, verified cycle — implement, review, fix, merge,
  close — rather than prompting it turn-by-turn. Mechanical operations are
  encoded as deterministic steps with a verification gate at each stage, not
  free-form natural-language instructions handed off in prose.
  _Avoid_: "automation", "workflow" (too generic — they elide the
  agent-in-the-loop and the per-stage verification that distinguishes a loop
  from a batch job).

- **Reference implementation (retired)** — the Python/Paseo driver that
  previously lived in this repo under `scripts/` and dogfooded the discipline
  end-to-end. Retired in
  [ADR-0011](docs/adr/0011-agent-skill-product-reframe.md); git history is the
  archive. The discipline survives in the skills; verifying it by running is now
  the consumer's (or a future repo's) job.

- **Ticket type** — the *kind of work* a ticket represents, set as a label at
  creation and read by the loop's dispatcher to route the ticket to its skill.
  Four values, mirroring `wayfinder`'s vocabulary: `research` (AFK — surface a
  fact), `prototype` (HITL — raise fidelity with an artifact), `grilling` (HITL
  — resolve a decision by interview), `task` (code-delivery, AFK — build and
  merge). Orthogonal to the triage readiness *state*: the loop gates on state,
  then dispatches on type.
  _Avoid_: "category" (reserved for bug/enhancement), "kind" (too vague).

- **Close-out gate** — the conditions that must all hold before a code-delivery
  ticket's PR may merge: the `/code-review` verdict is **pass** — *derived* from
  the reviewer's severity-tagged findings (no CRITICAL/HIGH + per-file coverage
  floor), never a self-declared token — **and** the host's required CI status
  checks are green. Applies to code-delivery (`task`) tickets only; `research` /
  `prototype` / `grilling` tickets resolve a decision and close without a PR.
  Universal for code delivery — never optional, never bypassed. A human
  approving review is the only optional component; it stacks on the AI and CI
  gates, never replaces them.
  _Avoid_: quality gate (too vague), review (overloaded — means the AI
  `/code-review`, the CI check, or a human approving review depending on
  context).

- **Review round / fix loop** — one iteration of the close-out cycle for a
  `task` PR: an independent review of the current head, followed by the derived
  verdict. On fail, the loop hands the findings to the same implementer
  **verbatim** and re-reviews; a finding is "resolved" only when it disappears
  from the *next* review, never self-declared. The loop is bounded by a 3-round
  cap: a third non-pass escalates `STUCK_REVIEW` (chat + issue comment, PR
  unmerged, no auto-close) rather than looping forever. The loop (never the
  implementer) enables auto-merge only on a pass, and closes via the PR's
  `Fixes #N` trailer plus a resolution comment.
  _Avoid_: "iteration" (too generic), "retry loop" (implies blind retry, not
  verdict-driven).

- **Quota failover** — switching execution to the secondary provider when the
  primary's quota is exhausted, and back again when a quota probe confirms
  restoration. Driven off **real quota signals**, never a fixed calendar
  schedule. Armed only when primary and secondary are on **different providers**
  (quota is tracked per provider, so a shared provider means failover is
  impossible and stays `disabled`).

- **Worktree** — a git worktree branched off the project's base branch, created
  one per ticket as that ticket's isolated workspace. The base branch is
  configurable (it may not be literally `main`).
  _Avoid_: "main branch" — the base branch is configurable; treat "main branch"
  as a loose synonym, never the literal merge target.

- **modeId / thinkingOptionId** — model-descriptor fields. `modeId` is the
  access mode of a `provider/model`; `thinkingOptionId` maps a reasoning-depth
  choice to a thinking option (omitted when the model has none). The canonical
  descriptor used across the skills is `{ provider, model, modeId }`. Concrete
  values are resolved from the runtime's provider enumeration (see
  [`tickets-to-paseo`](skills/tickets-to-paseo/SKILL.md) for the Paseo surface).
