---
name: tickets-to-paseo
description: "Paseo adapter for ticket-workflow-core — maps abstract primitives to Paseo 0.1.110 surface (chat rooms, schedules, prompt contracts, supervisor)."
version: 0.5.0
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

2. **Post completion signals:** After an agent finishes, post to chat:
   ```bash
   paseo chat post "wf-$workflowId" "DONE task_$taskId"
   ```

3. **Dependent agents wait:** Dependent tasks use `paseo chat wait` to block until blocker posts completion:
   ```bash
   paseo chat wait "wf-$workflowId" --filter "DONE task_$blockerId"
   ```

This preserves the dependency graph without daemon-level edges. **This is a gap, not a feature** — live daemon edges would be superior; chat rooms are the closest available surface.

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

### GATE → Prompt Contract + Branch Protection

Core's `GATE` primitive maps to **two layers** (Paseo 0.1.110 has no daemon gate):

**1. Trigger layer (prompt contract):** Encode close-out steps in agent prompt with verdict protocol:

```
Before committing, run a code review via the secondary model. The reviewer MUST respond with a verdict in this format:

VERDICT pass
[optional: preceding lines list issues as [file:line]: <severity>: <summary>]

OR

VERDICT fail
[file:line]: <severity>: <issue summary>
...

Severity levels: CRITICAL, HIGH, MEDIUM, LOW.
Pass = no CRITICAL or HIGH issues. MEDIUM/LOW are warnings only.

Loop fix → re-review until VERDICT pass. Do NOT commit or open PR until you see VERDICT pass.
If the reviewer fails to emit a verdict, treat it as VERDICT fail and re-invoke with explicit format request.
```

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

**Reality:** Enforcement lives at GitHub branch protection. The prompt contract is only the trigger. Paseo 0.1.110 has no daemon gate. See [ADR-0003](../../docs/adr/0003-branch-protection-quality-gate.md).

**3. Merge step (merge policy):** Once the close-out gate holds (review passed + CI green), the agent's action depends on `mergePolicy` from the core plan:

- **`"auto"`** → the agent enables GitHub auto-merge on its PR: `gh pr merge --auto --squash --delete-branch`. GitHub performs the merge the instant branch-protection rules pass.
- **`"wait-for-human"`** (default) → the agent opens the PR and does **not** enable auto-merge, leaving it for a human to review and merge.

The agent never performs the merge itself — merge authority is branch protection + auto-merge. Squash + delete-branch is the fixed adapter default (not a launch question). See [ADR-0005](../../docs/adr/0005-auto-merge-via-branch-protection.md).

---

### Workspace → `paseo worktree create`

Core's workspace spec maps to:

```bash
paseo worktree create "$workspace_name" --base "$base_branch"
```

---

### SUPERVISE → Supervisor Agent via `gh` CLI + Chat Room

Core's `SUPERVISE` primitive maps to a supervisor agent that polls PR/CI state via GitHub CLI, posts completion/stuck-subgraph signals to the workflow chat room, isolates blocked tasks so independent tickets proceed.

**Implementation shape:**

1. **Supervisor agent lifecycle:** Created after all leaf agents, runs in dedicated supervisor workspace. Receives dependency graph from workflow plan.

2. **Poll PR state:**
   ```bash
   gh pr view "$pr_number" --json state,mergeable,mergedAt,headRefOid -q '.state'
   ```

3. **Poll CI status:**
   ```bash
   gh api "repos/OWNER/REPO/commits/$commit_sha/status" \
     --jq '.statuses[] | select(.context=="validate-skills") | .state'
   ```

4. **Completion condition:**
   - PR state = `MERGED`
   - CI check = `success`
   - Once met, post to chat room:
     ```bash
     paseo chat post "wf-$workflowId" \
       "DONE task_$taskId pr=$pr_url merged_at=$timestamp"
     ```

5. **Bounded triage window:**
   - Poll every `interval_sec` (default 60s)
   - If not merged-and-gated within `max_wait_sec` (default 3600s):
     - **Compute transitive closure:** Walk dependency graph to find all tasks that (directly or indirectly) depend on the stuck blocker.
     - **Scoped escalation:** Post to chat room:
       ```bash
       paseo chat post "wf-$workflowId" \
         "STUCK_SUBGRAPH blocker=$taskId blocked=[$dependentIds...] pr=$pr_url reason=timeout_after_${max_wait_sec}s"
       ```
   - Independent tasks (not in `blocked` list) ignore this signal and proceed.
   - Continue polling; human fix allows gate to proceed.

6. **Completion semantics:** Dependents unblock on supervisor's `DONE task_$taskId pr=...` signal, not agent's `DONE task_$taskId`. Supervisor posts only after merged-and-gated.

**Subgraph isolation mapping:** Paseo 0.1.110 has no daemon-level dependency edges. The supervisor computes the blocked subgraph from the dependency graph passed at workflow generation and posts a scoped escalation to the chat room. Dependent tasks filter for their blocker in the `blocked` list; independent tasks proceed without waiting.

**Gap documentation:** Paseo 0.1.110 has no daemon supervisor. Adapter implements supervisor as a long-running agent that polls GitHub API. This is correct pattern — polling *gate state* ≠ polling *agent internals*. See ADR-0006.

---

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
| `GATE` as daemon gate | **Does not exist** | Prompt contract trigger + GitHub branch protection enforcement |
| `SUPERVISE` as daemon supervisor | **Does not exist** | Long-running supervisor agent polls GitHub API, posts to chat room |

Adding a second runtime (e.g., OpenAI, non-Paseo) is a **new adapter file** that consumes the same core workflow plan and maps primitives to its surface. No core changes required.

## Requirements

Generated workflow must:
- Preserve ticket order
- Preserve dependencies (via chat room coordination)
- Support parallel execution (via chat room waits)
- Fail over new agents on quota exhaustion (if armed)
- Enforce close-out gates (via prompt contracts)
- Supervisor observes PR/CI state, posts completion only on merged-and-gated

## Version Change

0.5.0: Added subgraph scoping to SUPERVISE — when a blocker is stuck, only its transitive dependents are blocked; independent tasks proceed. Supervisor computes blocked subgraph from dependency graph and posts scoped escalation.
0.4.0: Added SUPERVISE primitive — supervisor agent polls GitHub API, posts merged-and-gated completion, escalates stuck gates within bounded window. Honest reconciliation: polling gate state ≠ polling agents.
0.3.0: Added merge policy option (auto vs wait-for-human) to GATE primitive; maps to GitHub auto-merge.
0.2.0: Refactored from monolithic skill to Paseo adapter consuming `ticket-workflow-core`. Runtime gaps documented honestly.
