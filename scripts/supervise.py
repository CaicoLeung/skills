#!/usr/bin/env python3
"""Supervisor planner: watches gate state until merged-and-gated (ADR-0006 §T1).

The supervisor is the actor that owns the gap between **agent-finished** (the
leaf agent posted ``DONE`` at turn-end) and **merged-and-gated** (its PR merged
to the base branch AND the required CI check genuinely passed). Nothing else
owns that gap: a stuck gate produces an *absence of signal* that an
agent-finished dependent would otherwise wait on forever (the ``wf-skills-1``
stall — a renamed workflow meant the required check never appeared, the leaf
went idle, and nothing detected it).

This module is the **pure** planner that decides what the supervisor does next
for one task at one observation. It mirrors :mod:`closeout`'s shape (pure
planner + system-authored prompts + command builders) so the supervisor's
triage logic is unit-tested here, while the thin I/O driver lives in
:mod:`loop` (:func:`loop.run_supervise_round` / :func:`loop.run_supervise_trajectory`).

The decision is a total function over ``(GateState, retries_used)`` with four
outcomes:

* **COMPLETE** — merged-and-gated reached → post ``DONE task_$id pr=$url`` so
  dependents unblock on *verified* work.
* **WAIT** — no deviation, the deadline has not crossed, the gate is still
  converging. Observe again next interval. (No command.)
* **REDISPATCH** — mechanical/transient deviation, retries remain. Re-dispatch
  the SAME leaf agent via ``paseo send`` carrying the *specific* failure
  detail — no "fix all" prose. Bounded by :data:`MAX_GATE_RETRIES`.
* **ESCALATE** — genuine/ambiguous deviation, OR the retry budget is
  exhausted. Post an ``ESCALATE`` signal a human consumes (chat room + issue
  comment). Ambiguity defaults to escalate, never silent pass — that was the
  original sin (an agent read a blocked-but-passing PR as success).

Honest reconciliation (ADR-0006 §4; issue #11 AC6): the planner takes
:class:`GateState`, never agent state. Polling **gate state** (PR merge state,
CI check runs) is mandatory — a stuck gate is by definition an absence of
notification. Polling **agent internals** is the anti-pattern the original
"don't poll" guidance warned against; this planner cannot do it.

Runtime-neutral (ADR-0004): no ``paseo``, no ``gh``, no agent, no network. The
adapter (``tickets-to-paseo``) supplies the mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Bounded retry budget ---------------------------------------------------
# Mirrors :data:`closeout.MAX_REVIEW_ROUNDS`: a small, explicit cap so a
# redispatchable deviation converges or escalates, never loops forever. Two
# re-dispatches (three total observations of the same deviation) is a human
# signal, not a patience test.
MAX_GATE_RETRIES = 2

# --- Absence-of-signal deadline ---------------------------------------------
# A required check that has not reported within this window is a deviation
# (DEVIATION_CHECK_MISSING), not a silent wait. Default is conservative for
# the tracer bullet; production overrides per-workflow (the adapter maps
# ``bounded_window.max_wait_sec`` from the SUPERVISE primitive).
DEFAULT_SIGNAL_DEADLINE_SEC = 300

# --- Actions ----------------------------------------------------------------
ACTION_COMPLETE = "complete"      # merged-and-gated reached → post DONE signal
ACTION_WAIT = "wait"              # gate converging, no deviation, not timed out
ACTION_REDISPATCH = "redispatch"  # mechanical/transient, retries remain → paseo send leaf
ACTION_ESCALATE = "escalate"      # genuine/ambiguous OR retries exhausted → ESCALATE signal

# --- Deviations (the observed failure modes) --------------------------------
# DEVIATION_NONE is "no deviation; either converging or complete." Every other
# value is a discrete, named gate failure the supervisor can act on. This list
# is intentionally short — the tracer bullet's scope is the loop closing, not
# enumerating every GitHub state.
DEVIATION_NONE = "none"
DEVIATION_CHECK_MISSING = "check_missing"   # absence-of-signal: required check never reported
DEVIATION_CHECK_FAILING = "check_failing"   # required check is currently failing/error
DEVIATION_MERGE_DIRTY = "merge_dirty"       # mergeStateStatus=DIRTY (needs rebase)
DEVIATION_MERGE_BEHIND = "merge_behind"     # mergeStateStatus=BEHIND (needs rebase)
DEVIATION_MERGE_BLOCKED = "merge_blocked"   # mergeStateStatus=BLOCKED (unsatisfiable protection)
DEVIATION_UNKNOWN = "unknown"               # anything else — ambiguous, default to escalate

# --- Triage buckets (the fix / escalate decision) ---------------------------
# MECHANICAL/TRANSIENT → REDISPATCH (bounded). GENUINE/AMBIGUOUS → ESCALATE.
CLASS_MECHANICAL = "mechanical"   # re-dispatchable: needs rebase, check name drifted
CLASS_TRANSIENT = "transient"     # re-dispatchable: flaky test, transient SSL
CLASS_GENUINE = "genuine"         # escalate: unsatisfiable branch protection
CLASS_AMBIGUOUS = "ambiguous"     # escalate: unknown state — defaults to safe


@dataclass(frozen=True)
class GateState:
    """The supervisor's view of one task's gate at one observation.

    Built by the driver from ``gh`` reads (see :mod:`loop.run_supervise_round`).
    Carries absence-of-signal as a first-class field: ``signal_elapsed_sec`` is
    the time since the leaf agent finished (or the PR opened) without the
    required check appearing. ``check_seen`` records whether *this* observation
    found the required check in the commit's status contexts.

    Attributes:
        pr_state: ``OPEN`` | ``MERGED`` | ``CLOSED`` | ``""`` (unknown).
        merge_state_status: GitHub's ``mergeStateStatus`` — ``UNKNOWN``,
            ``BEHIND``, ``BLOCKED``, ``CLEAN``, ``DIRTY``, ``HAS_HOOKS``.
        merged_at: ISO timestamp when GitHub merged the PR (``""`` until then).
        required_check: The CI context the gate watches (e.g. a consumer's
            ``review-verdict``). **Empty (default) = no CI gate** — the driver's
            locally-derived verdict gates (ADR-0013); the supervisor neither
            waits on nor escalates from an absent check.
        check_state: The required check's current state — ``success``,
            ``failure``, ``error``, ``pending``, or ``""`` (not reported).
        check_seen: True iff the required check is present in the commit's
            status contexts at this observation.
        signal_elapsed_sec: Seconds since agent-finished (or PR open) without
            ``check_seen``. The driver computes this from its clock.
        signal_deadline_sec: Absence-of-signal deadline. ``check_seen=False``
            past this is DEVIATION_CHECK_MISSING.
    """

    pr_state: str
    merge_state_status: str
    required_check: str
    check_state: str
    check_seen: bool
    signal_elapsed_sec: int
    merged_at: str = ""
    signal_deadline_sec: int = DEFAULT_SIGNAL_DEADLINE_SEC

    @property
    def merged(self) -> bool:
        """True iff GitHub has merged the PR."""
        return self.pr_state == "MERGED"

    @property
    def has_required_check(self) -> bool:
        """True iff a CI gate is configured (``required_check`` is non-empty).

        Empty means no CI gate: the driver's locally-derived verdict is the
        gate (ADR-0013), so the supervisor neither waits on nor escalates from
        an absent check.
        """
        return bool(self.required_check)

    @property
    def gated(self) -> bool:
        """True iff the gate is satisfied: no required check, or it passed."""
        return (not self.has_required_check) or self.check_state == "success"

    @property
    def merged_and_gated(self) -> bool:
        """True iff PR merged AND gate passed — the only completion condition."""
        return self.merged and self.gated

    @property
    def signal_deadline_exceeded(self) -> bool:
        """True iff the required check has never been seen AND the deadline crossed.

        This is the absence-of-signal detector. A check that has *appeared*
        (even if now failing) is not absent — it is failing, a different
        deviation. Absence is specifically "never reported within the window."
        """
        return self.has_required_check and (not self.check_seen) and self.signal_elapsed_sec >= self.signal_deadline_sec


@dataclass(frozen=True)
class SuperviseDecision:
    """What the supervisor does next for a task, given its gate state + retries.

    Attributes:
        action: One of the ``ACTION_*`` constants.
        deviation: The detected deviation (``DEVIATION_NONE`` when none).
        classification: The triage bucket the deviation maps to (``""`` for
            COMPLETE/WAIT — no triage applied).
        retries_used: The retry count *at this decision* (the driver increments
            on every REDISPATCH it executes).
        retry_budget: The cap; ``retries_used >= retry_budget`` forces ESCALATE
            for any redispatchable deviation.
        reason: Human-readable rationale — surfaced in the loop report and the
            ESCALATE signal so a human can see *why* the supervisor stopped.
        redispatch_detail: The specific failure handed to the leaf, verbatim
            (REDISPATCH only); ``""`` for the other actions.
    """

    action: str
    deviation: str
    classification: str
    retries_used: int
    retry_budget: int
    reason: str
    redispatch_detail: str = ""

    def to_dict(self) -> dict:
        """JSON-serializable view for the loop report."""
        return {
            "action": self.action,
            "deviation": self.deviation,
            "classification": self.classification,
            "retries_used": self.retries_used,
            "retry_budget": self.retry_budget,
            "reason": self.reason,
            "redispatch_detail": self.redispatch_detail,
        }


# --- Triage: deviation → classification ------------------------------------


def classify_deviation(deviation: str) -> str:
    """Map a deviation to its triage bucket.

    The map is total and explicit — ambiguity is its own bucket (``unknown``
    deviations default to ESCALATE, never silent pass).

    * MECHANICAL — fixable by re-dispatching the leaf: needs rebase, check
      name drifted (the check never appeared).
    * TRANSIENT — plausibly a flap: required check currently failing/error.
      Could be a real test failure; bounded redispatch separates the two.
    * GENUINE — not leaf-fixable: unsatisfiable branch protection.
    * AMBIGUOUS — anything unrecognized. Defaults to ESCALATE.
    """
    if deviation in (DEVIATION_MERGE_DIRTY, DEVIATION_MERGE_BEHIND, DEVIATION_CHECK_MISSING):
        return CLASS_MECHANICAL
    if deviation == DEVIATION_CHECK_FAILING:
        return CLASS_TRANSIENT
    if deviation == DEVIATION_MERGE_BLOCKED:
        return CLASS_GENUINE
    return CLASS_AMBIGUOUS  # DEVIATION_UNKNOWN and any future token


# --- Observation: GateState → deviation ------------------------------------


def detect_deviation(state: GateState) -> str:
    """Detect the current deviation, if any.

    Returns :data:`DEVIATION_NONE` when the gate is genuinely converging (no
    failure mode present). Absence-of-signal is checked FIRST — a check that
    has never reported within the deadline is a deviation even if the merge
    state looks clean (the gate has not actually run).

    Order matters:

    1. ``check_missing`` (absence-of-signal) — the original ``wf-skills-1``
       stall. First because a clean mergeStateStatus with no check is exactly
       the false-positive that read as success.
    2. ``check_failing`` — the check ran and is currently red. The gate ran
       but did not pass.
    3. ``merge_blocked`` — unsatisfiable protection (GENUINE; never redispatch).
    4. ``merge_dirty`` / ``merge_behind`` — needs a rebase (MECHANICAL).
    5. ``unknown`` — unrecognized mergeStateStatus (AMBIGUOUS → escalate).
    """
    # Absence-of-signal: the check never appeared within the deadline.
    if state.signal_deadline_exceeded:
        return DEVIATION_CHECK_MISSING

    # The check ran and is currently red (failure/error). Pending or success
    # are not deviations.
    if state.check_seen and state.check_state in ("failure", "error"):
        return DEVIATION_CHECK_FAILING

    mss = (state.merge_state_status or "").upper()
    if mss == "BLOCKED":
        return DEVIATION_MERGE_BLOCKED
    if mss == "DIRTY":
        return DEVIATION_MERGE_DIRTY
    if mss == "BEHIND":
        return DEVIATION_MERGE_BEHIND

    # Recognised "no deviation" merge states (CLEAN, HAS_HOOKS, UNKNOWN-while-
    # patient) fall through here. Anything unrecognized is ambiguous.
    if mss and mss not in ("CLEAN", "HAS_HOOKS", "UNKNOWN", ""):
        return DEVIATION_UNKNOWN

    return DEVIATION_NONE


# --- The decision ----------------------------------------------------------


def plan_supervise(
    state: GateState,
    retries_used: int,
    retry_budget: int = MAX_GATE_RETRIES,
) -> SuperviseDecision:
    """Decide the supervisor's next step from a task's gate state + retry count.

    Total over ``(merged-and-gated?, deviation, retries_used)``:

    * **merged-and-gated** → :data:`ACTION_COMPLETE`. The *only* path that
      posts ``DONE``. This is what makes completion distinct from
      agent-finished.
    * **no deviation** → :data:`ACTION_WAIT`. The gate is converging or the
      deadline has not crossed; observe again next interval.
    * **deviation, classified GENUINE/AMBIGUOUS** → :data:`ACTION_ESCALATE`
      at ANY retry count. Bounded retries do not apply to deviations the leaf
      cannot fix.
    * **deviation, classified MECHANICAL/TRANSIENT, retries remain** →
      :data:`ACTION_REDISPATCH`. Re-dispatch the leaf with the specific
      failure detail.
    * **deviation, classified MECHANICAL/TRANSIENT, retries exhausted** →
      :data:`ACTION_ESCALATE`. The cap auto-escalates so the loop never
      waits forever on a non-converging deviation.

    Args:
        state: The task's current gate observation.
        retries_used: REDISPATCH actions already executed for this task. The
            driver increments on every executed REDISPATCH.
        retry_budget: The cap. Defaults to :data:`MAX_GATE_RETRIES`.

    Returns:
        The :class:`SuperviseDecision` the driver executes.
    """
    if state.merged_and_gated:
        return SuperviseDecision(
            action=ACTION_COMPLETE,
            deviation=DEVIATION_NONE,
            classification="",
            retries_used=retries_used,
            retry_budget=retry_budget,
            reason=(
                f"merged-and-gated reached ({state.required_check}=success; "
                f"PR merged at {state.merged_at or 'unknown'})"
            ),
        )

    deviation = detect_deviation(state)

    if deviation == DEVIATION_NONE:
        return SuperviseDecision(
            action=ACTION_WAIT,
            deviation=DEVIATION_NONE,
            classification="",
            retries_used=retries_used,
            retry_budget=retry_budget,
            reason=(
                "gate converging; no deviation detected "
                f"(check={state.check_state or 'unseen'}; "
                f"mergeStateStatus={state.merge_state_status or 'unknown'})"
            ),
        )

    classification = classify_deviation(deviation)

    # GENUINE/AMBIGUOUS deviations escalate at any retry count — bounded
    # retries only apply to deviations the leaf could plausibly fix.
    if classification in (CLASS_GENUINE, CLASS_AMBIGUOUS):
        return SuperviseDecision(
            action=ACTION_ESCALATE,
            deviation=deviation,
            classification=classification,
            retries_used=retries_used,
            retry_budget=retry_budget,
            reason=_escalate_reason(deviation, classification, retries_used, retry_budget),
        )

    # MECHANICAL/TRANSITION — check the budget.
    if retries_used >= retry_budget:
        return SuperviseDecision(
            action=ACTION_ESCALATE,
            deviation=deviation,
            classification=classification,
            retries_used=retries_used,
            retry_budget=retry_budget,
            reason=_escalate_reason(deviation, classification, retries_used, retry_budget),
        )

    detail = _redispatch_detail(deviation, state)
    return SuperviseDecision(
        action=ACTION_REDISPATCH,
        deviation=deviation,
        classification=classification,
        retries_used=retries_used,
        retry_budget=retry_budget,
        redispatch_detail=detail,
        reason=(
            f"{classification} deviation ({deviation}); re-dispatch the leaf "
            f"with the specific failure (retry {retries_used + 1}/{retry_budget})"
        ),
    )


def _escalate_reason(
    deviation: str, classification: str, retries_used: int, retry_budget: int,
) -> str:
    """The ESCALATE rationale — names the deviation and whether the cap fired."""
    if retries_used >= retry_budget and classification in (CLASS_MECHANICAL, CLASS_TRANSIENT):
        return (
            f"{classification} deviation ({deviation}) did not converge after "
            f"{retries_used}/{retry_budget} redispatch(s); cap exhausted — escalate"
        )
    return (
        f"{classification} deviation ({deviation}) is not leaf-fixable; "
        f"escalate to a human"
    )


def _redispatch_detail(deviation: str, state: GateState) -> str:
    """The specific failure handed to the leaf — named, not paraphrased.

    No "fix all issues" prose. Each deviation carries its own concrete
    description so the leaf knows exactly what to investigate. The leaf is
    told NOT to self-declare resolution — the supervisor re-observes the gate
    and decides; a deviation is "resolved" only when it disappears from the
    NEXT observation, never by the leaf's claim (mirrors closeout.fix_prompt).
    """
    common = (
        "This is a SUPERVISE re-dispatch (ADR-0006). The gate watcher observed "
        "a deviation after your implement turn finished. Investigate, push to "
        "the same branch, and DO NOT merge or self-declare resolution — the "
        "supervisor re-observes the gate and decides."
    )
    if deviation == DEVIATION_CHECK_MISSING:
        return (
            f"{common}\n\n"
            f"Required check `{state.required_check}` has not reported any "
            f"status within the {state.signal_deadline_sec}s absence-of-signal "
            f"deadline (last observed: check unseen after {state.signal_elapsed_sec}s). "
            f"This is the check-name-drift pattern: confirm the workflow that "
            f"produces the `{state.required_check}` status context still exists, "
            f"is triggered for this branch, and emits that exact context name."
        )
    if deviation == DEVIATION_CHECK_FAILING:
        return (
            f"{common}\n\n"
            f"Required check `{state.required_check}` is currently "
            f"`{state.check_state}`. This may be a flaky failure or a real test "
            f"failure — re-run the workflow, and if it is a real failure, fix "
            f"the underlying cause and push."
        )
    if deviation == DEVIATION_MERGE_DIRTY:
        return (
            f"{common}\n\n"
            f"GitHub reports mergeStateStatus=DIRTY: the PR has merge conflicts "
            f"with the base branch. Rebase onto the base branch and push so the "
            f"PR can merge cleanly."
        )
    if deviation == DEVIATION_MERGE_BEHIND:
        return (
            f"{common}\n\n"
            f"GitHub reports mergeStateStatus=BEHIND: the base branch has moved "
            f"ahead of the PR. Rebase onto the base branch and push."
        )
    # Should not reach here for GENUINE/AMBIGUOUS (those escalate, not redispatch);
    # kept for totality so the leaf always gets a concrete description.
    return f"{common}\n\nDeviation: {deviation}."


# --- System-authored signals ------------------------------------------------
# The supervisor authors every signal so the leaf can neither declare its own
# completion nor talk its way past the gate. These are deterministic strings —
# the testable contract between the supervisor and the chat room / human.


def completion_signal(task_id: str, pr_url: str, merged_at: str) -> str:
    """The supervisor's merged-and-gated signal.

    Dependents wait for this exact token (the adapter filters chat on
    ``DONE task_$id pr=``) — never for the leaf's own ``DONE task_$id``
    (that is agent-finished, not merged-and-gated). ``pr=`` is the marker that
    distinguishes the supervisor's verified signal from the leaf's
    agent-finished one (mirrors the DEPENDS_ON handoff in tickets-to-paseo).
    """
    return f"DONE {task_id} pr={pr_url} merged_at={merged_at}"


def escalate_signal(
    task_id: str,
    pr_url: str,
    deviation: str,
    reason: str,
    blocked: tuple[str, ...] = (),
) -> str:
    """The supervisor's ESCALATE signal — a human must intervene.

    Posted to the workflow chat room AND as a ``gh issue comment`` (durable).
    Names the deviation + the reason verbatim; lists transitive dependents in
    ``blocked`` so a human can see the scope of the stuck subgraph.
    """
    blocked_clause = (
        f" blocked=[{','.join(blocked)}]" if blocked else ""
    )
    return (
        f"ESCALATE {task_id} pr={pr_url} deviation={deviation}{blocked_clause}\n"
        f"reason: {reason}"
    )


# --- Adapter config + command builders -------------------------------------


@dataclass(frozen=True)
class SuperviseConfig:
    """Runtime knobs the adapter needs to build supervisor commands.

    Adapter-only: this module never executes the commands, it builds them.
    Mirrors the closeout adapter's command-builder contract (single source of
    truth so the ``--dry-run`` preview matches what runs).

    Attributes:
        repo: ``OWNER/REPO`` for ``gh issue comment`` (ESCALATE durability).
        chat_room: Workflow chat room the supervisor posts signals to.
        agent_id: The leaf agent's Paseo ID (target of ``paseo send``).
        workspace: The leaf's worktree (``--worktree`` for ``paseo send``).
        base_branch: Base branch (``--base`` for ``paseo send``).
    """

    repo: str
    chat_room: str
    agent_id: str
    workspace: str
    base_branch: str = "main"


def redispatch_command(cfg: SuperviseConfig, prompt: str) -> list[str]:
    """Build the ``paseo send`` that re-dispatches the leaf with the detail.

    ``paseo send`` targets an EXISTING agent (the leaf that opened the PR) —
    not ``paseo run`` (which would spawn a new one). The leaf holds its own
    context (the implement turn's workspace); re-dispatching it hands it the
    specific failure without losing that context. ``--detach`` keeps the
    supervisor non-blocking; the leaf runs async and the supervisor re-observes
    the gate on its next interval.
    """
    return [
        "paseo", "send",
        "--agent", cfg.agent_id,
        "--worktree", cfg.workspace,
        "--base", cfg.base_branch,
        "--detach",
        prompt,
    ]


def chat_post_command(chat_room: str, message: str) -> list[str]:
    """Build the ``paseo chat post`` for a supervisor signal.

    Single source of truth for the post shape; used by both COMPLETE and
    ESCALATE signals (the message body distinguishes them).
    """
    return ["paseo", "chat", "post", chat_room, message]


def issue_comment_command(repo: str, issue_number: int, body: str) -> list[str]:
    """Build the ``gh issue comment`` for a durable human signal.

    ESCALATE posts to BOTH the chat room (immediate) and an issue comment
    (durable — the chat room scrolls; the issue stays). Mirrors
    :func:`closeout.stuck_message`'s dual-post pattern.
    """
    return ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body", body]


def supervise_commands(
    decision: SuperviseDecision,
    cfg: SuperviseConfig,
    *,
    task_id: str,
    pr_url: str,
    issue_number: int | None = None,
    blocked: tuple[str, ...] = (),
) -> list[list[str]]:
    """The shell command(s) the driver runs for a supervisor decision.

    Single source of truth for the supervisor's commands, so the ``--dry-run``
    preview matches what runs (mirrors :func:`closeout.closeout_commands`).

    * COMPLETE → ``paseo chat post`` carrying :func:`completion_signal`
      (dependents filter on ``DONE task_$id pr=``).
    * WAIT → ``[]``. The supervisor observes again next interval; no command.
    * REDISPATCH → ``paseo send`` carrying :func:`redispatch_prompt` (built
      from the decision's verbatim ``redispatch_detail``).
    * ESCALATE → ``paseo chat post`` (immediate signal) + ``gh issue comment``
      (durable) — both carrying :func:`escalate_signal`. ``issue_number`` is
      required for ESCALATE; the driver asserts it.

    Args:
        decision: The supervisor's decision for this observation.
        cfg: Adapter config (repo, chat room, leaf agent_id/workspace).
        task_id: Workflow task ID (e.g. ``task_11``) for signal addressing.
        pr_url: PR web URL (the verified artifact).
        issue_number: The backing issue number — required for ESCALATE (the
            durable comment) and ignored otherwise.
        blocked: Transitive dependent task IDs affected by the stuck blocker
            (ESCALATE only) — scopes the stuck subgraph.
    """
    if decision.action == ACTION_COMPLETE:
        return [
            chat_post_command(
                cfg.chat_room,
                completion_signal(task_id, pr_url, _merged_at_from_decision(decision)),
            )
        ]

    if decision.action == ACTION_WAIT:
        return []

    if decision.action == ACTION_REDISPATCH:
        return [
            redispatch_command(
                cfg, redispatch_prompt(decision.redispatch_detail, task_id, pr_url)
            )
        ]

    # ACTION_ESCALATE — chat post (immediate) + gh issue comment (durable).
    if issue_number is None:
        raise RuntimeError(
            "ESCALATE requires issue_number (the durable gh issue comment target)"
        )
    signal = escalate_signal(
        task_id, pr_url, deviation=decision.deviation,
        reason=decision.reason, blocked=blocked,
    )
    return [
        chat_post_command(cfg.chat_room, signal),
        issue_comment_command(cfg.repo, issue_number, signal),
    ]


def redispatch_prompt(detail: str, task_id: str, pr_url: str) -> str:
    """Wrap the deviation detail as the leaf's re-dispatch prompt.

    The detail is the supervisor's specific observation (the deviation), passed
    through VERBATIM. No "resolve all issues" prose — a summary is exactly
    where a leaf could quietly decide not to investigate. The leaf is told to
    push and that the supervisor re-observes (never trust a self-declaration).
    """
    return (
        f"SUPERVISE re-dispatch for {task_id} ({pr_url}).\n\n"
        f"{detail}\n"
    )


def _merged_at_from_decision(decision: SuperviseDecision) -> str:
    """Recover the merged_at timestamp from the decision reason (best-effort).

    The COMPLETE reason embeds the merged_at the planner saw; the signal
    surfaces it for dependents. Empty when unknown (the supervisor still posts
    DONE — merged_and_gated held; the timestamp is informational).
    """
    marker = "PR merged at "
    idx = decision.reason.find(marker)
    if idx < 0:
        return ""
    tail = decision.reason[idx + len(marker):]
    # Strip the trailing ')' that closes the reason parenthetical.
    return tail.rstrip(")").strip() or ""


# --- Trajectory simulator (CI-safe demo / replay) --------------------------



def run_supervise_trajectory(
    gate_states: list[GateState],
    retry_budget: int = MAX_GATE_RETRIES,
    *,
    start_retries: int = 0,
) -> dict:
    """Simulate the supervisor over a sequence of gate observations.

    The pure, CI-safe realization of the supervisor loop (issue #11 AC5). No
    agents, no network: it iterates :func:`plan_supervise` over the supplied
    per-poll gate states, advances the retry counter on every REDISPATCH, and
    stops at the first terminal decision (COMPLETE or ESCALATE). Backs the
    ``supervise --sequence`` CLI and the replay demonstration in
    ``docs/agents/supervise.md``.

    The retry counter advances ONLY on REDISPATCH (WAIT does not consume a
    retry — the gate is still converging, not failing). This mirrors the
    close-out cap counting review rounds, not polls.
    """
    decisions: list[dict] = []
    retries = start_retries
    terminal = False
    for state in gate_states:
        decision = plan_supervise(state, retries_used=retries, retry_budget=retry_budget)
        decisions.append(decision.to_dict())
        if decision.action == ACTION_REDISPATCH:
            retries += 1
        if decision.action in (ACTION_COMPLETE, ACTION_ESCALATE):
            terminal = True
            break
    return {
        "decisions": decisions,
        "retries_used": retries,
        "terminal": terminal,
        "rounds_observed": len(decisions),
    }
