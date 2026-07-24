# ADR-0007: Derived verdict and reviewer independence

- **Status:** Accepted
- **Date:** 2026-07-24
- **Supersedes:** —
- **Related:** [ADR-0003](./0003-branch-protection-quality-gate.md), [ADR-0004](./0004-runtime-neutral-core-plus-adapter.md), [ADR-0005](./0005-auto-merge-via-branch-protection.md), [ADR-0006](./0006-supervisor-and-merged-and-gated-completion.md)

## Context

The close-out `/code-review` was enforced by two layers: a **prompt-contract
trigger** (the agent is *told* to run `/code-review` and emit
`VERDICT pass|fail`) and a **branch-protection block** (ADR-0003, requiring the
`validate-skills` CI check). The block was real; the trigger was advisory — and
`implement` (upstream) instructs the agent to *"use /code-review to review the
work,"* so the **implementing agent both performs the work and invokes and
frames its own review.**

Two injection points made the verdict forgeable:

1. **The verdict line** — the reviewer is asked to *declare* `VERDICT pass`. A
   declaration can be instructed into existence ("append Pass").
2. **The review prompt** — whoever invokes the review authors its framing
   ("report only LOW/MEDIUM").

Branch protection only checked `validate-skills` (frontmatter validity) — it
never evaluated the code-review verdict. So the code-quality gate was advisory
in practice: an agent that appended "Pass" passed.

## Decision

**The verdict is computed, never declared; the reviewer is independent of the
implementer; enforcement is a CI status check the implementer cannot reach.**
Four parts.

### 1. Derived verdict (core)

The `GATE` primitive in `ticket-workflow-core` drops the self-declared
`VERDICT pass|fail` line. The reviewer emits **only structured findings**
across the two `/code-review` axes (Standards, Spec):

```
[file:line]: SEVERITY: summary      # SEVERITY ∈ CRITICAL|HIGH|MEDIUM|LOW
```

The verdict is **derived by a script** (`scripts/verdict.py`):
`pass = no CRITICAL or HIGH finding across either axis, AND every changed file
has a finding or an explicit OK` (the coverage floor). There is no verdict
token for anyone to append. This is a runtime-neutral rule, so it lives in the
core; the *enforcement mechanism* (the CI check) lives in the adapter —
consistent with ADR-0004's rule/mechanism split.

### 2. Reviewer independence

The review is invoked by the **loop driver** (ADR-0008), not the
implement-agent, on five axes:

- **Invoker:** the loop, never the implementer.
- **Prompt:** a fixed system-authored template the implementer never sees or
  edits.
- **Reviewer:** the **secondary model** on a **different provider** (failover
  armed; a different provider also strengthens collusion-resistance — the
  reviewer shares no quota or context with the implementer).
- **Workspace:** a **separate isolated worktree**.
- **Input:** the **diff + ticket spec only** — never the author's commit
  messages or PR prose.

### 3. Transport and enforcement

Findings travel as a **PR comment** posted by a **dedicated reviewer identity**
(a separate PAT the implement-agent does not possess), tagged with the commit
SHA it reviewed. A CI workflow (`review-verdict`) reads only that identity's
latest SHA-matching comment and runs `verdict.py`. Findings never live in a
branch-controlled file — the implementer has branch write access and could
tamper. A stale review (findings SHA ≠ PR head) fails the check as *"no current
review,"* forcing a fresh round.

### 4. Branch protection

Branch protection requires **both** `validate-skills` **and** `review-verdict`.
The existing `scripts/skills.py` drift guard (which asserts every required
context has a matching workflow job) keeps this honest with no new machinery.

## Consequences

- **Cheating is structurally impossible, not discouraged.** No agent emits a
  verdict; the implementer can't frame the review or reach the CI that computes
  it; merge is gated by both checks.
- **The verdict is exclusively a CI-computed fact.** It exists only as the
  `review-verdict` status check.
- **Scoped to code-delivery (`task`) tickets.** `research` / `prototype` /
  `grilling` resolve decisions and close without a PR (see ADR-0008); they have
  no verdict gate.
- **Operational requirement:** a dedicated reviewer PAT. Without it,
  identity-filtering collapses and enforcement degrades to a weaker check-run
  model.
- **Two-axis input:** `verdict.py` aggregates Standards + Spec findings; a
  CRITICAL/HIGH in either axis fails.

## Version Implications

- `ticket-workflow-core` v0.5.0 — `GATE` verdict protocol: declared → derived;
  deletes the `VERDICT pass|fail` schema.
- New: `scripts/verdict.py`, `.github/workflows/review-verdict.yml`, a fixed
  review-prompt template.
- Branch protection: add the `review-verdict` context.
