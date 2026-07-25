---
name: tickets-to-paseo
description: "Paseo adapter for ticket-workflow-core — maps abstract primitives to Paseo 0.1.110 surface (chat rooms, schedules, prompt contracts, supervisor)."
version: 0.7.0
requires:
  - project
  - tickets
  - epics
produces:
  - workflow
  - paseo-agents
---

# Paseo Adapter for Ticket Workflow

**Adapter for `ticket-workflow-core`.** Consumes the core's runtime-neutral workflow plan and maps abstract primitives to the Paseo 0.1.110 surface.

## Runtime Mapping: Abstract → Paseo 0.1.110

### EXECUTE → `paseo run`

Core's `EXECUTE` primitive maps to `paseo run`:

```bash
paseo run \
  --provider "$provider" \
  --model "$model" \
  --mode "$modeId" \
  --thinking "$thinkingOptionId" \
  --worktree "$workspace_name" \
  --base "$base_branch" \
  --detach \
  "$prompt"
```

**Gap note:** Paseo 0.1.110 has no `notifyOnFinish` edge verb. Coordination uses chat rooms (see DEPENDS_ON below).

---

### DEPENDS_ON → Chat Rooms

Core's `DEPENDS_ON` primitive maps to Paseo chat rooms for coordination:

**Gap documentation:** In Paseo 0.1.110, there is NO `notifyOnFinish` dependency-edge verb. The adapter maps dependencies to chat-room handoff:

1. **Create a workflow chat room:**
   ```bash
   paseo chat create "wf-$workflowId" --purpose "Ticket workflow coordination"
   ```

2. **Post completion signals:** After supervisor observes merged-and-gated (PR merged + CI green), post to chat:
   ```bash
   paseo chat post "wf-$workflowId" "DONE task_$taskId pr=$pr_url merged_at=$timestamp"
   ```

3. **Dependent agents wait:** Dependent tasks block until the supervisor posts merged-and-gated. **`paseo chat wait` (0.1.110) has no `--filter`** — it only blocks for the next message (optional `--timeout`); filter client-side. Anchor on `task_<id> pr=` so (a) `task_1` does not substring-match `task_10`, and (b) the wait resolves only on the supervisor's merged-and-gated signal (`pr=` present), not an agent-finished `DONE task_<id>`:
   ```bash
   until paseo chat read "wf-$workflowId" | grep -qE "DONE task_${blockerId} pr="; do
     paseo chat wait "wf-$workflowId" --timeout 30m
   done
   ```

This preserves the dependency graph with verified completion: dependents unblock only on merged-and-gated, not agent-finished. **This is a gap, not a feature** — live daemon edges would be superior; chat rooms are the closest available surface.

---

### FAILOVER → Schedules + Manual Switch

Core's `FAILOVER` state machine maps to:

1. **Quota probing schedule:**
   ```bash
   paseo schedule create --every 15m "probe-primary-quota" \
     "Check primary provider quota; if restored, switch agents back"
   ```

2. **Model switching:**

   **Gap documentation:** Paseo 0.1.110 has NO `update_agent` model-mutation API. The adapter cannot change the model of running agents. The closest mapping is:

   - **New agents:** Create on the currently-active provider (primary or secondary)
   - **In-flight agents:** Cannot switch models mid-flight. They complete on their original provider.
   - **Recovery:** When quota restores, only **new** agents switch back to primary.

   **Document this as a runtime limitation.** The core abstract primitive assumes live model-switch; this adapter documents that Paseo 0.1.110 lacks that surface.

3. **Failover armed condition:** Only when primary and secondary are on **different providers**. Same provider = `disabled` (quota outage exhausts both).

---

### REASONING_DEPTH → `--thinking` flag

Core's `REASONING_DEPTH` mapping uses `paseo provider models <provider> --thinking`:

```bash
paseo provider models "$provider" --thinking --json
```

Map user choices to thinking option IDs:
- "Low" → lowest ID in array
- "Medium" → lower-middle ID
- "High" → upper-middle ID  
- "Maximum" → highest ID

If provider has **no** thinking options (empty array), omit `--thinking` flag and inform user reasoning-depth is not adjustable for that model.

---

### GATE → Independent Reviewer (derived verdict) + Branch Protection

Core's `GATE` primitive maps to **two layers** (Paseo 0.1.110 has no daemon gate). Post-ADR-0007 the trigger is no longer a self-declared `VERDICT` the implementer appends — it is an **independent reviewer** the loop invokes.

