#!/usr/bin/env python3
"""Deterministic loop driver — routing half (T5a / ADR-0008).

Loop Engineering (ADR-0008): a **scripted spine** drives the agent through a
goal-bounded, verified cycle. Agents are *leaves* the loop invokes; no agent
improvises the sequence. This module is that spine.

Two halves ship separately:

* **T5a (this file, issue #28)** — the *routing half*: read a claimed ticket's
  labels, enforce the **readiness gate** (implement is unreachable from a
  triage status), dispatch by **ticket type**, and for code-delivery
  (``task``) run the implement turn that opens a PR carrying ``Fixes #N``.
  This slice ends at "PR opened."
* **T5b (issue #29)** — the *close-out half*: independent review → derived
  verdict → fix loop → merge → close. Lives elsewhere; not wired here.

The decision is split the same way the verdict was (ADR-0007): the
**turn-planning** is a pure, unit-tested function (:func:`plan_turn`) reused
from the two-axis router (:mod:`routing`); the **driver** (:func:`run_ticket_loop`)
is the thin I/O layer that reads labels with ``gh`` and invokes skills with
``paseo run --detach``. Pure logic is not tested via integration (issue #23
testing decisions); the driver is exercised safely through ``--dry-run``.

Doing-skills (``/triage``, ``/implement``, ``/research``, …) **stay external**
— the loop *invokes* them, it never carries them (ADR-0001 selective-fork
principle).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

# Allow ``python3 scripts/loop.py`` (script) and ``from scripts.loop import``
# (pytest) to both find the sibling ``routing`` module.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import closeout  # noqa: E402
import routing  # noqa: E402

# --- Loop actions -----------------------------------------------------------
# The loop's view of a turn reuses the routing module's action vocabulary —
# DISPATCH is the only action that consults the ticket type; the rest are pure
# loop motions. Aliased here so callers (and the JSON report) name them as the
# loop's, without redeclaring the string contract in two places.

ACTION_TRIAGE = routing.ACTION_TRIAGE    # invoke /triage (untriaged / unlabeled / untyped)
ACTION_PAUSE = routing.ACTION_PAUSE      # pause for the reporter (needs-info)
ACTION_STOP = routing.ACTION_STOP        # leave the ticket for a human (ready-for-human)
ACTION_CLOSE = routing.ACTION_CLOSE      # close / skip (wontfix)
ACTION_DISPATCH = routing.ACTION_DISPATCH  # readiness clear → run the type's external skill

# The skill the loop invokes to triage a ticket. Doing-skills are external;
# the loop only names them.
TRIAGE_SKILL = "/triage"


@dataclass(frozen=True)
class Turn:
    """The scripted turn the loop executes for a claimed ticket (ADR-0008).

    The loop driver is a script; a :class:`Turn` is its unit of work. The
    doing-skills stay external — a Turn *names* the skill to invoke, it never
    carries the skill's body.

    Attributes:
        action: The loop action (one of the ``ACTION_*`` constants). Only
            ``ACTION_DISPATCH`` consults the ticket type.
        skill: The external skill the loop invokes (e.g. ``"/implement"``),
            or ``None`` for pure loop motions (pause / stop / close).
        mode: Run mode of the invoked skill — ``"AFK"`` or ``"HITL"`` — mirroring
            :attr:`routing.TypeSpec.mode`. ``None`` when no skill runs.
        opens_pr: ``True`` only for the code-delivery implement turn. The PR is
            opened by the implement agent under a system-authored prompt; the
            loop ensures its body carries ``Fixes #N``.
        pr_body: The canonical PR body (carrying ``Fixes #N``) when
            ``opens_pr``; otherwise ``None``.
    """

    action: str
    skill: Optional[str] = None
    mode: Optional[routing.Mode] = None
    opens_pr: bool = False
    pr_body: Optional[str] = None


def implement_pr_body(issue_number: int) -> str:
    """The canonical PR body for a code-delivery implement turn.

    Carries ``Fixes #N`` so GitHub auto-closes the issue on merge, plus a
    pointer to the loop's resolution comment (posted in the close-out half,
    T5b). The body is system-authored and deterministic — the implement agent
    does not author its own close text (ADR-0008; parent issue #23 story 28).
    """
    return (
        f"Fixes #{issue_number}\n\n"
        f"Implements #{issue_number} via the loop-engineering driver "
        f"(ADR-0008). A resolution comment follows on merge.\n"
    )


def plan_turn(labels: Iterable[str], issue_number: int) -> Turn:
    """Decide the loop's turn for a claimed ticket from its label set.

    Two-axis routing (ADR-0008 §2), expanded into an executable turn:

    * **Readiness gate first** (delegated to :func:`routing.route`). A ticket
      that is not ``ready-for-agent`` never reaches type dispatch, so the
      implement turn is structurally unreachable from any triage status.
    * **Type dispatch second.** Once ready, the type label selects the external
      skill (via :data:`routing.TYPE_DISPATCH`). Only ``task`` opens a PR.

    Args:
        labels: The ticket's label set (any iterable; order-independent).
        issue_number: The issue number, used to author the ``Fixes #N`` body
            for the implement turn.

    Returns:
        The :class:`Turn` the driver executes.

    Raises:
        ValueError: If the label set is ambiguous on either axis (propagated
            from :func:`routing.route`). Ambiguity is a data error the loop
            surfaces, never silently resolves.
    """
    decision = routing.route(labels)

    if decision.action == routing.ACTION_TRIAGE:
        return Turn(action=ACTION_TRIAGE, skill=TRIAGE_SKILL, mode="AFK")

    if decision.action == routing.ACTION_PAUSE:
        return Turn(action=ACTION_PAUSE)

    if decision.action == routing.ACTION_STOP:
        return Turn(action=ACTION_STOP)

    if decision.action == routing.ACTION_CLOSE:
        return Turn(action=ACTION_CLOSE)

    # routing.ACTION_DISPATCH — readiness cleared; dispatch by type.
    assert decision.ticket_type is not None  # routed DISPATCH always carries one
    spec = routing.TYPE_DISPATCH[decision.ticket_type]
    opens_pr = decision.ticket_type == "task"
    return Turn(
        action=ACTION_DISPATCH,
        skill=spec.skill,
        mode=spec.mode,
        opens_pr=opens_pr,
        pr_body=implement_pr_body(issue_number) if opens_pr else None,
    )


# --- System-authored prompts ------------------------------------------------
# The loop authors the skill prompts so the implementer never frames its own
# review or close text (ADR-0007/0008; parent issue #23 stories 15, 28). These
# are deterministic strings — the testable contract between the loop and the
# external doing-skill.


def triage_prompt(issue_number: int) -> str:
    """The prompt the loop hands to ``/triage`` for a claimed ticket."""
    return (
        f"Triage issue #{issue_number}. Assign exactly one readiness state "
        f"(needs-triage / needs-info / ready-for-agent / ready-for-human / "
        f"wontfix) and exactly one ticket type "
        f"(research / prototype / grilling / task). Stop when labelled."
    )


def implement_prompt(issue_number: int, pr_body: str) -> str:
    """The prompt the loop hands to ``/implement`` for a ``task`` ticket.

    The implement agent does the work and commits; the PR body is
    system-authored (``Fixes #N``) and the agent is told to use it verbatim.
    The close-out review → verdict → merge run in T5b, not here — this slice
    ends at "PR opened."
    """
    return (
        f"Implement issue #{issue_number} per its acceptance criteria. "
        f"Commit to the current branch, then open a pull request. Use this "
        f"PR body verbatim (it carries the auto-close trailer):\n\n"
        f"{pr_body}"
    )


def dispatch_prompt(skill: str, issue_number: int) -> str:
    """The prompt the loop hands to a non-task dispatched skill.

    ``task`` uses :func:`implement_prompt` (it opens a PR); the other types
    invoke their skill with a plain pointer to the issue.
    """
    return f"Run {skill} for issue #{issue_number} per its acceptance criteria."


# --- Driver: thin I/O over the pure planner ---------------------------------
# Reads labels with ``gh``, plans the turn, invokes skills with
# ``paseo run --detach``. Deliberately not unit-tested (issue #23 testing
# decisions); ``--dry-run`` emits the planned turn + command without executing.


def _gh_issue_labels(issue_number: int, repo: str) -> list[str]:
    """Return a ticket's label names via the GitHub CLI.

    Uses ``gh issue view --json labels``. Raises ``RuntimeError`` if ``gh`` is
    unavailable or the issue is not found — the driver surfaces I/O failures
    rather than guessing a route from silence.
    """
    try:
        result = subprocess.run(
            [
                "gh", "issue", "view", str(issue_number),
                "--repo", repo,
                "--json", "number,title,labels",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("`gh` CLI not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"gh issue view #{issue_number} failed: {exc.stderr.strip()}"
        ) from exc

    data = json.loads(result.stdout)
    return [label["name"] for label in data.get("labels", [])]


@dataclass(frozen=True)
class DriverConfig:
    """Runtime knobs for the loop driver.

    Defaults follow the Paseo adapter (``tickets-to-paseo``) and the
    conventional Paseo daemon defaults (CONTEXT.md); override via the CLI.

    Close-out fields (T5b): the independent reviewer runs on a **different
    provider** than the implementer (ADR-0007 §2, model axis — reviewer
    independence). ``secondary_provider`` / ``secondary_model`` default empty;
    a live review turn raises if they are unset or equal the primary, since
    armed independence requires a different provider (mirroring FAILOVER).
    """

    repo: str = "CaicoLeung/skills"
    base_branch: str = "main"
    provider: str = "anthropic"
    model: str = "claude-sonnet-4"
    mode: str = "primary"
    extra_run_args: tuple[str, ...] = field(default_factory=tuple)
    # Close-out (T5b / ADR-0007 §2):
    secondary_provider: str = ""
    secondary_model: str = ""
    reviewer_login: str = ""


def paseo_run_command(
    cfg: DriverConfig,
    workspace: str,
    prompt: str,
) -> list[str]:
    """Build the ``paseo run --detach`` invocation for a skill turn.

    Mirrors the EXECUTE → ``paseo run`` mapping in ``tickets-to-paseo``. The
    agent runs detached (10–30 min, async); the loop does not poll it.
    """
    return _paseo_run(
        provider=cfg.provider,
        model=cfg.model,
        mode=cfg.mode,
        workspace=workspace,
        base=cfg.base_branch,
        prompt=prompt,
        extra=cfg.extra_run_args,
    )


def _paseo_run(
    *,
    provider: str,
    model: str,
    mode: str,
    workspace: str,
    base: str,
    prompt: str,
    extra: tuple[str, ...] = (),
) -> list[str]:
    """Shared ``paseo run --detach`` builder.

    Both the routing turns (primary provider) and the close-out review turn
    (secondary provider, ADR-0007 §2) route through this so the command shape
    is defined once.
    """
    return [
        "paseo", "run",
        "--provider", provider,
        "--model", model,
        "--mode", mode,
        "--worktree", workspace,
        "--base", base,
        "--detach",
        *extra,
        prompt,
    ]


def workspace_name(issue_number: int, turn: Turn) -> str:
    """Deterministic worktree name for a ticket's turn.

    A dispatched ``task`` carries two skill names in one string
    (``/implement + /code-review``); the worktree is named after the *primary*
    skill (the one that owns the workspace and opens the PR) so the slug stays
    readable — no stray ``+`` or leading dash.
    """
    raw = turn.skill or turn.action
    primary = raw.split("+", 1)[0].strip().lstrip("/")
    slug = primary.replace("/", "-").replace(" ", "-") or turn.action
    return f"issue-{issue_number}-{slug}"


def _turn_command(cfg: DriverConfig, issue_number: int, turn: Turn) -> list[str]:
    """The shell command the driver runs for a planned turn.

    Single source of truth shared by the dry-run and execute arms, so the
    preview always matches what runs. Returns ``[]`` for turns with no shell
    command (pause / stop are pure loop motions).
    """
    if turn.action == ACTION_CLOSE:
        return ["gh", "issue", "close", str(issue_number), "--repo", cfg.repo]
    if turn.skill is None:
        return []  # pause / stop — pure loop motions, no shell command
    if turn.opens_pr and turn.pr_body is not None:
        prompt = implement_prompt(issue_number, turn.pr_body)
    elif turn.action == ACTION_TRIAGE:
        prompt = triage_prompt(issue_number)
    else:
        prompt = dispatch_prompt(turn.skill, issue_number)
    return paseo_run_command(cfg, workspace_name(issue_number, turn), prompt)


def turn_status(turn: Turn, issue_number: int) -> str:
    """The human-readable outcome of a planned/executed turn.

    Total over every action: pause, stop, close, and the dispatched skill
    turns. Encodes the ADR-0008 §3 invariant that HITL types pause for the
    human turn — their status is distinct from AFK so a consumer never
    mistakes a human-needed turn for a fire-and-forget one. ``mode`` is
    therefore not mere metadata; it shapes the outcome the loop reports.
    """
    if turn.action == ACTION_PAUSE:
        return "paused for reporter (needs-info); re-triage on update"
    if turn.action == ACTION_STOP:
        return "stopped; left for a human (ready-for-human)"
    if turn.action == ACTION_CLOSE:
        return "closed (wontfix)"
    if turn.opens_pr:
        return f"implement turn invoked; PR opened (Fixes #{issue_number})"
    if turn.mode == "HITL":
        return f"{turn.skill} turn invoked; paused for human turn (HITL)"
    return f"{turn.skill} turn invoked (AFK)"


def run_ticket_loop(
    issue_number: int,
    cfg: Optional[DriverConfig] = None,
    *,
    dry_run: bool = False,
    runner: Optional[Callable[..., int]] = None,
) -> dict:
    """Drive one routing turn for a claimed ticket.

    Reads the ticket's labels, plans the turn, and (unless ``dry_run``)
    executes it. Returns a JSON-serializable report of the planned turn and the
    command that was (or would be) run.

    Args:
        issue_number: The claimed issue to drive.
        cfg: Driver configuration; defaults to :class:`DriverConfig`.
        dry_run: If ``True``, plan only — emit the turn + command without
            invoking ``paseo``/``gh issue close``. Lets the driver be exercised
            safely in CI.
        runner: Optional callable ``(cmd: list[str]) -> int`` replacing the
            shell invocation. Defaults to :func:`subprocess.run`. Used by
            integration harnesses; not by the unit tests.

    The close-out half (review → verdict → merge → close, T5b) is out of
    scope here: for ``task`` this function ends at "implement turn invoked /
    PR opened."
    """
    cfg = cfg or DriverConfig()
    run = runner or (lambda cmd: subprocess.run(cmd, check=True).returncode)

    labels = _gh_issue_labels(issue_number, cfg.repo)
    turn = plan_turn(labels, issue_number)

    command = _turn_command(cfg, issue_number, turn)
    report: dict = {
        "issue": issue_number,
        "labels": labels,
        "turn": {
            "action": turn.action,
            "skill": turn.skill,
            "mode": turn.mode,
            "opens_pr": turn.opens_pr,
            "pr_body": turn.pr_body,
        },
        "command": command,
    }

    if dry_run:
        return report

    # --- Execute the planned turn -------------------------------------------
    # Pause / stop are pure loop motions (no command); close and the skill
    # turns carry a command built once by _turn_command, so the dry-run
    # preview matches what runs.
    if turn.action == ACTION_PAUSE:
        report["status"] = turn_status(turn, issue_number)
        return report

    if turn.action == ACTION_STOP:
        report["status"] = turn_status(turn, issue_number)
        return report

    if not command:
        return report

    run(command)
    report["status"] = turn_status(turn, issue_number)
    return report



# --- Close-out driver (T5b / ADR-0008 §5) ----------------------------------
# The close-out half: invoke the independent reviewer (T4) → derive the
# verdict (T1/T3) → hand findings to the same implementer verbatim → re-review
# until pass or the 3-round cap (STUCK_REVIEW) → on pass, the LOOP enables
# auto-merge → dual close. The pure decision logic + system-authored prompts
# + command builders live in ``scripts/closeout.py``; this is its thin I/O
# layer, mirroring the T5a routing driver's rule/IO split (issue #23 testing
# decisions: the pure planner is unit-tested in ``test_closeout.py``; the
# driver is exercised safely through ``--dry-run`` / ``--outcomes``).
#
# Two entry points:
#   * :func:`run_closeout_trajectory` — simulate the full trajectory over a
#     supplied verdict sequence (the CI-safe / demo path; no agents, no
#     network). Backs ``closeout --outcomes`` and ``docs/agents/closeout.md``.
#   * :func:`run_closeout_round` — drive ONE live round: read the PR's current
#     verdict (T3 selection + T1 rule), decide via ``closeout.plan_closeout``,
#     and execute the decision's commands (or print them with ``--dry-run``).
#     The multi-round iteration across the 10–30 min async agent turns is
#     orchestrated externally (the caller re-invokes per round after each agent
#     turn lands), exactly as the routing driver drives one routing turn.

# The skill the loop invokes for the independent review turn. Doing-skills stay
# external (ADR-0001); the loop only names them. /code-review is invoked on the
# secondary model in a separate worktree (ADR-0007 §2).
REVIEW_SKILL = "/code-review"


def review_worktree_name(issue_number: int) -> str:
    """Deterministic worktree name for the independent reviewer turn.

    Separate from the implement worktree (ADR-0007 §2, workspace axis): the
    reviewer works in its own isolated worktree branched off base, so it
    shares no workspace state with the implementer.
    """
    return f"issue-{issue_number}-review"


def implement_worktree_name(issue_number: int) -> str:
    """Deterministic worktree name for the implement (and fix) turn.

    Reuses the routing half's (T5a) implement worktree so the SAME agent
    holds the context across implement → fix (parent #23 story 24): the fixer
    is the implementer, not a fresh agent that must re-load the diff.
    """
    return workspace_name(
        issue_number, plan_turn(["ready-for-agent", "task"], issue_number)
    )


def pr_url(repo: str, pr_number: int) -> str:
    """Canonical PR web URL (used in system-authored prompt/comment text)."""
    return f"https://github.com/{repo}/pull/{pr_number}"


def _require_reviewer_independence(cfg: DriverConfig) -> None:
    """Armed reviewer independence needs a *different* provider (ADR-0007 §2).

    Mirrors the FAILOVER "armed only when different providers" rule. Raises
    ``RuntimeError`` if the secondary is unset or equals the primary, so a
    live review never silently runs on the implementer's own provider.
    """
    if not cfg.secondary_provider or not cfg.secondary_model:
        raise RuntimeError(
            "close-out review requires --secondary-provider/--secondary-model "
            "(the independent reviewer runs on a different provider; ADR-0007 §2)"
        )
    if cfg.secondary_provider == cfg.provider:
        raise RuntimeError(
            f"reviewer independence requires a different provider "
            f"(secondary {cfg.secondary_provider!r} == primary {cfg.provider!r}; "
            f"ADR-0007 §2)"
        )


def _gh_pr_head_sha(pr_number: int, repo: str) -> str:
    """Return the PR head SHA via ``gh``."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "headRefOid"],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"gh pr view #{pr_number} head failed: {exc}") from exc
    return json.loads(result.stdout)["headRefOid"]


def _gh_pr_diff(pr_number: int, repo: str) -> str:
    """Return the PR diff via ``gh pr diff`` (the reviewer's input; no prose)."""
    try:
        result = subprocess.run(
            ["gh", "pr", "diff", str(pr_number), "--repo", repo],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"gh pr diff #{pr_number} failed: {exc}") from exc
    return result.stdout


def _gh_issue_body(issue_number: int, repo: str) -> str:
    """Return the issue body (the ticket spec) via ``gh``."""
    try:
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_number), "--repo", repo,
             "--json", "body"],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"gh issue view #{issue_number} body failed: {exc}") from exc
    return json.loads(result.stdout).get("body", "") or ""


