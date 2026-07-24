#!/usr/bin/env python3
"""Unit tests for the two-axis ticket routing dispatcher (T2).

Zero-dependency: runnable directly as ``python3 scripts/test_routing.py``.
Exits non-zero on any failure. Covers the readiness gate, type dispatch, and
the orthogonality of the two label axes — the only non-trivial logic in the
loop's routing step (ADR-0008). Behavior, not plumbing: no ``gh``, no
``paseo``, no agent calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import routing  # noqa: E402


def _check_table(cases):
    """Run a list of (labels, expected_route) cases. Returns failure count."""
    failed = 0
    for labels, expected in cases:
        got = routing.route(labels)
        if got != expected:
            print(f"  FAIL route({sorted(labels)!r})")
            print(f"       got      = {got}")
            print(f"       expected = {expected}")
            failed += 1
    return failed


def main() -> int:
    failed = 0

    # --- Readiness gate: each triage state maps to its action ----------------
    # (type label is irrelevant until readiness clears)
    readiness_cases = [
        # Unlabeled ticket → triage (the core readiness gap).
        ([], routing.Route(routing.ACTION_TRIAGE)),
        # needs-triage → triage.
        (["needs-triage"], routing.Route(routing.ACTION_TRIAGE)),
        # needs-info → pause for reporter info.
        (["needs-info"], routing.Route(routing.ACTION_PAUSE)),
        # ready-for-human → leave for a human.
        (["ready-for-human"], routing.Route(routing.ACTION_STOP)),
        # wontfix → close / skip.
        (["wontfix"], routing.Route(routing.ACTION_CLOSE)),
        # A type label alone, with no readiness state, is still untriaged.
        (["task"], routing.Route(routing.ACTION_TRIAGE)),
        (["research"], routing.Route(routing.ACTION_TRIAGE)),
    ]
    print("readiness gate:")
    failed += _check_table(readiness_cases)

    # --- Type dispatch: readiness clear → run the type's skill ---------------
    dispatch_cases = []
    for ttype in routing.TICKET_TYPES:
        dispatch_cases.append(
            (["ready-for-agent", ttype], routing.Route(routing.ACTION_DISPATCH, ttype))
        )
    print("type dispatch:")
    failed += _check_table(dispatch_cases)

    # --- Orthogonality: non-axis labels never change the route ---------------
    # The readiness state still wins; type labels are ignored until ready.
    ortho_cases = [
        # Irrelevant labels on an untriaged ticket → still triage.
        (["bug", "documentation"], routing.Route(routing.ACTION_TRIAGE)),
        # Irrelevant labels with needs-info → still pause.
        (["needs-info", "bug", "enhancement"], routing.Route(routing.ACTION_PAUSE)),
        # Ready + task + irrelevant labels → dispatch task.
        (
            ["ready-for-agent", "task", "bug", "good first issue"],
            routing.Route(routing.ACTION_DISPATCH, "task"),
        ),
        # Ready + research + wayfinder label → dispatch research.
        (
            ["ready-for-agent", "research", "wayfinder:task"],
            routing.Route(routing.ACTION_DISPATCH, "research"),
        ),
    ]
    print("orthogonality (non-axis labels ignored):")
    failed += _check_table(ortho_cases)

    # --- Edge: ready-for-agent but no type label → triage gap ----------------
    # Ready state clears, but the type was never assigned. Dispatch must stay
    # deterministic: route to /triage rather than inferring a type from prose.
    print("ready-but-untyped → triage gap:")
    failed += _check_table(
        [(["ready-for-agent", "bug"], routing.Route(routing.ACTION_TRIAGE))]
    )

    # --- Axis accessors ------------------------------------------------------
    print("axis accessors:")
    accessor_cases = [
        (routing.readiness_state(["ready-for-agent", "task"]), "ready-for-agent"),
        (routing.readiness_state(["task"]), None),
        (routing.ticket_type(["ready-for-agent", "grilling"]), "grilling"),
        (routing.ticket_type(["ready-for-agent"]), None),
    ]
    for got, expected in accessor_cases:
        if got != expected:
            print(f"  FAIL accessor got {got!r}, expected {expected!r}")
            failed += 1

    # --- Type dispatch table is complete and well-formed ---------------------
    print("dispatch table integrity:")
    if set(routing.TYPE_DISPATCH) != routing.TICKET_TYPES:
        print(
            f"  FAIL TYPE_DISPATCH keys {sorted(routing.TYPE_DISPATCH)} "
            f"!= TICKET_TYPES {sorted(routing.TICKET_TYPES)}"
        )
        failed += 1
    for ttype, entry in routing.TYPE_DISPATCH.items():
        if entry.get("mode") not in ("AFK", "HITL"):
            print(f"  FAIL type {ttype!r} has bad mode {entry.get('mode')!r}")
            failed += 1
        for key in ("skill", "mode", "resolution"):
            if not entry.get(key):
                print(f"  FAIL type {ttype!r} missing '{key}'")
                failed += 1

    # --- Ambiguity is a hard error, not a silent pick ------------------------
    print("ambiguity raises:")
    ambiguity_cases = [
        (["needs-triage", "ready-for-agent"], "readiness"),  # two triage states
        (["ready-for-agent", "needs-info"], "readiness"),    # conflicting triage states
        (["ready-for-agent", "research", "task"], "type"),    # two types
    ]
    for labels, axis in ambiguity_cases:
        raised = False
        try:
            routing.route(labels)
        except ValueError as exc:
            raised = True
            msg = str(exc).lower()
            if axis not in msg:
                print(f"  FAIL route({sorted(labels)!r}) raised but message lacked {axis!r}: {exc}")
                failed += 1
        if not raised:
            print(f"  FAIL route({sorted(labels)!r}) should have raised (ambiguous {axis})")
            failed += 1

    # --- Determinism: identical input → identical output ---------------------
    print("determinism:")
    for _ in range(3):
        if routing.route(["ready-for-agent", "task"]) != routing.Route(
            routing.ACTION_DISPATCH, "task"
        ):
            print("  FAIL route is not deterministic across calls")
            failed += 1
            break

    total = (
        len(readiness_cases)
        + len(dispatch_cases)
        + len(ortho_cases)
        + 1
        + len(accessor_cases)
        + len(ambiguity_cases)
    )
    if failed:
        print(f"\n{failed} routing test(s) failed (of {total} cases).", file=sys.stderr)
        return 1
    print(f"\nAll {total} routing cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
