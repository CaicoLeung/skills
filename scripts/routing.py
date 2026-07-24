#!/usr/bin/env python3
"""Two-axis ticket routing dispatcher (T2 / ADR-0008).

The loop driver routes a claimed ticket on two **orthogonal** label axes:

1. **Readiness state** — the triage-state label (the five canonical triage
   roles). The loop gates on this *first*: a ticket that is not
   ``ready-for-agent`` never reaches type dispatch.
2. **Ticket type** — the kind of work (``research`` / ``prototype`` /
   ``grilling`` / ``task``), mirroring ``wayfinder``'s vocabulary. Only
   consulted once readiness clears; it selects which external skill runs and
   what resolution ritual applies.

This module is the **pure** routing core — no I/O, no ``gh``, no ``paseo``.
The deterministic loop driver (``scripts/loop.py``, future) reads a ticket's
labels, calls :func:`route`, and acts on the returned :class:`Route`. Keeping
the decision in a pure function makes it unit-testable and immune to the
natural-language unreliability Loop Engineering exists to remove (ADR-0008).

See ``docs/agents/ticket-types.md`` for the type vocabulary and its
orthogonality to the triage state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

# --- Axis 1: readiness (triage state) ----------------------------------------
# The five canonical triage roles (see docs/agents/triage-labels.md). Exactly
# one (or none) is present on a ticket.
READINESS_STATES = frozenset(
    {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"}
)

# --- Axis 2: ticket type -----------------------------------------------------
# The kind of work a ticket represents (see docs/agents/ticket-types.md).
# Orthogonal to readiness state: the loop gates on state, then dispatches on
# type. Set at ticket creation; never inferred from prose.
TICKET_TYPES = frozenset({"research", "prototype", "grilling", "task"})

# Type dispatch table — maps a type to the external skill the loop invokes, its
# AFK/HITL mode, and its resolution ritual (ADR-0008 §3). Doing-skills stay
# external; the loop *invokes* them, it does not carry them.
TYPE_DISPATCH = {
    "research": {
        "skill": "/research",
        "mode": "AFK",
        "resolution": "findings comment → close",
    },
    "prototype": {
        "skill": "/prototype",
        "mode": "HITL",
        "resolution": "pause → link artifact → close",
    },
    "grilling": {
        "skill": "/grilling + /domain-modeling",
        "mode": "HITL",
        "resolution": "pause → record decision → close",
    },
    "task": {
        "skill": "/implement + /code-review",
        "mode": "AFK",
        "resolution": "PR → derived verdict → merge → close",
    },
}

# The action the loop takes for a claimed ticket.
ACTION_TRIAGE = "triage"      # invoke /triage (untriaged, unlabeled, or untyped)
ACTION_PAUSE = "pause"        # pause for reporter info (needs-info)
ACTION_STOP = "stop"          # leave for a human (ready-for-human)
ACTION_CLOSE = "close"        # skip / close (wontfix)
ACTION_DISPATCH = "dispatch"  # readiness clear → run the type's skill


@dataclass(frozen=True)
class Route:
    """The action the loop takes for a ticket, plus the dispatched type if any.

    ``ticket_type`` is set only for ``ACTION_DISPATCH``; it is always a key of
    :data:`TYPE_DISPATCH`.
    """

    action: str
    ticket_type: Optional[str] = None


def _pick_axis(labels, universe, axis_name):
    """Return the single label from ``universe`` present in ``labels``, or None.

    Raises ``ValueError`` if more than one is present — each axis carries at
    most one label, and ambiguity is a data error the loop must surface, not
    silently resolve.
    """
    found = universe.intersection(labels)
    if len(found) > 1:
        raise ValueError(
            f"ticket has multiple {axis_name} labels: {sorted(found)} "
            f"(expected at most one of {sorted(universe)})"
        )
    return next(iter(found)) if found else None


def readiness_state(labels: Iterable[str]) -> Optional[str]:
    """Return the single triage-state label on a ticket, or ``None`` if none.

    Raises ``ValueError`` if more than one readiness label is present — a
    ticket is in exactly one triage state.
    """
    return _pick_axis(labels, READINESS_STATES, "readiness")


def ticket_type(labels: Iterable[str]) -> Optional[str]:
    """Return the single type label on a ticket, or ``None`` if none.

    Raises ``ValueError`` if more than one type label is present — type is a
    single explicit label, and ambiguity defeats deterministic dispatch.
    """
    return _pick_axis(labels, TICKET_TYPES, "type")


def route(labels: Iterable[str]) -> Route:
    """Decide the loop's action for a claimed ticket from its label set.

    Two-axis routing (ADR-0008 §2):

    * **Readiness gate first.** ``ready-for-agent`` proceeds to type dispatch;
      ``needs-triage`` or no triage label invokes ``/triage``; ``needs-info``
      pauses; ``ready-for-human`` stops; ``wontfix`` closes/skips.
    * **Type dispatch second** (only once ready). The type label selects the
      skill. A ``ready-for-agent`` ticket with **no type label** is itself a
      triage gap — the type was never assigned — so it routes to ``/triage``
      rather than guessing from prose.

    Labels outside the two axes (e.g. ``bug``, ``documentation``) are ignored.
    """
    labels = set(labels)
    state = readiness_state(labels)

    if state == "ready-for-agent":
        ttype = ticket_type(labels)
        if ttype is None:
            # Ready but untyped: the type was never decided. Treat as a triage
            # gap — dispatch must be deterministic, never inferred from prose.
            return Route(ACTION_TRIAGE)
        return Route(ACTION_DISPATCH, ttype)

    if state in (None, "needs-triage"):
        # No triage label, or explicitly needs-triage → invoke /triage.
        return Route(ACTION_TRIAGE)

    if state == "needs-info":
        return Route(ACTION_PAUSE)

    if state == "ready-for-human":
        return Route(ACTION_STOP)

    # state == "wontfix"
    return Route(ACTION_CLOSE)
