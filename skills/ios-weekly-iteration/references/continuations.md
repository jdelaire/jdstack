# Continuations and durable progress

Use this contract for a user-started cycle. A skill supplies instructions; persistent host scheduling supplies wakeups. Register and verify a wakeup before promising work will resume without the user.

## Project state

Resolve the repository root and the absolute path returned by `git rev-parse --git-path ios-weekly-iteration/active.json`. Resolve `ios-weekly-iteration/lock` through the same Git command. This keeps checkpoints and locks outside tracked app source. Keep deliverables in the project's established release paths.

On explicit user start, inspect any existing state. Resume a matching active cycle rather than overwrite it. If a different active cycle exists, ask which to finish or cancel. Archive terminal state by cycle ID before creating a replacement under a fresh explicit invocation.

Keep a JSON checkpoint with these fields. Null means not yet resolved; fill fields before dependent actions. Never fabricate an ID or approval.

| Field | Content |
| --- | --- |
| `schema_version` | `1` |
| `cycle_id`, `project_root`, `thread_id` | Unique cycle ID, absolute repository root, originating host thread |
| `started_by` | Explicit user request reference, timestamp, and invocation evidence |
| `phase` | `backlog`, `development`, `testing`, `preparation`, `submission`, `monitoring`, `complete`, or `cancelled` |
| `wait` | Kind, reason, next check in UTC, and pending question evidence; null while working |
| `backlog` | Artifact path, revision identity, and acceptance response reference |
| `source_commit` | Source revision used to produce the current candidate |
| `app` | App ID, platform, version string, version ID, build ID/number, and submission ID |
| `testing` | Thread rename status, simulator verification (device, candidate source, per-check results, screenshot paths, device-only checks), available-at UTC, readiness-at UTC, ready-question state/reference, tested build, user completion response, last TestFlight feedback check UTC, and feedback items with source (thread message or TestFlight submission ID), build, status, and fixing build |
| `package` | Manifest path and SHA-256 identity |
| `submission_approval` | Exact package identity, user response reference, and time |
| `review` | Thread rename status, last observed state, observed-at UTC, approval evidence, and exact-version public-release evidence |
| `publishing` | Thread rename status, intended account and route, authentication status, public-release trigger, user choice for optional feature posts, and a post list. Each entry has a stable key, release/feature kind, selected/skipped state, video/caption paths and hashes, status, attempt identity, provider job/container IDs, and verified post ID/URL |
| `schedules` | Owned task IDs, purpose, creation request ID, bound thread, and returned next-run time |
| `updated_at` | Last saved UTC timestamp |

Derive stable package identity from a saved manifest containing exact app/version/build IDs, source revision, metadata diff or file hashes, video and caption hashes, and release behavior. A new identity invalidates prior submission approval. Preserve actual user replies as evidence or reference retrievable originating-thread messages. Never store credentials, tokens, or private key contents.

Include every selected post in the package identity. For an older checkpoint with a single video and caption, preserve its release-only scope; extra files on disk do not select feature posts. Record an explicit later request to publish additional posts with its own asset identities and user evidence. A request after cycle completion uses separate durable publishing state and receipts, leaving the submitted package immutable. It is a publishing follow-up, not a new release cycle or a reason to renew or repeat the completed App Store submission.

Hold exclusive mutation ownership while reading, changing, and saving state. Save JSON to a temporary file in the same directory and atomically replace the checkpoint. Check its identity before writing so another cycle cannot be overwritten.

Acquire ownership with atomic directory creation at the resolved lock path. Record cycle ID, thread ID, operation ID, and acquired time in the lock. Release in `finally` after each bounded action and save; do not hold it while waiting for the user, a timer, or CI. An overlapping continuation leaves work to the current owner.

An old timestamp alone does not prove ownership ended. Inspect the host's run/thread state. Recover a lock only after proving its operation has stopped and reconciling any external action it might have performed. If ownership cannot be resolved, ask rather than stealing it.

## Resume decision

Read the checkpoint and originating user context before doing work. Verify the requested cycle, project, thread, explicit-start evidence, branch, candidate source/build, and outstanding user gate. Missing, mismatched, cancelled, or completed state is an exit, never a new start. Disable a stale continuation only after verifying its ownership.

If the agent's own main commits after the candidate only contain known release artifacts, record that relationship. If other source changed since the candidate, inspect it before using the candidate or its approvals. Do not assume latest build means intended build.

Choose the next action from the saved phase:

| Situation | Next action |
| --- | --- |
| Accepted backlog, no App Store version draft | Create the draft, then develop |
| Accepted backlog, development unfinished | Develop immediately |
| CI or TestFlight not ready | Reconcile exact pipeline/build; register an external check if needed |
| Testing before deadline | Collect new TestFlight feedback and crashes, handle incoming feedback, then yield to the next feedback check or readiness check |
| Testing due, no completion response | Retain a recovery wakeup, deliver readiness once, then disable after delivery is established |
| Readiness already asked, no reply | Retain question and wait without duplicate prompts |
| User finished testing, blockers resolved | Prepare package immediately |
| Assets ready, Instagram connection unavailable before public release | Record deferred sign-in; continue package presentation and authorized submission |
| Package ready, no matching submission go | Present package and ask go |
| Matching go saved | Validate and submit, reconciling remote state first |
| Submitted version pending | Register or retain a review continuation every 12 hours |
| Exact version approved, not publicly released | Retain prepared assets; wait for public release under the configured manual or automatic policy |
| Exact approved version publicly released | Verify release evidence and target-account authentication, then complete the Instagram step |
| Some selected posts verified, others unfinished | Preserve verified post receipts; publish or reconcile only unfinished selected posts |
| Every remaining selected post verified, with named user-directed removals recorded | Disable schedules and complete cycle |