def _gh_pr_changed_files(pr_number: int, repo: str) -> list[str]:
    """Return the PR's changed file paths via ``gh``."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "files"],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"gh pr view #{pr_number} files failed: {exc}") from exc
    files = json.loads(result.stdout).get("files") or []
    return [f.get("path") for f in files if f.get("path")]


def _gh_pr_issue_comments(pr_number: int, repo: str) -> list[dict]:
    """Return the PR's top-level (issue) comments via the REST API."""
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/issues/{pr_number}/comments",
             "--paginate"],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"gh api comments #{pr_number} failed: {exc}") from exc
    out = result.stdout.strip()
    comments = json.loads(out) if out else []
    return comments if isinstance(comments, list) else []


def _build_reviewer_prompt(
    cfg: DriverConfig, issue_number: int, pr_number: int, head_sha: str
) -> str:
    """Render the fixed review prompt from diff + spec ONLY (ADR-0007 §2).

    Delegates to ``reviewer.build_review_prompt`` (T4), which substitutes the
    committed ``review-prompt.md`` — no author-prose slot, so commit messages
    and PR descriptions can never reach the reviewer.
    """
    import reviewer  # noqa: E402  (lazy: keep loop.py standalone-importable)

    diff = _gh_pr_diff(pr_number, cfg.repo)
    spec = _gh_issue_body(issue_number, cfg.repo)
    changed = _gh_pr_changed_files(pr_number, cfg.repo)
    return reviewer.build_review_prompt(
        diff=diff, spec=spec, sha=head_sha, changed_files=changed
    )


