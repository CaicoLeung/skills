# Skills

How skills are structured and validated in this repo. A *skill* is a directory
under `skills/` containing a `SKILL.md`. The contract is defined in
[ADR-0002](../adr/0002-skill-frontmatter-contract.md) and enforced by
`scripts/validate-skills.py`.

## Frontmatter contract

Every `SKILL.md` begins with a YAML frontmatter block carrying exactly these
**required** fields (schema closed):

```yaml
---
name: my-skill              # kebab-case, MUST equal the directory name
description: "One line."    # non-empty, <= 300 chars
version: 0.1.0              # MAJOR.MINOR.PATCH
requires:                   # named inputs (may be empty)
  - tickets
produces:                   # named outputs (may be empty)
  - workflow
---
```

- `name` — `[a-z0-9][a-z0-9-]*`, identical to the skill's directory.
- `version` — the **skill's** version, independent of the frontmatter schema
  version (schema changes are recorded in ADR-0002 / amended by ADR-0009).
- `requires` / `produces` — lowercase kebab tokens naming what the skill
  consumes / emits. Accept indented `- item` blocks or inline flow
  `[a, b]`; an empty list is `[]`.

### Optional: `asks-user-questions` (ADR-0009)

Assert `asks-user-questions: true` on any skill that interviews the user
(grilling, refactor planning, brainstorming, clarifying questions). When
asserted true, the skill body **must reference** the question-numbering
convention (`docs/agents/question-numbering.md`) or `validate-skills.py`
rejects the build. Absent (or `false`) means the skill does not interview and
the convention does not bind it. See
[question-numbering.md](question-numbering.md).

```yaml
---
name: my-interview-skill
description: "Interviews the user for decisions."
version: 0.1.0
requires: []
produces: []
asks-user-questions: true
---

Body must link docs/agents/question-numbering.md somewhere below.
```

## Validate and index

```bash
python3 scripts/validate-skills.py        # exits non-zero on any bad skill
python3 scripts/index-skills.py           # (re)generate skills/INDEX.md
python3 scripts/index-skills.py --check   # fail if committed index is stale
```

CI runs `validate-skills` and `index-skills --check` on every push and pull
request, so a malformed skill — or a stale index — breaks the build.
`skills/INDEX.md` is auto-generated; edit skills, not the index.

## Adding a skill

1. `mkdir skills/<name>`; add `SKILL.md` with the frontmatter above.
2. Run `python3 scripts/validate-skills.py` — it must pass.
3. Run `python3 scripts/index-skills.py` to refresh the index, then commit it.
