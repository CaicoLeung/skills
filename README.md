# skills

A fork of [mattpocock/skills](https://github.com/mattpocock/skills) organized
around **Loop Engineering** — designing the *system* that drives an agent
through a goal-bounded, verified cycle (implement, review, fix, merge, close),
rather than prompting it turn-by-turn. Routines are mechanical operations
encoded as scripted steps with a verification gate at each stage. See
[`CONTEXT.md`](./CONTEXT.md) for the vocabulary and
[ADR-0001](./docs/adr/0001-fork-with-selective-sync.md) for the fork's
selective-sync policy.

## Install

Install all three skills into your agent (Claude Code, Codex, Cursor, pi,
and 70+ others) via the open [`skills`](https://github.com/vercel-labs/skills)
CLI:

```bash
npx skills add CaicoLeung/skills
```

The runtime scripts (`loop.py`, `routing.py`, `closeout.py`, `verdict.py`,
`reviewer.py`) are vendored inside `skills/loop-engineering/scripts/`, so each
skill is self-contained — no separate checkout needed. `tickets-to-paseo`
reaches its reviewer through the sibling skill (`../loop-engineering/scripts/`),
so install all three together (the default).

For development, driving the loop locally, or replicating the CI gates, clone
the whole repo:

```bash
git clone https://github.com/CaicoLeung/skills.git
cd skills
```

Prerequisites:

- **Python 3** — runs the runtime scripts in `skills/loop-engineering/scripts/`
  and the dev/CI tooling (`validate-skills.py`, `index-skills.py`) in `scripts/`
  (zero third-party deps; CI uses `3.x`).
- **[`gh` CLI](https://cli.github.com/)** — the loop reads ticket labels, posts
  comments, enables auto-merge, and closes issues through it. Run `gh auth login`
  first.
- **Paseo daemon (0.1.110)** — the executor `tickets-to-paseo` maps onto
  (`paseo run`, `paseo chat`, `paseo worktree`). Verify with `paseo daemon status`.
- **External doing-skills** — the loop *invokes* `/implement`, `/triage`,
  `/code-review`, `/research`, `/prototype`, `/grilling` but does **not** carry
  them (ADR-0001). Install them from upstream
  [`mattpocock/skills`](https://github.com/mattpocock/skills).

> **CI gates.** `validate-skills` and `review-verdict` run only on this repo's
> GitHub Actions behind branch protection (ADR-0003). A consumer fork must
> replicate `.github/workflows/` and the required status checks to keep the
> auto-merge gate.

## Skills

| Skill | Role |
| --- | --- |
| [`ticket-workflow-core`](./skills/ticket-workflow-core/SKILL.md) | Runtime-neutral core — turns ticket data into a workflow plan |
| [`tickets-to-paseo`](./skills/tickets-to-paseo/SKILL.md) | Paseo adapter — maps the plan onto the Paseo 0.1.110 surface |
| [`loop-engineering`](./skills/loop-engineering/SKILL.md) | Deterministic loop driver — scripts routing + close-out |

Full list with versions and I/O: [`skills/INDEX.md`](./skills/INDEX.md).

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
- [Close-out loop](./docs/agents/closeout.md) — review → verdict → fix → merge → close

## Validate

```bash
python3 scripts/validate-skills.py        # every skill is well-formed
python3 scripts/index-skills.py --check   # the committed index is not stale
```

CI runs both on every push and pull request, so a malformed skill — or a stale
index — breaks the build.
