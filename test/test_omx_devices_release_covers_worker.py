"""2026-11-21: the omx-devices release (the paths of omx-devices-autoupdate.json) must hold every repo module the cell
task worker and its arm session wrappers import; the live release missed omx_adapter.kinematics, area_xyz, z_profile
and pose_plan, so the worker would have failed after its move onto that release."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy/robot/omx"
# the worker unit's PYTHONPATH and the wrappers' tools-env.sh (search order)
SEARCH = [ROOT, OMX, ROOT / "middleware/devices/omx/adapter", ROOT / "operations/overhead", ROOT / "contracts/foundation"]
# the worker, its executor, and what the session wrappers run: cell_auto_pick (worker argv) and record_session (wrapper)
ENTRIES = [OMX / n for n in ("cell_task_worker.py", "cell_task_exec.py", "cell_auto_pick.py", "record_session.py")]


def _resolve(name: str) -> list[Path]:
    """The repo files that importing `name` loads (each package __init__ on the way), or [] for a third-party module."""
    parts = name.split(".")
    for base in SEARCH:
        files, here = [], base
        for i, part in enumerate(parts):
            here = here / part
            last = i == len(parts) - 1
            if (here / "__init__.py").is_file():
                files.append(here / "__init__.py")
            elif last and here.with_suffix(".py").is_file():
                files.append(here.with_suffix(".py"))
            elif not (here.is_dir() and not last):  # namespace dirs pass through; anything else is not this base
                files = []
                break
        if files:
            return files
    return []


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    package = path.parent
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):  # function-local imports too
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package
                for _ in range(node.level - 1):
                    base = base.parent
                for root in SEARCH:
                    if base.is_relative_to(root):
                        prefix = ".".join(base.relative_to(root).parts)
                        break
                else:
                    continue
                mod = ".".join(p for p in (prefix, node.module or "") if p)
            else:
                mod = node.module or ""
            names.add(mod)
            names.update(f"{mod}.{a.name}" for a in node.names)  # `from pkg import submodule`
    return {n for n in names if n}


def closure() -> set[Path]:
    seen: set[Path] = set()
    todo = list(ENTRIES)
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in _imports(path):
            todo.extend(f for f in _resolve(name) if f not in seen)
    return seen


def _covered(rel: str, paths: list[str]) -> bool:
    return any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in paths)


def test_the_release_paths_cover_the_worker_import_closure():
    paths = json.loads((OMX / "omx-devices-autoupdate.json.example").read_text(encoding="utf-8"))["paths"]
    files = closure()
    rel = sorted(f.relative_to(ROOT).as_posix() for f in files)
    assert "middleware/devices/omx/adapter/omx_adapter/kinematics.py" in rel  # the walk reaches the adapter at all
    missing = [r for r in rel if not _covered(r, paths)]
    assert not missing, missing
    # the session wrappers and their tools env ship in the same release
    assert _covered("deploy/robot/omx/session-wrappers/tools-env.sh", paths)


def test_the_release_smoke_refuses_a_release_without_the_worker_adapter_modules():
    smoke = json.loads((OMX / "omx-devices-autoupdate.json.example").read_text(encoding="utf-8"))["smoke"]
    assert "from omx_adapter import chunk_library, kinematics, area_xyz, z_profile, pose_plan" in smoke
