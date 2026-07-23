---
name: tickets-to-paseo
description: "Paseo adapter for ticket-workflow-core — maps abstract primitives to Paseo 0.1.110 surface (chat rooms, schedules, prompt contracts)."
version: 0.2.0
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

**1. Trigger layer (prompt contract):** Encode close-out steps in agent prompt:

```
Run /code-review (via the secondary model) before committing.
DO NOT commit or open a PR until the review passes with no CRITICAL or HIGH issues.
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

---

### Workspace → `paseo worktree create`

Core's workspace spec maps to:

```bash
paseo worktree create "$workspace_name" --base "$base_branch"
```

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
   - Return workflow ID and agent IDs

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
  "status": "...",
  "chatRoom": "wf-...",
  "quotaProbeSchedule": "probe-primary-quota"
}
```

## Paseo CLI Reference

Discoverable commands (use `--help` — do not hardcode):

```bash
paseo run --help                    # EXECUTE
paseo chat --help                   # DEPENDS_ON coordination
paseo schedule --help               # FAILOVER quota probing
paseo worktree --help               # Workspace creation
paseo provider ls --json            # Provider enumeration
paseo provider models <p> --thinking --json  # REASONING_DEPTH
paseo daemon status                 # Runtime confirmation
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

Adding a second runtime (e.g., OpenAI, non-Paseo) is a **new adapter file** that consumes the same core workflow plan and maps primitives to its surface. No core changes required.

## Requirements

Generated workflow must:
- Preserve ticket order
- Preserve dependencies (via chat room coordination)
- Support parallel execution (via chat room waits)
- Fail over new agents on quota exhaustion (if armed)
- Enforce close-out gates (via prompt contracts)

## Version Change

0.2.0: Refactored from monolithic skill to Paseo adapter consuming `ticket-workflow-core`. Runtime gaps documented honestly.
