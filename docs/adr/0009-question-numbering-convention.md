# ADR-0009: Numbered questions convention for interviewing skills

- **Status:** Accepted
- **Date:** 2026-07-25
- **Supersedes:** —
- **Amends:** [ADR-0002](./0002-skill-frontmatter-contract.md) (adds one optional frontmatter field)
- **Related:** [ADR-0008](./0008-script-driven-loop-driver-and-type-aware-routing.md) (the dispatch hook lives in the loop driver)

## Context

When a skill interviews the user — `grilling`, refactor planning, brainstorming,
clarifying questions — it asks questions in free prose with no ordering and no
numbered options. The user cannot answer with a bare number, and cannot refer
back to an earlier question by number ("forget my response for question 7 —
ask me again"). The interaction is slower and harder to track than it needs to
be, especially in long decision interviews. (Origin: issue #45 feature request;
research: `docs/research/issue-45-numbered-questions.md`.)

The repo already has the machinery to encode and enforce a convention: a closed
frontmatter contract ([ADR-0002](./0002-skill-frontmatter-contract.md)) with a
zero-dependency validator that gates CI, and a scripted loop driver
([ADR-0008](./0008-script-driven-loop-driver-and-type-aware-routing.md)) that
dispatches `grilling` tickets to the external `/grilling` skill. The question
was where to put the convention so it is (a) durable, (b) discoverable, and
(c) enforced for skills authored in this repo without trying to re-author
interview skills this repo does not own.

## Decision

**Establish a repo-wide numbered-questions convention, encoded as this ADR plus
a convention doc, with one machine-enforced frontmatter hook and one
prompt-level dispatch reference.** Four parts.

### 1. Convention doc (source of truth)

A new agent-facing doc — `docs/agents/question-numbering.md` — defines:

- the prose format: `Question N: <text>` heading, `1. … 2. …` numbered
  options, `Recommended: N. because …`;
- the persistent-counter rule: `N` increments across the whole interview,
  maintained by the skill's own reasoning (the structured tool's per-call index
  does not survive across invocations);
- the tool-vs-prose split: the structured `ask_user_question` tool keeps its
  pointer UI and `(Recommended)` label suffix; the prose format applies on the
  prose-fallback path and in any skill that interviews without the tool;
- the reserved-label constraint carried over from the tool (`Other` /
  `Type something.` / `Chat about this` must not be authored as option labels);
- a "look up before you ask" rule, so numbering is reserved for genuine
  decisions and not polluted with look-up questions;
- a worked example a new contributor can copy.

### 2. Frontmatter contract extension (amends ADR-0002)

Add one **optional** boolean field to the skill frontmatter contract:
`asks-user-questions`, asserted `true` by any skill that asks the user
questions. This change extends the restricted-YAML parser to coerce **bare**
YAML core-schema booleans (`true` / `false` → Python `bool`) — a quoted value
(``"true"``) stays a string and is then rejected by the validator as
non-boolean. The schema's closed set grows from five required fields to five
required plus one optional. Absence means the skill does not interview and
the convention does not bind it.

### 3. Validator rule (the single new test seam)

The existing frontmatter validator (`scripts/validate-skills.py`, implementing
ADR-0002) gains one rule: **if a skill's frontmatter asserts
`asks-user-questions: true`, its body must reference the convention doc**
(`docs/agents/question-numbering.md`). Accept/reject is the external behavior;
prose quality (wording, option clarity, recommendation reasoning) is **not**
linted — those are review concerns. The rule is exercised by a new
zero-dependency, table-driven test (`scripts/test_skills.py`) that mirrors the
existing `test_routing.py` / `test_reviewer.py` pattern: a list of
`(frontmatter, body, expected_pass)` cases run directly via `python3`,
exiting non-zero on any failure.

### 4. Dispatch hook (prompt edit in the driver)

The loop driver's `dispatch_prompt` (`scripts/loop.py`) is updated so a
`grilling` dispatch points the external `/grilling` skill at the convention:
its prompt tells the skill to number every question, number its options, mark
the recommendation, and keep the counter across the interview. This is a prompt
edit, not a new dispatch path or a code-change to the routing logic; the
external interview skill inherits the convention when invoked through the loop.
The driver skills themselves do not interview, so they are not flagged as
interviewing — the flag is forward-looking for any future interview skill
authored here.

### Recommendation-format resolution

- **Prose path:** `Recommended: N. because …`.
- **Structured-tool path:** keep the tool's first-option-plus-`(Recommended)`
  suffix rule.

The convention doc states both and says which surface wins.

### Counter-scope resolution

Persistent across the whole interview, skill-maintained. This is what makes
"question 7" references possible; a per-turn reset would defeat the originating
request.

### Scope resolution

Fork-local to this repo. The structured tool itself is **not** modified: its
TUI renders selectable rows, not a numbered list, and its `promptGuidelines`
cannot be silently contradicted by the UI. Interview skills that live outside
this repo (the global `grilling`, `ce-brainstorm`, `ce-plan`, `qa`,
`request-refactor-plan`) are guidance targets, not merge targets.

## Rejected alternatives

- **Tweak the structured tool's `promptGuidelines`.** Rejected: the tool's TUI
  interaction model cannot be numbered from this repo, so a guideline there
  would be silently contradicted by the pointer UI the user actually sees.
- **Invert the "prefer blocking tool" stance** and force every interview onto
  the prose path so numbering always applies. Rejected: the structured tool's
  pointer UI is a genuine usability win for bounded-choice questions; the
  convention keeps it and only governs the prose path and the skill's own
  running counter.
- **Push the convention upstream to the origin repo.** Out of scope here. This
  fork owns only its driver/governance layer; an upstream PR is a separate
  decision (see Divergence note).

## Consequences

- **Numbered, referenceable questions.** Any question a prose-path skill asks
  can be cited by number across the whole interview; the user can answer with a
  bare number.
- **One closed schema, now with an optional flag.** ADR-0002's "closed and
  versioned" property holds: adding a field is still a recorded schema change
  (this ADR) plus a validator change, not a silent prose edit. Existing skills
  are unaffected (they do not assert the flag).
- **CI is the gate.** The existing `validate-skills` status check continues to
  be the gate; the new rule simply makes it reject a non-conforming interview
  skill before merge. No new workflow job — one more `python3 scripts/test_*`
  step is added to the existing job.
- **Grilling runs under the convention when dispatched through the loop.** The
  external `/grilling` skill is handed the convention in its dispatch prompt;
  it is not edited (it is not owned by this repo).
- **Divergence from upstream.** This convention is fork-local. Upstreaming is
  tracked here as a divergence note, not pursued in this change.

## Version implications

- New: `docs/agents/question-numbering.md`, `docs/adr/0009-…md`,
  `scripts/test_skills.py`.
- Amended: `scripts/skills.py` (one optional boolean field + the reference
  rule + bare-boolean coercion), `docs/agents/skills.md` (documents the field),
  [ADR-0002](./0002-skill-frontmatter-contract.md) (amended-by pointer),
  `scripts/loop.py` (`dispatch_prompt` grilling reference),
  `.github/workflows/validate-skills.yml` (one more test step).
- No change to the structured `ask_user_question` tool, its TUI, its return
  shape, or its `promptGuidelines`.