Save an impending question before asking with status `pending`; after the tool or message succeeds, save status `sent` and its evidence. Keep the readiness recovery wakeup enabled until delivery is established from a successful send result or originating-thread evidence. Following interruption, reconcile that thread before sending: an existing delivered question is recorded without sending another; an undelivered pending question is sent under the retained recovery wakeup. Disable the wakeup only after establishing delivery. User replies resume the same phase and consume only the gate they actually answer.

## T3 scheduling

Discover the live `schedule_task`, `list_scheduled_tasks`, and `update_scheduled_task` schemas. Read capabilities and use the supported T3 transport. Stay in the originating thread; do not create top-level conversations for continuations.

Create a schedule only after a user-started checkpoint exists. Bind to the current originating thread with `bindToCurrentThread: true`. Pass a structured object, never JSON text. Use a stable creation `clientRequestId` for that cycle and wait occurrence; preserve it across retries.

For testing, compute `readiness_at = available_at + 48 hours`. Use a positive interval in milliseconds equal to the smaller of 12 hours and the remaining time until readiness. On each wakeup before readiness, collect TestFlight feedback, save the check time, and update the same owned schedule to the smaller of 12 hours and the remaining time. When due, first update the same owned schedule to `{"type":"interval","everyMs":300000}` and verify it remains enabled. This five-minute recovery interval stays active while question delivery is pending. If already due without an owned task, establish this recovery wakeup before sending. Then reconcile thread evidence, deliver the readiness question only if absent, save delivery evidence, and disable the owned wakeup. A crash after sending but before saving is recovered by finding the delivered question; a crash before sending retains an automatic retry. Do not silently move the testing deadline when a replacement build appears. When the user extends testing, record the new check and a new wait occurrence.

For review and automatic-release availability checks, use `{"type":"interval","everyMs":43200000}` for a 12-hour cadence. Apply a user-requested cadence change to the existing owned schedule and checkpoint; do not create a duplicate. A manual-release decision remains a user gate; do not silently release the app. For CI or build processing, use the project's existing watcher when available; otherwise schedule a suitable bounded check using the same ownership rules. One active owned continuation is sufficient for the current wait.

Give the task a title containing cycle ID and purpose, and use this continuation prompt with resolved values:

```text
Continue $ios-weekly-iteration cycle <cycle_id>, previously started explicitly by the user, in project <absolute_project_root> and originating thread <thread_id>. Read checkpoint <absolute_state_path> and references/continuations.md. Resume only that matching active cycle; missing or terminal state must not start a cycle. Reconcile phase, user responses, candidate identity, outstanding external actions, and owned schedules before taking the next authorized action. This wakeup grants no backlog acceptance, testing completion, or submission approval.
```

Save and inspect returned `scheduledTaskId`, `boundThreadId`, `enabled`, and `nextRunAt`. Confirm the binding and next run, then report the next check to the user. Schedule registration is part of the user-started workflow, not automatic activation of an unstarted skill.

Before creating a replacement or retrying an uncertain creation, list tasks in the originating project. Match cycle ID, purpose, prompt identity, and bound thread. Reuse the matching owned task; disable extra owned matches after reconciliation. Never disable unrelated tasks. Scheduler and checkpoint writes are separate operations, so save pending creation intent first and reconcile incomplete results on resume.

Once a user-gate question is confirmed delivered, disable periodic checks that would repeat it. A pending, undelivered readiness question retains its recovery check. A reply resumes the workflow through the originating thread. Use an absolute deadline rather than a long running sleep. On completion or user cancellation, disable all tasks owned by the cycle and verify the returned state before recording cleanup complete. If disable fails, retain IDs for retry; terminal state still prevents queued wakeups from performing release work. A terminal checkpoint permits retrying recorded owned-schedule cleanup without resuming release or publication actions.

If persistent scheduling is absent or unsupported, preserve progress and explain that automatic wakeups are unavailable in this host. Resume when the user returns. Do not install a daemon, modify a VPS, or claim an unregistered background runner is active.

## External action recovery

Before submission, save intended app/version/build/package identity. After an uncertain outcome, query asc for the exact version and submission before attempting again. Continue an existing matching draft or active submission under the appropriate asc skill. A newer or different build needs fresh approval.

Before Instagram publishing, verify public App Store availability of this cycle's exact approved version and save the release evidence. An approval without public release retains all selected posts without publishing. Confirm target-account authentication at publication time; missing sign-in earlier does not block generation or App Store submission. For each selected post, save the target account, media and caption identity, attempt ID, and any provider container/job ID. Prefer provider idempotency support where available. On timeout, inspect that operation and the account's posts using the project's supported route. Save a verified matching post rather than publishing again. Preserve successful entries while reconciling unfinished ones; never restart the entire post set. If absence or success cannot be established reliably, request the user's help resolving the outcome.

On rejections, missing access, or changed product requirements, keep the cycle identity and completed work. Continue independent authorized preparation or diagnosis. Ask only the question blocking dependent work, and require a renewed go if a repaired release materially changes its package.
