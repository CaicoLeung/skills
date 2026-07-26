#!/usr/bin/env python3
"""Close-out loop planner: review → verdict → fix → merge → close (T5b / ADR-0008).

The close-out half of the loop driver. Where :mod:`routing` (T2) and the
routing half of :mod:`loop` (T5a) get a claimed ticket to "PR opened", this
module is the *pure* planner that takes it from "PR opened" to "merged +
closed". The thin I/O driver lives in :mod:`loop` (:func:`loop.run_closeout`
and friends); this module holds the deterministic state machine, the
system-authored prompts, and the loop-only ``gh`` commands — no ``paseo``, no
network, no agent. It is unit-tested in ``scripts/test_closeout.py`` (issue #23
testing decisions: behavior, not plumbing).

Loop Engineering (ADR-0008 §5; parent #23 stories 23–29): the close-out is a
bounded state machine::

    round k: independent review (T4) → derived verdict (T1/T3)
      pass    → loop enables auto-merge → Fixes #N closes → resolution comment
      fail    → if rounds remain: hand findings VERBATIM to the SAME implementer
                (no "resolve all issues" prose); it pushes; re-review (k+1)
                if rounds exhausted: STUCK_REVIEW (chat + issue comment,
                PR unmerged, no auto-close)
      missing → no current review for this head → invoke the reviewer

A finding is "resolved" **only** when it disappears from the NEXT independent
review — never self-declared (parent #23 story 25). The loop never trusts a
fixer's claim; it re-derives the verdict each round from the fresh review, so
a finding that was not actually fixed reappears and the verdict stays fail.

This module composes the pure building blocks shipped by earlier slices:
:mod:`verdict` (T1), :mod:`review_verdict` (T3), :mod:`reviewer` (T4). It is
runtime-neutral (ADR-0004: the rule lives in the core; the loop + adapter
supply the mechanism).
"""

from __future__ import annotations

from dataclasses import dataclass

# --- The bounded fix loop ---------------------------------------------------
# Parent #23 story 26 / ADR-0008 §5: three review rounds, then escalate. A
# "round" is one completed independent review of the current PR head. The cap
# bounds the fix→review loop so it converges or escalates, never loops forever
# ("cheating by exhaustion"). Three independent failures to fix the same diff
# is a human signal, not a patience test.
MAX_REVIEW_ROUNDS = 3

# --- Close-out actions ------------------------------------------------------
# The four things the loop can do after reading a PR's verdict. Only PASS
# merges; only the loop (never the implementer) reaches it.
ACTION_PASS = "pass"      # verdict passed → loop enables auto-merge + dual close
ACTION_REVIEW = "review"  # no current review → invoke the independent reviewer
ACTION_FIX = "fix"        # verdict failed, rounds remain → verbatim findings → fixer
ACTION_STUCK = "stuck"    # rounds exhausted → STUCK_REVIEW, PR unmerged, no close

# --- Verdict states ---------------------------------------------------------
# What the loop derives from the PR by composing T3 + T1
# (review_verdict.select_current_findings → verdict.derive_verdict). The
# verdict is exclusively a CI-computed fact (ADR-0007); the loop reads it to
# *decide*, the CI check enforces it to *gate*.
VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_MISSING = "missing"  # no sha-matched review (stale head, or never reviewed)


@dataclass(frozen=True)
class VerdictState:
    """The derived verdict for a PR head, as the loop sees it.

    Built by the driver from the reviewer's latest sha-matched findings
    (T3 selection) fed to the verdict rule (T1). ``findings_text`` is the
    reviewer's findings body **verbatim** — the same string handed to the
    fixer on a FIX decision, so nothing is lost in handoff (parent #23
    story 23).
    """

    status: str  # VERDICT_PASS | VERDICT_FAIL | VERDICT_MISSING
    findings_text: str  # reviewer's verbatim findings body ("" when missing)
    blocking_count: int  # CRITICAL/HIGH findings (fail reason)
    coverage_gap_count: int  # changed files with no finding/OK (fail reason)

    @property
    def passed(self) -> bool:
        """True iff the derived verdict is a pass (the only merge condition)."""
        return self.status == VERDICT_PASS


@dataclass(frozen=True)
class CloseoutDecision:
    """What the loop does next for a PR, given its verdict and round.

    Attributes:
        action: One of the ``ACTION_*`` constants.
        round: The review round just completed (0 when no review yet). The
            driver counts a round per reviewer findings comment posted.
        verdict: The verdict status that produced this decision.
        findings_text: The reviewer's findings handed to the fixer VERBATIM
            (FIX only); "" for PASS/REVIEW/STUCK.
        reason: Human-readable rationale — surfaced in the loop report and the
            STUCK_REVIEW escalation so a human can see *why* the loop stopped.
    """

    action: str
    round: int
    verdict: str
    findings_text: str
    reason: str

    def to_dict(self) -> dict:
        """JSON-serializable view for the loop report."""
        return {
            "action": self.action,
            "round": self.round,
            "verdict": self.verdict,
            "findings_text": self.findings_text,
            "reason": self.reason,
        }


