# jdstack

## Flow diagrams

A skill with a file in `docs/flows/<skill>.html` has a flow diagram, shown in the README as `docs/flows/<skill>-light.png` and `docs/flows/<skill>-dark.png`. Keep it in step with the skill.

When you change anything under `skills/<skill>/` for such a skill:

1. Edit `docs/flows/<skill>.html` so its phases, gates, loops, timers and thread titles match the new skill text. If the change has no visible effect on the flow, say so in the commit message.
2. Run `scripts/render-flows.sh <skill>`. It renders both PNGs and writes `docs/flows/<skill>.stamp`, which records the Git blob of every input and output.
3. Look at both PNGs before committing.
4. Commit the skill change, the HTML, both PNGs and the stamp together.

`scripts/check-flows.sh --staged` runs as the pre-commit hook and rejects a commit whose staged skill files, HTML, PNGs or stamp disagree. CI runs `scripts/check-flows.sh HEAD` on every push and pull request. The check proves the diagram was rendered after the last change; it cannot prove the HTML content was revised, so step 1 is on you.

Rendering needs Node and Playwright's bundled Chromium. On a fresh machine run `npx -y playwright@1.64.1 install chromium` once.

To add a diagram for another skill, create `docs/flows/<skill>.html` using the existing one as a template, render it, and embed both PNGs in the README with a `<picture>` element.
