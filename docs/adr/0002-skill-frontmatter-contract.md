# ADR-0002: Skill frontmatter contract

- **Status:** Accepted
- **Date:** 2026-07-23
- **Supersedes:** —

## Context

`tickets-to-paseo/SKILL.md` is pure prose: a human-readable workflow description
with no machine-checkable contract. There is no way for a tool — or the next
agent — to answer "what is a skill in this repo, and does this one conform?"
without reading free text. That made the skill unindexable and impossible to
gate: CI cannot reject a malformed skill because "malformed" has no definition.

The gap surfaced in the grilling session as issue #1 gap 2: *"No verifiable
skill contract — `tickets-to-paseo/SKILL.md` is pure prose with no
frontmatter/schema; no validator or index."*

Two shapes were on the table: (a) a heavy JSON-Schema + external YAML library
toolchain, or (b) a small, pinned frontmatter schema plus a zero-dependency
validator that runs anywhere Python 3 does (locally and in CI).

## Decision

**Skills are validated, parseable artifacts.** Every `SKILL.md` begins with a
YAML frontmatter block pinned to five fields:

| Field         | Type              | Rule                                                            |
| ------------- | ----------------- | --------------------------------------------------------------- |
| `name`        | string            | kebab-case `[a-z0-9-]+`, must equal the skill's directory name  |
| `description` | string            | non-empty, ≤ 300 chars                                          |
| `version`     | string            | semantic version `MAJOR.MINOR.PATCH` (`\d+\.\d+\.\d+`)          |
| `requires`    | list of strings   | named inputs the skill consumes (may be empty `[]`)             |
| `produces`    | list of strings   | named outputs the skill emits (may be empty `[]`)               |

All five are **required**. Unknown fields are rejected (the schema is closed).

The grammar is intentionally a restricted YAML subset — top-level
`key: scalar` pairs, indented `- item` block sequences, and inline flow
sequences `[a, b]` (including the empty list `[]`) — so the validator parses it
with no third-party YAML dependency. Nothing else from YAML is accepted.

Enforcement and discoverability are delivered by two scripts in `scripts/`:

1. **`scripts/validate-skills.py`** — exits non-zero on any `SKILL.md` whose
   frontmatter is missing, malformed, or schema-invalid; passes on the current
   repo. Runs in CI (`.github/workflows/validate-skills.yml`) on every push and
   pull request, so a non-conforming skill breaks the build.
2. **`scripts/index-skills.py`** — generates `skills/INDEX.md` from every
   conforming skill, and `--check` fails if the committed index is stale (the
   "is the index current?" equivalent of a formatter's `--check` mode).

## Consequences

- **"What is a skill?" is machine-checkable.** `validate-skills.py` is the
  single source of truth for conformance; the index is its derived view.
- **The contract is closed and versioned.** Adding a field is a schema change
  recorded here (ADR) and a validator change, not a silent prose edit. Skill
  authors `version` their skill independently of this schema version.
- **No runtime lock-in.** The validator is plain Python 3 with no deps, so it
  runs on a developer's macOS and on a CI runner without a `package.json` or
  installed packages — consistent with keeping this repo runtime-light.
- **Unblocks runtime-neutral restructuring (#4).** The core and adapter that
  #4 produces must conform to this contract; the validator now exists to prove
  they do.
- **The gate is honest.** The frontmatter gate is a real CI check; the
  close-out `/code-review` gate remains prompt-contract enforcement until #5
  moves it to branch protection (ADR-0003).