def plan_closeout(verdict: VerdictState, round: int) -> CloseoutDecision:
    """Decide the loop's next close-out step from a PR's verdict + round count.

    The decision is total over ``(verdict.status, round)``:

    * **pass** → :data:`ACTION_PASS`. The loop enables auto-merge and posts the
      resolution comment (dual close). This is the *only* path that merges,
      and only the loop reaches it — the implementer never merges (parent #23
      story 27).
    * **otherwise, round ≥ cap** → :data:`ACTION_STUCK`. Three review rounds
      without a pass is a human signal: post ``STUCK_REVIEW``, leave the PR
      unmerged, do not auto-close (parent #23 story 29). The cap applies to
      *every* non-pass state — a fail OR a missing review at the cap escalates,
      so the loop can never loop forever on reviews that don't converge.
    * **missing** → :data:`ACTION_REVIEW`. No current review for this head
      (stale after a push, or the first review). The loop invokes the
      independent reviewer (T4).
    * **fail** (rounds remain) → :data:`ACTION_FIX`. Hand the reviewer's
      findings to the same implementer **verbatim**; it pushes; the loop
      re-reviews. "resolved" is defined by the next review, not by the fixer.

    Args:
        verdict: The PR's derived verdict state.
        round: Review rounds already completed for this PR (≥ 0). The driver
            counts one per reviewer findings comment.

    Returns:
        The :class:`CloseoutDecision` the driver executes.
    """
    if verdict.status == VERDICT_PASS:
        return CloseoutDecision(
            action=ACTION_PASS,
            round=round,
            verdict=verdict.status,
            findings_text="",
            reason=(
                "derived verdict passed; loop enables auto-merge"
            ),
        )

    # Not passed. The cap guards every non-pass path, so a review that keeps
    # going stale, or a fix that keeps failing, both escalate at the same bound.
    if round >= MAX_REVIEW_ROUNDS:
        return CloseoutDecision(
            action=ACTION_STUCK,
            round=round,
            verdict=verdict.status,
            findings_text=verdict.findings_text,
            reason=(
                f"{MAX_REVIEW_ROUNDS}-round cap exhausted without a pass; "
                f"escalate STUCK_REVIEW (PR unmerged, no auto-close)"
            ),
        )

    if verdict.status == VERDICT_MISSING:
        return CloseoutDecision(
            action=ACTION_REVIEW,
            round=round,
            verdict=verdict.status,
            findings_text="",
            reason="no current review for this head; invoke the independent reviewer",
        )

    # VERDICT_FAIL with rounds remaining. Any other status reaching here is a
    # programmer error — pass/missing are handled above, so make the totality
    # claim honest rather than silently treating an unknown status as a fail.
    if verdict.status != VERDICT_FAIL:
        raise ValueError(
            f"unknown verdict status {verdict.status!r}; "
            f"expected one of {VERDICT_PASS!r}/{VERDICT_FAIL!r}/{VERDICT_MISSING!r}"
        )
    return CloseoutDecision(
        action=ACTION_FIX,
        round=round,
        verdict=verdict.status,
        findings_text=verdict.findings_text,
        reason=(
            "verdict failed; hand findings verbatim to the same implementer; "
            "re-review after push"
        ),
    )


# --- System-authored prompts ------------------------------------------------
# The loop authors every prompt so the implementer can neither frame its own
# review (ADR-0007) nor talk its way past the fix loop. These are deterministic
# strings — the testable contract between the loop and the external doing-skill.


def fix_prompt(findings_text: str, issue_number: int, pr_url: str) -> str:
    """Hand the reviewer's findings to the SAME implementer VERBATIM.

    Parent #23 story 23: the handoff is the findings, not a paraphrase. There is
    no "resolve all issues" / "fix everything" prose — such a summary is exactly
    where a fixer could quietly drop a finding. The findings are the fixer's
    entire input beyond a pointer to its own PR.

    Parent #23 story 25: a finding counts as "resolved" only when it disappears
    from the NEXT independent review. The fixer is told this explicitly and is
    told **not** to self-declare resolution — the loop re-derives the verdict
    from the fresh review and treats any reappearance as unresolved.

    The fixer pushes to the same branch; it does **not** merge (merge authority
    is the loop's, exercised only on PASS — parent #23 story 27).
    """
    return (
        f"The independent code review of your PR for #{issue_number} ({pr_url}) "
        f"produced the findings below. Address each one.\n\n"
        f"A finding counts as resolved **only** when it disappears from the "
        f"NEXT independent review — do not self-declare resolution. The loop "
        f"re-runs the reviewer on your next push and re-derives the verdict "
        f"from that fresh review; any finding that reappears is unresolved.\n\n"
        f"Commit and push to the same branch. Do not merge — merge is the "
        f"loop's, exercised only after the derived verdict passes.\n\n"
        f"Findings (verbatim, from the independent reviewer):\n\n"
        f"{findings_text}\n"
    )


