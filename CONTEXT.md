# CONTEXT

This repo **is the Loop Driver** — an auxiliary tool that batch-completes the
issues [`mattpocock/skills`](https://github.com/mattpocock/skills) generates.
It is **built on top of** `mattpocock/skills`, not a fork of it:
`mattpocock/skills`'s `to-spec` / `to-tickets` produce GitHub issues; the Loop
Driver drains the ready queue and drives each issue through implement → review
→ fix → merge → close, unattended, via Paseo. Architecture decisions live in
[`docs/adr/`](docs/adr/) — start with
[ADR-0012](docs/adr/0012-reverse-skill-reframe-loop-driver-tool.md) for the
current product framing.

## Glossary

When your output names one of these concepts, use the term as defined here —
don't drift to synonyms.

- **Loop Driver** — the product. The `scripts/loop.py` CLI with four
  subcommands: `route` (one routing turn / T5a), `closeout` (the review → fix →
  merge → close loop / T5b), `supervise` (watch a PR's gate), and `batch`
  (drain the ready queue). Shells out to `paseo` and `gh`.
  _Avoid_: "the skill", "the discipline" (the skill surface was deleted in
  ADR-0012; the driver is the product, not a description of one).

- **Loop Engineering** *(historical)* — the name of the discipline the Loop
  Driver implements: designing the *system* that drives an agent through a
  goal-bounded, verified cycle rather than prompting it turn-by-turn. Retired
  as a product brand in ADR-0012; survives only as the mechanism name inside
  this ADR series and the close-out resolution comment.
  _Avoid_: "automation", "workflow" (too generic — they elide the
  agent-in-the-loop and the per-stage verification that distinguishes a loop
  from a batch job).

- **mattpocock/skills (upstream)** — the repo whose `to-spec` / `to-tickets`
  generate the issues this driver consumes. The relationship is
  upstream-generates → downstream-drives, **not** a fork. There is no selective
  sync of its tree (ADR-0001's "fork" framing was withdrawn in ADR-0012).
  _Avoid_: "the upstream skills", "our fork" (this repo carries no fork of it).

- **Ticket type** — the *kind of work* a ticket represents, set as a label at
  creation and read by the routing core to dispatch. Four values, mirroring
  `wayfinder`'s vocabulary: `research` (AFK — surface a fact), `prototype`
  (HITL — raise fidelity with an artifact), `grilling` (HITL — resolve a
  decision by interview), `task` (code-delivery, AFK — build and merge).
  Orthogonal to the triage readiness *state*: the loop gates on state, then
  dispatches on type.
  _Avoid_: "category" (reserved for bug/enhancement), "kind" (too vague).

- **Close-out gate** — the condition that must hold before a code-delivery
  ticket's PR may merge: the `/code-review` verdict is **pass** — *derived* by
  the driver from the reviewer's severity-tagged findings (no CRITICAL/HIGH +
  per-file coverage floor), never a self-declared token. There is **no CI gate
  by default** (ADR-0013): the driver's local derivation is the gate, and it
  enables `gh pr merge --auto` only on a pass. Applies to code-delivery
  (`task`) tickets only; `research` / `prototype` / `grilling` tickets resolve a
  decision and close without a PR. Universal for code delivery — never
  optional, never bypassed. A consumer who wants independent re-derivation can
  wire `review_verdict.py` into their own CI and set `required_check` to that
  context (an *additional* gate, not a replacement).
  _Avoid_: quality gate (too vague), review (overloaded — means the AI
  `/code-review`, a consumer's CI check, or a human approving review depending
  on context).

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
  configurable (it may not be literally `main`). The restored driver delegates
  worktree creation to Paseo's `--worktree` flag; first-class `tmux` + direct
  `git worktree` seams are deferred (ADR-0012).
  _Avoid_: "main branch" — the base branch is configurable; treat "main branch"
  as a loose synonym, never the literal merge target.

- **modeId / thinkingOptionId** — model-descriptor fields. `modeId` is the
  access mode of a `provider/model`; `thinkingOptionId` maps a reasoning-depth
  choice to a thinking option (omitted when the model has none). The canonical
  descriptor used across the driver is `{ provider, model, modeId }`. Concrete
  values are resolved from the Paseo runtime's provider enumeration.