def read_verdict_state(
    cfg: DriverConfig, issue_number: int, pr_number: int, head_sha: str,
    comments: Optional[list[dict]] = None,
) -> closeout.VerdictState:
    """Compose the PR's current derived verdict (T3 selection + T1 rule).

    Selects the reviewer identity's latest sha-matched findings comment
    (``review_verdict.select_current_findings``) and derives the verdict
    (``verdict.derive_verdict``), packing both into the
    :class:`closeout.VerdictState` the planner consumes. A missing/stale review
    reads as ``VERDICT_MISSING`` (no findings to hand the fixer); the findings
    body is carried verbatim so the fix-step prompt embeds it exactly.

    ``comments`` may be passed to reuse PR comments the caller already fetched
    (avoids a second paginated fetch); fetched via ``gh`` when ``None``.
    """
    import review_verdict  # noqa: E402
    import verdict  # noqa: E402

    comments = comments if comments is not None else _gh_pr_issue_comments(
        pr_number, cfg.repo
    )
    selected = review_verdict.select_current_findings(
        comments, head_sha, cfg.reviewer_login
    )
    if selected is None:
        return closeout.VerdictState(
            status=closeout.VERDICT_MISSING, findings_text="",
            blocking_count=0, coverage_gap_count=0,
        )
    changed = _gh_pr_changed_files(pr_number, cfg.repo)
    result = verdict.derive_verdict(selected.body, changed)
    return closeout.VerdictState(
        status=closeout.VERDICT_PASS if result.passed else closeout.VERDICT_FAIL,
        findings_text=selected.body,
        blocking_count=len(result.blocking_issues),
        coverage_gap_count=len(result.coverage_gaps),
    )


