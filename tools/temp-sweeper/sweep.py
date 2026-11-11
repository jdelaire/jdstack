import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import uuid
from pathlib import Path

HOME = Path.home()
CLAUDE_TMP = Path("/private/tmp/claude-501")
PRIVATE_TMP = Path("/private/tmp")
AGENT_BUILDS = PRIVATE_TMP / "agent-builds"
TRANSCRIPTS = HOME / ".claude" / "projects"
DEVELOPER = HOME / "Developer"
LOG = HOME / "Library" / "Logs" / "temp-sweeper.log"
LOCK = HOME / "Library" / "Caches" / "temp-sweeper.lock"
STATE = HOME / "Library" / "Caches" / "temp-sweeper-state.json"
SNAPSHOTS = HOME / "Library" / "Application Support" / "temp-sweeper" / "snapshots"

SESSION_IDLE = 24 * 3600
ORPHAN_IDLE = 72 * 3600
TRACE_IDLE = 6 * 3600
MAX_DEPTH = 8
LOG_SKIP_BYTES = 500_000_000
SNAPSHOT_BUDGET = 200 * 2**20
BASE_COMMITS = 100
MAX_REFLOG = 500

DD_DIRS = {
    "Build", "CompilationCache.noindex", "Index.noindex", "Logs", "ModuleCache.noindex",
    "SDKExplicitPrecompiledModules", "SDKStatCaches.noindex", "SourcePackages",
    "SymbolCache.noindex", "TestResults", "TextIndex",
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
SKIP_WALK = ("node_modules", ".git")
GIT_OPS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply")
QUIET = ("recent", "session recent", "no transcript")


class InspectionError(Exception):
    pass


class Skip(Exception):
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


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode != 0:
        raise Skip(f"git {args[0]} failed")
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
        if name in SKIP_WALK or not is_dir(entry):
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


def checkpoint_refs(repos):
    refs = set()
    for repo in repos:
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


def scope_of(kind, path):
    if kind in ("trace", "report"):
        return kind, None, None
    project, session = session_of(path)
    if session:
        return "session", project, session
    return "orphan", None, None


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


def worktree_gitdir(path):
    dotgit = path / ".git"
    if dotgit.is_symlink() or not dotgit.is_file():
        return None
    try:
        text = dotgit.read_text(errors="replace").strip()
    except OSError:
        return None
    if not text.startswith("gitdir: "):
        return None
    target = text[len("gitdir: "):]
    gitdir = Path(canonical(target if os.path.isabs(target) else str(path / target)))
    back = gitdir / "gitdir"
    if gitdir.parent.name != "worktrees" or not back.is_file():
        return None
    if canonical(back.read_text(errors="replace").strip()) != canonical(str(dotgit)):
        return None
    return gitdir


def has_marker(path):
    found = entries(path) or {}
    dirs = [path] + [Path(e.path) for n, e in found.items() if n not in SKIP_WALK and is_dir(e)]
    for d in dirs:
        for name in entries(d) or {}:
            if name.endswith(".xcodeproj") or name in ("Package.swift", "project.yml"):
                return True
    return False


_top_names = {}


def repo_top_names(repo):
    if repo not in _top_names:
        out = subprocess.run(["git", "-C", str(repo), "ls-tree", "--name-only", "HEAD"],
                             capture_output=True, text=True)
        _top_names[repo] = set(out.stdout.splitlines()) if out.returncode == 0 else set()
    return _top_names[repo]


def export_repo(path, project, repos):
    names = {n for n in entries(path) or {} if n != ".DS_Store"}
    if len(names) < 3 or ".git" in names or not has_marker(path):
        return None
    for repo in sorted(repos, key=lambda r: slug(str(r)) != project):
        top = repo_top_names(repo)
        common = names & top
        if len(common) >= 3 and len(common) >= 0.8 * len(top) and len(common) >= 0.5 * len(names):
            return repo
    return None


def snapshot_shape(path, repos):
    dotgit = path / ".git"
    if dotgit.is_dir() and not dotgit.is_symlink():
        return ("clone", None, None) if has_marker(path) else None
    gitdir = worktree_gitdir(path)
    if gitdir:
        common = Path(canonical(str(gitdir.parent.parent)))
        return ("worktree", common.parent if common.name == ".git" else None, gitdir)
    repo = export_repo(path, session_of(path)[0], repos)
    return ("export", repo, None) if repo else None


def snapshot_roots(base, repos, depth=0):
    if depth > MAX_DEPTH:
        return
    for name, entry in (entries(base) or {}).items():
        if name in SKIP_WALK or not is_dir(entry):
            continue
        path = Path(entry.path)
        if is_build_root(path):
            continue
        if snapshot_shape(path, repos):
            yield path
        else:
            yield from snapshot_roots(path, repos, depth + 1)


def blob_sha(path, st):
    h = hashlib.sha1()
    if stat.S_ISLNK(st.st_mode):
        data = os.fsencode(os.readlink(path))
        h.update(b"blob %d\0" % len(data))
        h.update(data)
        return h.hexdigest()
    h.update(b"blob %d\0" % st.st_size)
    read = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            read += len(chunk)
            h.update(chunk)
    if read != st.st_size:
        raise Skip("file changed while hashing")
    return h.hexdigest()


def walk_error(error):
    raise Skip(f"unreadable {error.filename}")


def snapshot_entries(path):
    found, excluded = {}, []
    for root, dirs, files in os.walk(path, onerror=walk_error):
        here = Path(root)
        keep = []
        for d in dirs:
            p = here / d
            if p.is_symlink():
                files.append(d)
            elif d == ".git":
                raise Skip("nested repository")
            elif is_build_root(p):
                excluded.append(p.relative_to(path).as_posix())
            else:
                keep.append(d)
        dirs[:] = keep
        for f in files:
            p = here / f
            if f == ".git":
                if here == path:
                    continue
                raise Skip("nested repository")
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                mode = "120000"
            elif stat.S_ISREG(st.st_mode):
                mode = "100755" if st.st_mode & 0o100 else "100644"
            else:
                raise Skip("special file")
            found[p.relative_to(path).as_posix()] = (mode, st)
    return found, excluded


def base_tree(repo, commit):
    tree = {}
    for item in git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not item:
            continue
        meta, _, name = item.partition(b"\t")
        mode, _, sha = meta.decode().split()
        if mode == "160000":
            raise Skip("submodules")
        tree[os.fsdecode(name)] = (mode, sha)
    return tree


def reachable(repo, commit):
    out = git(repo, "for-each-ref", "--count=1", "--contains", commit,
              "refs/heads", "refs/remotes", "refs/tags")
    return bool(out.strip())


def worktree_listing(repo, path):
    blocks = git(repo, "worktree", "list", "--porcelain").decode(errors="replace").split("\n\n")
    for block in blocks:
        lines = block.splitlines()
        if lines and lines[0].startswith("worktree ") and canonical(lines[0][9:]) == str(path):
            return lines
    return None


def worktree_base(path, repo, gitdir):
    if repo is None:
        raise Skip("bare repository")
    lines = worktree_listing(repo, path)
    if lines is None:
        raise Skip("not registered as a worktree")
    if any(l == "locked" or l.startswith("locked ") for l in lines):
        raise Skip("locked worktree")
    if any((gitdir / n).exists() for n in GIT_OPS):
        raise Skip("unfinished git operation")
    head = git(path, "rev-parse", "--verify", "HEAD").decode().strip()
    if subprocess.run(["git", "-C", str(path), "diff", "--cached", "--quiet", "HEAD", "--"],
                      capture_output=True).returncode != 0:
        raise Skip("staged changes")
    history = set(git(path, "reflog", "show", "--format=%H", "HEAD").decode().split()) | {head}
    if len(history) > MAX_REFLOG:
        raise Skip("worktree history too long")
    if not all(reachable(repo, c) for c in history):
        raise Skip("unpushed commits in worktree history")
    return head


def export_base(repo, hashes):
    commits = git(repo, "rev-list", "--date-order", f"--max-count={BASE_COMMITS}",
                  "--branches", "--remotes", "--tags").decode().split()
    best = None
    for commit in commits:
        tree = base_tree(repo, commit)
        score = sum(1 for rel, entry in hashes.items() if tree.get(rel) == entry)
        if best is None or score > best[0]:
            best = (score, commit, tree)
    if not best or best[0] == 0:
        raise Skip("no matching commit")
    return best[1], best[2]


def inventory(path):
    found, excluded = snapshot_entries(path)
    hashes = {rel: (mode, blob_sha(path / rel, st)) for rel, (mode, st) in found.items()}
    return found, excluded, hashes


def preserve(path, shape, project, session, dry_run):
    kind, repo, gitdir = shape
    found, excluded, hashes = inventory(path)
    if kind == "worktree":
        base = worktree_base(path, repo, gitdir)
        tree = base_tree(repo, base)
    else:
        base, tree = export_base(repo, hashes)
    for rel in tree:
        if any(rel == e or rel.startswith(e + "/") for e in excluded):
            raise Skip("tracked files inside build folder")
    changed = sorted(rel for rel, entry in hashes.items() if tree.get(rel) != entry)
    size = sum(found[rel][1].st_size for rel in changed)
    if size > SNAPSHOT_BUDGET:
        raise Skip(f"too much unique data ({size / 2**20:.0f} MB)")
    if dry_run:
        return None, size, base, hashes
    sid = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:12]}"
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    partial = SNAPSHOTS / f".{sid}.partial"
    partial.mkdir()
    try:
        with tarfile.open(partial / "files.tar.gz", "w:gz") as tar:
            for rel in changed:
                tar.add(str(path / rel), arcname=rel, recursive=False)
        manifest = {
            "source": str(path), "kind": kind, "repo": str(repo), "base": base,
            "project": project, "session": session, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "entries": {rel: list(entry) for rel, entry in hashes.items()},
            "changed": changed, "deleted": sorted(rel for rel in tree if rel not in hashes),
            "excluded": excluded,
        }
        (partial / "manifest.json").write_text(json.dumps(manifest))
        verify_snapshot(partial, manifest)
        git(repo, "update-ref", f"refs/temp-sweeper/{sid}", base, "")
        os.rename(partial, SNAPSHOTS / sid)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return sid, size, base, hashes


