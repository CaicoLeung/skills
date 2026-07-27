# Close-out loop (review → verdict → fix → merge → close)

The close-out half of the loop driver (T5b, issue #29; ADR-0008 §5). Once a
`task` ticket's PR is open (routing half, T5a), the close-out loop drives it to
merge + close: **invoke the independent reviewer → derive the verdict → hand
findings to the same implementer verbatim → re-review until pass or the 3-round
cap → on pass, the loop enables auto-merge → dual close.** Every decision is
made by a pure function; the implementer never merges and never self-declares a
fix.

This doc specifies the loop's shape, the CLI, and how to demo it without a live
reviewer. See [ADR-0008](../adr/0008-script-driven-loop-driver-and-type-aware-routing.md)
for the decision, [review-verdict.md](review-verdict.md) for the derived-verdict
gate the loop reads, and [ticket-types.md](ticket-types.md) for why only
code-delivery (`task`) tickets run this loop.

## Shape

```
PR opened (Fixes #N)                         ← routing half (T5a)
  │
  ▼
round k:  loop invokes the independent reviewer (T4)
          → reviewer posts sha-tagged findings (ADR-0007)
          → loop derives the verdict (T1/T3)
          → loop reads the verdict: closeout.plan_closeout(verdict, round)
                pass    → MERGE: loop runs `gh pr merge --auto`
                                 → CLOSE: loop posts resolution_comment
                                 → Fixes #N auto-closes the issue   (terminal)
                fail    → if round < 3: FIX → findings verbatim → implementer
                                                         pushes → re-review (k+1)
                          if round = 3: STUCK → STUCK_REVIEW (chat + issue
                                         comment), PR unmerged, no auto-close
                                  (terminal)
                missing → REVIEW (no current review for this head)
```

* **Pure planner** — [`scripts/closeout.py`](../../scripts/closeout.py):
  `plan_closeout(verdict, round)` is total over `(status, round)` and is the
  only thing that decides pass/review/fix/stuck. Also authors `fix_prompt`
  (verbatim handoff), `resolution_comment` (dual close), `stuck_message`
  (`STUCK_REVIEW`), and `auto_merge_command` (loop-only).
* **Thin driver** — [`scripts/loop.py`](../../scripts/loop.py):
  `run_closeout_round` (one live round) and `run_closeout_trajectory` (a pure
  sim over a verdict sequence). They read PR state via `gh`, reuse T3's
  `review_verdict.select_current_findings` + T1's `verdict.derive_verdict`, and
  reuse T4's `reviewer.build_review_prompt` for the review turn.

## Invariants (acceptance criteria of #29)

| AC | Where enforced |
| --- | --- |
| Findings handed to the fixer **verbatim**; "resolved" = disappears from the next review | `closeout.fix_prompt` embeds the findings unchanged; the loop re-derives the verdict each round (a recurring finding keeps the verdict fail). No "resolve all issues" prose exists in the prompt. |
| 3-round cap escalates `STUCK_REVIEW`, never silently passes | `closeout.MAX_REVIEW_ROUNDS = 3`; `plan_closeout` returns `STUCK` for any non-pass at the cap. |
| Loop enables auto-merge **only** on a pass; implementer never merges | `auto_merge_command` is built only on `ACTION_PASS`; the FIX turn is a `paseo run`, never a merge. |
| Dual close: `Fixes #N` + loop resolution comment | PR body (`loop.implement_pr_body`) carries `Fixes #N`; `ACTION_PASS` runs `gh pr merge --auto` **then** `gh issue comment` with `resolution_comment`. |
| End-to-end demonstration | The `--outcomes` trajectory sim below (no agents, no network). |

## CLI

```bash
# Simulate the full trajectory for a per-round outcome list (CI-safe):
python3 scripts/loop.py closeout 29 --pr 99 --outcomes pass                 # clean pass
python3 scripts/loop.py closeout 29 --pr 99 --outcomes fail,fail,pass       # fix loop → pass
python3 scripts/loop.py closeout 29 --pr 99 --outcomes fail,fail,fail       # → STUCK_REVIEW

# Drive one live round for a real PR (reviewer on a different provider):
python3 scripts/loop.py closeout 29 --pr 99 \
  --secondary-provider openai --secondary-model gpt-4o \
  --reviewer-login "$REVIEWER_LOGIN" --dry-run
```

Each outcome token is one review round's verdict: `pass` (verdict passed),
`fail` (verdict failed — carries sample findings), or `none` (no current
review → REVIEW step). The sim stops at the first terminal decision (PASS or
STUCK) and reports `rounds_used` + `terminal`.

## Demo procedure (no live reviewer)

The loop is demoed with the trajectory simulator — no agent, no reviewer App,
no secondary provider — exactly as `review-verdict.md` demos the gate with
manually-posted findings. The *logic* those live runs would exercise is the
pure planner, asserted in `scripts/test_closeout.py`.

1. **Clean pass.** `--outcomes pass`. Expect: one decision, `ACTION_PASS` with
   two commands — `gh pr merge --auto --squash --delete-branch` (loop-only)
   and `gh issue comment … --body <resolution_comment>`. `terminal: true`,
   `rounds_used: 1`.
2. **Fix loop → pass.** `--outcomes fail,fail,pass`. Expect: `FIX` (round 1),
   `FIX` (round 2), `PASS` (round 3). `terminal: true`, `rounds_used: 3`. The
   FIX decisions carry the sample findings verbatim in `findings_text`.
3. **Stuck.** `--outcomes fail,fail,fail`. Expect: `FIX`, `FIX`, `STUCK`
   (round 3). `terminal: true`, `rounds_used: 3`. The STUCK decision's command
   is a `gh issue comment` with `stuck_message` (names `STUCK_REVIEW`, leaves
   the PR unmerged, does not auto-close). No merge command is emitted.
4. **No current review.** `--outcomes none`. Expect: `REVIEW` (round 1),
   non-terminal — the loop invokes the independent reviewer.

For example:

```console
$ python3 scripts/loop.py closeout 29 --pr 99 --outcomes fail,fail,pass
{
  "issue": 29,
  "pr": 99,
  "start_round": 1,
  "rounds_used": 3,
  "terminal": true,
  "decisions": [
    { "action": "fix",  "round": 1, "verdict": "fail", "findings_text": "…", … },
    { "action": "fix",  "round": 2, "verdict": "fail", "findings_text": "…", … },
    { "action": "pass", "round": 3, "verdict": "pass",
      "commands": [
        ["gh", "pr", "merge", "99", "--repo", "…", "--auto", "--squash", "--delete-branch"],
        ["gh", "issue", "comment", "29", "--repo", "…", "--body", "Resolved #29 …"]
      ], … }
  ]
}
```

## Honest enforcement (caveats)

The loop is only as honest as the reviewer identity and the secondary provider:

* **Reviewer identity.** `REVIEWER_LOGIN` is the GitHub App's bot login in
  production — a separate identity whose token the implement-agent does not
  possess (see [review-verdict.md](review-verdict.md)). The App's provisioning
  is an operational prerequisite, not part of this code change.
* **Different provider.** Armed reviewer independence needs the secondary model
  on a **different provider** than the implementer (ADR-0007 §2). The driver
  raises if `--secondary-provider` is unset or equals `--provider`.
* **Async turns.** `run_closeout_round` drives **one** round; the multi-round
  iteration across the 10–30 min async agent turns is orchestrated externally
  (the driver sleeps/polls between rounds per ADR-0008 §1), exactly as the
  routing driver drives one routing turn.