def review_round_count(cfg: DriverConfig, pr_number: int, comments: Optional[list[dict]] = None) -> int:
    """Number of reviewer findings comments already posted on the PR.

    A *round* is one completed independent review of the current PR head
    (ADR-0008 §5; ``closeout.plan_closeout`` counts the cap in these). The
    driver counts the reviewer identity's sha-tagged findings comments — each
    posted comment is one review round completed. ``comments`` may be passed to
    reuse PR comments the caller already fetched; fetched via ``gh`` when ``None``.
    """
    import review_verdict  # noqa: E402

    comments = comments if comments is not None else _gh_pr_issue_comments(
        pr_number, cfg.repo
    )
    rounds = 0
    for c in comments:
        user = (c.get("user") or {})
        if (user.get("login") or "") != cfg.reviewer_login:
            continue
        if review_verdict.extract_reviewed_sha(c.get("body") or "") is not None:
            rounds += 1
    return rounds


def closeout_decision_commands(
    cfg: DriverConfig,
    decision: closeout.CloseoutDecision,
    issue_number: int,
    pr_number: int,
    head_sha: Optional[str] = None,
) -> list[list[str]]:
    """The shell command(s) for a close-out decision, enriched for live review.

    Wraps :func:`closeout.closeout_commands` (the pure command builder). For a
    REVIEW decision it substitutes the real fixed review prompt (built from
    diff + spec by ``reviewer.build_review_prompt``) and the secondary
    provider/model — reviewer independence axes 2/3 (ADR-0007 §2). For FIX it
    fills the primary provider/model on the implementer's worktree. PASS/STUCK
    commands are returned verbatim (loop-owned ``gh`` operations).

    ``head_sha`` (which :func:`run_closeout_round` already holds) is passed
    through to the review-prompt builder; when omitted it is fetched via ``gh``
    so the function stays callable standalone.
    """
    url = pr_url(cfg.repo, pr_number)
    sha = head_sha or _gh_pr_head_sha(pr_number, cfg.repo)
    commands = closeout.closeout_commands(
        decision,
        cfg.repo, issue_number, pr_number, url, cfg.base_branch,
        reviewer_workspace=review_worktree_name(issue_number),
        implementer_workspace=implement_worktree_name(issue_number),
    )

    if decision.action == closeout.ACTION_REVIEW:
        # Replace the placeholder review prompt with the real fixed prompt on
        # the secondary provider (the pure builder could not know cfg/diff).
        _require_reviewer_independence(cfg)
        prompt = _build_reviewer_prompt(cfg, issue_number, pr_number, sha)
        commands = [
            _paseo_run(
                provider=cfg.secondary_provider, model=cfg.secondary_model,
                mode=cfg.mode, workspace=review_worktree_name(issue_number),
                base=cfg.base_branch, prompt=prompt, extra=cfg.extra_run_args,
            )
        ]

    if decision.action == closeout.ACTION_FIX:
        # closeout_commands already built the FIX paseo run with the verbatim
        # prompt; re-emit it through _paseo_run so provider/model/mode come
        # from cfg (the pure builder hardcodes a minimal paseo shape).
        commands = [
            _paseo_run(
                provider=cfg.provider, model=cfg.model, mode=cfg.mode,
                workspace=implement_worktree_name(issue_number),
                base=cfg.base_branch,
                prompt=closeout.fix_prompt(
                    decision.findings_text, issue_number, url
                ),
                extra=cfg.extra_run_args,
            )
        ]

    return [list(c) for c in commands]


