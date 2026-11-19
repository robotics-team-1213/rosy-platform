"""Bootstrap or configure a fast blobless partial clone of rosy-platform (D-1052)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_URL = "https://github.com/robotics-team-1213/rosy-platform.git"
FAST_GIT_CONFIG = {
    "core.fsmonitor": "true",
    "core.untrackedCache": "true",
    "feature.manyFiles": "true",
    "fetch.prune": "true",
    "remote.origin.tagOpt": "--no-tags",
    "fetch.negotiationAlgorithm": "skipping",
    "fetch.writeCommitGraph": "true",
    "rosy.staticPrePush": "true",
}
GRAPHIFY_HOOKS = ("post-merge", "post-checkout", "post-commit")


def _git(cwd: Path | None, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    res = subprocess.run(["git", *(["-C", str(cwd)] if cwd else []), *args],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and res.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed ({res.returncode}): {(res.stderr or res.stdout).strip()}")
    return res


def configure_clone(repo: Path) -> Path:
    """Apply fast git settings, unset publishOnly/graphify, install static pre-push hook."""
    for key, value in FAST_GIT_CONFIG.items():
        _git(repo, "config", key, value)
    for key in ("rosy.publishOnly", "merge.graphify.driver", "merge.graphify.name"):
        _git(repo, "config", "--unset-all", key, check=False)

    git_dir = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-dir").stdout.strip())
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    for name in GRAPHIFY_HOOKS:
        hp = hooks_dir / name
        if hp.is_file() and "graphify" in hp.read_text(encoding="utf-8", errors="replace").lower():
            hp.unlink()
    src_hook = repo / "tools" / "hooks" / "pre-push"
    if src_hook.is_file():
        dst = hooks_dir / "pre-push"
        shutil.copyfile(src_hook, dst)
        dst.chmod(0o755)
    if _git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0:
        _git(repo, "commit-graph", "write", "--reachable", "--changed-paths", check=False)
    return repo


def bootstrap_fast_clone(target: Path, repo_url: str = DEFAULT_URL, *, configure_only: bool = False) -> Path:
    target = target.resolve()
    if not configure_only and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        _git(None, "clone", "--filter=blob:none", "--no-tags", repo_url, str(target))
    return configure_clone(target)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("target_dir", type=Path)
    p.add_argument("--repo-url", default=DEFAULT_URL)
    p.add_argument("--configure-only", action="store_true")
    args = p.parse_args(argv)
    out = bootstrap_fast_clone(args.target_dir, repo_url=args.repo_url, configure_only=args.configure_only)
    print(f"[setup-fast-clone] ready: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
