---
name: tickets-to-paseo
description: "Turn ticket data into an executable Paseo workflow — one agent per ticket, gated on /code-review, supervised by the Paseo daemon."
version: 0.1.0
requires:
  - project
  - tickets
  - epics
produces:
  - workflow
  - paseo-agents
---

# Workflow Launcher

This skill receives ticket data — typically from `/to-tickets`, or routed there via `/ask-matt` ([Mattpocock Skills](https://github.com/mattpocock/skills)) — and turns it into an executable Paseo workflow: one agent per ticket, running `/implement` with `/tdd` at the agreed seams and gating each close-out on `/code-review`. The whole graph is supervised by the Paseo daemon.

## Inputs

Expected parameters:

```json
{
  "project": "...",
  "tickets": [...],
  "epics": [...],
  "metadata": {}
}
```

If `project` or `tickets` is empty or missing, do not skip ahead to the model questions — collect them first (see _Input_ question below).

## User Interaction

Before executing the workflow, ask the user up to four questions, in order. Skip the first if the inputs are already populated.

### 0. Input (only if parameters are empty)

If `project` or `tickets` is missing, ask before anything else:

> Please provide the project name and the tickets/epics to plan. You can paste output from `/to-tickets`, or describe the work.

Wait for a non-empty payload, then continue.

---

### 1. Primary Model

Ask:

> Which model would you like to use as the primary execution model?

Do not hardcode candidates — enumerate them live from the Paseo CLI:

1. `paseo provider ls --json` — list providers; keep only those with `"status": "available"`.
2. For each available provider, `paseo provider models <provider> --thinking --json` — its models (and thinking option IDs).

Present the resulting models as the option list, each shown as `Label — provider/model` (e.g. `Claude Opus — claude/opus`). Wait for the user's response.

---

### 2. Secondary Model

Ask:

> Which model should be used as the fallback and reviewer?

Enumerate options the same way as the primary model (`paseo provider ls` → `paseo provider models <provider> --thinking`). The secondary runs `/code-review` and takes over execution when the primary is unavailable (see _Model Failover_).

**Failover needs a different provider.** Quota is tracked per provider, so selecting the same provider as the primary means a quota outage exhausts both — failover is then impossible and `/code-review` becomes a self-review. If the user picks the same provider, warn explicitly and record `failover: "disabled"` (the secondary then acts as reviewer only). Wait for the user's response.

---

### 3. Reasoning Depth

Ask:

> How much reasoning should be applied?

Offer choices, each mapped to one of the thinking option IDs returned by `paseo provider models <provider> --thinking --json` (an ordered list, lowest → highest reasoning):

- Low → the lowest thinking option
- Medium → the lower-middle option
- High → the upper-middle option
- Maximum → the highest thinking option

If the chosen provider/model returns **no** thinking options, omit `thinkingOptionId` entirely (run with the provider default) and tell the user reasoning-depth is not adjustable for that model. Wait for the user's response.

## Execution

After the inputs and the three model answers are collected:

1. **Resolve the model descriptors.** Each selection already carries its `provider/model` string and `modeId` from the live enumeration (see _Primary Model_ / _Secondary Model_), so use those directly — do not re-resolve through a separate tool. The canonical descriptor used everywhere below is `{ provider, model, modeId }`; never hardcode a provider.

2. **Resolve the base branch.** Branch worktrees off the project base branch: read `inputs.metadata.baseBranch`; if absent, fall back to the repository default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`, or the Paseo equivalent); if that is unresolved, ask the user before creating any worktree.

3. **Map each ticket to a worktree + agent (all up-front).** For every ticket, `create_worktree` (branch-off from the base branch resolved above), then `create_agent` with `workspace: { kind: "existing", workspaceId }`, `relationship: { kind: "subagent" }`, and an `/implement` initial prompt that names the ticket. Create **all** agents here — do not defer creation for dependencies.

4. **Preserve the graph by declaring edges, not by delaying creation.** Ticket dependencies become Paseo edges declared at creation: for each dependency, set a `notifyOnFinish` edge blocker → dependent. `notifyOnFinish` is a per-edge dependency attribute — it both gates the dependent's start (the daemon holds a dependent until all its blockers finish) and emits the completion notification the clients consume — so order, dependencies, priorities, and milestones (labels) are preserved without creating agents lazily.

5. **Set runtime settings (full descriptor).** Every task gets its primary model descriptor `{ provider, model, modeId }`, its secondary descriptor (fallback/reviewer), and reasoning depth (`thinkingOptionId`, per the mapping in _Reasoning Depth_ — omitted when the provider has no thinking options). For Codex fast mode, pass `settings: { features: { "fast_mode": true } }`.

6. **Encode the close-out gate in the `/implement` prompt contract.** Because `create_agent` is the submit and the daemon owns the async lifecycle, there is no separate pre-commit hook — so the gate is enforced by the initial prompt: instruct each agent to run `/code-review` (via the secondary model) and **not** commit or open a PR until it passes, with `/tdd` driven at the seams agreed during `/grill-with-docs`. This is prompt-contract enforcement, not a daemon gate.

7. **Submit.** `create_agent` is the submit — the Paseo daemon then owns lifecycle, state, and the WebSocket the mobile/desktop clients consume. There is no separate submit call.

8. **Return** the workflow identifier (root agent/workspace id) plus the per-ticket agent ids.

## Model Failover

The primary model is the default execution model for every task. Failover is **armed only when the primary and secondary are on different providers** (see _Secondary Model_); if they share a provider, a quota outage exhausts both, so failover stays `disabled` and the secondary acts as reviewer only.

Quota is provider-specific (calendar month, rolling window, or daily), so drive every transition off a real quota signal, never off a fixed calendar schedule:

- **Primary quota exhausted.** When the primary returns a quota/billing error (or a quota probe reports zero remaining), switch new **and** in-flight tasks to the secondary. Apply this live to running agents with the full descriptor — `update_agent { settings: { model: { provider, model, modeId } } }` (provider + modeId, not a bare string, or the daemon cannot target the correct provider) — and create new agents on the secondary provider.
- **Primary quota resets.** Switch back **only after a quota probe confirms restoration** on the primary provider (do not assume a billing-period boundary): `update_agent` the running agents back to the primary descriptor, and create new agents on the primary again. Drive the probe on a short health-check cadence rather than a fixed weekly time — e.g. `paseo schedule create --every 15m "probe primary quota; if restored, switch agents back to primary"` (discover the real schedule/quota verbs with `paseo schedule --help` and `paseo provider --help`).
- **Reviewer role preserved.** While the primary is healthy, the secondary still runs `/code-review`; it only takes over execution during a primary outage.

Switching never loses in-flight work — `update_agent` changes runtime settings without restarting the agent's workspace.

## Paseo CLI

The `paseo` CLI is a thin wrapper over the daemon and mirrors the tool surface. Use whichever is in reach:

```bash
paseo run --provider codex/gpt-5.4 --mode full-access --worktree feat/x "$(cat ticket-prompt.md)"
paseo send <agent-id> "run /code-review against main"
paseo ls                 # agents
paseo worktree ls        # worktrees
paseo schedule create --every 15m "probe primary quota; if restored, switch agents back to primary"
```

Discover the rest with `paseo --help` and `paseo <cmd> --help`. If `paseo` is not on PATH but the desktop app is installed, the bundled binary is conventionally at one of (verify the path exists before relying on it):

- macOS: `/Applications/Paseo.app/Contents/Resources/bin/paseo`
- Linux: `<install-dir>/resources/bin/paseo`
- Windows: `C:\Program Files\Paseo\resources\bin\paseo.cmd`

Offer to symlink it to `~/.local/bin/paseo` if the first-run hook didn't — never do it silently.

**Daemon & state.** These are conventional defaults — confirm them at runtime via `paseo daemon status` and `paseo --help` before relying on them, rather than assuming. Typical: listen `127.0.0.1:6767` (`PASEO_LISTEN`); home `~/.paseo` (`PASEO_HOME`); daemon log `$PASEO_HOME/daemon.log`; agent state `$PASEO_HOME/agents/<id>.json`; health `GET http://127.0.0.1:6767/api/health`. Debug in order: `tail -n 200 ~/.paseo/daemon.log` → `paseo daemon status` → `curl -s localhost:6767/api/health`. Never restart the daemon without explicit user approval — it kills every running agent.

**Async by default.** Agents take 10–30+ minutes. Keep the `notifyOnFinish` edges intact (do not disable completion notifications); do not poll `paseo ls` to "check on" a running agent — the notification arrives on its own.

## Requirements

The generated workflow must:

- preserve ticket order
- preserve dependencies
- support parallel execution where possible
- fail over to the secondary model on primary quota exhaustion, and recover automatically when quota resets (armed only when primary/secondary differ by provider)

These are delivered by the workflow running **under the Paseo daemon**, not hand-rolled by this skill. The daemon owns agent lifecycle and the WebSocket the clients consume, so the remaining capabilities are satisfied through daemon-level controls and its status API — discover the exact verbs with `paseo --help` / `paseo <cmd> --help` rather than assuming names:

- allow pausing / resuming / cancellation → daemon agent-lifecycle controls
- expose execution progress / logs / task status → daemon status API + per-agent state
- support live updates for the Paseo mobile client → the daemon WebSocket the clients already consume

## Output

Return:

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
  "failover": "armed",
  "status": "..."
}
```

Derive `failover` and `status` from daemon state, not constants: `failover` is `"armed"` only when primary and secondary differ by provider (otherwise `"disabled"`); `status` reflects the workflow's real state (e.g. `created`, `running`, `partial`, `failed`) read from the daemon rather than the literal `"created"`.