def run_closeout_trajectory(
    issue_number: int,
    pr_number: int,
    outcomes: list[closeout.VerdictState],
    cfg: Optional[DriverConfig] = None,
    *,
    start_round: int = 1,
) -> dict:
    """Simulate the full close-out trajectory for a verdict sequence.

    The pure, CI-safe realization of the close-out loop (issue #29 AC #5).
    No agents, no network: it iterates :func:`closeout.plan_closeout` over the
    supplied per-round verdict states and records each decision + its commands
    (via :func:`closeout.closeout_commands`). Backs the ``closeout --outcomes``
    CLI and the demo in ``docs/agents/closeout.md``.

    A *round* = one completed review (``closeout`` convention: ``round`` counts
    reviews already done). The sim starts at ``start_round`` (default 1 = first
    review in hand) and advances one round per FIX/REVIEW (a re-review will
    complete); PASS and STUCK are terminal.
    """
    cfg = cfg or DriverConfig()
    decisions: list[dict] = []
    terminal = False
    round_ = start_round
    for vs in outcomes:
        decision = closeout.plan_closeout(vs, round_)
        commands = closeout.closeout_commands(
            decision, cfg.repo, issue_number, pr_number,
            pr_url(cfg.repo, pr_number), cfg.base_branch,
            reviewer_workspace=review_worktree_name(issue_number),
            implementer_workspace=implement_worktree_name(issue_number),
        )
        decisions.append({
            **decision.to_dict(),
            "commands": [list(c) for c in commands],
        })
        if decision.action in (closeout.ACTION_PASS, closeout.ACTION_STUCK):
            terminal = True
            break
        # FIX or REVIEW → a re-review completes; advance the round count.
        round_ += 1
    rounds_used = max((d["round"] for d in decisions), default=0)
    return {
        "issue": issue_number,
        "pr": pr_number,
        "start_round": start_round,
        "rounds_used": rounds_used,
        "terminal": terminal,
        "decisions": decisions,
    }


