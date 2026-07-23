## Agent skills

### Skills

Every `SKILL.md` carries validated YAML frontmatter (`name`/`description`/`version`/`requires`/`produces`). See `docs/agents/skills.md`; schema in `docs/adr/0002-skill-frontmatter-contract.md`. Validate with `python3 scripts/validate-skills.py`; refresh `skills/INDEX.md` with `python3 scripts/index-skills.py`.

### Issue tracker

Issues live as GitHub issues in CaicoLeung/skills, driven by the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the five default labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
