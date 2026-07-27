# Loop Driver

**An auxiliary tool that batch-completes the issues [`mattpocock/skills`](https://github.com/mattpocock/skills) generates.** It is built *on top of* `mattpocock/skills` — not a fork of it. `mattpocock/skills`'s `to-spec` / `to-tickets` produce GitHub issues; the Loop Driver drains the ready queue and drives each issue through **implement → review → fix → merge → close**, unattended, via [Paseo](https://github.com/paseo).

> **What this replaces.** Prompting an agent turn-by-turn through a ticket. The cycle is encoded as a deterministic script with a verification gate at each stage — the agent does the judgment work, the driver owns the loop.

## Install

The driver is a Python CLI that shells out to two binaries. You need:

- **Python 3.11+**
- the **[`paseo`](https://github.com/paseo) CLI** — runs the implement/review/supervise agents
- the **[`gh`](https://cli.github.com) CLI** — reads issues/PRs, posts comments, enables auto-merge

```bash
git clone https://github.com/CaicoLeung/skills.git loop-driver
cd loop-driver
python3 scripts/loop.py --help
```

There is no build step and no Python package to install — `scripts/loop.py` runs from the clone. Configure the target repo and model via flags or env (`LOOP_REPO`, `LOOP_PROVIDER`, `LOOP_MODEL`, `LOOP_MODE`, …).

## Run it

Four subcommands. The first three drive **one** issue through one phase; `batch` drains the whole ready queue.

```bash
# Advance one issue by the DISPATCH phase (triage → invoke the type's skill).
python3 scripts/loop.py route 42

# Drive the close-out loop for issue 42's PR: independent review → derived
# verdict → fix → auto-merge → close. Caps at 3 rounds, then STUCK_REVIEW.
python3 scripts/loop.py closeout 42 --pr 17

# Watch PR 17's gate (merge state) until merged-and-gated
# or escalated.
python3 scripts/loop.py supervise 42 --pr 17

# Drain the ready queue: dispatch the implement turn for every open
# ready-for-agent issue, up to --limit, fail-stopping on the first error.
python3 scripts/loop.py batch --limit 10
```

Every subcommand takes `--dry-run` (plan and print the `paseo`/`gh` commands without executing) and `--help`.

**Batch is the headline.** One `batch` run advances every queued issue by the DISPATCH phase; the close-out and supervise phases run as the PRs land. Drive the whole queue to completion by re-running `batch` (and the per-PR subcommands) as the queue shifts — cron it.

## How it works

The driver is one turn-per-invocation by design (ADR-0008); an external scheduler (you, cron, your harness) sequences the phases. A `task` ticket's happy path:

```
ready-for-agent issue
        │
        ▼
   route (T5a) ── triage ok? ── dispatch /implement (paseo, own worktree)
        │
        ▼  (implement agent opens a PR carrying `Fixes #N`)
        │
   closeout (T5b) ── independent /code-review (different provider, ADR-0007)
        │              │
        │              ▼  derived verdict (scripts/verdict.py) — pass | fail | missing
        │              │
        │              ├─ pass  → loop enables `gh pr merge --auto`; GitHub merges the PR;
        │              │         `Fixes #N` closes the issue
        │              └─ fail  → findings handed to the implementer verbatim, re-review
        │                        (a finding is "resolved" only when the NEXT review drops it)
        │              └─ 3rd non-pass → STUCK_REVIEW (issue + chat, PR unmerged, no auto-close)
        ▼
   supervise ── watch the gate until merged-and-gated or escalated (ADR-0006)
```

The merge gate is **never** a self-declared token: `closeout` enables auto-merge only on the *derived* verdict (no CRITICAL/HIGH findings + per-file coverage floor), computed by the loop from an independent review. There is no CI gate by default (ADR-0013) — the driver's local derivation suffices; a consumer who wants independent re-derivation can wire `scripts/review_verdict.py` into their own CI and set `--required-check`.

## Concepts & decisions

- [Glossary](CONTEXT.md) — the terms the driver uses (Loop Driver, ticket type, close-out gate, review round, quota failover, worktree)
- [ADR-0012](docs/adr/0012-reverse-skill-reframe-loop-driver-tool.md) — current framing: why this is a tool, not a skill product
- [All ADRs](docs/adr/) — the decision log (skill-era ADRs are marked superseded/voided in place)
- Ticket model: [ticket types](docs/agents/ticket-types.md) · [triage labels](docs/agents/triage-labels.md)
- Behavior docs: [close-out](docs/agents/closeout.md) · [review-verdict](docs/agents/review-verdict.md) · [supervise](docs/agents/supervise.md) · [issue tracker](docs/agents/issue-tracker.md)

## Roadmap

- **[#63](https://github.com/CaicoLeung/skills/issues/63)** — Promote `tmux` + `git worktree` to first-class EXECUTE seams. Today the driver delegates worktrees to Paseo's `--worktree` flag and has no `tmux` integration.
- **[#64](https://github.com/CaicoLeung/skills/issues/64)** — Rename the GitHub repo (`skills` → on-brand). The dir name still says `skills` and collides with upstream.

**Out-of-band admin action:** live branch protection on `CaicoLeung/skills` still lists `validate-skills` and `review-verdict` as required contexts; both workflows are now retired (ADR-0012, ADR-0013). Drop both from the required status checks, or PRs cannot merge. `scripts/branch_protection.py` will surface this drift if run locally.

## License

MIT — see [LICENSE](LICENSE). This repo carries material originating in [`mattpocock/skills`](https://github.com/mattpocock/skills) (© Matt Pocock); see [NOTICE](NOTICE).