def run_closeout_round(
    issue_number: int,
    pr_number: int,
    cfg: Optional[DriverConfig] = None,
    *,
    head_sha: Optional[str] = None,
    verdict_state: Optional[closeout.VerdictState] = None,
    round_number: Optional[int] = None,
    dry_run: bool = False,
    runner: Optional[Callable[..., int]] = None,
) -> dict:
    """Drive ONE close-out round for a PR.

    Reads the PR head, the current derived verdict (unless ``verdict_state`` is
    supplied — useful for tests/dry-run), and the review-round count, decides
    via :func:`closeout.plan_closeout`, and (unless ``dry_run``) executes the
    decision's commands. The multi-round iteration across async agent turns is
    orchestrated externally: the caller re-invokes this per round after each
    agent turn lands, just as the routing driver drives one routing turn.

    Args:
        issue_number: The issue the PR implements.
        pr_number: The PR under review.
        cfg: Driver configuration; defaults to :class:`DriverConfig`.
        head_sha: Override the PR head SHA (else fetched via ``gh``).
        verdict_state: Override the verdict (else read via the T3+T1 core).
        round_number: Override the review-round count (else counted via ``gh``).
        dry_run: Plan + print the decision/commands without executing.
        runner: Optional ``(cmd, **kwargs) -> int`` replacing the shell call.
    """
    cfg = cfg or DriverConfig()
    run = runner or (lambda cmd, **kw: subprocess.run(cmd, check=True, **kw).returncode)

    sha = head_sha or _gh_pr_head_sha(pr_number, cfg.repo)
    # Fetch the PR's issue comments once and thread them through both the
    # verdict derivation and the round count — each would otherwise paginate
    # the same endpoint a second time per round.
    comments = None
    if verdict_state is None or round_number is None:
        comments = _gh_pr_issue_comments(pr_number, cfg.repo)
    vs = verdict_state if verdict_state is not None else read_verdict_state(
        cfg, issue_number, pr_number, sha, comments=comments
    )
    rnd = round_number if round_number is not None else review_round_count(
        cfg, pr_number, comments=comments
    )

    decision = closeout.plan_closeout(vs, rnd)

    try:
        commands = closeout_decision_commands(
            cfg, decision, issue_number, pr_number, head_sha=sha
        )
    except RuntimeError as exc:
        commands = []
        command_error = str(exc)
    else:
        command_error = None

    report: dict = {
        "issue": issue_number,
        "pr": pr_number,
        "head_sha": sha,
        "round": rnd,
        "verdict": {
            "status": vs.status,
            "passed": vs.passed,
            "blocking_count": vs.blocking_count,
            "coverage_gap_count": vs.coverage_gap_count,
        },
        "decision": decision.to_dict(),
        "commands": commands,
        "status": closeout_decision_status(decision),
    }
    if command_error:
        report["command_error"] = command_error

    if dry_run or not commands:
        return report

    for cmd in commands:
        run(cmd)
    return report


