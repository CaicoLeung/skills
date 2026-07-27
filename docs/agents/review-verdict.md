# Review Verdict (derived-verdict gate)

The close-out code-review verdict is **computed**, never declared. The Loop
Driver derives it from the reviewer identity's structured findings — there is no
`VERDICT` token for anyone to append. This doc specifies the findings-comment
format, how the driver selects a *current* review, and how to demo the gate. See
[ADR-0007](../adr/0007-derived-verdict-and-reviewer-independence.md) for the
decision (verdict computation + reviewer independence) and
[ADR-0013](../adr/0013-ci-gate-optional-local-verdict-gates.md) for why the gate
is the driver's local derivation rather than a CI check.

> **The CI check is gone from this repo.** The `review-verdict` workflow ran the
> same verdict logic in GitHub Actions on this repo's own PRs; it gated *this*
> repo, not any repo that installs the driver, so it was self-referential dead
> weight (ADR-0013). The verdict *logic* stays — `scripts/verdict.py` (the rule)
> and `scripts/review_verdict.py` (the selection) are composed by
> `scripts/closeout.py` to decide PASS→auto-merge. A consumer who wants
> independent CI re-derivation (defense in depth) can wire
> `scripts/review_verdict.py`'s `main()` into their own workflow and point
> `--required-check` at it; see [ADR-0013](../adr/0013-ci-gate-optional-local-verdict-gates.md).

## Findings-comment format

The reviewer posts **one top-level PR comment** per review round (issue
comment, not an inline review thread) carrying a machine anchor plus the
findings body:

```
<!-- review-verdict-findings sha=<7..40 hex of the reviewed commit> -->
## Code review findings (ADR-0007) — reviewed SHA `<sha>`

[src/foo.py:12]: HIGH: null deref on none input
[src/bar.py:5]: MEDIUM: misleading variable name
src/baz.py: OK
```

- **Marker line** (line 1) is the anchor: `<!-- review-verdict-findings sha=… -->`.
  The SHA is the commit the reviewer actually reviewed.
- **Findings body** follows. One finding per line, two legal shapes:
  - `[file:line]: SEVERITY: summary` — `SEVERITY` ∈ `CRITICAL | HIGH | MEDIUM | LOW`.
  - `file: OK` — explicit coverage-floor ack for a clean file.
- Prose lines that match neither shape are ignored by `scripts/verdict.py`, so a
  human-readable heading is harmless — but keep the body mostly findings.

## How the driver selects a current review

`scripts/review_verdict.py` ships the selection the driver's close-out uses. On
each review round `closeout` calls `select_current_findings(comments, head_sha,
reviewer_login)`:

1. Fetch the PR's issue comments and changed files (`gh`, via `scripts/github.py`).
2. Keep only comments authored by `REVIEWER_LOGIN` whose marker SHA **equals**
   the PR head SHA (case-insensitive, exact — a short SHA is not a prefix match
   against a full head).
3. Of those, take the latest by `created_at`.
4. Feed its findings body + the changed files to `derive_verdict`
   (`scripts/verdict.py`).

If **no** comment matches (stale SHA, or no review yet), the verdict is
**"missing"** → `closeout` invokes a fresh review round. A stale review therefore
cannot merge; every push demands a fresh review round. CRITICAL/HIGH findings
fail; MEDIUM/LOW are non-blocking warnings; a changed file with neither a
finding nor `OK` is a coverage gap that fails.

`scripts/review_verdict.py`'s `main()` is the **optional consumer-side CI entry
point**: it runs steps 1–4 in GitHub Actions and exits with the verdict's code,
exposing it as a status-check context a consumer can require. It is unused in
this repo (ADR-0013) but kept as the reusable gate for consumers who opt into
independent CI enforcement.

## The gate (no required contexts in this repo)

This repo has **no required status-check contexts** — the `review-verdict` and
`validate-skills` workflows are both retired. The merge gate is the driver's
locally-derived verdict (ADR-0013): `closeout` enables `gh pr merge --auto` only
on a derived PASS, and with no `required_check` configured GitHub merges once the
other protection rules are satisfied.

A consumer who wants the gate enforced independently in CI:

1. Run `scripts/review_verdict.py --repo … --pr … --sha … --reviewer-login …`
   from a workflow in *their* repo (the script is self-contained).
2. Add the resulting `review-verdict` context to their branch protection's
   required status checks.
3. Point the driver at it: `loop.py … --required-check review-verdict`
   (or `LOOP_REQUIRED_CHECK=review-verdict`).

`scripts/branch_protection.py` asserts every required context has a matching
workflow job name — run it locally to catch context/job drift.

## Honest enforcement (caveat)

The verdict is only as honest as the reviewer identity. `REVIEWER_LOGIN` is the
GitHub App's bot login in production — a separate identity whose token the
implement-agent does not possess, so the implementer cannot post its own
findings. The App's provisioning is an **operational prerequisite** (out of
scope for the code change per the parent epic). While the App is absent,
`REVIEWER_LOGIN` is the maintainer's login and findings are posted manually —
the *mechanism* (filter by login + sha) is fully in place; only the
*credential* that makes it un-cheatable is deferred.

## Demo procedure (no live reviewer)

The gate is demoed via the close-out trajectory simulator — no agent, no App, no
CI. `scripts/test_closeout.py` and `scripts/test_review_verdict.py` exercise the
pure selection + derivation; `python3 scripts/loop.py closeout <issue> --pr <N>
--dry-run --outcomes pass,fail,pass` replays a multi-round trajectory through the
planner. To drive a live review round, run `closeout` without `--outcomes` (it
invokes the independent reviewer via `paseo`, derives the verdict, and acts on
it). See [closeout.md](closeout.md).

To post findings manually (substitute the PR head SHA):

```bash
HEAD=$(gh pr view <PR> --repo CaicoLeung/skills --json headRefOid --jq '.headRefOid')
gh pr comment <PR> --repo CaicoLeung/skills --body "$(cat <<EOF
<!-- review-verdict-findings sha=${HEAD} -->
## Code review findings (ADR-0007) — reviewed SHA \`${HEAD}\`

src/changed.py: OK
EOF
)"
```
