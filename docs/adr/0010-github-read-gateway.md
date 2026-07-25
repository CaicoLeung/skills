# ADR-0010: GitHub read gateway — reads injected, writes stay command-list data

- **Status:** Accepted
- **Date:** 2026-07-25
- **Supersedes:** —
- **Amends:** —
- **Related:** [ADR-0004](./0004-runtime-neutral-core-plus-adapter.md) (the gateway is a transport adapter; the rule stays runtime-neutral), [ADR-0008](./0008-script-driven-loop-driver-and-type-aware-routing.md) (the `runner` injection this twins), [ADR-0007](./0007-derived-verdict-and-reviewer-independence.md) (the REVIEW enrichment the gateway makes testable)

## Context

Two modules shelled out to the `gh` CLI for the *same* read operations with two
copies of the subprocess + json + error-wrapping machinery:

- `scripts/loop.py` — six private helpers (`_gh_issue_labels`, `_gh_pr_head_sha`,
  `_gh_pr_diff`, `_gh_issue_body`, `_gh_pr_changed_files`, `_gh_pr_issue_comments`),
  each a near-identical `try/subprocess.run/except (FileNotFoundError,
  CalledProcessError)/raise RuntimeError` block.
- `scripts/review_verdict.py` — its own `_gh` / `_gh_json` / `_pr_changed_files`
  / `_pr_issue_comments`, two of which (`changed_files`, `issue_comments`) were
  byte-for-byte reimplementations of `loop`'s.

