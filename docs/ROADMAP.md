# Roadmap

This repo publishes Loop Engineering as installable Agent Skills. The roadmap
is deliberately thin: the product is the discipline, and most "next steps"
belong to consumers, not here. See
[ADR-0011](./adr/0011-agent-skill-product-reframe.md) for the reframe.

## Now

- **Three self-contained skills ship**: `loop-engineering` (the discipline),
  `ticket-workflow-core` (runtime-neutral primitives), `tickets-to-paseo`
  (Paseo 0.1.110 adapter). Each validates, indexes, and is drift-free.
- **Meta-tooling retained**: `validate-skills`, `index-skills`,
  `build-marketplace`, the `branch_protection` drift guard, and their tests.
  They produce and validate skills; they are not product.

## Required out-of-band action

- **Drop the `review-verdict` required status-check context** from `main`
  branch protection on `CaicoLeung/skills`. The `review-verdict` workflow is
  retired (ADR-0011); the context is now orphaned, so PRs cannot merge until an
  admin removes it. `validate-skills` stays required (still backed by
  `.github/workflows/validate-skills.yml`). This needs an admin token and was
  not done from the worktree.

## Accepted limitation

- **The discipline is unverified-by-running in this repo.** Retiring the
  reference implementation (ADR-0011) means no in-repo code exercises the loop
  end-to-end. That is the accepted cost of staying stack-agnostic. The skills
  are internally consistent, and the meta-tooling validates frontmatter, the
  marketplace manifest, and INDEX drift — but a real ticket cycle is not
  executed here.

## Possible later (not committed)

- **A separate reference-implementation repo** that consumes these skills and
  dogfoods them against a real runtime (Paseo or another), restoring
  verified-by-running without re-coupling the product to a stack.
- **Additional adapters** (a second runtime) — each is a new skill file
  consuming `ticket-workflow-core`; no core change.
- **Skill-level worked examples** if consumers need more than the current
  contract-plus-discipline description.

## Explicitly not on the roadmap

- **Re-introducing an in-repo loop driver.** That re-couples the product to a
  specific stack and re-opens the self-serving-path problem ADR-0011 closed.
- **A competing `npx skills` binary.** This fork installs via the upstream
  installer; it does not ship its own.
