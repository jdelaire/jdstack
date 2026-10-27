# jdstack

Agent skills I write and maintain. They work with Claude Code and Codex.

## Skills

| Skill | What it does |
| --- | --- |
| [creative-council](skills/creative-council/SKILL.md) | Asks one strong model from each available model family the same open question, shows every answer, then adds a short take. Needs [T3 Code](https://t3.codes) for `delegate_task`. |
| [roadmap-writer](skills/roadmap-writer/SKILL.md) | Writes or reformats a roadmap as milestones holding typed deliverables (feature, debt, revenue, fix) with their implementation requirements. |

## Install

Symlink a skill into each agent's skills folder, for example:

```sh
ln -s "$PWD/skills/roadmap-writer" ~/.claude/skills/roadmap-writer
ln -s "$PWD/skills/roadmap-writer" ~/.codex/skills/roadmap-writer
```

Edits in this repo apply on the next session.