def closeout_decision_status(decision: closeout.CloseoutDecision) -> str:
    """Human-readable outcome of a planned/executed close-out decision."""
    if decision.action == closeout.ACTION_PASS:
        return "derived verdict passed; loop enabled auto-merge + dual close"
    if decision.action == closeout.ACTION_REVIEW:
        return "no current review; independent reviewer invoked (ADR-0007 §2)"
    if decision.action == closeout.ACTION_FIX:
        return "verdict failed; findings handed verbatim to the implementer; re-review next"
    if decision.action == closeout.ACTION_STUCK:
        return "STUCK_REVIEW: 3-round cap exhausted; PR unmerged, no auto-close"
    return decision.action




# --- CLI --------------------------------------------------------------------


def _route_parser(sub) -> None:
    """The routing subparser (T5a)."""
    p = sub.add_parser(
        "route",
        help="drive one routing turn for a claimed ticket (ADR-0008 / T5a)",
    )
    p.add_argument("issue", type=int, help="claimed issue number to drive")
    p.add_argument("--repo", default=os.environ.get("LOOP_REPO", "CaicoLeung/skills"))
    p.add_argument("--base", default=os.environ.get("LOOP_BASE_BRANCH", "main"))
    p.add_argument("--provider", default=os.environ.get("LOOP_PROVIDER", "anthropic"))
    p.add_argument("--model", default=os.environ.get("LOOP_MODEL", "claude-sonnet-4"))
    p.add_argument("--mode", default=os.environ.get("LOOP_MODE", "primary"))
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="plan the turn and print the command without executing it",
    )


