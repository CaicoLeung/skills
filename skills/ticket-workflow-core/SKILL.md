---
name: ticket-workflow-core
description: "Runtime-neutral core for ticket-driven workflows — abstract primitives for execution, dependencies, failover, reasoning depth, gates, and supervision."
version: 0.7.0
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

**Two completion states:**
- `merged-and-gated`: PR merged to base branch AND gate passed (CI green). Supervisor observes this state, posts completion signal. This is the default for PR-based workflows.
- `agent-finished`: Agent posted `DONE` at turn-end. PR may not exist; gate may not have run. Fallback for pre-supervisor workflows or non-PR tasks — unblocks on unverified work.

**Critical distinction:** In `wf-skills-1`, DEPENDS_ON resolved to agent-finished — dependents unblocked on unverified work (gap #2). Post-T1, merged-and-gated is the default: the supervisor observes platform state (PR/CI) and posts `DONE task_$taskId pr=$pr_url` only after verification.

**Subgraph scoping:** When a blocker is stuck (gate not converging / not merging within a bounded window), only the **transitive closure** of that blocker's dependents are blocked. Independent tasks (no path to the blocker in the DAG) proceed normally. The supervisor computes the blocked subgraph and posts scoped escalation (gap #3).

**Runtime mapping:** Adapters map to available primitives. Paseo 0.1.110 uses supervisor + chat rooms: the supervisor posts a completion signal only after merged-and-gated, and scopes stuck subgraphs rather than freezing the frontier. Future runtimes with daemon edges would wire `notifyOnMerge` directly.

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

Enforce close-out gates before task completion (e.g., `/code-review` must pass). Derived verdict protocol (ADR-0007): verdict is computed from severity-tagged findings, never self-declared.

**Abstract shape:**
```
GATE task:
  type: "review"
  reviewer: "secondary_model"
  verdict_protocol: "derived"
  findings_format: "[file:line]: <severity>: <summary>"
  severity_levels: ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
  explicit_ok_format: "file: OK"
  verdict_rule:
    pass: "no CRITICAL or HIGH findings AND every changed file has a finding or explicit OK"
    fail: "any CRITICAL or HIGH finding OR any changed file lacks coverage"
  action:
    - type: "block_completion"
      until: "verdict_pass"
    - type: "merge"
      policy: "auto" | "wait-for-human"
```

**Derived verdict protocol (ADR-0007):** Reviewer emits **only structured findings** across the two `/code-review` axes (Standards, Spec). Format: `[file:line]: SEVERITY: summary` where `SEVERITY ∈ {CRITICAL, HIGH, MEDIUM, LOW}`. Explicit OK: `file: OK`. No `VERDICT pass|fail` line — the verdict is computed by a pure function (`derive_verdict(findings_text, changed_files)`).

**Verdict rule:** `pass = (no CRITICAL and no HIGH) AND (every changed file has a finding or explicit OK)`. CRITICAL/HIGH findings block. MEDIUM/LOW are non-blocking warnings. Coverage floor: a changed file with neither finding nor OK is a gap that fails.

**Reviewer independence (ADR-0007 §2) — concretized:** The reviewer is the findings producer, separated from the implementer on five axes, each enforced structurally rather than by instruction:

| axis | guarantee | where it lives |
| --- | --- | --- |
| invoker | the loop driver invokes the review, never the implementer | loop driver (ADR-0008) |
| prompt | a **fixed, system-authored** template the implementer never sees or edits | `skills/ticket-workflow-core/review-prompt.md` |
| model | the **secondary model** on a **different provider** than the implementer | adapter (e.g. `paseo run --provider <secondary>`) |
| workspace | a **separate isolated worktree** | adapter (`paseo worktree`) |
| input | **diff + ticket spec only** — never the author's commit messages or PR prose | `scripts/reviewer.py build_review_prompt` (no author-prose parameter) |

The reviewer emits **only** findings (no `VERDICT` line). `scripts/reviewer.py` is the runtime-neutral reviewer core: it renders the fixed template from diff + spec only, strips any self-declared verdict line (defense in depth), parses findings via `verdict.py` (single source of truth for the format), and formats the sha-tagged findings comment the reviewer's GitHub-App identity posts. The loop posts that comment; the `review-verdict` CI (T3) reads it and runs `verdict.py`.

**Runtime mapping:** Adapters invoke the secondary-model reviewer with the fixed prompt template (`review-prompt.md`) via the reviewer core (`reviewer.py`), in a separate worktree, on a different provider. Findings are transported as a sha-tagged PR comment from the reviewer's dedicated GitHub-App identity and evaluated by `verdict.py`. The CI check enforces the computed verdict. Reviewer independence ensures no agent can forge its own verdict (ADR-0007).

---

### SUPERVISE

Supervisor role owns the gap between **agent-finished** (leaf posted `DONE` at
turn-end) and **merged-and-gated** (PR merged to base branch AND required CI
check genuinely passed). Nothing else owns that gap: a stuck gate produces an
*absence of signal* that an agent-finished dependent would wait on forever
(the `wf-skills-1` stall — a renamed workflow meant the required check never
appeared, the leaf went idle, and nothing detected it).

The supervisor, per task, watches gate state until merged-or-escalated. It
**detects** deviations (including absence-of-signal), **classifies** them via
an explicit triage state machine, and **acts** within a bounded retry budget
that auto-escalates on exhaustion — never wait-forever.

**Abstract shape:**
```
SUPERVISE workflow:
  tasks: [task_ids...]
  dependencies: { dependent_id: [blocker_ids...] }
  base_branch: string
  bounded_window:
    interval_sec: 60
    signal_deadline_sec: 300      # absence-of-signal deadline (per task)
    max_wait_sec: 3600            # outer wall clock (informational)
    escalation_target: workflow_chat_room
  completion_condition:
    type: "merged-and-gated"      # PR merged AND required check passed
    required_check: "validate-skills"
  retry_budget:
    max_gate_retries: 2           # redispatch cap; auto-escalate on exhaustion
  triage:                         # the fix / escalate state machine
    mechanical: [check_missing, merge_dirty, merge_behind]  # -> redispatch leaf
    transient:  [check_failing]                            # -> redispatch leaf
    genuine:    [merge_blocked]                            # -> escalate (any retry)
    ambiguous:  [unknown]                                  # -> escalate (default-safe)
  redispatch_action:
    type: "send_to_leaf_with_failure"
    detail_format: "the specific deviation, verbatim — no 'fix all' prose"
  escalation_action:
    type: "post_escalate_signal"
    format: "ESCALATE task=$taskId pr=$pr_url deviation=$deviation blocked=[$dependentIds...] reason=$reason"
```

**Semantics:**
- Supervisor polls PR and CI state (via adapter API) — NOT agent internals.
- **Completion is merged-and-gated only.** `pr_state=MERGED` AND
  `check_state=success`. A merged PR with no check is NOT complete (the gate
  did not genuinely pass) — this is the original sin in reverse, and the
  supervisor refuses to read it as success.
- **Triage state machine.** Every deviation maps to exactly one bucket:
  - **mechanical** (check name drifted, needs rebase) → redispatch the SAME
    leaf with the specific failure, **bounded by `max_gate_retries`**.
  - **transient** (flaky test, currently failing) → redispatch the leaf
    (the failure could be real or a flap; bounded retries separate the two).
  - **genuine** (unsatisfiable branch protection) → **escalate at ANY retry
    count**. Bounded retries do not apply — the leaf cannot fix this.
  - **ambiguous** (unrecognized state) → **escalate**. Ambiguity defaults to
    escalate, never silent pass — that was the original sin (an agent read a
    blocked-but-passing PR as success).
- **Bounded retry budget auto-escalates.** A mechanical/transient deviation
  that does not converge after `max_gate_retries` redispatches escalates —
  the cap is the never-wait-forever guarantee. Genuine/ambiguous deviations
  skip the budget entirely (escalate immediately).
- **Absence-of-signal is a deviation.** A required check that has not
  reported within `signal_deadline_sec` is `check_missing` (mechanical), not
  a silent wait. This is the exact `wf-skills-1` stall: the check never
  appeared, the agent was already idle, nothing was watching.
- **Subgraph isolation.** When a blocker escalates, only the **transitive
  closure** of its dependents are blocked. Independent tasks (no path to the
  blocker in the DAG) proceed normally.
- Polling gate state is NOT the "don't poll agents" anti-pattern — that
  warned against polling agent internals; gates are platform state you MUST
  observe because stuck = absence of notification.

**Completion signal** (posted only on merged-and-gated):
```
DONE task_$taskId pr=$pr_url merged_at=$timestamp
```
Dependents wait for this signal (filter on `DONE task_<id> pr=`, not the
leaf's own `DONE task_<id>`), not agent-finished.

**Redispatch action** (mechanical/transient, retries remain): re-dispatch the
SAME leaf via the adapter's "send to existing agent" verb (e.g.
`paseo send --agent $leaf_agent_id`) carrying the specific deviation detail
verbatim — no "fix all issues" prose. The leaf pushes to the same branch; the
supervisor re-observes the gate on its next interval and decides again. A
deviation is "resolved" only when it disappears from the NEXT observation,
never by the leaf's self-declaration (mirrors the GATE fix-loop contract).

**Escalation signal** (genuine/ambiguous, OR retries exhausted):
```
ESCALATE task=$taskId pr=$pr_url deviation=$deviation blocked=[$dependentIds...] reason=$reason
```
Posted to the workflow chat room AND as a durable `gh issue comment` (the
chat room scrolls; the issue stays). A human must intervene; the supervisor
does NOT auto-close. Dependents in `blocked` wait on this blocker; others
ignore.

**Honest reconciliation (the "don't poll" guidance):**
- DON'T poll **agents** — use `notifyOnFinish` / chat-room signals. Agent
  internals (CPU, turn state) are none of the supervisor's business.
- DO poll **gate state** (PR merge state, CI check runs) via the platform
  API. This is mandatory — a stuck gate is by definition an *absence of
  notification*, and the bounded window is the only way to detect it.
- The original "don't poll" guidance warned against the former; observing
  gate state is the fix, not the anti-pattern it warned against.

**Runtime mapping:** Adapters implement the supervisor via their git host's
API. The pure planner (`scripts/supervise.py`: `plan_supervise(state,
retries_used, retry_budget)`) is runtime-neutral; the adapter supplies the
I/O (the `gh pr view --json mergeStateStatus` + `gh api commits/$sha/status`
reads, and the `paseo send` / `paseo chat post` / `gh issue comment` writes).
Interval, deadline, and retry budget are configurable defaults. Subgraph
computation uses the dependency graph passed at workflow generation.

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

## Version Changes

0.7.0: SUPERVISE primitive concretized with an explicit triage state machine (mechanical/transient → redispatch leaf; genuine/ambiguous → escalate), a bounded retry budget (`max_gate_retries`) that auto-escalates on exhaustion, and absence-of-signal as a first-class deviation (`check_missing` — a required check that never reports within `signal_deadline_sec`). Pure planner in `scripts/supervise.py` (`plan_supervise`, `GateState`, `SuperviseDecision`); driver in `scripts/loop.py` (`run_supervise_round`, `run_supervise_trajectory`, `supervise` CLI). Completion redefined as merged-and-gated only (PR merged AND check success — a merged PR with no check is NOT complete). ADR-0006 §T1 tracer bullet (issue #11).
0.6.0: GATE reviewer-independence contract concretized (ADR-0007 §2) — five axes (invoker, prompt, model, workspace, input), each enforced structurally. Added the fixed, system-authored review prompt (`skills/ticket-workflow-core/review-prompt.md`) and the runtime-neutral reviewer core (`scripts/reviewer.py`): builds the prompt from diff + spec only, strips self-declared verdicts, and formats sha-tagged findings comments. The reviewer emits findings only; the verdict stays computed.
0.5.0: GATE verdict protocol changed from self-declared to derived (ADR-0007). Removed `VERDICT pass|fail` schema. Verdict is computed by pure function from severity-tagged findings: `pass = (no CRITICAL/HIGH) AND (every changed file has coverage)`. MEDIUM/LOW are non-blocking warnings.
0.4.0: DEPENDS_ON clarified — completion semantics now explicitly distinguish merged-and-gated (default) from agent-finished. Two-state completion documented: supervisor observes merged-and-gated, posts verified signal; dependents unblock on verified work, not agent-finished. Resolves gap #2.
0.3.0: Added SUPERVISE primitive — supervisor observes gate/merge state, declares completion only on merged-and-gated, escalates stuck gates within bounded window.