**1. Reviewer layer (independent, derived verdict):** The **loop driver** — not the implementer — invokes the secondary-model reviewer. Five independence axes (ADR-0007 §2), mapped to Paseo 0.1.110:

```bash
# (a) Render the FIXED, system-authored prompt from diff + spec ONLY.
#     scripts/reviewer.py has NO parameter for commit messages or PR prose.
prompt=$(python3 scripts/reviewer.py build-prompt \
  --diff <(git diff "$base..$head") \
  --spec <(extract-ticket-spec "$issue") \
  --sha "$head" --changed-files <(git diff --name-only "$base..$head"))

# (b) Run the SECONDARY model (different provider) in a SEPARATE worktree.
paseo worktree create "review-$pr" --base "$head"
paseo run --provider "$secondary_provider" --model "$secondary_model" \
  --worktree "review-$pr" --base "$head" --detach "$prompt" > reviewer.out

# (c) Strip any verdict, check coverage, format the sha-tagged findings comment.
python3 scripts/reviewer.py format-findings \
  --findings reviewer.out --sha "$head" \
  --changed-files <(git diff --name-only "$base..$head") > findings.md

# (d) Post findings from the reviewer's DEDICATED GitHub-App identity (the
#     implementer lacks this token). The sha marker lets review-verdict (T3)
#     select the latest current review.
GH_TOKEN="$REVIEWER_APP_TOKEN" gh pr comment "$pr" --body-file findings.md
```

The reviewer emits **only** severity-tagged findings across the two axes (Standards, Spec) — never a `VERDICT` line. The verdict is *derived* from those findings by `scripts/verdict.py`. The same implementer then fixes against the findings handed to it verbatim; a finding is "resolved" only when it disappears from the next independent review (T5b).

**2. Enforcement layer (branch protection):** GitHub branch protection requires CI status check:

```bash
gh api -X PUT repos/CaicoLeung/skills/branches/main/protection \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["validate-skills"]
  },
  "enforce_admins": true
}
EOF
```

A PR cannot merge unless `validate-skills` (which runs `scripts/validate-skills.py`) passes.

**Reality:** Enforcement lives at GitHub branch protection. Today it requires `validate-skills`; the `review-verdict` context (which reads the reviewer App's sha-tagged findings and runs `verdict.py`) is added by T3, after which branch protection requires both. Paseo 0.1.110 has no daemon gate. See [ADR-0003](../../docs/adr/0003-branch-protection-quality-gate.md) and [ADR-0007](../../docs/adr/0007-derived-verdict-and-reviewer-independence.md).

**3. Merge step (merge policy):** Once the close-out gate holds (derived verdict passed + CI green), the **loop driver** — never the implementer — enables GitHub auto-merge, per `mergePolicy` from the core plan:

- **`"auto"`** → the **loop** enables GitHub auto-merge on the PR: `gh pr merge --auto --squash --delete-branch`. GitHub performs the merge the instant branch-protection rules pass.
- **`"wait-for-human"`** (default) → the PR is opened and auto-merge is **not** enabled, leaving it for a human to review and merge.

The implementer never performs the merge itself — merge authority is branch protection + auto-merge, flipped on by the loop only after the derived verdict passes (ADR-0007). Squash + delete-branch is the fixed adapter default (not a launch question). See [ADR-0005](../../docs/adr/0005-auto-merge-via-branch-protection.md).

---

### Workspace → `paseo worktree create`

Core's workspace spec maps to:

```bash
paseo worktree create "$workspace_name" --base "$base_branch"
```

---

### SUPERVISE → `loop.py supervise` driven by `paseo loop` / `paseo schedule` + Chat Room + `paseo send`

Core's `SUPERVISE` primitive maps to a long-lived supervisor surface that
observes each task's gate (`gh pr view --json mergeStateStatus` + the commit's
status contexts), classifies deviations via the triage state machine
(`scripts/supervise.py: plan_supervise`), and either **re-dispatches the leaf
agent** (`paseo send` with the specific failure) or **posts an `ESCALATE`
signal** a human consumes. Completion is merged-and-gated only.

**Implementation shape:**