The pure cores (`routing`, `closeout`, `verdict`, `reviewer`,
`review_verdict.select_current_findings`) were deep and well unit-tested; the
*wiring layer* that stitches them to `gh` was duplicated, untested through its
own interface, and explicitly disclaimed in the test suites ("the I/O driver
is deliberately not covered"). An architecture review surfaced extracting a
single GitHub read gateway as the highest-leverage deepening — the seam was
already *real* (two modules depended on it), and it was the prerequisite for
making the driver testable.

The open design question was **scope**: does the gateway own reads only, or
reads **and** writes (the `gh pr merge` / `gh issue comment` / `gh issue close`
operations), or even the `urllib`+`GITHUB_TOKEN` REST calls in `skills.py`'s
branch-protection guard? This ADR records why the split is reads-only and why
that split should be durable.

## Decision

**A single GitHub read gateway behind an injected Protocol; writes stay as
pure command-list builders executed by the driver's `runner`.** Six parts.

### 1. One read module — `scripts/github.py`

A `GitHubReader` `Protocol` with six repo-first methods returning raw
primitives (`list[str]`, `str`, `list[dict]`):

```
issue_labels(repo, issue)    -> list[str]
issue_body(repo, issue)      -> str
issue_comments(repo, number) -> list[dict]   # PR + issue share the endpoint
pr_head_sha(repo, pr)        -> str
pr_diff(repo, pr)            -> str
pr_changed_files(repo, pr)   -> list[str]
```

`GhCliReader` is the live adapter (subprocess + json). Pagination is hidden
inside `issue_comments` (`--paginate`); callers never want a partial thread.
The module imports **zero siblings** — it is transport only, not a data model.
The typed parsing (`Finding`, `SelectedFindings`, `VerdictState`) stays where
it earns its keep, in `verdict` / `review_verdict`.

### 2. The seam is injected, twin to `runner`

The driver entry points gain a `gh: Optional[GitHubReader] = None` parameter
that defaults to `GhCliReader()` — exactly the shape of the existing `runner`
injection on `run_ticket_loop` / `run_closeout_round`. A fake in tests; the
live adapter in production. `review_verdict.main` constructs the live reader
inline (its pure core is already unit-tested; `main()` stays an I/O shell).
`DriverConfig` is unchanged — `gh` is a reader, not config data.

### 3. Reads only — writes stay command-list data

The gateway owns **reads**. Writes (`gh pr merge --auto`, `gh issue comment`,
`gh issue close`) continue to be emitted as pure command *lists* by
`closeout.closeout_commands` and the routing driver, and executed by the
driver's injected `runner`. Folding writes into the gateway was considered and
rejected (see below).

### 4. One error shape — `RuntimeError` with context

`gh` missing (`FileNotFoundError`) and `gh` failing (`CalledProcessError`) both
become a `RuntimeError` carrying the failing command and stderr. The driver's
CLI boundary catches it (a single catch, twinned across `loop` and
`review_verdict`). Missing resource = raises; empty resource = `[]` / `""` —
the contract callers already assumed.

### 5. Inline replacement, no shims

The ten duplicated helpers (`loop`'s six `_gh_*`, `review_verdict`'s four) were
**deleted**, not renamed into shims. Call sites call `gh.issue_labels(repo, n)`
etc. directly. Shimming would have renamed the duplication, not removed it.

### 6. The driver is now tested through its own interface

`FakeGitHubReader` (a small in-memory adapter duplicated in `test_loop.py` and
`test_closeout.py`, per the repo's standalone-`_check` test convention) exercises
`run_ticket_loop`, `run_closeout_round`, and REVIEW enrichment end to end with
no `gh` and no network — the paths the suite previously disclaimed.

## Rejected alternatives

- **Reads + writes in the gateway.** Writes are already a clean, tested seam:
  `closeout.closeout_commands` emits them as pure command-list *data*, the
  driver's `runner` executes them, and `--dry-run` asserts on the list verbatim.
  That "command-as-data" property is load-bearing — the dry-run preview and the
  pure-builder unit tests both depend on writes being values, not executed
  calls. Folding writes into the gateway would collapse two good patterns into
  one (injected reader for reads, injected runner for writes) and lose that
  property. Writes also have a **single** adapter shape (command list + runner);
  reads had **two** implementations. Per the codebase-design test, two adapters
  make a real seam; one does not.
- **Everything GitHub (reads + writes + `skills.py` REST branch-protection).**
  That conflates two transports (`gh` CLI vs `urllib` + `GITHUB_TOKEN`) and two
  concerns. The `skills.py` branch-protection drift guard is its own
  deepening candidate (a seam leak where `cmd_validate` silently audits CI);
  merging it here widens the blast radius and muddies the diff.
- **Module-level functions + monkeypatch.** Reintroduces a test idiom the suite
  does not use (the hand-rolled `_check` tests call pure functions; they
  monkeypatch nothing). The injected Protocol is consistent with the existing
  `runner` injection and gives mypy a contract to check the fake against.
- **`DriverConfig` field.** `runner` deliberately stayed off `DriverConfig`
  (config is data; injections are callables/readers). Putting `gh` on the
  dataclass would muddy that split and couple transport to config.
- **Typed exception hierarchy / `Result` return.** No caller branches on error
  kind — both CLI boundaries report and exit. A `RuntimeError` with context is
  the fail-loud stance the drivers already take; a typed hierarchy is a seam
  nothing varies across yet. `Optional` returns would spread `None`-handling
  and silently downgrade "not found" from a loud failure.

## Consequences

- **The duplicated read layer is gone.** Ten private helpers → six methods on
  one Protocol. One source of truth for every `gh` read command shape.
- **The wiring layer is testable through its own interface.** `run_ticket_loop`
  and `run_closeout_round` — previously "deliberately not covered" — are
  exercised via `FakeGitHubReader`, including the REVIEW enrichment path
  (`closeout_decision_commands` building the real review prompt from a fake
  diff + spec) that the suite explicitly skipped.
- **Reads and writes keep distinct, honest seams.** Reads: an injected reader
  with two adapters (live + fake). Writes: command-list-as-data + an injected
  runner. Neither pretends to be the other.
- **Failures stay loud and uniform.** Every transport failure surfaces as one
  `RuntimeError` shape at one CLI catch per entry point.
- **A future second runtime does not change this module.** Consistent with
  ADR-0004: the gateway is a transport adapter over `gh`; a non-Paseo runtime
  that also reads from GitHub reuses it unchanged.

## What this ADR exists to prevent

A future architecture review will see a `github.py` module that owns reads but
*not* writes, and the obvious suggestion will be "unify them — one GitHub
surface for everything." This ADR records the load-bearing reason not to: the
read seam is real (it had two duplicated implementations and earns a fake
adapter for testing); the write seam is a different, already-clean shape
(command-as-data + `runner`) whose dry-run and pure-builder test contracts
depend on writes remaining values. The split is deliberate, not an unfinished
merge.

## Version implications

- New: `scripts/github.py` (`GitHubReader` Protocol, `GhCliReader`).
- Amended: `scripts/loop.py` (deleted six `_gh_*`; `gh` param on
  `run_ticket_loop` / `run_closeout_round` and threaded through
  `read_verdict_state` / `review_round_count` / `_build_reviewer_prompt` /
  `closeout_decision_commands`), `scripts/review_verdict.py` (deleted four
  helpers + `PR_COMMENTS_PATH` + the `subprocess` import; `main()` uses
  `GhCliReader` + the single CLI catch).
- New tests: `FakeGitHubReader` + driver coverage in `scripts/test_loop.py`
  and `scripts/test_closeout.py`.
- No change to writes: the close-out command-list builders (then `closeout.closeout_commands`;
  issue #52 later renamed it `closeout_plan` to return intent, with the driver
  building the command list — the write-stays-command-data principle this ADR
  argues for is unchanged), the `runner` injection, and the dry-run contract.