def _closeout_parser(sub) -> None:
    """The close-out subparser (T5b)."""
    p = sub.add_parser(
        "closeout",
        help="drive the close-out loop (review → verdict → fix → merge → close; ADR-0008 §5 / T5b)",
    )
    p.add_argument("issue", type=int, help="issue number the PR implements")
    p.add_argument("--pr", type=int, help="PR number under review")
    p.add_argument(
        "--sha", default=os.environ.get("PR_HEAD_SHA"),
        help="PR head SHA (else fetched via gh)",
    )
    p.add_argument(
        "--round", type=int, default=None,
        help="review rounds already completed (default: counted via gh)",
    )
    p.add_argument(
        "--start-round", type=int, default=1,
        help="first review round for --outcomes simulation (default: 1)",
    )
    p.add_argument(
        "--outcomes",
        help=(
            "simulate the full trajectory for a comma-separated per-round "
            "outcome list (pass | fail | none). CI-safe: no agents, no network. "
            "Mutually exclusive with a live single-round drive."
        ),
    )
    p.add_argument("--repo", default=os.environ.get("LOOP_REPO", "CaicoLeung/skills"))
    p.add_argument("--base", default=os.environ.get("LOOP_BASE_BRANCH", "main"))
    p.add_argument("--provider", default=os.environ.get("LOOP_PROVIDER", "anthropic"))
    p.add_argument("--model", default=os.environ.get("LOOP_MODEL", "claude-sonnet-4"))
    p.add_argument(
        "--secondary-provider", default=os.environ.get("LOOP_SECONDARY_PROVIDER", ""),
        help="independent reviewer provider (must differ from --provider; ADR-0007 §2)",
    )
    p.add_argument(
        "--secondary-model", default=os.environ.get("LOOP_SECONDARY_MODEL", ""),
        help="independent reviewer model (ADR-0007 §2)",
    )
    p.add_argument(
        "--reviewer-login", default=os.environ.get("REVIEWER_LOGIN", ""),
        help="identity whose findings count (review-verdict CI filter)",
    )
    p.add_argument("--mode", default=os.environ.get("LOOP_MODE", "primary"))
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="plan the decision/trajectory and print commands without executing",
    )


def _route_main(args) -> int:
    cfg = DriverConfig(
        repo=args.repo, base_branch=args.base,
        provider=args.provider, model=args.model, mode=args.mode,
    )
    try:
        report = run_ticket_loop(args.issue, cfg, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    if args.dry_run and report.get("command"):
        print("\n# command:", " ".join(shlex.quote(c) for c in report["command"]))
    return 0


# Outcome tokens → closeout.VerdictState for the trajectory simulator.
_SAMPLE_FINDINGS = (
    "### Standards\n[src/x.py:9]: HIGH: null deref\n"
    "### Spec\n[src/x.py]: OK\n"
)
_OUTCOME_TOKENS = {
    "pass": lambda: closeout.VerdictState(closeout.VERDICT_PASS, "", 0, 0),
    "fail": lambda: closeout.VerdictState(
        closeout.VERDICT_FAIL, _SAMPLE_FINDINGS, 1, 0
    ),
    "none": lambda: closeout.VerdictState(closeout.VERDICT_MISSING, "", 0, 0),
}


def _closeout_main(args) -> int:
    cfg = DriverConfig(
        repo=args.repo, base_branch=args.base,
        provider=args.provider, model=args.model, mode=args.mode,
        secondary_provider=args.secondary_provider,
        secondary_model=args.secondary_model,
        reviewer_login=args.reviewer_login,
    )

    if args.outcomes is not None:
        # Trajectory simulation (pure; the canonical demo path).
        outcomes: list[closeout.VerdictState] = []
        for tok in args.outcomes.split(","):
            tok = tok.strip().lower()
            if tok not in _OUTCOME_TOKENS:
                print(f"error: unknown outcome {tok!r} (expected pass/fail/none)", file=sys.stderr)
                return 2
            outcomes.append(_OUTCOME_TOKENS[tok]())
        if not args.pr:
            print("error: --outcomes also requires --pr (the PR under review)", file=sys.stderr)
            return 2
        report = run_closeout_trajectory(
            args.issue, args.pr, outcomes, cfg, start_round=args.start_round
        )
        print(json.dumps(report, indent=2))
        return 0

    if not args.pr:
        print("error: closeout requires --pr (or --outcomes for a pure sim)", file=sys.stderr)
        return 2

    try:
        report = run_closeout_round(
            args.issue, args.pr, cfg,
            head_sha=args.sha, round_number=args.round, dry_run=args.dry_run,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    if args.dry_run and report.get("commands"):
        for cmd in report["commands"]:
            print("\n# command:", " ".join(shlex.quote(c) for c in cmd))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Loop driver CLI (ADR-0008).

    Subcommands:
      route <issue>     drive one routing turn (T5a)
      closeout <issue>  drive the close-out loop (T5b)

    Legacy form: ``loop.py <issue>`` is treated as ``loop.py route <issue>``
    so the T5a examples (``python3 scripts/loop.py 28``) keep working.
    """
    argv = list(argv) if argv is not None else sys.argv[1:]
    known = {"route", "closeout"}
    if argv and argv[0] not in known and not argv[0].startswith("-"):
        argv = ["route", *argv]  # legacy: bare issue number → route

    p = argparse.ArgumentParser(
        description="Deterministic loop driver (ADR-0008): routing (T5a) + close-out (T5b)"
    )
    sub = p.add_subparsers(dest="cmd")
    _route_parser(sub)
    _closeout_parser(sub)
    args = p.parse_args(argv)

    if args.cmd == "closeout":
        return _closeout_main(args)
    return _route_main(args)


if __name__ == "__main__":
    sys.exit(main())