1. **Supervisor lifecycle:** A `paseo loop` (preferred) or a `paseo schedule`
   re-invokes the supervisor's planner once per poll interval. Each invocation
   is a thin, idempotent I/O step — read the gate, decide, act — exactly as
   the routing and close-out drivers drive one turn. The supervisor's state
   (per-task `retries_used`, `signal_elapsed_sec`) lives in the workflow chat
   room's history or a workflow-state file, not in the daemon.
   ```bash
   paseo loop --every 60s \
     "python3 scripts/loop.py supervise $issue --pr $pr --task-id $taskId \
        --chat-room wf-$workflowId --leaf-agent $leafAgentId \
        --signal-elapsed-sec $(( $(date +%s) - $agentFinishedAt )) \
        --retries-used $retriesUsed"
   ```
   The `paseo loop` / `paseo schedule` choice is operational — both
   re-invoke; `paseo loop` is the closer fit for a per-task watcher.

2. **Observe gate state** (the supervisor reads platform state, never agent
   internals):
   ```bash
   # PR merge state — state, mergeStateStatus, mergedAt, headRefOid
   gh pr view "$pr_number" --json state,mergeStateStatus,mergedAt,headRefOid

   # Required check's status — absence-of-signal if the context never appears
   gh api "repos/OWNER/REPO/commits/$headRefOid/status" \
     --jq '.statuses[] | select(.context=="validate-skills") | .state'
   ```
   These two reads compose into a `supervise.GateState` (`scripts/loop.py:
   read_gate_state`). A check that has not appeared in the status list within
   `signal_deadline_sec` is `check_missing` — the absence-of-signal deviation.

3. **Triage** (`supervise.plan_supervise` — pure, total, unit-tested):
   - **COMPLETE** (`pr_state=MERGED` AND `check_state=success`) → post the
     completion signal. Dependents filter on `DONE task_$id pr=`.
   - **WAIT** (no deviation, deadline not crossed) → no command; observe
     again next interval.
   - **REDISPATCH** (mechanical/transient, retries remain) → `paseo send`
     the leaf with the specific failure (below).
   - **ESCALATE** (genuine/ambiguous, OR retries exhausted) → post the
     `ESCALATE` signal (below).

4. **Completion signal** (supervisor → chat room):
   ```bash
   paseo chat post "wf-$workflowId" \
     "DONE task_$taskId pr=$pr_url merged_at=$timestamp"
   ```
   Dependents wait on this exact token (`paseo chat wait` has no `--filter`
   in 0.1.110 — filter client-side, anchored on `DONE task_$id pr=` so
   `task_1` does not substring-match `task_10`, and the wait resolves only on
   the supervisor's merged-and-gated signal, not the leaf's agent-finished
   `DONE task_$id`).

5. **Redispatch action** (mechanical/transient — `paseo send` to the leaf):
   ```bash
   # The leaf keeps its implement-turn workspace; send hands it the failure.
   paseo send --agent "$leafAgentId" --worktree "$leafWorkspace" \
     --base "$base_branch" --detach \
     "SUPERVISE re-dispatch for $taskId ($pr_url). <specific deviation detail>"
   ```
   The detail is the supervisor's observation verbatim — e.g. *"Required
   check `validate-skills` has not reported within the 300s deadline; confirm
   the workflow that emits that context still exists"* (the check-name-drift
   pattern), or *"GitHub reports mergeStateStatus=DIRTY; rebase onto the base
   branch"*. **No "fix all issues" prose** — a summary is exactly where a
   leaf could quietly decide not to investigate. The leaf pushes to the same
   branch; the supervisor re-observes the gate on its next interval. A
   deviation is "resolved" only when it disappears from the NEXT observation,
   never by the leaf's self-declaration.

6. **Escalation signal** (genuine/ambiguous, OR retries exhausted — chat room
   + durable issue comment):
   ```bash
   paseo chat post "wf-$workflowId" \
     "ESCALATE task=$taskId pr=$pr_url deviation=$deviation blocked=[$dependentIds...] reason=$reason"
   gh issue comment "$issue" --repo "$repo" --body \
     "ESCALATE task=$taskId pr=$pr_url deviation=$deviation blocked=[$dependentIds...] reason=$reason"
   ```
   The chat room is the immediate signal; the issue comment is the durable
   one (the chat room scrolls, the issue stays). A human must intervene; the
   supervisor does NOT auto-close.

