# skills

A fork of [mattpocock/skills](https://github.com/mattpocock/skills) organized
around **Loop Engineering** — designing the *system* that drives an agent
through a goal-bounded, verified cycle (implement, review, fix, merge, close),
rather than prompting it turn-by-turn. Routines are mechanical operations
encoded as deterministic steps with a verification gate at each stage.

This repo publishes Loop Engineering as **installable Agent Skills** —
stack-agnostic discipline the consumer instantiates in their own harness. The
skills teach the discipline; an in-repo Python/Paseo reference implementation
previously lived under `scripts/` and has been retired (see
[ADR-0011](./docs/adr/0011-agent-skill-product-reframe.md)). See
[`CONTEXT.md`](./CONTEXT.md) for the vocabulary and
[ADR-0001](./docs/adr/0001-fork-with-selective-sync.md) for the fork's
selective-sync policy.

## Skills

| Skill | Role |
| --- | --- |
| [`ticket-workflow-core`](./skills/ticket-workflow-core/SKILL.md) | Runtime-neutral core — turns ticket data into a workflow plan |
| [`tickets-to-paseo`](./skills/tickets-to-paseo/SKILL.md) | Paseo adapter — maps the plan onto the Paseo 0.1.110 surface |
| [`loop-engineering`](./skills/loop-engineering/SKILL.md) | The discipline — two-axis routing + the close-out loop (runtime-neutral) |

Full list with versions and I/O: [`skills/INDEX.md`](./skills/INDEX.md).

## Install

These are Claude-Code-style skills. Install the fork with a compatible skill
installer (e.g. the upstream `npx skills add`), which copies the committed
`skills/<name>/` tree verbatim — there is no build step, so each skill is
self-contained in the committed source.

## How do I use these skills?

Start with **[Flows](./docs/flows.md)** — pick your starting point and follow the
arrows. The happy path (a `task` ticket) runs end-to-end: route → implement →
independent review → derived verdict → merge → close.

> **New here?** Read [Flows](./docs/flows.md) once — it explains how the three
> skills layer and which runs next. (TL;DR: tickets carry two labels (readiness +
> type); the loop gates on readiness, dispatches on type, and for `task` tickets
> drives an independent review to a derived verdict before merge.)

## Concepts and decisions

- [Glossary](./CONTEXT.md) — the domain terms these skills use
- [Architecture decisions](./docs/adr/) — ADRs
- [Skill contract](./docs/agents/skills.md) — frontmatter, validation, indexing
- [Ticket types](./docs/agents/ticket-types.md) · [triage labels](./docs/agents/triage-labels.md)
- [Close-out loop](./skills/loop-engineering/SKILL.md) — review → verdict → fix → merge → close (in `loop-engineering`)

## Validate

```bash
python3 scripts/validate-skills.py        # every skill is well-formed
python3 scripts/index-skills.py --check   # the committed index is not stale
```

CI runs both on every push and pull request, so a malformed skill — or a stale
index — breaks the build.
