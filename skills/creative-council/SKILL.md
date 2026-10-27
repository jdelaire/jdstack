---
name: creative-council
description: Ask one strong model from every available model family the same open question and show each answer, followed by a short take. Use when the user says "creative council" or "ask the council" for ideas rather than a review, or is out of ideas on a concept, design, visualization, name or approach and wants several models' suggestions.
---

# Creative council

Send the user's question to one strong model per model family, in parallel, and show every answer. Members suggest ideas. They never write code or edit files.

## Pick members

1. Call `orchestrator_capabilities`. Its model list is short, so search once per family you see or expect (Claude, GPT, Gemini, Grok, Muse, Composer) before declaring a family unavailable or choosing its model.
2. Take one member per model family, including families that appear later. Treat the same model served by several providers as one model.
3. For each family, pick its strongest model: the flagship tier, newest version within that tier. Skip light tiers (Haiku, Flash, Luna, Mini, Fast, free variants). Skip a family entirely when only light tiers are available.
4. When several providers offer that model, use the first-party provider (Grok through `grok`, not `cursor`). Use a proxy such as `opencode` when it is the only provider offering the strongest model.
5. Set reasoning with the exact option id and values the model advertises (`effort`, `reasoningEffort`, `variant` or `reasoning_effort`): `xhigh` if listed, otherwise `high`, otherwise the highest listed value below `max`. Never use `max`, `ultra`, `ultrathink` or `ultracode`. If the model advertises no reasoning option, send no options and label its effort "default".
6. Skip disabled providers. If the user names members, use exactly those. If a named member is unavailable, report it and do not substitute.

## Brief

Start every member with `delegate_task` in the same turn, `mode: "async"`, `runtimeMode: "full-access"`, using the exact `providerInstanceId` and model id from `orchestrator_capabilities`. Include the Claude member, so each answers without seeing this conversation.

Each brief contains:
- The user's question, verbatim.
- The context a member needs: what the concept or data is, its shape, a small sample, constraints, audience. Point to file paths rather than pasting large files.
- This instruction: "Do not edit files. Do not write or run code. Suggest ideas only: 2 to 4 distinct ideas, each with one line on why it fits. Under 300 words. No preamble."

For a first question, do not include your own ideas or any member's answer.

## Wait

Follow each delegate's `next` instruction. Do not poll with `task_status`, `sleep` or loops. Give the council 10 minutes. Cancel any member still running after that with `task_cancel` and mark it timed out. Reply with the answers that came back.

## Reply

One section per member:

```markdown
### <Model label> (<reasoning effort>)

<the member's answer, unedited except for trimming any preamble or sign-off>
```

If an answer contains code, replace the code with "[code removed]" and keep the rest. Do not re-ask that member.

After the member sections, add:

```markdown
### Take

<2 to 4 lines: where members agree, the most unusual idea worth trying, and your pick with the reason>
```

End with one line naming any member that was skipped, failed or timed out, and why. Write no code in the take either.

## Follow-ups

When the user asks a follow-up, start new delegates for the same members. Each brief holds the original question, a summary of the previous round of at most 3 lines per member, and the follow-up. Never send to an earlier delegate's thread.
