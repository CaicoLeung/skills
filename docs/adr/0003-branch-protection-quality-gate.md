# ADR-0003: Branch protection quality gate

- **Status:** Accepted
- **Date:** 2026-07-24
- **Supersedes:** —
- **Related:** [ADR-0004](./0004-runtime-neutral-core-plus-adapter.md)

## Context

The close-out quality gate (code review, validation) was enforced only by prompt contract — agents instructed to run `/code-review` before committing. Advisory, not a block. A PR could merge without passing the gate if the agent ignored instructions or a human bypassed review.

Two options: (a) add Paseo pre-commit/pre-PR hooks, or (b) enforce at the git layer via GitHub branch protection requiring CI status checks.

## Decision

**Branch protection requiring CI status checks.** Enforcement lives at GitHub, not in Paseo.

### 1. Paseo surface discovery (0.1.110)

Paseo 0.1.110 has **no** pre-commit or pre-PR hook interception surface. The available coordination primitives are:
- Chat rooms for handoff
- Schedules for recurring tasks
- `paseo hooks <agent> <event>` for recording hook activity (read-only, not a gate)

**Conclusion:** There is no Paseo daemon gate to wire. The gate must live at the platform layer.

### 2. Branch protection configuration

Require CI status checks before PR merge:

```bash
gh api -X PUT repos/CaicoLeung/skills/branches/main/protection \
  --input - <<'EOF'
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

**Key points:**
- `contexts: ["validate-skills", "review-verdict"]` — see [Required status-check contexts](#required-status-check-contexts-source-of-truth) below
- `strict: true` — require updates to the base branch before merge
- `enforce_admins: true` — admins cannot bypass without approval

### Required status-check contexts (source of truth)

Each required context is a workflow *job* whose name equals the context name. The
`scripts/skills.py` drift guard asserts this 1:1 mapping — a required context with no
matching job name fails `validate-skills.py`, and a job whose name no longer matches a
required context is flagged. Add or remove a context here and in branch protection
together.

| Context | Workflow job | Enforces |
| --- | --- | --- |
| `validate-skills` | `.github/workflows/validate-skills.yml → validate-skills` | Skill frontmatter conformance (ADR-0002); `skills/INDEX.md` up-to-date; `.claude-plugin/marketplace.json` up-to-date (the **marketplace drift gate**, issue #46, generator from #44/#47); and the script test suites (`test_marketplace`, `test_routing`, `test_reviewer`, `test_loop`, `test_review_verdict`, `test_closeout`). |
| `review-verdict` | `.github/workflows/review-verdict.yml → review-verdict` | Derived verdict from the reviewer's findings equals `approved` (ADR-0007). |

**Marketplace drift gate (#46).** The marketplace check rides as a *step* inside the
`validate-skills` job (`python3 scripts/build-marketplace.py --check`), so a stale
`.claude-plugin/marketplace.json` fails the already-required `validate-skills` context
and blocks merge — no separate context is warranted. A regression test
(`scripts/test_marketplace.py → CI gating guard`) fails if that step is removed or
commented out, so the drift step resists silent deletion (the residual limit — a PR
that deletes both the drift step and the test step at once — is left to human review;
the `skills.py` contexts↔jobs drift guard still requires the `validate-skills` job).

### 3. Gate enforcement location

**Enforcement lives at branch protection.** The prompt contract is only the trigger:
- Agent runs `/code-review` (prompt contract trigger)
- Review passes → agent commits → CI runs `validate-skills`
- Status check → branch protection blocks merge if failed
- **Gate is real, not advisory.**

**ADR-0004 adapter wording update:** The `tickets-to-paseo` GATE mapping must reflect this honestly:

```
### GATE → Prompt Contract + Branch Protection

Core's GATE primitive maps to TWO layers:

1. **Trigger layer (prompt contract):** Encode close-out steps in agent prompt.
   "Run /code-review before committing. Do not commit until review passes."

2. **Enforcement layer (branch protection):** GitHub requires CI status check.
   A PR cannot merge unless `validate-skills` (which runs `scripts/validate-skills.py`) passes.

**Gap note:** Paseo 0.1.110 has no daemon gate. Enforcement lives at GitHub branch protection; prompt is only the trigger.
```

### 4. Runtime implications

- **Paseo:** No interception surface → no daemon gate possible
- **GitHub:** Branch protection is the enforcement layer
- **Adapters:** Must document where their runtime lacks daemon gates and whether platform-level enforcement exists

## Consequences

- **Gate is real.** Advisory prompt contract becomes hard block via branch protection.
- **Multi-runtime difference.** Non-GitHub runtimes need their own enforcement layer (e.g., GitLab merge requests, Azure DevOps branch policies).
- **Adapter docs must be honest.** `tickets-to-paseo` and future adapters must explicitly state: "No daemon gate; enforcement at branch protection" or equivalent.

## Acceptance Criteria (from issue #5)

- ✅ Paseo's interception surface discovered (0.1.110 has no pre-commit/pre-PR hook)
- ✅ Branch protection configured to require `validate-skills` status check
- ✅ `tickets-to-paseo` GATE section reworded to reflect enforcement lives at branch protection, prompt is only trigger
- ✅ `docs/adr/0003-branch-protection-quality-gate.md` records the decision
- ✅ PR missing the check is demonstrably blocked

## Platform Commands

**Enable protection:**
```bash
gh api -X PUT repos/CaicoLeung/skills/branches/main/protection \
  --input - <<'EOF'
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

**Verify protection:**
```bash
gh api repos/CaicoLeung/skills/branches/main/protection
```

**Disable protection (if needed):**
```bash
gh api -X DELETE repos/CaicoLeung/skills/branches/main/protection
```

## Test: Demonstrate block

Create a test PR with a failing validator; verify merge is blocked:

```bash
# 1. Create branch with invalid skill
git checkout -b test/failing-validator
echo "# Invalid frontmatter" > skills/test/SKILL.md
git commit -am "test: failing validator"

# 2. Push and open PR
git push origin test/failing-validator
gh pr create --title "test: failing validator" --body "Test PR to verify branch protection blocks merge"

# 3. Check status (expect "blocked")
gh pr checks <pr-number>
gh api repos/CaicoLeung/skills/pulls/<pr-number> --jq '.mergeable, .mergeable_state'
```

Expected: `mergeable_state: "blocked"` or `draft`.
