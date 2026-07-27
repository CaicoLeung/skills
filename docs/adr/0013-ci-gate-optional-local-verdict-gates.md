# ADR-0013: CI gate is optional; the driver's local verdict gates

- **Status:** Accepted
- **Date:** 2026-07-27
- **Supersedes:** the "CI gates" half of [ADR-0007](0007-derived-verdict-and-reviewer-independence.md) (§3–§4: the verdict as an exclusively CI-computed fact, and `review-verdict` as a required status-check context). The independent-**reviewer** half of ADR-0007 (§1–§2: sha-tagged findings from a separate identity) survives.
- **Relates:** [ADR-0003](0003-branch-protection-quality-gate.md) (branch-protection required contexts — now fully historical for this repo), [ADR-0012](0012-reverse-skill-reframe-loop-driver-tool.md) (retired `validate-skills`; this retires the other required context).

## Context

ADR-0007 split the close-out verdict into one rule computed in two places: the
loop derives it *to decide* (enable auto-merge), and a CI check re-derives it
*to gate* (branch protection requires `review-verdict`). The two were the same
logic (`scripts/verdict.py` + `scripts/review_verdict.py`) — the "rule lives in
the core, mechanism in two adapters" shape of ADR-0004.

That CI check (`.github/workflows/review-verdict.yml`) ran **only in this repo**,
on this repo's own PRs. ADR-0012 repositioned the product as the Loop Driver — a
tool a consumer installs against **their own** repo. A workflow pinned to
`CaicoLeung/skills` gates this repo's development; it does nothing for any
consumer. The consumer would have to copy the workflow into their repo to get
the gate. For a *tool* repo, the workflow is self-referential: it is not part of
the product, only of this repo's own dogfooding.

After ADR-0012 retired `validate-skills`, `review-verdict` remained the sole
required status-check context. The question: is it pulling its weight, or is it
dead weight the product does not carry?

## Decision

**Remove the `review-verdict` CI workflow from this repo. The merge gate is the
driver's locally-derived verdict.**

1. **Delete `.github/workflows/review-verdict.yml`.** This repo now has **no**
   required status-check contexts.
2. **The gate is `closeout`'s local derivation.** `closeout` composes
   `review_verdict.select_current_findings` (T3) + `verdict.derive_verdict` (T1)
   from the independent reviewer's sha-tagged findings, and enables
   `gh pr merge --auto` only on a derived **pass**. The verdict *logic* stays in
   the driver — it is imported, not run as CI.
3. **`required_check` defaults to empty (no CI gate).** `DriverConfig.required_check`
   and the `--required-check` CLI / `LOOP_REQUIRED_CHECK` env default to `""`.
   `supervise.GateState` treats an empty `required_check` as "gate satisfied"
   (new `has_required_check` property): the supervisor neither waits on nor
   escalates from an absent check, and `merged_and_gated` reduces to `merged`.
4. **CI enforcement becomes opt-in, consumer-side.** A consumer who wants
   independent re-derivation (defense in depth) runs
   `scripts/review_verdict.py`'s `main()` from a workflow in **their** repo, adds
   the resulting context to their branch protection, and points the driver at it
   (`--required-check`). `review_verdict.py` and `test_review_verdict.py` stay in
   this repo as that reusable gate; they are simply not wired into CI here.

## Consequences

- **ADR-0007 is partially superseded.** The "verdict is exclusively a
  CI-computed fact" / "branch protection requires `review-verdict`" thesis
  (§3–§4) is void. The verdict is now the **driver's** derived fact. What
  survives unchanged: the verdict is *computed from an independent reviewer's
  sha-tagged findings, never self-declared* (§1–§2). The implementer still
  cannot declare a verdict; the loop derives it.

- **Defense in depth is lost by default.** ADR-0007's two-place computation was
  belt-and-braces: even a buggy/compromised loop derivation would be re-caught
  by CI. With CI gone, the gate is single-source. This is an accepted tradeoff:
  the derivation is still from an *independent* review (not the implementer's
  claim), so the anti-self-declaration property holds — only the independent
  *re-derivation* is gone. Consumers who need it opt in per §4.

- **`supervise` no-escalation on no-check.** `GateState.has_required_check` guards
  `gated` and `signal_deadline_exceeded`; an empty `required_check` cannot trip
  `DEVIATION_CHECK_MISSING`. Covered by `scripts/test_supervise.py` (AC2b).

- **`review_verdict.py main()` is dormant in this repo.** It is the consumer-side
  CI entry point, kept + tested as the reusable gate, unused locally.

- **Out-of-band action required.** Live branch protection on `CaicoLeung/skills`
  lists `review-verdict` (and `validate-skills`) as required contexts. With both
  workflows deleted, an admin must **drop both** from the required status checks
  or PRs cannot merge. `scripts/branch_protection.py` surfaces this drift.

- **ADR-0003 is fully historical.** Its `contexts: ["validate-skills",
  "review-verdict"]` branch-protection model described a gate this repo no longer
  has. It stays in the record with a header note.
