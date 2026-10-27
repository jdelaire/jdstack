---
name: roadmap-writer
description: Use when asked to create, update, format, reformat, normalize, or restructure a product, project, or release roadmap, including docs/roadmap.md, or when roadmap milestones are verbose or lack clear implementation items.
---

# Roadmap writer

Write compact Markdown roadmaps as milestones containing typed deliverables and the requirements needed to implement them.

## Workflow

1. Read the requested roadmap and relevant project instructions. Find an existing roadmap with `rg --files` when no path is given. For a new roadmap, use `docs/roadmap.md` unless the project establishes another location. Return a chat draft when requested.
2. Identify milestones, their deliverables, and implementation-critical facts. Preserve version assignments across all content types.
3. Write the shape below. Compare it with the source and check links before finishing. Report unresolved decisions and consumer compatibility limits briefly.

## Required shape

- One H1: `# <Project> roadmap`.
- One H2 per milestone in delivery order: `## <version> <title>`. Use the milestone's name when no version exists. Record a short `Status:` line when known; add a `Target:` line only for a recorded target, preserving approximate dates and deadline meaning.
- One H3 per deliverable: `### <item title>`. Follow it with `Type: <type>` and concise requirement bullets. Common types are `feature`, `debt`, `revenue`, and `fix`; retain other explicit types when appropriate.
- Bullets state behavior, scope exclusions, implementation constraints, dependencies, blocking decisions, and required checks. Keep these beside the affected item. Separate recorded verification results from checks still required, and product outcomes from release delivery status.
- Keep supplied shared release rules once in a short `## Release rules` section. Include it only when rules exist; project cadence, quotas, languages, and policies are never global defaults.
- Preserve unassigned items under `## Ideas without a version`, using the same typed item blocks. Keep compact historical records under `## Previous releases`. Include these sections only when they have content.

Use direct bullets, without narrative introductions, duplicated milestone overviews, empty fields, or mandatory item counts. Keep implementation-critical requirements inline; link lengthy background. Add references and details only where they change implementation or preserve source facts. Match heading-derived anchors when updating links.

## Preserve meaning

For formatting requests, change presentation only. Preserve requirements, caveats, open questions, status, assignments, and link destinations. Adjust relative links if a file moves. Missing status stays unknown; a version assignment is not a commitment. Never invent versions, dates, priorities, metrics, policies, verification, or completion claims.

For creation requests, label proposed sequencing and keep unassigned ideas unassigned. Preserve deadline exceptions, unresolved decisions, and release follow-ups. A released milestone can still have pending checks or outcome measurements.

Follow explicit user format choices over this default. If a consumer still requires a legacy structure, disclose the incompatibility rather than silently changing its parser or restoring duplicated summaries. Writing a roadmap does not authorize implementing its milestones.

## Example

```markdown
# Beacon roadmap

## 0.6.0 Saved places
Status: proposed

### Save and browse places
Type: feature

- Save a place from its detail page and browse a private saved list.
- Reuse existing sync storage. No public sharing or accounts.
- Decide the saved-place limit before implementation.

### Saved-list loading
Type: debt

- Measure loading for 2,000 places on the oldest supported phone.
- Record the result before choosing an optimization.

### Store screenshots
Type: revenue

- Show saving a place in the store screenshots.
- Compare page views and first-time downloads before and after.
```
