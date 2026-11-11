# temp-sweeper

A LaunchAgent that runs `sweep.py` at 00:00, 06:00, 12:00 and 18:00 and deletes build caches, repo copies and profiler leftovers that agents abandon.

It deletes:

- DerivedData and SwiftPM build folders in Claude session scratchpads (`/private/tmp/claude-501/<project>/<session>/scratchpad`) once the session's transcript has been idle for 24 hours and no `claude --resume=<session>` process is running. While a `claude` process without a session ID runs in the same project folder, that project's scratchpads are left alone.
- The same kinds of build folder elsewhere in `/private/tmp` after 72 hours without changes.
- Repo copies and git worktrees in those scratchpads (same 24-hour rule) and in `/private/tmp/agent-builds` (72 hours), after saving a snapshot.
- `instruments*.ktrace` and `xrgpu_aps_*` files in the user temp folder after 6 hours, when no `xctrace` or Instruments process is running.

A folder counts as a build folder only if every entry in it belongs to a DerivedData or SwiftPM layout and it holds Xcode or SwiftPM build metadata, so a scratchpad that mixes builds with screenshots or videos keeps everything except the build folder itself.

A repo copy is a folder with an Xcode project, `Package.swift` or `project.yml` whose top-level entries match a repository under `~/Developer` (`git archive`, `cp` or `rsync` exports), or a linked git worktree. Before deleting one, the sweeper hashes every file outside nested build folders, picks the reachable commit it matches best (the worktree's own HEAD for worktrees), and writes the files that differ plus a manifest of every path, mode and blob hash to `~/Library/Application Support/temp-sweeper/snapshots/<id>`. The snapshot is read back and checked, the base commit is pinned in that repository as `refs/temp-sweeper/<id>` so garbage collection keeps it, and the copy is hashed again right before deletion and kept if anything changed. Snapshots and their refs are never pruned automatically. It skips and logs copies with staged changes, unfinished merges or rebases, commits not reachable from a branch, remote or tag, locked worktrees, nested repositories, submodules, special files, or more than 200 MB of differing data. Full clones (a `.git` directory) are only logged.

Restore a snapshot into a new folder with `/usr/bin/python3 -I sweep.py --restore <id> <dest>`; it rebuilds every file from the base commit and the saved differences and verifies the hashes.

Before each delete it skips anything a running process names or has open, anything a SimLease job names, anything an `ios-weekly-iteration` checkpoint references, and anything containing tracked files, and it checks again right before deleting. If an inspection command fails, the run stops without deleting more. Build folders in repository `tmp/` directories are only logged.

Install or update with `./install.sh`. Preview with `/usr/bin/python3 -I sweep.py --dry-run`. The log is `~/Library/Logs/temp-sweeper.log`.