def member_sha(tar, member):
    h = hashlib.sha1()
    if member.issym():
        data = os.fsencode(member.linkname)
        h.update(b"blob %d\0" % len(data))
        h.update(data)
        return "120000", h.hexdigest()
    if not member.isfile():
        raise Skip("snapshot verification failed")
    h.update(b"blob %d\0" % member.size)
    f = tar.extractfile(member)
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
    return ("100755" if member.mode & 0o100 else "100644"), h.hexdigest()


def verify_snapshot(folder, manifest):
    seen = set()
    with tarfile.open(folder / "files.tar.gz", "r:gz") as tar:
        for member in tar:
            expected = manifest["entries"].get(member.name)
            if member.name in seen or not expected or list(member_sha(tar, member)) != expected:
                raise Skip("snapshot verification failed")
            seen.add(member.name)
    if seen != set(manifest["changed"]):
        raise Skip("snapshot verification failed")


def write_entry(dest, rel, mode, source, size):
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "120000":
        os.symlink(os.fsdecode(source.read(size)), target)
        return
    with open(target, "wb") as out:
        left = size
        while left:
            chunk = source.read(min(left, 1 << 20))
            if not chunk:
                raise SystemExit(f"truncated data for {rel}")
            out.write(chunk)
            left -= len(chunk)
    os.chmod(target, 0o755 if mode == "100755" else 0o644)


