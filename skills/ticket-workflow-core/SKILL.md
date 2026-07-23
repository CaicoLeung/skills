---
name: ticket-workflow-core
description: "Runtime-neutral core for ticket-driven workflows — abstract primitives for execution, dependencies, failover, reasoning depth, gates, and supervision."
version: 0.4.0
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

Declare a dependency between tasks: a dependent waits until all its blockers finish and are **merged-and-gated** (PR merged to base branch AND close-out gate passed).

**Abstract shape:**
```
DEPENDS_ON dependent <- blocker:
  edge_type: "merged-and-gated" | "agent-finished"
  notify: bool
```

**Completion semantics:** By default, `edge_type: "merged-and-gated"`. The blocker is NOT complete until its PR merges AND the required CI check passes. Dependents unblock on verified work, not agent-finished.

**Subgraph scoping:** When a blocker is stuck (gate not converging / not merging within bounded window), only the **transitive closure** of that blocker's dependents are blocked. Independent tasks (no path to the blocker in the DAG) proceed normally. Supervisor computes the blocked subgraph and posts scoped escalation.

**Fallback:** `edge_type: "agent-finished"` for pre-supervisor workflows or non-PR tasks. Not recommended for PR-based workflows — unblocks on unverified work.

**Runtime mapping:** Adapters map to available primitives (chat rooms, daemon edges, supervisor coordination). See SUPERVISE for merged-and-gated enforcement and subgraph isolation.

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

Enforce close-out gates before task completion (e.g., `/code-review` must pass). Convergent verdict protocol: gate fails until reviewer emits explicit pass.

**Abstract shape:**
```
GATE task:
  type: "review"
  reviewer: "secondary_model"
  verdict_schema:
    format: "VERDICT pass|fail"
    issues_format: "[file:line]: <severity>: <summary>"
    severity_levels: ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
  convergence_rule:
    pass: "no CRITICAL or HIGH issues"
    fail: "any CRITICAL or HIGH issue"
    loop: "fix → re-review until VERDICT pass"
  action:
    - type: "block_completion"
      until: "verdict_pass"
    - type: "merge"
      policy: "auto" | "wait-for-human"
```

**Verdict protocol:** Reviewer MUST emit final line `VERDICT pass` or `VERDICT fail`. Preceding lines list issues as `[file:line]: <severity>: <summary>`. Gate is NOT satisfied by review execution alone — only by explicit `VERDICT pass`. Non-convergence (no verdict, or `VERDICT fail` with CRITICAL/HIGH) is a failure that surfaces, not a silent stall.

**Runtime mapping:** Adapters encode the verdict schema and convergence rule in the prompt contract that invokes the secondary-model reviewer. The primary agent loops fix → re-review until `VERDICT pass`.

---

### SUPERVISE

Supervisor role observes gate/merge state for a set of tasks, declares completion only on **merged-and-gated** (PR merged to base branch AND required CI checks passed), escalates within bounded window on stuck gates, isolates stuck subgraphs so independent tasks proceed.

**Abstract shape:**
```
SUPERVISE workflow:
  tasks: [task_ids...]
  dependencies: { dependent_id: [blocker_ids...] }
  base_branch: string
  bounded_window:
    interval_sec: 60
    max_wait_sec: 3600
    escalation_target: workflow_chat_room
  completion_condition:
    type: "merged-and-gated"
    required_check: "validate-skills"
  escalation_action:
    type: "post_stuck_gate_alert"
    format: "STUCK_SUBGRAPH blocker=$taskId blocked=[$dependentIds...] pr=$pr_url reason=$reason"
```

**Semantics:**
- Supervisor polls PR and CI state (via adapter API) — NOT agent internals.
- Completes only when all tasks' PRs are merged AND required CI checks passed.
- Stuck gate detection: after `max_wait_sec`, compute transitive closure of blocked tasks, escalate to chat room.
- **Subgraph isolation:** Only transitive dependents of the stuck blocker are blocked; independent tasks proceed normally.
- Polling gate state is NOT the "don't poll agents" anti-pattern — that warned against polling agent internals; gates are platform state you MUST observe because stuck = absence of notification.

**Completion signal:** When task is merged-and-gated, supervisor posts:
```
DONE task_$taskId pr=$pr_url merged_at=$timestamp
```
Dependents wait for this signal, not agent-finished.

**Escalation signal:** When task stuck beyond `max_wait_sec`, supervisor posts:
```
STUCK_SUBGRAPH blocker=$taskId blocked=[$dependentIds...] pr=$pr_url reason=timeout_after_${max_wait_sec}s
```
Dependents in `blocked` list wait on this blocker; others ignore.

**Honest reconciliation:**
- DON'T poll agents (use `notifyOnFinish` / chat-room signals).
- DO poll gate state (PR/CI) via platform API — supervisor's job.
- Stuck = absence of signal; bounded window is the only way to detect it.
- **Isolated blockage:** One stuck PR does NOT freeze the entire frontier — only its transitive dependents.

**Runtime mapping:** Adapters implement supervisor via their git host's API (e.g., `gh pr view`, `gh api` for GitHub). Bounded window interval and timeout are configurable defaults. Subgraph computation uses the dependency graph passed at workflow generation.

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
