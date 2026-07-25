# Issue #45 — Enforce numbered questions and responses

Research into [`CaicoLeung/skills`#45](https://github.com/CaicoLeung/skills/issues/45)
(mirror of upstream [`mattpocock/skills`#45](https://github.com/mattpocock/skills/issues/45)).

> **Note on location:** this repo has no existing research-notes convention
> (no `docs/solutions/`, no `docs/research/`). `docs/research/` is the new
> sensible home for issue-scoped investigation; if a convention emerges later,
> move this file there.

---

## 1. Issue summary

The requester (Matt Pocock, upstream author) wants every question an agent
asks the user to be **numbered**, and every option within a question to be
**numbered**, so that:

- the user can reply with a bare number (`2`), and
- the user can refer back to an earlier question by number
  ("forget my response for question 7 — ask me again").

Desired shape ([`CaicoLeung/skills`#45](https://github.com/CaicoLeung/skills/issues/45)):

```
Question 10: XXXX

1. YYYY
2. ZZZ
3. AAAA

Recommended: 2. because ....
```

The goal is a **convention** the repo's skills can enforce, not a one-off.

---

## 2. Current state — does anything number questions today?

**Short answer: no.** No skill in this repo or in the global skill set
numbers its questions or options. Interview skills either delegate to a
structured tool (which uses a pointer UI, not numbers) or ask in free prose.

| Skill | Asks user questions? | Numbered? | Source |
| --- | --- | --- | --- |
| `grilling` (global) | Yes — one-at-a-time interview | No — "provide your recommended answer" in prose | `/Users/caico/.pi/agent/skills/grilling/SKILL.md:6,8` |
| `ce-brainstorm` (global) | Yes — delegates to blocking tool | No — "Fall back to **numbered options in chat** only when no blocking tool exists" | `/Users/caico/.pi/agent/skills/ce-brainstorm/SKILL.md:33` |
| `ce-plan` (global) | Yes — delegates to blocking tool | No — same fallback rule | `/Users/caico/.pi/agent/skills/ce-plan/SKILL.md:19,98,835` |
| `request-refactor-plan` (global) | Yes — prose interview | No — "Ask the user for a long, detailed description… Interview the user" | `/Users/caico/.pi/agent/skills/request-refactor-plan/SKILL.md` (steps 1,4) |
| `qa` (global) | Yes — ≤2-3 clarifying questions | No — "Ask at most 2-3 short clarifying questions" | `/Users/caico/.pi/agent/skills/qa/SKILL.md` §1 |
| `loop-engineering` (this repo) | No — routes ticket types to leaf skills | n/a | `skills/loop-engineering/SKILL.md:86` (routes `grilling` → `/grilling` + `/domain-modeling`) |
| `ticket-workflow-core` (this repo) | Only fallback ("else ask user") | No | `skills/ticket-workflow-core/SKILL.md:246` |
| `tickets-to-paseo` (this repo) | No — adapter, delegates model Qs to core | n/a | `skills/tickets-to-paseo/SKILL.md:242` |

Two important corollaries:

1. **This repo's three skills are loop-drivers**, not interviewers. They route
   a `grilling` ticket to the external `/grilling` skill
   (`skills/loop-engineering/SKILL.md:86,90`) and pause for the human. So a
   numbering convention is enforced at the **leaf doing-skills** (and the
   shared question tool), not in these driver skills.

2. The upstream interview skills (`mattpocock/skills`) are equally unnumbered:
   - `skills/productivity/grilling/SKILL.md`: *"Ask the questions one at a
     time… For each question, provide your recommended answer."*
   - `skills/in-progress/to-questionnaire/SKILL.md` produces a Markdown doc
     with `###` question headings + `>` answer stubs — unnumbered, and it is a
     hand-off document rather than a live interview.

So the issue is reacting against a real, repo-wide gap: **nothing numbers
questions today.**

---

## 3. How user selections flow today

The structured-question tool in this harness is **`ask_user_question`**. Two
facts from primary source that decide whether "answer with the number 2" can
even work:

### 3a. The installed backing extension is `rpiv-ask-user-question`, not `pi-ask-user`

`AGENTS.md` names `pi-ask-user` (by edlsh) as the recommended backing
extension, but **it is not installed**. A filesystem search under
`/Users/caico/.pi/agent/` finds only one ask-user package:

```
/Users/caico/.pi/agent/npm/node_modules/@juicesharp/rpiv-ask-user-question
```

So the `ask_user_question` tool actually in effect is
[`@juicesharp/rpiv-ask-user-question`](https://github.com/juicesharp/rpiv-mono/tree/main/packages/rpiv-ask-user-question)
(README confirms it "adds the `ask_user_question` tool to Pi Agent"). All
claims below are sourced from that package.

### 3b. The tool uses a pointer/tabbed TUI, not a type-a-number UI

From `ask-user-question.ts` (`registerAskUserQuestionTool`), the tool renders
a tabbed overlay the user navigates by **keyboard** (arrows / `Space` to
toggle / `Enter`), not by typing an index. The README's feature list confirms
this: *"Multi-question dialogs — tabbed," "Multi-select — checkboxes with
Space to toggle," "Submit tab — review every answer before submitting."*

The return shape the **agent** receives is the selected **label text**, keyed
by an internal `questionIndex`, never a user-typed number:

```ts
// tool/types.ts:113-116
questionIndex: number;
kind: "option" | "custom" | "chat" | "multi";
answer: string | null;          // the option LABEL the user picked
```

(`tool/response-envelope.ts:22` re-joins answers by `questionIndex`.)

**Consequence:** when a skill uses `ask_user_question`, the user never types
`2` — they move a cursor to a row and press Enter. The "I can just answer `2`"
UX the issue wants **does not apply on the tool path**; it only applies on the
prose-fallback path.

### 3c. The recommendation mechanism conflicts with the issue's format

The tool hard-codes recommendation as a **suffix on the first option's
label**, not a "Recommended: N. because…" line
(`ask-user-question.ts:54,72`):

> *"If you recommend a specific option, make it the first option in the list
> and add '(Recommended)' at the end of the label."*

The reserved-label validator (`ask-user-question.ts:70`; README "Schema")
**rejects** authoring `"Other"`, `"Type something."`, `"Chat about this"`, or
`"Next →"` as option labels — relevant if a skill tried to mimic the issue's
shape inside the tool.

### 3d. Cross-call "Question 7" is not a tool feature

`questionIndex` (`types.ts:113`) is per-invocation and 0-based within one
`ask_user_question` call. There is **no persistent cross-call counter**. So
"forget my response for question 7" can only work if the **skill itself**
maintains a running `Q1..Qn` tally in its own reasoning and renders it in the
question text — the tool will not do it.

---

## 4. Where numbering could be enforced

Four candidate surfaces, with trade-offs:

### Surface A — Per-skill prompt instructions (leaf doing-skills)

Edit `grilling/SKILL.md`, `ce-brainstorm/SKILL.md`, `ce-plan/SKILL.md`,
`qa/SKILL.md`, `request-refactor-plan/SKILL.md` to mandate:
`Question N: …` / `1. … 2. …` / `Recommended: N. because…`, and a running
counter for cross-turn references.

- **Pro:** only place that affects the **prose fallback** path where "type `2`"
  actually works; matches how these skills already phrase questions.
- **Con:** no effect when the skill delegates to `ask_user_question` (the
  pointer UI dominates and re-labels options). Many skills to edit; drift risk.

### Surface B — The `ask_user_question` tool's `promptGuidelines`

`rpiv-ask-user-question` loads `promptSnippet` / `promptGuidelines` from config
and otherwise uses `DEFAULT_PROMPT_GUIDELINES` (`ask-user-question.ts:51-54,83`).
A config override could inject numbering guidance.

- **Pro:** one place, affects every skill that calls the tool.
- **Con:** **does not change the UI.** The TUI still renders selectable rows,
  returns label text, and uses "(Recommended)". Numbering the *prompt* the
  model writes into `question`/`label` strings won't make the user able to
  type `2` — the interaction model is pointer-based. Low real leverage here.

### Surface C — A repo convention doc + ADR

A `docs/agents/numbered-questions.md` backed by an ADR (this repo is
ADR-governed — see `docs/adr/`, and the frontmatter contract ADR-0002).
Codifies: (1) prose interviews number questions `Q1..Qn` with a running
counter; (2) options `1..N`; (3) `Recommended: N. because…` in prose; (4)
acknowledges the structured tool's pointer UI and `(Recommended)` suffix are a
**different surface** where "answer by number" does not apply.

- **Pro:** matches this repo's governance style (ADR-0002 skill-frontmatter,
  ADR-0008 script-driven-loop-driver); applies uniformly to any skill authored
  here; survives tool swaps.
- **Con:** still needs Surface A edits to actually land in the leaf skills.

### Surface D — Frontmatter field (e.g. `numbering: strict`)

Extend the skill frontmatter contract (ADR-0002) so a skill can *declare* the
numbering mode, enforced by `scripts/validate-skills.py`.

- **Pro:** machine-checkable, consistent with the repo's validator-driven
  approach (`CLAUDE.md`: "Validate with `python3 scripts/validate-skills.py`").
- **Con:** heavyweight for a formatting convention; the validator can check the
  field exists but not the prose content.

---

## 5. Recommendation

**Adopt Surface C (convention doc + ADR) as the rule, and land Surface A edits
in the prose-interview leaf skills as the implementation.** Grounding:

- This repo's own skills (`loop-engineering`, `ticket-workflow-core`,
  `tickets-to-paseo`) are loop-**drivers** that route a `grilling` ticket to
  external `/grilling` and pause (`skills/loop-engineering/SKILL.md:86,90`).
  The numbering concern lives in the leaf doing-skills and the prose fallback,
  not the drivers — so a per-skill prompt tweak plus a governing ADR is the
  right weight, not a driver-skill change.
- The repo encodes decisions as ADRs (`docs/adr/0002` frontmatter contract,
  `0008` script-driven-loop-driver) and validates skills by script
  (`CLAUDE.md`). A convention that isn't an ADR here is invisible.
- "Type `2` to answer" only works on the **prose fallback** path
  (§3b). The convention must therefore (a) mandate `Q1..Qn` + `1..N` +
  `Recommended: N. because…` **in prose**, and (b) explicitly state that when
  `ask_user_question` is used, its pointer UI and `(Recommended)` suffix
  (`ask-user-question.ts:54,72`) take over and "answer by number" is moot.
- Surface B (tool `promptGuidelines`) is **not** worth changing: it cannot
  alter the TUI interaction model, so it would create a rule the UI silently
  contradicts.

Minimal landing:
1. New ADR `docs/adr/0009-numbered-questions.md` stating the rule + the
   tool-vs-prose split.
2. New `docs/agents/numbered-questions.md` with the format template and the
   running-counter requirement (so "question 7" references are possible).
3. Edit the leaf `grilling` SKILL.md (the skill this repo's `grilling` ticket
   type dispatches to) to mandate the format; leave driver skills untouched.

---

## 6. Open questions for the maintainer

1. **Counter scope.** Does `Q1..Qn` reset each agent turn, or persist across
   the whole interview? "Forget my response for question 7"
   ([`#45`](https://github.com/CaicoLeung/skills/issues/45)) implies
   **persistent** — which the skill must track itself; `ask_user_question`'s
   `questionIndex` is per-call (`types.ts:113`) and will not help.
2. **Recommendation format clash.** The issue wants `Recommended: 2. because…`;
   the tool mandates `(Recommended)` as a label suffix on option 1
   (`ask-user-question.ts:54,72`). The convention must say which wins on which
   surface, or they will collide whenever the tool is available.
3. **Tool vs prose boundary.** `ce-brainstorm`/`ce-plan` *prefer* the blocking
   tool and only fall back to numbered prose when it is absent
   (`ce-brainstorm/SKILL.md:33`; `ce-plan/SKILL.md:19`). If the repo wants
   "type a number" to be the *primary* UX, that preference may need to invert
   for interview-heavy skills — a real design change, not just formatting.
4. **Reserved labels.** A skill cannot put `"Other"` in an option
   (`ask-user-question.ts:70`); the convention's option list must avoid it on
   the tool path.
5. **Scope of enforcement.** Does this bind only skills authored in *this*
   repo, or is it intended to push upstream to `mattpocock/skills` (where the
   issue originated)? Affects whether the ADR is local or a fork-divergence
   note.
