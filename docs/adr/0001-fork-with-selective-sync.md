# ADR-0001: Fork with a documented selective-sync strategy

- **Status:** Accepted
- **Date:** 2026-07-23
- **Supersedes:** —

## Context

This repository is a fork of [`mattpocock/skills`](https://github.com/mattpocock/skills),
a large collection ("Skills for Real Engineers"). We do not want the whole
collection: only selected skills and the documentation conventions that support
them. Initially the fork carried **no provenance** — no `LICENSE`, no `NOTICE`,
no `upstream` remote — yet skill files still cited `mattpocock/skills`. That is
neither a clean fork nor a clean original; it is an unattributed derivation,
which fails the most basic provenance expectations and risks licensing
ambiguity.

Two paths were on the table: (a) start a fully independent repo with no upstream
relationship, or (b) fork and carry a documented subset.

## Decision

**Fork, with a documented selective-sync strategy.** Specifically:

1. **Provenance is explicit.** `LICENSE` (MIT, matching upstream) and `NOTICE`
   attribute the derivation. The `upstream` git remote points at
   `mattpocock/skills` so upstream changes are fetchable.
2. **Selective, not wholesale.** Only chosen skills and docs are carried; the
   rest of upstream's tree is intentionally absent. This is not a mirror.
3. **Local overrides live in `docs/agents/*`.** This fork's own conventions
   (issue tracker, triage labels, domain docs) override or specialise upstream's
   defaults, recorded as files rather than tacit deviations.

## Consequences

- **Upstream sync is a deliberate act, not automatic.** Pulling from `upstream`
  is a per-path decision: we choose what to take. A blind `git merge upstream`
  would reintroduce the collection we deliberately left out, so it must not be
  routine.
- **Provenance is self-evident.** Anyone landing here can see the source, the
  license, and what diverges, without asking.
- **Override layer is discoverable.** Differences from upstream live as files in
  `docs/agents/*`, not as silent edits scattered across carried skills.
- **Carried skills remain responsible for their own attribution.** A skill that
  cites upstream should remain consistent with the LICENSE/NOTICE recorded here.
