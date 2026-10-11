# Agent Skills

Personal collection of agent skills (Claude Code / pi / any agent that loads SKILL.md-format skills).

## Layout

```
skills/
  <skill-name>/
    SKILL.md          # required: frontmatter (name, description) + instructions
    reference/        # optional: detailed docs loaded on demand
    data/             # optional: data files used by the skill
```

## Skills

| Skill | Purpose |
|---|---|
| [zh-en-translation-drill](skills/zh-en-translation-drill/) | Chinese-to-English translation drill coach: AI generates sentences, corrects each translation, tracks weak spots |

## Install

Symlink a skill into an agent's skills directory:

```bash
ln -s $(pwd)/skills/<skill-name> ~/.agents/skills/<skill-name>
```

or copy:

```bash
cp -R skills/<skill-name> ~/.agents/skills/<skill-name>
```

## Conventions

- One skill per directory under `skills/`, directory name = skill name.
- **All skill content in English** — SKILL.md, reference docs, and data-file structure. Non-English text is allowed only when it is functional content (e.g. quoted source sentences, trigger phrases that must match user utterances).
- `SKILL.md` frontmatter must have `name` and `description`.
- Keep `SKILL.md` lean; push detail into `reference/`, runtime state into `data/`.
- Never commit secrets or personal data outside what the skill needs.