def resolution_comment(
    issue_number: int,
    pr_url: str,
    rounds: int,
    merged_sha: str | None = None,
) -> str:
    """The loop's dual-close comment, posted after auto-merge is enabled.

    Parent #23 story 28: the PR body's ``Fixes #N`` auto-closes the issue on
    merge; this comment is the human-readable resolution the loop adds. It is
    posted once the loop has enabled auto-merge (the merge itself completes
    when CI is green), so a reader can see *how* the ticket closed and at what
    review cost.
    """
    sha_line = f" Merged SHA: `{merged_sha}`." if merged_sha else ""
    return (
        f"Resolved #{issue_number} via the Loop Driver close-out "
        f"(ADR-0008). The derived verdict passed after {rounds} review "
        f"round(s); the loop enabled auto-merge and GitHub merged {pr_url}."
        f"{sha_line}\n\n"
        f"Closes #{issue_number}.\n"
    )


def stuck_message(issue_number: int, pr_url: str, round: int) -> str:
    """The STUCK_REVIEW escalation (parent #23 story 29).

    Posted to the workflow chat room **and** as a ``gh issue comment``. The PR
    is left unmerged and the issue is **not** auto-closed — a human must
    intervene. The verbatim findings are included so the human sees what the
    loop could not converge on.
    """
    return (
        f"STUCK_REVIEW on #{issue_number}: the close-out loop exhausted its "
        f"{MAX_REVIEW_ROUNDS}-round fix→review cap ({round} review round(s) "
        f"completed) without the derived verdict passing. The PR is left "
        f"unmerged and this issue is not auto-closed. PR: {pr_url}\n\n"
        f"A human must resolve the remaining findings and re-run the review."
    )


# --- Loop-only merge authority ----------------------------------------------
# Parent #23 story 27 / ADR-0007 §4: the LOOP enables auto-merge, only after
# the derived verdict passes; GitHub merges when both checks are green. The
# implementer never runs this — there is no path from a fix turn to merge.


def auto_merge_command(repo: str, pr_number: int) -> list[str]:
    """Build the ``gh pr merge --auto`` the loop runs on a PASS decision.

    ``--auto`` makes GitHub perform the merge the instant branch protection's
    required checks are satisfied — so
    enabling auto-merge does not bypass the gate, it queues behind it. Squash
    + delete-branch is the fixed adapter default (``tickets-to-paseo`` GATE
    mapping; ADR-0005). The command is built ONLY on PASS (see
    :func:`plan_closeout`), so a failing or missing verdict can never reach it.
    """
    return [
        "gh", "pr", "merge",
        str(pr_number),
        "--repo", repo,
        "--auto",
        "--squash",
        "--delete-branch",
    ]


def review_placeholder_prompt(pr_url: str) -> str:
    """The placeholder review prompt the pure builder can emit without ``gh``.

    The live driver (:func:`loop.closeout_decision_commands`) substitutes the
    real fixed review prompt — built from the PR diff + issue spec via the
    injected GitHub gateway (ADR-0010) — so this placeholder only surfaces in
    the trajectory sim, which has no live diff. Reviewer-independence axes 2/3
    (no author-prose slot, separate identity) are still honored: the
    placeholder carries no commit message or PR description, only a pointer.
    """
    return (
        f"Run the independent code review (review-prompt.md) for "
        f"{pr_url}. Emit only the two axes' findings; never a verdict."
    )


