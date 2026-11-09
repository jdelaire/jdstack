import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
CLAUDE_TMP = Path("/private/tmp/claude-501")
PRIVATE_TMP = Path("/private/tmp")
TRANSCRIPTS = HOME / ".claude" / "projects"
DEVELOPER = HOME / "Developer"
LOG = HOME / "Library" / "Logs" / "temp-sweeper.log"
LOCK = HOME / "Library" / "Caches" / "temp-sweeper.lock"

SESSION_IDLE = 24 * 3600
ORPHAN_IDLE = 72 * 3600
TRACE_IDLE = 6 * 3600
MAX_DEPTH = 8
LOG_SKIP_BYTES = 500_000_000

DD_DIRS = {
    "Build", "CompilationCache.noindex", "Index.noindex", "Logs", "ModuleCache.noindex",
    "SDKExplicitPrecompiledModules", "SDKStatCaches.noindex", "SourcePackages",
    "SymbolCache.noindex", "TextIndex",
}
DD_FILES = {"info.plist", ".DS_Store"}
SPM_DIRS = {
    "checkouts", "repositories", "artifacts", "debug", "release", "plugins", "prebuilts",
    "index-build", "out", "cache", "configuration", "registry", "security", "module-cache",
}
SPM_FILES = {"workspace-state.json", "description.json", "build.db", ".lock", ".DS_Store"}
SPM_ARCH = re.compile(r"^[a-z0-9_]+-apple-[a-z0-9._-]+$")
SPM_FILE = re.compile(r"^[A-Za-z0-9._-]+\.(yaml|db)$")
TRACE_PATTERN = re.compile(r"^(instruments[A-Za-z0-9]+\.ktrace|xrgpu_aps_0x[0-9a-f]+_\d+)$")
TRACE_PROCESS = re.compile(r"(^|/)(xctrace|Instruments|instruments)$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
RESUME = re.compile(r"--resume[= ]([0-9a-f-]{36})")
CLAUDE_COMMAND = re.compile(r"^(\S*/)?claude(\s|$)")


class InspectionError(Exception):
    pass


def log(line):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > 1_000_000:
        LOG.replace(LOG.with_suffix(".log.1"))
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with LOG.open("a") as f:
        f.write(f"{stamp} {line}\n")
    print(line)


def run(cmd, ok=(0,)):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as error:
        raise InspectionError(f"{cmd[0]}: {error}")
    if result.returncode not in ok:
        raise InspectionError(f"{' '.join(cmd)} exited {result.returncode}: {result.stderr.strip()[:200]}")
    return result.stdout


def canonical(text):
    text = os.path.normpath(os.path.expanduser(text))
    for prefix, real in (("/tmp", "/private/tmp"), ("/var", "/private/var")):
        if text == prefix or text.startswith(prefix + "/"):
            text = real + text[len(prefix):]
    if os.path.exists(text):
        text = os.path.realpath(text)
    return text


def related(a, b):
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def entries(path):
    try:
        return {e.name: e for e in os.scandir(path)}
    except OSError:
        return None


def is_dir(entry):
    return entry.is_dir(follow_symlinks=False)


def is_file(entry):
    return entry.is_file(follow_symlinks=False)


def is_derived_data(path, found):
    if not found:
        return False
    for name, entry in found.items():
        if not ((name in DD_DIRS and is_dir(entry)) or (name in DD_FILES and is_file(entry))):
            return False
    return (
        (path / "Build" / "Intermediates.noindex").is_dir()
        or (path / "SourcePackages" / "workspace-state.json").is_file()
        or ("ModuleCache.noindex" in found and "info.plist" in found)
    )


def is_swiftpm(path, found):
    if not found or "workspace-state.json" not in found or not is_file(found["workspace-state.json"]):
        return False
    for name, entry in found.items():
        if is_dir(entry) and (name in SPM_DIRS or SPM_ARCH.match(name)):
            continue
        if is_file(entry) and (name in SPM_FILES or SPM_FILE.match(name)):
            continue
        return False
    try:
        state = json.loads((path / "workspace-state.json").read_text())
    except (OSError, ValueError):
        return False
    return isinstance(state, dict) and "object" in state and "version" in state


def is_build_root(path):
    found = entries(path)
    return found is not None and (is_derived_data(path, found) or is_swiftpm(path, found))


def build_roots(base, depth=0):
    if depth > MAX_DEPTH:
        return
    found = entries(base)
    if not found:
        return
    for name, entry in found.items():
        if name in ("node_modules", ".git") or not is_dir(entry):
            continue
        path = Path(entry.path)
        if is_build_root(path):
            yield path
        else:
            yield from build_roots(path, depth + 1)


def tree_stats(path):
    newest = os.lstat(path).st_mtime
    total = 0
    for root, dirs, files in os.walk(path):
        for name in dirs:
            try:
                newest = max(newest, os.lstat(os.path.join(root, name)).st_mtime)
            except OSError:
                pass
        for name in files:
            try:
                st = os.lstat(os.path.join(root, name))
                newest = max(newest, st.st_mtime)
                total += st.st_size
            except OSError:
                pass
    return newest, total


def path_strings(value, base):
    if isinstance(value, dict):
        for v in value.values():
            yield from path_strings(v, base)
    elif isinstance(value, list):
        for v in value:
            yield from path_strings(v, base)
    elif isinstance(value, str):
        whole = value.strip()
        if whole.startswith(("/", "~/")) and "\n" not in whole:
            yield canonical(whole)
        for token in re.split(r"[\s;,]+", value):
            token = token.strip("\"'()[]`")
            if token.startswith(("/", "~/")):
                yield canonical(token)
            elif "/" in token and not token.startswith(("http", "-")):
                yield canonical(str(base / token))


def git_repos():
    repos = []
    for root, dirs, files in os.walk(DEVELOPER):
        if ".git" in dirs or ".git" in files:
            repos.append(Path(root))
            dirs[:] = []
            continue
        if len(Path(root).relative_to(DEVELOPER).parts) >= 4:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".build", "build", "tmp")]
    return repos


