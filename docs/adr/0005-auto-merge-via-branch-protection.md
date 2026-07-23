# ADR-0005: The close-out merge option is a per-PR agent toggle; merge authority is branch protection + auto-merge

- **Status:** Accepted
- **Date:** 2026-07-24
- **Supersedes:** —

## Context

A request to "let users decide whether, when a PR review is completed, the PR is
automatically merged into the main branch or waits for human approval." This
builds on two already-landed decisions: ADR-0003 (#5 — the close-out gate is a
real branch-protection **status check**) and ADR-0004 (#4 — a runtime-neutral
core plus adapter). It also reuses a fuzzy word — "review" — that this repo
uses three ways: the AI `/code-review`, the CI status check, and a human
approving review. The glossary now pins **close-out gate** = the first two,
universal and non-optional, with the human review as the only optional arm.

Three ways to "perform the merge" were on the table: the implementing agent
self-merging (`gh pr merge` at the end of `/implement`), a Paseo daemon
automation, or GitHub-native branch protection + auto-merge.

## Decision

**Merge authority is branch protection; the option is a per-PR agent behavior,
not a repo-config mutation.** Concretely:

1. **Merge authority = branch protection + auto-merge.** The implementing agent
   only *enables* GitHub auto-merge on its PR (`gh pr merge --auto --squash
   --delete-branch`); GitHub performs the actual merge the moment the close-out
   gate holds. The agent never performs the merge itself.
2. **The per-workflow option (a 5th setup question, default = "Wait for human
   review") controls only whether the agent enables auto-merge.** "Auto" → the
   agent enables it; "Wait for human" → the agent opens the PR and does **not**
   enable auto-merge, leaving it for a human to review and merge.
3. **Branch protection stays admin-owned.** Whether a human review is *required*
   is configured once by an admin under #5; this skill never mutates repo BP.
4. **Effective behavior = skill mode ∩ BP.** In "Auto" mode, if BP requires a
   human review, the PR still blocks until a human approves — BP wins, which is
   the safe failure.
5. **Merge target = the base branch** (`inputs.metadata.baseBranch`, else the
   repo default), never hard-coded `main`. Method = squash + delete-branch, a
   fixed skill default, not a launch question.

## Consequences

- **The agent self-merge path was rejected** because it reintroduces the exact
  "advisory gate advertised as real" anti-pattern (#1 gap 3) that ADR-0003/#5
  exist to kill. The daemon-merge path was rejected as runtime lock-in (#4 /
  ADR-0004) and because it would re-couple merge to a single runtime.
- **"When a PR review is completed" is GitHub's auto-merge trigger, not a skill
  event.** The agent enables auto-merge at PR-open time; GitHub fires the merge
  when the gate holds (AI review + CI green, plus a human review if BP requires
  one).
- **Safe-by-default.** Default is "Wait for human"; auto-merge is opt-in.
- **No admin token in the skill; no cross-workflow BP conflict.** BP mutation
  was rejected precisely because a per-ticket launcher rewriting repo-wide BP is
  surprising, needs admin credentials, and two launches targeting the same base
  branch would clobber each other (last-writer-wins).
- **Output gains a `merge` field** (`"wait-for-human" | "auto"`).
- **Worktree cleanup after merge stays Paseo's lifecycle concern**, not this
  skill's.
- **Numbered 0005** because 0003 (status-check BP) and 0004 (runtime-neutral
  core) were already taken by #5 and #4. This extends the "enforcement lives at
  branch protection" thesis from the status-check gate to merge mechanics; it
  does not supersede ADR-0003.
- **Split across the core/adapter seam.** The merge *policy* (`mergePolicy`,
  runtime-neutral) lives in `ticket-workflow-core`'s `GATE` action; the concrete
  *mechanism* (`gh pr merge --auto --squash --delete-branch`) lives in the
  `tickets-to-paseo` adapter. A second runtime adapter maps the same policy to
  its git host's merge.
