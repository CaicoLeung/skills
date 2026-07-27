# ADR-0004: Runtime-neutral core plus adapter architecture

- **Status:** Accepted
- **Date:** 2026-07-24
- **Supersedes:** —
- **Voided by:** [ADR-0012](./0012-reverse-skill-reframe-loop-driver-tool.md) (the skill surface is deleted — no core skill, no adapter skill)

## Context

`tickets-to-paseo` (v0.1.0) was monolithic and welded to Paseo's surface. Every runtime concern — ticket-to-agent mapping, dependency edges, quota failover, reasoning depth, close-out gates — was expressed in Paseo-specific terms (`create_agent`, `notifyOnFinish`, `update_agent`). Adding a second runtime (e.g., OpenAI, non-Paseo) would require a complete rewrite.

Two shapes were on the table: (a) keep `tickets-to-paseo` monolithic and duplicate for each runtime, or (b) extract a runtime-neutral core expressed as abstract primitives, then reduce `tickets-to-paseo` to a thin adapter that maps those primitives to Paseo's surface.

## Decision

**Runtime-neutral core plus adapter architecture.** Specifically:

1. **Core (`ticket-workflow-core`) — runtime-neutral primitives.**
   - `EXECUTE` — run a task with prompt, model, reasoning depth
   - `DEPENDS_ON` — declare task dependencies with completion semantics
   - `FAILOVER` — quota-failover state machine (primary ↔ secondary)
   - `REASONING_DEPTH` — map user choices to provider thinking options
   - `GATE` — enforce close-out conditions (e.g., `/code-review` must pass)

   The core consumes ticket data and emits a **workflow plan** (not executed). No runtime binding.

2. **Adapter (`tickets-to-paseo`) — maps primitives to Paseo surface.**
   - `EXECUTE` → `paseo run --provider --model --mode --thinking --worktree`
   - `DEPENDS_ON` → chat room handoff (`paseo chat post / wait`)
   - `FAILOVER` → schedule-based quota probing + new-agent model selection
   - `REASONING_DEPTH` → `paseo provider models --thinking` enumeration
   - `GATE` → prompt-contract trigger + GitHub branch protection enforcement (daemon gates don't exist in 0.1.110; see ADR-0003)

3. **Runtime gaps documented honestly.** The adapter explicitly calls out where Paseo 0.1.110 lacks the ideal primitive surface:
   - **No `notifyOnFinish` edge.** Coordination uses chat rooms — a gap, not a feature.
   - **No `update_agent` model mutation.** In-flight agents cannot switch models mid-flight; only new agents get the failover provider.
   - **No daemon gate.** Close-out enforcement is prompt-contract trigger + GitHub branch protection block (not a runtime block; see ADR-0003).

4. **Second runtime = new adapter file, not core rewrite.** Adding an OpenAI adapter means `tickets-to-openai.md` that consumes the same core workflow plan and maps primitives to OpenAI's surface. Core changes are rare and versioned; adapters are plentiful.

## Consequences

- **Core is stable, adapters are volatile.** Runtime API changes touch adapters only. Core primitives change only when the workflow model itself evolves.
- **Skill contract enforced.** Both core and adapter conform to ADR-0002 frontmatter contract; validator proves it.
- **Gaps are visible, not hidden.** Adapters must document where their runtime falls short of the abstract primitive. No pretending `notifyOnFinish` exists in Paseo 0.1.110.
- **Testing is focused.** Core primitive tests are runtime-agnostic; adapter tests are integration tests against the live runtime surface.
- **Multi-runtime is additive.** New runtime → new adapter file. No core changes, no monolithic rewrite.

## Acceptance Criteria (from issue #4)

- ✅ Ticket-to-agent mapping, dependency-edge semantics, quota-failover state machine, and reasoning-depth mapping live in runtime-neutral core expressed as abstract primitives (`EXECUTE`, `DEPENDS_ON`, `FAILOVER`, `REASONING_DEPTH`, `GATE`).
- ✅ `tickets-to-paseo` shrinks to adapter mapping primitives to Paseo surface (`paseo run`, `paseo chat`, `paseo schedule`).
- ✅ Both core and adapter conform to frontmatter contract and pass validator.
- ✅ Adding second runtime is new adapter file, not core rewrite.
- ✅ `docs/adr/0004-runtime-neutral-core-plus-adapter.md` records the decision.

## Version Implications

- `ticket-workflow-core` v0.1.0 — initial primitive set
- `tickets-to-paseo` v0.2.0 — refactored from monolithic to adapter
