# jdstack

Agent skills I write and maintain. They work with Claude Code and Codex.

## Skills

| Skill | What it does |
| --- | --- |
| [creative-council](skills/creative-council/SKILL.md) | Asks one strong model from each available model family the same open question, shows every answer, then adds a short take. Needs [T3 Code](https://t3.codes) for `delegate_task`. |

## Install

Symlink a skill into each agent's skills folder:

```sh
ln -s "$PWD/skills/creative-council" ~/.claude/skills/creative-council
ln -s "$PWD/skills/creative-council" ~/.codex/skills/creative-council
```

Edits in this repo apply on the next session.
