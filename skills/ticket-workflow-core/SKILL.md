---
name: ticket-workflow-core
description: "Runtime-neutral core for ticket-driven workflows — abstract primitives for execution, dependencies, failover, reasoning depth, and gates."
version: 0.2.0
requires:
  - project
  - tickets
  - epics
produces:
  - workflow-plan
  - task-specifications
---

# Ticket Workflow Core

Runtime-neutral core for turning ticket data into executable workflows. Defines abstract primitives for execution, dependencies, quota failover, reasoning depth mapping, and close-out gates. This core has **no runtime binding** — it produces a workflow plan that concrete adapters (e.g., `tickets-to-paseo`) map to their surfaces.

## Abstract Primitives

### EXECUTE

Execute a task with a given prompt, model descriptor, and reasoning depth.

**Abstract shape:**
```
EXECUTE task:
  id: string
  prompt: string
  model: { provider, model, modeId }
  reasoningDepth: option_id | null
  workspace: workspace_spec
  metadata: {}
```

**Runtime mapping:** Concrete adapters map `EXECUTE` to their agent creation API (e.g., Paseo's `create_agent` / `run`).

---

### DEPENDS_ON

Declare a dependency between tasks: a dependent waits until all its blockers finish.

**Abstract shape:**
```
DEPENDS_ON dependent <- blocker:
  edge_type: "completion" | "signal"
  notify: bool
```

**Runtime mapping:** Adapters map to their available coordination primitives (e.g., Paseo chat rooms, daemon edges, or manual polling).

---

### FAILOVER

State machine for quota failover: switch execution to secondary provider on primary quota exhaustion, recover when quota restores.

**Abstract shape:**
```
FAILOVER state:
  primary: { provider, model, modeId }
  secondary: { provider, model, modeId }
  active: "primary" | "secondary"
  armed: bool
  transitions:
    - trigger: "quota_exhausted"
      action: "switch_to_secondary"
    - trigger: "quota_restored"
      action: "switch_to_primary"
```

**Requirements:**
- Armed only when primary and secondary are on **different providers** (quota is per-provider)
- Driven by **real quota signals**, not fixed schedules
- Live model-switch for in-flight tasks (if adapter surface supports it)
- New tasks start on currently-active provider

**Runtime mapping:** Adapters map to their quota detection and model-switch capabilities. Some runtimes lack live model-switch — document the gap.

---

### REASONING_DEPTH

Map user-friendly reasoning depth choices to provider-specific thinking option IDs.

**Abstract shape:**
```
REASONING_DEPTH mapping:
  levels: ["Low", "Medium", "High", "Maximum"]
  provider_thinking_options: [id1, id2, ...]
  map:
    "Low" -> lowest_thinking_option_id
    "Medium" -> lower_middle_option_id
    "High" -> upper_middle_option_id
    "Maximum" -> highest_thinking_option_id
```

**Fallback:** If provider has no thinking options, omit `thinkingOptionId` and use provider default.

---

### GATE

Enforce close-out gates before task completion (e.g., `/code-review` must pass).

**Abstract shape:**
```
GATE task:
  conditions:
    - type: "review"
      reviewer: "secondary_model"
      pass_criteria: "no_critical_or_high_issues"
  action:
    - type: "block_completion"
      until: "gate_pass"
    - type: "merge"
      policy: "auto" | "wait-for-human"
```

**Runtime mapping:** Adapters encode gates in prompt contracts or runtime hooks, depending on available surface.

## Inputs

```json
{
  "project": "...",
  "tickets": [...],
  "epics": [...],
  "metadata": {}
}
```

## Output

**Workflow plan** (not an executed workflow — adapters execute):

```json
{
  "workflowId": "...",
  "project": "...",
  "baseBranch": "...",
  "primaryModel": { "provider": "...", "model": "...", "modeId": "..." },
  "secondaryModel": { "provider": "...", "model": "...", "modeId": "..." },
  "reasoningDepth": "...",
  "mergePolicy": "auto" | "wait-for-human",
  "failover": { "armed": true|false, "active": "primary" },
  "tasks": [
    {
      "ticket": {...},
      "taskId": "...",
      "workspace": {...},
      "prompt": "...",
      "model": {...},
      "reasoningDepth": "...",
      "dependencies": ["task_id_of_blocker"],
      "gate": {...}
    }
  ]
}
```

## Workflow Generation Process

1. **Resolve base branch.** From `inputs.metadata.baseBranch`, else repo default, else ask user.

2. **Map tickets to tasks.** Each ticket becomes a task with:
   - Generated `taskId`
   - Workspace spec (branch-off base branch)
   - Prompt naming the ticket

3. **Preserve dependencies.** For each ticket dependency, emit a `DEPENDS_ON` edge.

4. **Configure model descriptors.** Apply primary/secondary models and reasoning depth to each task.

5. **Encode close-out gates.** Each task gets a `GATE` specifying review requirements.

6. **Resolve merge policy.** Ask whether PRs auto-merge or wait for human review once the close-out gate holds. Default = **wait-for-human** (safe-by-default; auto-merge is opt-in). Record as `mergePolicy` on the plan and as the merge action on each task's `GATE`. The policy is runtime-neutral; the adapter maps it to its git host's merge mechanism.

7. **Emit workflow plan.** Return complete plan for adapter execution.

## Adapter Contract

Adapters (e.g., `tickets-to-paseo`) consume this core's workflow plan and map primitives to their runtime surface. Adapters MUST:

1. **Map EXECUTE** to their agent creation API
2. **Map DEPENDS_ON** to available coordination primitives (honest about gaps)
3. **Map FAILOVER** to their quota detection and model-switch capabilities
4. **Map REASONING_DEPTH** using provider thinking options
5. **Map GATE** to prompt contracts or runtime hooks, including the merge policy (`"auto"` / `"wait-for-human"`) → the git host's merge mechanism (e.g., GitHub auto-merge)

## Requirements

Generated workflow plans must:
- Preserve ticket order
- Preserve dependencies
- Support parallel execution where dependencies allow
- Support quota failover (when armed)
- Enforce close-out gates

## Zero/Low Dep

This core is intentionally zero/low-dependency and provider-neutral. No runtime-specific API calls.
