"""Build and query external Graphify snapshots of code and optional document links."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from graphify_documents import augment


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], encoding="utf-8").strip()


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def selection_rules(repo: Path, scope: Path) -> dict:
    paths = set()
    directory = scope
    while True:
        paths.update(directory / name for name in (".gitignore", ".graphifyignore"))
        if directory == repo:
            break
        directory = directory.parent
    paths.add(Path(git(repo, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")))
    config = subprocess.run(["git", "-C", str(repo), "config", "--path", "--get", "core.excludesfile"],
                            capture_output=True, text=True, encoding="utf-8")
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or ".")
    default = (xdg if xdg.is_absolute() else Path.home() / ".config") / "git/ignore"
    configured = config.stdout.strip() if config.returncode == 0 else ""
    global_path = Path(configured).expanduser() if configured else default
    paths.add(global_path if global_path.is_absolute() else repo / global_path)
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            for path in sorted(paths)}


def snapshot(repo: Path, scope: Path) -> dict:
    paths = subprocess.check_output(
        ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others",
         "--exclude-standard", "--", scope.relative_to(repo).as_posix()]
    ).decode("utf-8").split("\0")
    hashes = {}
    for name in sorted(set(paths) - {""}):
        path = repo / name
        # Git enumerates nested checkouts as directories, while Graphify reads their untracked contents.
        if path.is_dir():
            raise ValueError(f"Nested checkout or directory link must be analyzed separately: {name}")
        if path.is_file():
            if not path.resolve().is_relative_to(scope):
                raise ValueError(f"Source link escapes scope: {name}")
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"commit": git(repo, "rev-parse", "HEAD"), "files": hashes,
            "selection_rules": selection_rules(repo, scope)}


def executable() -> str:
    binary = shutil.which("graphify")
    if not binary:
        candidate = Path.home() / ".local/bin" / ("graphify.exe" if os.name == "nt" else "graphify")
        binary = str(candidate) if candidate.is_file() else None
    if not binary:
        raise ValueError("Install first: python -m uv tool install graphifyy==0.9.91")
    return binary


def output_base() -> Path:
    if os.environ.get("DEV_SESSION"):
        return Path(os.environ["DEV_SESSION"]) / "scratch/graphify"
    cache = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_CACHE_HOME")
    return (Path(cache) if cache else Path.home() / ".cache") / "ROSY/analysis/graphify"


def run(binary: str, args: list[str], folder: Path, name: str, env: dict) -> None:
    print(f"[{name}]", flush=True)
    with (folder / f"{name}.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([binary, *args], stdout=log, stderr=subprocess.STDOUT,
                                env=env, cwd=folder)
    if result.returncode:
        raise RuntimeError(f"{name} failed ({result.returncode}); see {folder / (name + '.log')}")


def build(args: argparse.Namespace) -> None:
    tool_repo = Path(__file__).resolve().parents[1]
    repo = Path(getattr(args, "repository", None) or tool_repo).expanduser().resolve()
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise ValueError("Repository must be a Git checkout root")
    scope = (repo / args.scope).resolve()
    if (not scope.is_dir() or not scope.is_relative_to(repo)
            or {".git", ".worktrees"}.intersection(scope.relative_to(repo).parts)):
        raise ValueError("Source scope must be inside the repository, outside Git metadata/worktrees")
    base = (args.output or output_base()).expanduser().resolve()
    for root in (repo, tool_repo):
        common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).parent
        if base.is_relative_to(common) or base.is_relative_to(root):
            raise ValueError("Output must be outside the repository and its worktrees (source and tool)")
    binary = executable()
    before = snapshot(repo, scope)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = base / f"{scope.name}-{stamp}-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=False)
    print(f"Run: {folder}", flush=True)
    env = {**os.environ, "GRAPHIFY_OUT": str(folder / "graphify-out"),
           "PYTHONPYCACHEPREFIX": str(folder / "python-cache"), "PYTHONUTF8": "1"}
    record = {"status": "building", "repository": str(repo), "scope": str(scope),
              "started_utc": stamp, "source": before,
              "mode": "code and explicit document links" if getattr(args, "documents", False) else "code-only",
              "graphify_version": subprocess.check_output([binary, "--version"], env=env, encoding="utf-8").strip()}
    save(folder / "provenance.json", record)
    graph = folder / "graphify-out/graph.json"
    try:
        run(binary, ["extract", str(scope), "--code-only", "--no-cluster", "--max-workers", "4", "--out", str(folder)], folder, "extract", env)
        coverage = {"semantic_inference": False, "multimedia_content_analysis": False}
        if getattr(args, "documents", False):
            data = json.loads(graph.read_text(encoding="utf-8"))
            coverage.update(augment(data, graph.parent, scope))
            save(graph, data)
        coverage["extractor_warnings"] = [line for line in (folder / "extract.log").read_text(encoding="utf-8").splitlines()
                                          if "warning:" in line.lower()]
        save(folder / "coverage.json", coverage)
        run(binary, ["cluster-only", str(scope), "--graph", str(graph), "--no-label", "--no-viz"], folder, "report", env)
        data = json.loads(graph.read_text(encoding="utf-8"))
        edges = data.get("links", data.get("edges", []))
        ids = {node["id"] for node in data["nodes"]}
        health = {"nodes": len(ids), "edges": len(edges), "directed": data.get("directed", False),
                  "dangling_edges": sum(e.get("source") not in ids or e.get("target") not in ids for e in edges),
                  "self_loops": sum(e.get("source") == e.get("target") for e in edges)}
        save(folder / "health.json", health)
        if not ids or health["dangling_edges"]:
            raise RuntimeError("Empty graph or dangling edges; see health.json")
        if len(ids) > 1500:
            print("HTML will aggregate communities; JSON retains all nodes.", flush=True)
        run(binary, ["export", "html", "--graph", str(graph), "--node-limit", "1500"], folder, "html", env)
        run(binary, ["god-nodes", "--graph", str(graph), "--json"], folder, "hubs", env)
        if snapshot(repo, scope) != before:
            raise RuntimeError("Source changed during build; rebuild before using this graph")
        record.update(status="verified", graph_sha256=hashlib.sha256(graph.read_bytes()).hexdigest(),
                      health=health, verification="artifact integrity and CLI smoke only; retrieval quality unmeasured")
    except Exception as exc:
        record.update(status="failed", error=str(exc))
        raise
    finally:
        save(folder / "provenance.json", record)
    print(json.dumps(health), flush=True)
    print(f"Query: python tools/graphify_pipeline.py query --run \"{folder}\" \"<symbol>\"")


def query(args: argparse.Namespace) -> None:
    folder = args.run.expanduser().resolve()
    record = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    if record["status"] != "verified":
        raise ValueError("This build did not finish verification")
    if snapshot(Path(record["repository"]), Path(record["scope"])) != record["source"]:
        raise ValueError("Graph is stale: source revision or files changed; rebuild first")
    graph = folder / "graphify-out/graph.json"
    if hashlib.sha256(graph.read_bytes()).hexdigest() != record["graph_sha256"]:
        raise ValueError("Graph hash changed; rebuild before querying")
    env = {**os.environ, "PYTHONUTF8": "1", "GRAPHIFY_OUT": str(graph.parent),
           "PYTHONPYCACHEPREFIX": str(folder / "python-cache")}
    result = subprocess.run([executable(), "query", args.question, "--graph", str(graph),
                             "--budget", str(args.budget)], env=env, cwd=folder)
    raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--repository", type=Path, help="Source Git checkout root (default: this tool's repository)")
    builder.add_argument("--scope", default="middleware/core")
    builder.add_argument("--documents", action="store_true", help="Include filtered file inventory and explicit local Markdown links")
    builder.add_argument("--output", type=Path, help="External output parent; each build creates a new run")
    reader = commands.add_parser("query")
    reader.add_argument("--run", type=Path, required=True)
    reader.add_argument("--budget", type=int, default=1500)
    reader.add_argument("question", help="Use code symbol names; no automatic Korean synonym expansion")
    args = parser.parse_args()
    try:
        (build if args.command == "build" else query)(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"graphify pipeline: {exc}\n")


if __name__ == "__main__":
    main()