def restore(sid, dest):
    folder = SNAPSHOTS / sid
    manifest = json.loads((folder / "manifest.json").read_text())
    dest = Path(dest)
    dest.mkdir(parents=True)
    changed = set(manifest["changed"])
    batch = subprocess.Popen(["git", "-C", manifest["repo"], "cat-file", "--batch"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    for rel, (mode, sha) in manifest["entries"].items():
        if rel in changed:
            continue
        batch.stdin.write(sha.encode() + b"\n")
        batch.stdin.flush()
        header = batch.stdout.readline().split()
        if len(header) != 3 or header[1] != b"blob":
            raise SystemExit(f"missing blob {sha} for {rel}")
        write_entry(dest, rel, mode, batch.stdout, int(header[2]))
        batch.stdout.read(1)
    batch.stdin.close()
    batch.wait()
    with tarfile.open(folder / "files.tar.gz", "r:gz") as tar:
        for member in tar:
            if member.issym():
                link = os.fsencode(member.linkname)
                (dest / member.name).parent.mkdir(parents=True, exist_ok=True)
                os.symlink(os.fsdecode(link), dest / member.name)
            else:
                mode = "100755" if member.mode & 0o100 else "100644"
                write_entry(dest, member.name, mode, tar.extractfile(member), member.size)
    bad = [rel for rel, entry in manifest["entries"].items()
           if [entry[0], blob_sha(dest / rel, os.lstat(dest / rel))] != entry]
    print(f"restored {len(manifest['entries'])} files to {dest}, {len(bad)} mismatched")
    return 1 if bad else 0


def candidates(repos):
    found = []
    for base in (CLAUDE_TMP, AGENT_BUILDS):
        if base.is_dir():
            found += [("snapshot", p) for p in snapshot_roots(base, repos)]
    if CLAUDE_TMP.is_dir():
        found += [("build", p) for p in build_roots(CLAUDE_TMP)]
    for name, entry in (entries(PRIVATE_TMP) or {}).items():
        if name == CLAUDE_TMP.name or not is_dir(entry):
            continue
        path = Path(entry.path)
        if is_build_root(path):
            found.append(("build", path))
        else:
            found += [("build", p) for p in build_roots(path, 1)]
    temp = Path(os.path.realpath(run(["getconf", "DARWIN_USER_TEMP_DIR"]).strip()))
    for name, entry in (entries(temp) or {}).items():
        if TRACE_PATTERN.match(name) and is_file(entry):
            found.append(("trace", Path(entry.path)))
    for repo in repos:
        if (repo / "tmp").is_dir():
            found += [("report", p) for p in build_roots(repo / "tmp")]
    return found


def static_check(kind, path, refs, repos):
    if os.path.realpath(path) != str(path):
        return "symlinked", 0, 0, None
    if kind == "trace":
        st = path.lstat()
        if time.time() - st.st_mtime < TRACE_IDLE:
            return "recent", st.st_size, st.st_mtime, None
        if any(related(r, str(path)) for r in refs):
            return "checkpoint reference", st.st_size, st.st_mtime, None
        return None, st.st_size, st.st_mtime, None
    shape = None
    if kind == "snapshot":
        shape = snapshot_shape(path, repos)
        if not shape:
            return "no longer a repo copy", 0, 0, None
    elif not is_build_root(path):
        return "no longer a build folder", 0, 0, None
    scope, project, session = scope_of(kind, path)
    if scope == "session":
        idle = transcript_idle(project, session)
        if idle is None:
            return "no transcript", 0, 0, shape
        if idle < SESSION_IDLE:
            return "session recent", 0, 0, shape
    elif scope == "orphan" and related(str(path), str(CLAUDE_TMP)):
        return "not in a session scratchpad", 0, 0, shape
    elif kind == "snapshot" and not str(path).startswith(str(AGENT_BUILDS) + "/"):
        return "outside snapshot folders", 0, 0, shape
    if any(related(r, str(path)) for r in refs):
        return "checkpoint reference", 0, 0, shape
    newest, size = tree_stats(path)
    if time.time() - newest < (ORPHAN_IDLE if scope == "orphan" else SESSION_IDLE):
        return "recent", size, newest, shape
    if tracked(path):
        return "tracked files", size, newest, shape
    if kind == "report":
        return "report only", size, newest, shape
    if shape and shape[0] == "clone":
        return "full clone, report only", size, newest, shape
    if shape and shape[1] is None:
        return "no owner repository", size, newest, shape
    return None, size, newest, shape


def load_state():
    try:
        data = json.loads(STATE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def delete(kind, path, shape):
    if kind == "trace":
        path.unlink()
    elif kind == "snapshot" and shape[0] == "worktree":
        run(["git", "-C", str(shape[1]), "worktree", "remove", "--force", str(path)])
        if path.exists():
            raise InspectionError(f"worktree remove left {path}")
    else:
        shutil.rmtree(path)


def sweep(dry_run):
    repos = git_repos()
    refs = checkpoint_refs(repos)
    Live()
    state, next_state = load_state(), {}
    freed = deleted = 0
    for kind, path in candidates(repos):
        scope, project, session = scope_of(kind, path)
        reason, size, newest, shape = static_check(kind, path, refs, repos)
        if not reason:
            live = Live()
            reason = live.blocker(path, session, project)
            if not reason and kind == "trace" and live.tracing:
                reason = "profiler running"
        sid = base = hashes = None
        if not reason and kind == "snapshot":
            cached = state.get(str(path))
            if cached and cached[0] == newest:
                reason = cached[1]
            else:
                try:
                    sid, kept, base, hashes = preserve(path, shape, project, session, dry_run)
                except (Skip, OSError) as error:
                    reason = str(error) if isinstance(error, Skip) else f"inspection failed: {error}"
            if reason:
                next_state[str(path)] = [newest, reason]
        if not reason:
            live = Live()
            reason = live.blocker(path, session, project)
            if not reason:
                reason, size, again, shape = static_check(kind, path, checkpoint_refs(repos), repos)
                if not reason and again != newest:
                    reason = "changed during snapshot"
                if not reason and kind == "snapshot":
                    try:
                        if inventory(path)[2] != hashes:
                            reason = "changed during snapshot"
                        elif shape[0] == "worktree" and worktree_base(path, shape[1], shape[2]) != base:
                            reason = "HEAD moved during snapshot"
                    except (Skip, OSError) as error:
                        reason = str(error) if isinstance(error, Skip) else f"inspection failed: {error}"
        label = f"{kind}/{scope}"
        if reason:
            if size >= LOG_SKIP_BYTES or reason not in QUIET:
                log(f"skip {label} {reason} {size / 2**30:.2f}G {path}")
            continue
        saved = f" (kept {kept / 2**20:.1f} MB{' as ' + sid if sid else ''})" if kind == "snapshot" else ""
        if dry_run:
            log(f"would delete {label} {size / 2**30:.2f}G {path}{saved}")
        else:
            delete(kind, path, shape)
            log(f"deleted {label} {size / 2**30:.2f}G {path}{saved}")
        freed += size
        deleted += 1
    if not dry_run:
        STATE.write_text(json.dumps(next_state))
    log(f"done: {deleted} paths, {'would free' if dry_run else 'freed'} {freed / 2**30:.2f}G")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restore", nargs=2, metavar=("SNAPSHOT", "DEST"))
    args = parser.parse_args()
    if args.restore:
        return restore(*args.restore)
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
