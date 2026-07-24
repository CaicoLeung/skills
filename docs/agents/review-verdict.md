# Review Verdict (derived-verdict gate)

The close-out code-review verdict is **computed**, never declared. A CI check
(`review-verdict`) derives the verdict from the reviewer identity's structured
findings and gates merge via branch protection. There is no `VERDICT` token for
anyone to append. This doc specifies the findings-comment format, how the check
selects a *current* review, and how to demo the gate. See
[ADR-0007](../adr/0007-derived-verdict-and-reviewer-independence.md) for the
decision and [ADR-0003](../adr/0003-branch-protection-quality-gate.md) for the
branch-protection gate model.

## Findings-comment format

The reviewer posts **one top-level PR comment** per review round (issue
comment, not an inline review thread) carrying a machine anchor plus the
findings body:

```
<!-- review-verdict-findings sha=<7..40 hex of the reviewed commit> -->
## Code review findings (ADR-0007) — reviewed SHA `<sha>`

[src/foo.py:12]: HIGH: null deref on None input
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

## How the check selects a current review

`scripts/review_verdict.py` (run by the `review-verdict` job) does, on each PR:

1. Fetch the PR's issue comments and changed files (`gh`).
2. Keep only comments authored by `REVIEWER_LOGIN` whose marker SHA **equals**
   the PR head SHA (case-insensitive, exact — a short SHA is not a prefix match
   against a full head).
3. Of those, take the latest by `created_at`.
4. Feed its findings body + the changed files to `derive_verdict`
   (`scripts/verdict.py`).
5. Exit with the verdict's code — the job's pass/fail *is* the
   `review-verdict` status check.

If **no** comment matches (stale SHA, or no review yet), the check fails as
**"no current review"**. A stale review therefore cannot merge; every push
demands a fresh review round. CRITICAL/HIGH findings fail; MEDIUM/LOW are
non-blocking warnings; a changed file with neither a finding nor `OK` is a
coverage gap that fails.

## Branch protection

`main` requires **both** `validate-skills` **and** `review-verdict`. The
`scripts/skills.py` drift guard asserts each required context has a matching
workflow job name — the `review-verdict` job in
`.github/workflows/review-verdict.yml` satisfies it.

```bash
gh api -X PUT repos/CaicoLeung/skills/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["validate-skills", "review-verdict"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
```

## Honest enforcement (caveat)

The verdict is only as honest as the reviewer identity. `REVIEWER_LOGIN` is the
GitHub App's bot login in production — a separate identity whose token the
implement-agent does not possess, so the implementer cannot post its own
findings. The App's provisioning is an **operational prerequisite** (out of
scope for the skill/code change per the parent epic). While the App is absent,
`REVIEWER_LOGIN` is the maintainer's login and findings are posted manually —
the *mechanism* (filter by login + sha) is fully in place; only the
*credential* that makes it un-cheatable is deferred.

## Demo procedure (no live reviewer)

The gate is demoed with manually-posted findings — no agent, no App.

1. **Passing case.** On a PR with a trivial change, post a comment under
   `REVIEWER_LOGIN` whose marker SHA equals the PR head, acking every changed
   file (`file: OK` or only MEDIUM/LOW findings). Re-run the `review-verdict`
   job (or push to retrigger). Expected: check passes, PR `mergeable_state`
   becomes clean (once `validate-skills` is also green).
2. **Failing case.** Post a comment with a `HIGH`/`CRITICAL` finding (or a
   coverage gap). Expected: check fails; `gh pr checks` shows `review-verdict`
   red and `mergeable_state` is `blocked`.
3. **Stale case.** Push a new commit (new head SHA) without a fresh review.
   Expected: the prior review no longer matches → check fails "no current
   review".

Post findings with (substitute the PR head SHA):

```bash
HEAD=$(gh pr view <PR> --repo CaicoLeung/skills --json headRefOid --jq '.headRefOid')
gh pr comment <PR> --repo CaicoLeung/skills --body "$(cat <<EOF
<!-- review-verdict-findings sha=${HEAD} -->
## Code review findings (ADR-0007) — reviewed SHA \`${HEAD}\`

src/changed.py: OK
EOF
)"
```