@dataclass(frozen=True)
class RunIntent:
    """Pure intent to shape one ``paseo run`` from (REVIEW or FIX).

    The driver (:func:`loop.closeout_decision_commands`) and the trajectory
    sim (:func:`loop.run_closeout_trajectory`) both turn this into a real
    ``paseo run`` via the SAME builder (:func:`loop._intent_to_paseo_run`) —
    one source of truth for the command shape. The pure builder owns the
    prompt text: for FIX it is the verbatim findings handoff
    (:func:`fix_prompt`); for REVIEW it is a placeholder
    (:func:`review_placeholder_prompt`) the live driver enriches with the diff
    + spec (the pure builder has no ``gh``). The workspace, base, and provider
    are cfg-derived — the driver owns the paseo shell, not the pure builder
    (issue #52).

    Attributes:
        kind: ``ACTION_REVIEW`` or ``ACTION_FIX`` (selects the workspace +
            provider/model the driver attaches).
        prompt: The skill prompt. FIX: verbatim findings; REVIEW: placeholder.
    """

    kind: str
    prompt: str


@dataclass(frozen=True)
class CloseoutPlan:
    """Pure intent for one close-out decision — no ``paseo``, no network.

    The single source of truth the live driver and the trajectory sim both
    consume (issue #52). ``gh_commands`` are the loop-owned deterministic
    ``gh`` operations (PASS auto-merge + resolution comment; STUCK escalation
    comment) — the only commands the pure builder emits. ``run`` is the
    ``paseo run`` intent for REVIEW/FIX, which the consumers shape into a real
    command from their config. Exactly one of the two is active: PASS/STUCK
    carry ``gh_commands`` (``run`` is ``None``); REVIEW/FIX carry ``run``
    (``gh_commands`` is empty).

    Attributes:
        gh_commands: The loop-owned ``gh`` ops (PASS/STUCK); ``[]`` for
            REVIEW/FIX.
        run: The ``paseo run`` intent (REVIEW/FIX); ``None`` for PASS/STUCK.
    """

    gh_commands: list[list[str]]
    run: RunIntent | None = None


def closeout_plan(
    decision: CloseoutDecision,
    repo: str,
    issue_number: int,
    pr_number: int,
) -> CloseoutPlan:
    """The pure intent for a close-out decision (no ``paseo``, no network).

    Narrows the former ``closeout_commands`` (issue #52): the builder returns
    **intent**, not shell commands, for REVIEW/FIX — the driver
    (:func:`loop.closeout_decision_commands`) and the trajectory sim
    (:func:`loop.run_closeout_trajectory`) build the real ``paseo run`` from
    the same :class:`RunIntent` via one shared builder
    (``loop._intent_to_paseo_run``), so the command shape has a single source
    of truth instead of a placeholder the live driver discards.

    Only the loop-owned ``gh`` ops retain command form:

    * PASS → ``gh pr merge --auto`` (loop-only auto-merge) + ``gh issue
      comment`` (the resolution comment — dual close with ``Fixes #N``).
    * STUCK → ``gh issue comment`` (the STUCK_REVIEW escalation); no merge.
    * REVIEW → a :class:`RunIntent` (placeholder prompt; the driver enriches
      it with the live diff + spec on the secondary provider).
    * FIX → a :class:`RunIntent` carrying :func:`fix_prompt` with the findings
      verbatim.

    The signature collapses to the decision + the values the intent text
    needs (``repo`` / ``issue_number`` / ``pr_number``); the PR URL is derived,
    and the paseo-shell values (workspace, base, provider, model) are
    cfg-derived and attached by the driver — the driver owns the paseo shell.

    Args:
        decision: The planned close-out decision.
        repo: The ``owner/name`` repo (for the ``gh`` ops + the derived PR URL).
        issue_number: The issue the PR implements.
        pr_number: The PR under review.

    Returns:
        The :class:`CloseoutPlan` the driver / sim consume.
    """
    url = f"https://github.com/{repo}/pull/{pr_number}"

    if decision.action == ACTION_PASS:
        return CloseoutPlan(gh_commands=[
            auto_merge_command(repo, pr_number),
            [
                "gh", "issue", "comment", str(issue_number),
                "--repo", repo,
                "--body", resolution_comment(issue_number, url, decision.round),
            ],
        ])

    if decision.action == ACTION_STUCK:
        return CloseoutPlan(gh_commands=[
            [
                "gh", "issue", "comment", str(issue_number),
                "--repo", repo,
                "--body", stuck_message(issue_number, url, decision.round),
            ],
        ])

    if decision.action == ACTION_REVIEW:
        # Intent only: the driver enriches the placeholder with the real fixed
        # review prompt (diff + spec via gh) on the secondary provider.
        return CloseoutPlan(
            gh_commands=[],
            run=RunIntent(kind=ACTION_REVIEW, prompt=review_placeholder_prompt(url)),
        )

    # ACTION_FIX — same implementer, verbatim findings (computed once here).
    return CloseoutPlan(
        gh_commands=[],
        run=RunIntent(
            kind=ACTION_FIX,
            prompt=fix_prompt(decision.findings_text, issue_number, url),
        ),
    )