def checkpoint_refs():
    refs = set()
    for repo in git_repos():
        state = Path(run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute",
                          "--git-path", "ios-weekly-iteration"]).strip())
        if not state.is_dir():
            continue
        for root, dirs, files in os.walk(state):
            dirs[:] = [d for d in dirs if d != "work"]
            for name in files:
                if not name.endswith(".json"):
                    continue
                try:
                    text = Path(root, name).read_text(errors="replace")
                except OSError as error:
                    raise InspectionError(f"unreadable checkpoint {root}/{name}: {error}")
                try:
                    data = json.loads(text)
                except ValueError:
                    data = text
                refs.update(r for r in path_strings(data, repo) if len(Path(r).parts) > 3)
    return refs


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


class Live:
    def __init__(self):
        self.ps = run(["ps", "-axo", "pid=,command="])
        lsof = run(["lsof", "-nP", "-F", "n"])
        self.open_paths = [canonical(l[1:]) for l in lsof.splitlines() if l.startswith("n/")]
        if len(self.open_paths) < 100:
            raise InspectionError("lsof listed too few files")
        self.lease_paths = self._lease()
        commands = [line.strip().partition(" ") for line in self.ps.splitlines()]
        self.tracing = any(TRACE_PROCESS.search(c.split(" ", 1)[0]) for _, _, c in commands)
        self.resumed = set(RESUME.findall(self.ps))
        self.unresumed_slugs = set()
        for pid, _, command in commands:
            if CLAUDE_COMMAND.match(command) and not RESUME.search(command):
                out = run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], ok=(0, 1))
                self.unresumed_slugs.update(slug(l[1:]) for l in out.splitlines() if l.startswith("n/"))

    def _lease(self):
        lease = json.loads(run(["simlease", "status", "--json", "--devices"]))
        jobs = [lease.get("owner") or {}] + list(lease.get("waiters") or [])
        for lane in lease.get("lanes") or []:
            if isinstance(lane, dict):
                jobs.append(lane.get("owner") or {})
        paths = []
        for job in jobs:
            cwd = Path(job.get("cwd") or "/")
            if len(cwd.parts) > 3:
                paths.append(canonical(str(cwd)))
            for arg in job.get("command") or []:
                for piece in str(arg).split("="):
                    if piece.startswith(("/", "~")):
                        paths.append(canonical(piece))
                    elif "/" in piece:
                        paths.append(canonical(str(cwd / piece)))
        return paths

    def blocker(self, path, session=None, project=None):
        text = str(path)
        aliases = {text, text.replace("/private/tmp/", "/tmp/", 1), text.replace("/private/var/", "/var/", 1)}
        if any(a in self.ps for a in aliases):
            return "process"
        if session and (session in self.resumed or session in self.ps):
            return "session running"
        if project and project in self.unresumed_slugs:
            return "unidentified session running in project"
        if any(p == text or p.startswith(text + "/") for p in self.open_paths):
            return "open file"
        if any(related(p, text) for p in self.lease_paths):
            return "simlease"
        return None


