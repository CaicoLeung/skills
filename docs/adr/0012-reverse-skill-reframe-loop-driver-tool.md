# ADR-0012: Reverse the skill-product reframe; this repo is the Loop Driver tool

- **Status:** Accepted
- **Date:** 2026-07-27
- **Supersedes:** [ADR-0011](./0011-agent-skill-product-reframe.md) (un-retire the driver), [ADR-0002](./0002-skill-frontmatter-contract.md) (voided — no skills), [ADR-0004](./0004-runtime-neutral-core-plus-adapter.md) (voided — no skills)
- **Partially supersedes:** [ADR-0001](./0001-fork-with-selective-sync.md) (the "fork" framing is withdrawn — this repo is built *on top of* `mattpocock/skills`, not a fork of it), [ADR-0009](./0009-question-numbering-convention.md) (the numbering convention survives as a driver concern in `docs/agents/question-numbering.md`; the skill-frontmatter field is voided)

## Context

ADR-0011 (2026-07-26) reframed the repo as an **Agent Skill product** and
**retired** the Python/Paseo reference implementation — deleting the loop
driver, reviewer, verdict, GitHub gateway, and the `review-verdict` CI
workflow, leaving only three installable skills plus the meta-tooling that
produces and validates them. A day later two things were clear:

1. **The skill framing was wrong for the product we actually want to ship.**
   What the repo does usefully is *drive tickets to completion unattended* —
   implement → review → fix → merge → close — not publish discipline-as-prose
   for a consumer to reimplement. The skill artifacts described a system this
   repo used to run and no longer did; the discipline-without-a-runner state
   ADR-0011 accepted as "the consumer's job" was in fact nobody's job.
2. **The repo is not a fork of `mattpocock/skills`.** ADR-0001's title and the
   README's opening line both assert a fork relationship. In reality this repo
   is **built on top of** `mattpocock/skills`: it consumes the issues
   `mattpocock/skills`'s `to-spec` / `to-tickets` generate, and drives them
   through the verified cycle. There is no selective sync of an upstream tree;
   the "fork" label was inherited from the repo's origin and never corrected.

Carrying the three skills alongside a re-introduced driver would reproduce the
exact product/infrastructure blur ADR-0011 retired the driver to escape — but
inverted (the skills would be the dead weight, the driver the product). The
clean cut is to abandon the skill framing entirely.

## Decision

**Reposition the repo as the Loop Driver — an auxiliary tool that
batch-completes the issues `mattpocock/skills` generates — and abandon the
Agent Skill product surface.**

1. **The driver is restored.** The tree retired in ADR-0011 is restored from
   `095339d^`: `scripts/{loop,routing,closeout,reviewer,verdict,review_verdict,
   github,supervise,_test_fakes}.py`, their tests, `tests/test_verdict.py`,
   and the `docs/agents/{closeout,review-verdict,supervise}.md` behavior docs.
   The driver is the product. (The `review-verdict.yml` workflow is *not*
   restored — ADR-0013, same day, retires it before restore; see §1 there.)
2. **A `batch` subcommand is added** (`scripts/loop.py batch`): drains the
   `ready-for-agent` queue via `gh issue list`, dispatching the implement turn
   for each, up to `--limit`, with fail-stop on the first dispatch error. One
   batch run advances every queued issue by the DISPATCH phase (T5a); the
   close-out (T5b) and supervise phases remain per-PR driver invocations, since
   batch does not poll for PRs that async implement agents open downstream.
   Driving the whole queue to completion means re-running batch against each
   phase as the queue shifts.
3. **The skill surface is deleted.** `skills/` (the three `SKILL.md` trees and
   `INDEX.md`), the skill meta-tooling (`scripts/{validate-skills,index-skills,
   skills,marketplace,build-marketplace}.py` and their tests), the marketplace
   manifest (`.claude-plugin/`), `docs/agents/skills.md`, and the
   `.github/workflows/validate-skills.yml` job are removed. With no skills to
   validate, the `validate-skills` status-check context is retired;
   `review-verdict` is now the **sole** required context, and the driver's
   default `required_check` (`DriverConfig`, the `supervise` subcommand) moves
   from `validate-skills` to `review-verdict`.
4. **The reviewer template is internalized.** `reviewer.DEFAULT_TEMPLATE`
   pointed at `skills/ticket-workflow-core/review-prompt.md`; that file is
   relocated to `scripts/review-prompt.md` so the driver has no dependency on
   the deleted skills tree. The `import skills` in `loop.py` (used only for the
   `CONVENTION_DOC_REF` string) is replaced with an inlined
   `QUESTION_NUMBERING_DOC` constant — the driver no longer imports any
   skill-producing module.
5. **`branch_protection.py` stays, as standalone repo infrastructure.** ADR-0011
   listed it under "meta-tooling that stays." Its drift logic
   (`workflow_job_names`, `missing_job_errors`, `drift_errors`) is
   context-name-agnostic and still meaningful for the `review-verdict` gate.
   **Its CI runner is gone** (the `validate-skills` job that invoked it is
   retired): run it locally (`python3 scripts/branch_protection.py`) or give it
   a new workflow home. Giving it a runner is an out-of-band follow-up, not a
   blocker for this decision.
6. **"Loop Engineering" is retired as a product brand**, surviving only as the
   historical mechanism name inside this ADR series and `CONTEXT.md`. The
   product name is **Loop Driver**.

## Consequences

- **The repo runs again.** `python3 scripts/loop.py {route,closeout,supervise,
  batch}` works against `HEAD`; the restored test suites (6 script runners +
  `tests/test_verdict.py`) and the new `scripts/test_batch.py` pass.
- **Out-of-band action required.** Live GitHub branch protection on
  `CaicoLeung/skills` lists both `validate-skills` and `review-verdict` as
  required contexts. With `validate-skills.yml` deleted, an admin must **drop
  `validate-skills`** from the required status checks or PRs cannot merge.
  (`review-verdict` remains, still backed by its workflow.) This is the inverse
  of ADR-0011's out-of-band note, which feared the opposite.
- **The `tmux` + `git worktree` first-class EXECUTE surface is still deferred.**
  The restored driver delegates worktrees to Paseo's `--worktree` flag and has
  no `tmux` integration; promoting them to first-class seams is tracked as a
  follow-up issue, alongside the GitHub repo rename (`skills` → on-brand).
- **The skill-era ADRs are historical.** 0001's fork framing, 0002's
  frontmatter contract, 0004's core+adapter architecture, and 0009's
  skill-frontmatter field describe a product surface that no longer exists;
  they stay in the record as superseded/voided, not edited in place.
- **`branch_protection.py` and `docs/agents/{closeout,review-verdict,supervise,
  ticket-types,triage-labels,question-numbering,domain,issue-tracker}.md`
  survive** — they describe the driver's behavior or the ticket model it
  consumes, not the deleted skill surface.
