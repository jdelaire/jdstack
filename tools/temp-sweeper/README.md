# temp-sweeper

A LaunchAgent that runs `sweep.py` at 00:00, 06:00, 12:00 and 18:00 and deletes build caches and profiler leftovers that agents abandon.

It deletes:

- DerivedData and SwiftPM build folders in Claude session scratchpads (`/private/tmp/claude-501/<project>/<session>/scratchpad`) once the session's transcript has been idle for 24 hours and no `claude --resume=<session>` process is running. While a `claude` process without a session ID runs in the same project folder, that project's scratchpads are left alone.
- The same kinds of build folder elsewhere in `/private/tmp` after 72 hours without changes.
- `instruments*.ktrace` and `xrgpu_aps_*` files in the user temp folder after 6 hours, when no `xctrace` or Instruments process is running.

A folder counts as a build folder only if every entry in it belongs to a DerivedData or SwiftPM layout and it holds Xcode or SwiftPM build metadata, so a scratchpad that mixes builds with screenshots or videos keeps everything except the build folder itself. Before each delete it skips anything a running process names or has open, anything a SimLease job names, anything an `ios-weekly-iteration` checkpoint references, and anything containing tracked files. If an inspection command fails, the run stops without deleting more. Build folders in repository `tmp/` directories are only logged.

Install or update with `./install.sh`. Preview with `/usr/bin/python3 -I sweep.py --dry-run`. The log is `~/Library/Logs/temp-sweeper.log`.