**Bounded retry budget mapping.** `MAX_GATE_RETRIES=2` (default). A
mechanical/transient deviation that does not converge after two redispatches
auto-escalates — the cap is the never-wait-forever guarantee. Genuine
(`merge_blocked`) and ambiguous (unrecognized state) deviations escalate at
any retry count. The driver advances `retries_used` per executed REDISPATCH.

**Absence-of-signal mapping.** A required check that has not reported within
`signal_deadline_sec` (default 300s) is `check_missing` (mechanical), not a
silent wait. This is the exact `wf-skills-1` stall: the workflow was renamed
so the required check never appeared, the leaf went idle, nothing detected
it. The supervisor's per-poll composition (`commit_status_contexts` +
`signal_elapsed_sec` vs `signal_deadline_sec`) detects it and redispatches
the leaf within bounded time.

**Subgraph isolation mapping.** Paseo 0.1.110 has no daemon-level dependency
edges. The supervisor computes the blocked subgraph from the dependency graph
passed at workflow generation and includes it in the `ESCALATE` signal's
`blocked=[...]`. Dependent tasks filter for their blocker in that list;
independent tasks proceed without waiting.

**Completion semantics.** Dependents unblock on the supervisor's
`DONE task_$taskId pr=...` signal, NOT on the leaf's `DONE task_$taskId`.
The supervisor posts it only after merged-and-gated (PR merged AND required
check `success`).

**Gap documentation.** Paseo 0.1.110 has no daemon supervisor and no
`notifyOnMerge` edge. The adapter implements the supervisor as a `paseo loop`
re-invoking a stateless planner that observes the GitHub API. This is the
correct pattern — polling *gate state* ≠ polling *agent internals* (see
ADR-0006 §4 for the honest reconciliation of the "don't poll" guidance).

## Inputs

Same as core (passes through to `ticket-workflow-core`):

```json
{
  "project": "...",
  "tickets": [...],
  "epics": [...],
  "metadata": {}
}
```

## User Interaction

Delegate model selection questions to core, then execute plan:

1. **Call core** to generate workflow plan (abstract primitives)
2. **Map plan to Paseo surface** using the mappings above
3. **Execute workflow:**
   - Create workflow chat room
   - Create worktrees and agents (using `paseo run`)
   - Set up quota probe schedule (if failover armed)
   - Create supervisor agent (polls PR/CI state, posts completion/stuck-gate signals)
   - Return workflow ID, agent IDs, and supervisor ID

## Output

```json
{
  "workflowId": "...",
  "project": "...",
  "primaryModel": { "provider": "...", "model": "...", "modeId": "..." },
  "secondaryModel": { "provider": "...", "model": "...", "modeId": "..." },
  "reasoningDepth": "...",
  "baseBranch": "...",
  "tasks": [
    {
      "ticket": "...",
      "agentId": "...",
      "model": { "provider": "...", "model": "...", "modeId": "..." },
      "secondary": { "provider": "...", "model": "...", "modeId": "..." },
      "thinking": "..."
    }
  ],
  "failover": "armed" | "disabled",
  "merge": "auto" | "wait-for-human",
  "status": "...",
  "chatRoom": "wf-...",
  "quotaProbeSchedule": "probe-primary-quota",
  "supervisor": {
    "agentId": "...",
    "boundedWindow": { "intervalSec": 60, "maxWaitSec": 3600 },
    "completionCondition": { "type": "merged-and-gated", "requiredCheck": "validate-skills" }
  }
}
```

## Paseo CLI Reference

Discoverable commands (use `--help` — do not hardcode):

```bash
paseo run --help                    # EXECUTE
paseo chat --help                   # DEPENDS_ON coordination, supervisor signals
paseo schedule --help               # FAILOVER quota probing
paseo worktree --help               # Workspace creation
paseo provider ls --json            # Provider enumeration
paseo provider models <p> --thinking --json  # REASONING_DEPTH
paseo daemon status                 # Runtime confirmation
```

**GitHub CLI (supervisor uses these):**
```bash
gh pr view <number> --json state,mergedAt,headRefOid  # Poll PR state
gh api repos/OWNER/REPO/commits/$sha/status           # Poll CI checks
gh pr merge --auto --squash --delete-branch           # Enable auto-merge
```

**Daemon paths (confirm at runtime):**
- Home: `~/.paseo` (or `PASEO_HOME`)
- Listen: `127.0.0.1:6767` (or `PASEO_LISTEN`)
- Logs: `$PASEO_HOME/daemon.log`
- Health: `GET http://127.0.0.1:6767/api/health`

