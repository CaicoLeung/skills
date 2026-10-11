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
| [zh-en-translation-drill](skills/zh-en-translation-drill/) | 中译英翻译练习陪练：AI 出题、逐句批改、追踪弱项 |

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
- `SKILL.md` frontmatter must have `name` and `description`.
- Keep `SKILL.md` lean; push detail into `reference/`, runtime state into `data/`.
- Never commit secrets or personal data outside what the skill needs.
