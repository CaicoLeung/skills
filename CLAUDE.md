## Loop Driver

This repo **is the Loop Driver** — a tool that batch-completes the issues
[`mattpocock/skills`](https://github.com/mattpocock/skills) generates (built on
top of it, not a fork). See [CONTEXT.md](CONTEXT.md) for the vocabulary and
[ADR-0012](docs/adr/0012-reverse-skill-reframe-loop-driver-tool.md) for the
current framing. The skill surface was deleted in ADR-0012; do not reintroduce
`skills/`, `validate-skills`, or `npx skills add` framing.

### Driver

`scripts/loop.py` is the CLI, with four subcommands: `route` (one routing turn
/ T5a), `closeout` (the review → fix → merge → close loop / T5b), `supervise`
(watch a PR's gate), and `batch` (drain the `ready-for-agent` queue). It shells
out to `paseo` and `gh`. Tests are **hand-rolled runners** — invoke as
`python3 scripts/test_<module>.py`, not via pytest (only `tests/test_verdict.py`
is pytest-style). Run the lot: `for f in batch closeout loop review_verdict
reviewer routing supervise; do python3 scripts/test_$f.py; done`.

### Close-out gate

The merge gate is the derived `/code-review` verdict (**pass**) — computed by
`closeout` from an independent review's findings (`verdict.py` +
`review_verdict.select_current_findings`). There is **no CI gate by default**
(ADR-0013 retired the `review-verdict` workflow — it gated this repo's own PRs,
not any consumer's). `required_check` defaults to empty; set it (or
`LOOP_REQUIRED_CHECK`) to gate on a consumer's own CI check. `validate-skills`
was retired in ADR-0012.

### Issue tracker

Issues live as GitHub issues in CaicoLeung/skills, driven by the `gh` CLI. See
`docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the five default labels (`needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`). See
`docs/agents/triage-labels.md`.

### Ticket types

Routing dispatches on ticket type (`research` / `prototype` / `grilling` /
`task`) after the readiness gate — orthogonal to triage state. See
`docs/agents/ticket-types.md`.

### Domain docs

Single-context — one `CONTEXT.md` and `docs/adr/` at the repo root. See
`docs/agents/domain.md`.
