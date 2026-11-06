---
name: creative-council
description: Ask up to 6 strong models, one per model family, the same open question and show each answer, followed by a short take. It probes each model first, and free models fill the seats unavailable flagships leave empty. Use when the user says "creative council" or "ask the council" for ideas rather than a review, or is out of ideas on a concept, design, visualization, name or approach and wants several models' suggestions. Never use it inside a delegated task or as a council member.
---

# Creative council

Send the user's question to one strong model per model family, in parallel, and show every answer. Members suggest ideas. They never write code, edit files or start agents.

If your task came from `delegate_task` or another agent, do not run this skill and do not call `orchestrator_capabilities` or `delegate_task`. Answer the question yourself. Only the agent talking directly to the user convenes a council, and a council has one level: that agent and its members.

## Pick members

The council has 6 seats unless the user asks for another size. The seat count is a hard limit: never have more members than seats, counting replacements. Flagships that pass their probe take seats first, and free models that pass fill the rest.

1. Call `orchestrator_capabilities`. Its model list is short, so search once per family you see or expect (Claude, GPT, Gemini, Grok, Muse, Composer), and once for "free", before declaring a family unavailable or choosing a model.
2. Flagship candidates: one per model family, including families that appear later. Treat the same model served by several providers as one model.
3. For each family, pick its strongest model: the flagship tier, newest version within that tier. Skip light tiers (Haiku, Flash, Luna, Mini, Fast, free variants). Skip a family entirely when only light tiers are available.
4. When several providers offer that model, use the first-party provider (Grok through `grok`, not `cursor`). Use a proxy such as `opencode` when it is the only provider offering the strongest model.
5. Free candidates: models whose label or id marks them free (`Free`, `-free`), plus models on a no-subscription tier such as Antigravity. Skip subscription routes such as `opencode-go/`. Light tiers are fine here. Rank each family's free models: Ultra or Super before Flash, Lightning or Lite, then the newest version. Only one model per family sits on the council at a time, and families that hold a flagship seat get no free one.
6. Set reasoning with the exact option id and values the model advertises (`effort`, `reasoningEffort`, `variant` or `reasoning_effort`): `xhigh` if listed, otherwise `high`, otherwise the highest listed value below `max`. Never use `max`, `ultra`, `ultrathink` or `ultracode`. If the model advertises no reasoning option, send no options and label its effort "default".
7. Skip disabled providers. If the user names members, use exactly those and fill nothing. If a named member is unavailable, report it and do not substitute.

## Availability

Probe candidates before sending the question, so the brief only goes to models that answer.

1. Probe in rounds, and in each round probe only as many models as there are empty seats. Take flagship candidates first, in the order Claude, GPT, Gemini, Grok, Muse, Composer, then other families. When flagships run out, take the top free model of each family without a seat. Stop as soon as the seats are full. Each probe is a `delegate_task` with the target and options the real run will use, `runtimeMode: "full-access"`, `mode: "wait"`, `timeoutMs: 120000`, and the task "Reply with the single word OK. Do not read files, run tools or edit anything."
2. A probe passes when it completes with a reply. It fails on a start error, a failed status (billing, quota or plan limit, insufficient funds, "model unavailable") or a timeout. Cancel a timed-out probe with `task_cancel`. Do not retry a failed model or move it to another paid provider.
3. Seat each model that passed, one per family, with flagships before free models and non-light tiers before light ones.
4. If seats are still empty, run another round, until the seats are full or the candidates run out. A council with fewer members than seats is fine.
5. A seated member can still fail during the real run. If fewer members than seats are then running or finished, give the seat to a passing free model without a seat, or probe the next untested free model. A failed member's seat is reused, never added to.

## Brief

In one turn, start every seated member with `delegate_task`, `mode: "async"`, `runtimeMode: "full-access"`, using the exact `providerInstanceId` and model id from `orchestrator_capabilities`. Include the Claude member, so each answers without seeing this conversation.

Each brief contains:
- The user's question, verbatim, with any request to ask the council removed. A member that reads "ask the creative council" may try to convene one.
- The context a member needs: what the concept or data is, its shape, a small sample, constraints, audience. Point to file paths rather than pasting large files.
- This instruction: "You are one member answering alone. Do not start subagents or delegate. Do not call delegate_task or orchestrator tools. Do not load the creative-council skill. Do not edit files. Do not write or run code. Suggest ideas only: 2 to 4 distinct ideas, each with one line on why it fits. Under 300 words. No preamble."

Every member gets the same brief, fills included. For a first question, do not include your own ideas or any member's answer.

## Wait

Follow each delegate's `next` instruction. Do not poll with `task_status`, `sleep` or loops. Give each member 10 minutes from its start. Cancel any member still running after that with `task_cancel` and mark it timed out. Reply with the answers that came back.

A member that starts agents has failed. If a task result shows `waiting_for_children`, or a reply has no ideas or talks about waiting for other members, call `task_cancel` on that member to stop its agents, discard its answer and treat its seat as empty.

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

End with one line naming any member that was skipped, failed or timed out, why, and which free model took its seat. Write no code in the take either.

## Follow-ups

When the user asks a follow-up, start new delegates for the members that answered. If they number fewer than the seat count, probe free models from families without a seat, skipping models that failed earlier, and fill the empty seats. If nobody answered, pick members again from scratch. Each brief holds the original question, a summary of the previous round of at most 3 lines per member, and the follow-up. Never send to an earlier delegate's thread.
