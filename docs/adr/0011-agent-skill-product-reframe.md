# ADR-0011: This repo is an Agent Skill product; the reference implementation is retired

- **Status:** Accepted
- **Date:** 2026-07-26
- **Supersedes:** ADR-0003, ADR-0005, ADR-0006, ADR-0007, ADR-0008, ADR-0010

## Context

This repo began as a fork of `mattpocock/skills` organised around **Loop
Engineering**, and grew a Python/Paseo reference implementation under `scripts/`
that dogfooded the discipline end-to-end — loop driver, routing, close-out,
derived-verdict reviewer, GitHub gateway, branch-protection gate, and the
`review-verdict` CI context. As the work matured, two things became clear:

1. **The product is the discipline, not the driver.** What is portable,
   installable, and useful to other people is the *skill* — the stack-agnostic
   description of two-axis routing, the scripted-vs-judgment boundary, the
   close-out loop, the derived-verdict protocol, and the abstract primitives.
   The Python driver is one realisation of that discipline; it is not the thing
   being distributed.
2. **Self-serving code is a liability in an installable skill.** A skill that
   points the consumer at `../../scripts/loop.py` ships broken — those paths do
   not exist in the installed copy. The upstream `npx skills` installer copies
   the committed `skills/<name>/` tree verbatim, with no build/transform hook,
   so self-containment must be achieved in the committed source.

Carrying the reference implementation alongside the skills created a constant
tension: every skill described the discipline *and* leaned on `scripts/*`,
blurring the line between *product* (the skill) and *infrastructure* (the
scripts that produce and validate it). The grilling of "support `npx skills
add`" surfaced that "skill" was itself undefined in the glossary — conflating
scripts with skills was an easy mistake precisely because the boundary was
unspoken.

## Decision

**Reframe the repo as an Agent Skill product for external consumption, and
retire the reference implementation.**

1. **The three skills are the product.** `loop-engineering` (the discipline),
   `ticket-workflow-core` (runtime-neutral primitives), and `tickets-to-paseo`
   (the Paseo adapter) are self-contained knowledge artifacts. They describe
   contracts the consumer implements; they do not import or point at in-repo
   scripts.
2. **The `scripts/` reference implementation is retired** — deleted from the
   tree; git history is the archive (no `archive/` folder, which would clutter
   the product surface and risk confusing skill discovery). This retires the
   loop driver (`loop.py`, `routing.py`, `closeout.py`), the reviewer core
   (`reviewer.py`), the verdict function (`verdict.py`), the review-verdict
   runner (`review_verdict.py`), the GitHub gateway (`github.py`), and their
   tests, plus the `review-verdict` CI workflow.
3. **The meta-tooling stays.** The scripts that *produce and validate* skills
   are infrastructure, not product: `validate-skills.py`, `index-skills.py`,
   `build-marketplace.py`, `marketplace.py`, `branch_protection.py`, and their
   tests. They validate every skill and have no home skill to live in.
4. **Surviving decisions are recaptured in the skills.** The design rationale
   that previously lived in the superseded ADRs survives as discipline: the
   derived-verdict protocol and the five reviewer-independence axes live in
   [`ticket-workflow-core`](../../skills/ticket-workflow-core/SKILL.md) (GATE);
   merged-and-gated completion lives there too (SUPERVISE);
   [`loop-engineering`](../../skills/loop-engineering/SKILL.md) carries
   two-axis routing, the close-out loop, and the `STUCK_REVIEW` cap.
5. **Surviving ADRs** — 0001 (fork), 0002 (frontmatter contract), 0004
   (core + adapter), 0009 (question numbering) — remain in force.

## Consequences

- **The discipline is now unverified-by-running in this repo.** This is the
  accepted cost of the reframe: a reference implementation would re-couple the
  product to a specific stack. Verifying the discipline by executing it is now
  the consumer's job, or the job of a future separate reference-repo. The
  skills remain internally consistent, and the meta-tooling still validates
  frontmatter, the marketplace manifest, and INDEX drift.
- **Out-of-band action required.** Live GitHub branch protection on
  `CaicoLeung/skills` still lists the `review-verdict` context, which no longer
  has a workflow job. An admin must drop `review-verdict` from the required
  status checks or PRs cannot merge. The `validate-skills` context (still backed
  by `.github/workflows/validate-skills.yml`) remains required.
- **`reviewer.py` / `verdict.py` / the loop driver are gone from the tree.**
  Any external link to those paths is now a 404 against `HEAD` (recoverable via
  git history or a tag).
- **"Skill" is now a glossary term** ([CONTEXT](../../CONTEXT.md)), drawing the
  line between installable knowledge artifact and repo infrastructure — the
  boundary the reframe exists to make explicit.