def session_of(path):
    try:
        parts = path.relative_to(CLAUDE_TMP).parts
    except ValueError:
        return None, None
    if len(parts) < 3 or parts[2] != "scratchpad" or not UUID.match(parts[1]):
        return None, None
    return parts[0], parts[1]


def transcript_idle(project, session):
    transcript = TRANSCRIPTS / project / f"{session}.jsonl"
    if not transcript.exists():
        return None
    last = transcript.stat().st_mtime
    side = TRANSCRIPTS / project / session
    if side.is_dir():
        last = max(last, tree_stats(side)[0])
    return time.time() - last


def tracked(path):
    top = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode != 0:
        return False
    out = run(["git", "-C", top.stdout.strip(), "ls-files", "--", str(path)])
    return bool(out.strip())


def candidates():
    found = []
    if CLAUDE_TMP.is_dir():
        found += [("scratch", p) for p in build_roots(CLAUDE_TMP)]
    for name, entry in (entries(PRIVATE_TMP) or {}).items():
        if name == CLAUDE_TMP.name or not is_dir(entry):
            continue
        path = Path(entry.path)
        if is_build_root(path):
            found.append(("orphan", path))
        else:
            found += [("orphan", p) for p in build_roots(path, 1)]
    temp = Path(os.path.realpath(run(["getconf", "DARWIN_USER_TEMP_DIR"]).strip()))
    for name, entry in (entries(temp) or {}).items():
        if TRACE_PATTERN.match(name) and is_file(entry):
            found.append(("trace", Path(entry.path)))
    for repo in git_repos():
        if (repo / "tmp").is_dir():
            found += [("report", p) for p in build_roots(repo / "tmp")]
    return found


def static_check(kind, path, refs):
    if os.path.realpath(path) != str(path):
        return "symlinked", 0
    if kind == "trace":
        st = path.lstat()
        if time.time() - st.st_mtime < TRACE_IDLE:
            return "recent", st.st_size
        if any(related(r, str(path)) for r in refs):
            return "checkpoint reference", st.st_size
        return None, st.st_size
    if not is_build_root(path):
        return "no longer a build folder", 0
    if kind == "scratch":
        project, session = session_of(path)
        if not session:
            return "not in a session scratchpad", 0
        idle = transcript_idle(project, session)
        if idle is None:
            return "no transcript", 0
        if idle < SESSION_IDLE:
            return "session recent", 0
    if any(related(r, str(path)) for r in refs):
        return "checkpoint reference", 0
    newest, size = tree_stats(path)
    if time.time() - newest < (ORPHAN_IDLE if kind == "orphan" else SESSION_IDLE):
        return "recent", size
    if tracked(path):
        return "tracked files", size
    if kind == "report":
        return "report only", size
    return None, size


def sweep(dry_run):
    refs = checkpoint_refs()
    Live()
    freed = deleted = 0
    for kind, path in candidates():
        reason, size = static_check(kind, path, refs)
        project, session = session_of(path) if kind == "scratch" else (None, None)
        if not reason:
            live = Live()
            reason = live.blocker(path, session, project)
            if not reason and kind == "trace" and live.tracing:
                reason = "profiler running"
            if not reason:
                reason, size = static_check(kind, path, checkpoint_refs())
        if reason:
            if size >= LOG_SKIP_BYTES or reason not in ("recent", "session recent", "no transcript"):
                log(f"skip {reason} {size / 2**30:.2f}G {path}")
            continue
        if dry_run:
            log(f"would delete {kind} {size / 2**30:.2f}G {path}")
        else:
            if kind == "trace":
                path.unlink()
            else:
                shutil.rmtree(path)
            log(f"deleted {kind} {size / 2**30:.2f}G {path}")
        freed += size
        deleted += 1
    log(f"done: {deleted} paths, {'would free' if dry_run else 'freed'} {freed / 2**30:.2f}G")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another sweep is running")
            return 0
        try:
            sweep(args.dry_run)
        except InspectionError as error:
            log(f"aborted, nothing more deleted: {error}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