Never restart daemon without explicit user approval — it kills all running agents.

## Runtime Gaps Documented

| Core Primitive | Paseo 0.1.110 Reality | Adapter Mapping |
|----------------|----------------------|------------------|
| `DEPENDS_ON` with `notifyOnFinish` edge | **Does not exist** | Chat room handoff (`paseo chat post / wait`) |
| `FAILOVER` with live model-switch | **Does not exist** (`update_agent` only metadata) | New agents switch; in-flight agents stay on original model |
| `GATE` as daemon gate | **Does not exist** | Independent reviewer (loop-invoked, secondary model, separate worktree, App identity) + `review-verdict` CI (T3) + GitHub branch protection |
| `SUPERVISE` as daemon supervisor | **Does not exist** | `paseo loop` / `paseo schedule` re-invokes `loop.py supervise` (stateless planner in `supervise.py`); observes gate state via `gh`, redispatches leaf via `paseo send`, posts DONE/ESCALATE to chat room + issue |

Adding a second runtime (e.g., OpenAI, non-Paseo) is a **new adapter file** that consumes the same core workflow plan and maps primitives to its surface. No core changes required.

## Version Changes

0.5.0: DEPENDS_ON chat-room handoff clarified — supervisor posts completion signal only after merged-and-gated, not agent-finished. Two-state completion documented: agent-finished (work submitted) vs merged-and-gated (work verified).
0.4.0: Added SUPERVISE primitive — supervisor agent polls GitHub API, posts merged-and-gated completion, escalates stuck gates within bounded window. Honest reconciliation: polling gate state ≠ polling agents.

## Requirements

Generated workflow must:
- Preserve ticket order
- Preserve dependencies (via chat room coordination)
- Support parallel execution (via chat room waits)
- Fail over new agents on quota exhaustion (if armed)
- Enforce close-out gates (via prompt contracts)
- Supervisor observes PR/CI state, posts completion only on merged-and-gated

## Version Change

0.7.0: SUPERVISE mapping concretized (ADR-0006 §T1 / issue #11). Replaces the timeout-only escalation with an explicit **triage state machine**: mechanical/transient deviations (check name drifted, needs rebase, flaky test) → redispatch the SAME leaf via `paseo send` with the specific failure, bounded by `MAX_GATE_RETRIES=2`; genuine/ambiguous deviations (unsatisfiable branch protection, unknown state) → `ESCALATE` signal at any retry count. **Absence-of-signal** is a first-class deviation: a required check that has not reported within `signal_deadline_sec` (default 300s) is `check_missing`, not a silent wait — this is the exact `wf-skills-1` stall (renamed workflow → check never appeared). Drives `loop.py supervise` (`run_supervise_round`, `run_supervise_trajectory`); pure planner in `scripts/supervise.py`.
0.6.0: GATE mapping changed from self-declared `VERDICT pass|fail` prompt contract to an **independent reviewer** the loop invokes (ADR-0007): loop-invoked, fixed system-authored prompt (`review-prompt.md`) via `scripts/reviewer.py`, secondary model on a different provider, separate worktree, diff+spec input only, findings posted from a dedicated GitHub-App identity. Reviewer emits findings only; verdict is derived. Merge authority moved to the loop (not the implementer).
0.5.1: Fixed DEPENDS_ON wait — `paseo chat wait` (0.1.110) has no `--filter`; dependents now filter client-side (`chat read` + `grep`) anchored on `task_<id> pr=`, so `task_1` no longer matches `task_10` and the wait resolves only on the supervisor's merged-and-gated signal, not agent-finished.
0.5.0: Added subgraph scoping to SUPERVISE — when a blocker is stuck, only its transitive dependents are blocked; independent tasks proceed. Supervisor computes blocked subgraph from dependency graph and posts scoped escalation.
0.4.0: Added SUPERVISE primitive — supervisor agent polls GitHub API, posts merged-and-gated completion, escalates stuck gates within bounded window. Honest reconciliation: polling gate state ≠ polling agents.
0.3.0: Added merge policy option (auto vs wait-for-human) to GATE primitive; maps to GitHub auto-merge.
0.2.0: Refactored from monolithic skill to Paseo adapter consuming `ticket-workflow-core`. Runtime gaps documented honestly.
