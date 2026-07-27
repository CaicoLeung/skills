# Question-numbering convention

How a skill asks the user questions so every question is numbered, every option
is numbered, and any past question is referenceable by number. The convention
is recorded as [ADR-0009](../adr/0009-question-numbering-convention.md). The
skill-frontmatter enforcement was retired in
[ADR-0012](../adr/0012-reverse-skill-reframe-loop-driver-tool.md); the
convention now binds the Loop Driver's `grilling`-type dispatch.

## When it binds

The convention binds the Loop Driver's **`grilling`**-type dispatch. When the
driver routes a `grilling` ticket, its dispatch prompt points the external
`/grilling` skill at this doc (`scripts/loop.py`, `dispatch_prompt`), so the
interview runs under `Question N:` / numbered options / `Recommended: N. because
…` form rather than free prose.

The skill-frontmatter enforcement — the `asks-user-questions: true` flag, the
build-time validator, and the `skills/` surface — was retired in
[ADR-0012](../adr/0012-reverse-skill-reframe-loop-driver-tool.md); the
convention survives as a driver concern, recorded in
[ADR-0009](../adr/0009-question-numbering-convention.md), not as a skill
contract.

## Two interview paths

| Path | Surface | Recommendation marker | Counter |
| --- | --- | --- | --- |
| **Prose** (fallback, or any skill interviewing without the tool) | Markdown in chat | `Recommended: N. because …` | Skill-maintained, persistent across the whole interview |
| **Structured tool** (`ask_user_question`) | Pointer / tabbed UI | First option plus the `(Recommended)` label suffix | Per-call (the tool's index resets each invocation) |

The structured tool keeps its own interaction model: it renders selectable
rows, not a numbered list, and a "answer with `2`" affordance is a **prose-path
only** feature. Do not try to number the tool's tabbed UI — it cannot be
numbered from this repo.

Name the tool by its tool name (`ask_user_question`), not by a specific backing
package; the backing package can be swapped without touching this convention.

## The prose format

Every question a prose-path skill asks uses this shape:

```markdown
Question 7: Which persistence layer should the loop read its verdicts from?

1. Postgres (the team default).
2. SQLite, in-process.
3. Plain JSON files in the repo.

Recommended: 1. because the loop already owns a Postgres connection for the
PR-status reads, so reusing it avoids a second dependency.
```

- **`Question N: <text>`** — the heading. `N` is the question's number.
- **`1. … 2. …`** — every option is numbered, starting at `1`, so the user can
  answer with a bare number (`2`).
- **`Recommended: N. because …`** — exactly one option is recommended, with a
  reason. The user can accept the recommendation without re-reading every
  option.

### The persistent counter

`N` increments across the **whole interview**, maintained by the skill's own
reasoning — **not** by the structured tool (whose per-call question index does
not survive across invocations). This is what makes "forget my response for
question 7 — ask me again" resolve. The skill carries a running `Q1..Qn` tally
in its own context across turns.

### Answering in plain chat

A bare number (`2`) in plain chat means "option 2 of the most recent question".
The skill resolves the number against its running counter, then records the
choice against the numbered question so the final decision log is unambiguous.

Rejecting the recommendation is recorded the same way: if the user picks an
option other than the recommended one (or writes an explicit rejection), the
skill records that choice against the question's number. The decision log then
shows which question got which answer regardless of whether the recommendation
was accepted — e.g. `Question 7 → option 2 (recommended was 1)` stays
unambiguous, so a later "forget my response for question 7" still resolves.

## The structured-tool path

When a skill delegates to the harness's `ask_user_question` tool, the tool's
own UI and recommendation suffix govern that interaction:

- put the recommended option **first** and append `(Recommended)` to its label;
- give each question 2–4 distinct, mutually exclusive options;
- **do not author** `Other`, `Type something.`, or `Chat about this` as option
  labels — they are reserved by the tool and rejected at runtime; the tool
  appends `Type something.` automatically.

The convention's intent (a clear recommended option, unambiguous choices) stays
self-consistent across both paths; only the marker differs — `(Recommended)` on
the tool path, `Recommended: N. because …` on the prose path.

## Look up before you ask

Numbering is reserved for **genuine decisions**. If a fact is answerable from
the environment — the repo's conventions, an existing ADR, the ticket's labels,
the current branch, a file's contents — **look it up**; do not burn a question
number on it. A question that the skill could have answered itself pollutes the
counter and slows the interview.

## Worked example

A grilling ticket that needs one decision:

```markdown
Question 1: Should the verdict derive blocking from a dedicated field, or from
a HIGH severity tag?

1. Dedicated `blocking` boolean on each finding.
2. Derive it from `severity == HIGH`.

Recommended: 1. because a finding can be HIGH but non-blocking (a style smell
in a critical file), and a dedicated field keeps the derivation rule in one
place.

(Looked up, not asked: the repo already names findings with a `severity` field
— ADR-0007 — so no question was spent on whether severities exist.)
```

The user can answer `1`, or `Recommended`, or write free prose; whichever they
pick, the skill records it against "Question 1".
