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
    """

    repo: str = "CaicoLeung/skills"
    base_branch: str = "main"
    provider: str = "anthropic"
    model: str = "claude-sonnet-4"
    mode: str = "primary"
    extra_run_args: tuple[str, ...] = field(default_factory=tuple)


def paseo_run_command(
    cfg: DriverConfig,
    workspace: str,
    prompt: str,
) -> list[str]:
    """Build the ``paseo run --detach`` invocation for a skill turn.

    Mirrors the EXECUTE → ``paseo run`` mapping in ``tickets-to-paseo``. The
    agent runs detached (10–30 min, async); the loop does not poll it.
    """
    return [
        "paseo", "run",
        "--provider", cfg.provider,
        "--model", cfg.model,
        "--mode", cfg.mode,
        "--worktree", workspace,
        "--base", cfg.base_branch,
        "--detach",
        *cfg.extra_run_args,
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


# --- CLI --------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Deterministic loop driver — routing half (ADR-0008 / T5a)"
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
    args = p.parse_args(argv)

    cfg = DriverConfig(
        repo=args.repo,
        base_branch=args.base,
        provider=args.provider,
        model=args.model,
        mode=args.mode,
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


if __name__ == "__main__":
    sys.exit(main())
