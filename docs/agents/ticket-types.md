# Ticket Types

The loop routes a claimed ticket on **two orthogonal label axes**: a readiness
*state* (the triage roles in [triage-labels](./triage-labels.md)) and a ticket
*type* — the kind of work. This file maps the type vocabulary to the actual
label strings used in this repo's issue tracker. See
[`scripts/loop.py`](../../scripts/loop.py) (the `route` subcommand) for the
two-axis routing that consumes these types.

The loop gates on readiness **first** (a ticket that is not `ready-for-agent`
never reaches type dispatch), then dispatches on type. Type is set at ticket
creation and read deterministically — never inferred from prose, since inference
is the unreliability Loop Engineering exists to remove.

| Type label | Mode | Skill (external, invoked) | Resolution ritual |
| --- | --- | --- | --- |
| `research` | AFK | `/research` subagent | findings comment → close |
| `prototype` | HITL | `/prototype` | pause → link artifact → close |
| `grilling` | HITL | `/grilling` + `/domain-modeling` | pause → record decision → close |
| `task` | AFK (code) | `/implement` + `/code-review` | PR → derived verdict → merge → close |

## Orthogonality to triage state

The type axis is **orthogonal** to the triage readiness state — a ticket
carries one of each, and neither implies the other:

- A `task` ticket can be `needs-triage`, `needs-info`, or `ready-for-agent`.
- A `ready-for-agent` ticket can be any of `research`, `prototype`, `grilling`,
  or `task`.

The loop's dispatcher encodes this as a pure two-axis function: `route(labels)`
returns the action (invoke `/triage`, pause for info, stop, close/skip, or
dispatch by type). The consumer implements it; see
[`scripts/loop.py`](../../scripts/loop.py) — the driver implements it. Notable rules:

- **Unlabeled** (no triage state) → `/triage`.
- **`needs-info`** → pause for the reporter.
- **`ready-for-agent`** with **no type label** → `/triage` (the type was never
  assigned; dispatch stays deterministic, never guessed from prose).
- **`ready-for-agent`** with a type → dispatch that type's skill.

Only the AFK types (`research`, `task`) are fully automated; the HITL types
(`prototype`, `grilling`) invoke their skill and then **pause for the human
turn** — the loop never fakes the human's side of the exchange.

## Mirrors `wayfinder`'s vocabulary

The four types mirror `wayfinder`'s `research` / `prototype` / `grilling` /
`task` vocabulary, keeping this fork's routing aligned with upstream. They are
**not** the bug/enhancement *category* (reserved for triage classification) —
type is the *kind of work* the loop dispatches on.
