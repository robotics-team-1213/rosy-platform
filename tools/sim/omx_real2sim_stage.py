"""Put a fresh, uncommitted cell snapshot in front of remote_sim without a branch commit.

remote_sim ships commits only. `stage` builds one commit on a temporary index (the omx_hotfix.py pattern): the code SHA's
tree plus exactly the snapshot path, parented on the code SHA, kept alive by refs/rosy-wip/ (never pushed, no branch, no
worktree or shared index touched). The permanent record still lands the snapshot through land.py."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

SNAP_DIR = "deploy/robot/omx/sim/cell_snapshots"


def _git(repo, *args, env=None):
    done = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=False)
    if done.returncode:
        raise SystemExit(f"[r2s-stage] git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def committed(repo, sha, rel, snapshot):
    """True when `sha` already holds `rel` with exactly the snapshot file's bytes (a path that merely exists there proves nothing:
    the remote would run the old blob while the provenance digest named the new file)."""
    listed = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{sha}:{rel}"], cwd=repo, capture_output=True, text=True, check=False)
    return listed.returncode == 0 and listed.stdout.strip() == _git(repo, "hash-object", "--no-filters", "--", str(snapshot))


def stage(repo, code_sha, snapshot, rel=None):
    """-> dict(code_sha, sha, rel, snapshot_sha256): `sha` is the commit to hand to remote_sim."""
    repo, snapshot = Path(repo), Path(snapshot)
    code = _git(repo, "rev-parse", "--verify", f"{code_sha}^{{commit}}")
    rel = rel or f"{SNAP_DIR}/{snapshot.stem if snapshot.name != 'snapshot.json' else snapshot.resolve().parent.name}.json"
    if not rel.startswith(f"{SNAP_DIR}/") or ".." in rel.split("/"):
        raise SystemExit(f"[r2s-stage] {rel} is outside {SNAP_DIR}: a snapshot is the only path a WIP commit may add")
    digest = sha256(snapshot)
    listed = _git(repo, "ls-tree", code, "--", rel)
    with tempfile.TemporaryDirectory(prefix="r2s-stage-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(repo, "read-tree", code, env=env)
        blob = _git(repo, "hash-object", "-w", "--no-filters", "--", str(snapshot))  # raw bytes, as the digest hashes them (no CRLF filter)
        if listed and listed.split()[2] != blob:
            raise SystemExit(f"[r2s-stage] {rel} already exists in {code[:10]} with other bytes: pick another snapshot name")
        _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}", env=env)
        tree = _git(repo, "write-tree", env=env)
    new = _git(repo, "commit-tree", tree, "-p", code, "-m", f"wip: r2s snapshot {rel} sha256 {digest[:16]} on {code[:10]}")
    changed = _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", code, new).splitlines()
    if changed not in ([rel], []):
        raise SystemExit(f"[r2s-stage] refusing: the staged commit differs from {code[:10]} in {changed}")
    _git(repo, "update-ref", f"refs/rosy-wip/r2s-{hashlib.sha256((code + digest).encode()).hexdigest()[:12]}", new)  # code and snapshot: a newer code SHA keeps the older ref
    return dict(code_sha=code, sha=new, rel=rel, snapshot_sha256=digest)


def stage_files(repo, code_sha, files, prefix, tag):
    """-> the commit to hand to remote_sim: `code_sha`'s tree plus `files` ({rel: local Path}), every rel under `prefix`
    (the omx_loop twin stage ships its joined episodes this way). Same temporary index and refs/rosy-wip as `stage`."""
    repo = Path(repo)
    code = _git(repo, "rev-parse", "--verify", f"{code_sha}^{{commit}}")
    with tempfile.TemporaryDirectory(prefix="loop-stage-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(repo, "read-tree", code, env=env)
        for rel, path in sorted(files.items()):
            if not rel.startswith(prefix) or ".." in rel.split("/"):
                raise SystemExit(f"[loop-stage] {rel} is outside {prefix}: only the episodes may ride a WIP commit")
            blob = _git(repo, "hash-object", "-w", "--no-filters", "--", str(path))
            _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}", env=env)
        tree = _git(repo, "write-tree", env=env)
    new = _git(repo, "commit-tree", tree, "-p", code, "-m", f"wip: {tag} on {code[:10]}")
    changed = [c for c in _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", code, new).splitlines() if not c.startswith(prefix)]
    if changed:
        raise SystemExit(f"[loop-stage] refusing: the staged commit differs from {code[:10]} outside {prefix}: {changed}")
    _git(repo, "update-ref", f"refs/rosy-wip/{tag}-{new[:12]}", new)
    return new
