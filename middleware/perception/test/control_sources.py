"""Canonical source files keyed by the preserved ``control`` package paths."""

from pathlib import Path
from runpy import run_path


_layout = run_path(str(Path(__file__).resolve().parents[1] / "control/_source_layout.py"))
FLAT_ROOTS, PACKAGE_DIRS, PACKAGE_ROOT = (
    _layout[name] for name in ("FLAT_ROOTS", "PACKAGE_DIRS", "PACKAGE_ROOT"))


def control_sources():
    root = PACKAGE_ROOT / "control"
    sources = {path.relative_to(root).as_posix(): path
               for path in root.rglob("*.py")}
    for folder in _layout['CONTROL_ROOTS']:
        for path in folder.glob('*.py'):
            assert path.name not in sources, path.name
            sources[path.name] = path
    for namespace, folder in PACKAGE_DIRS.items():
        prefix = namespace.removeprefix("control.").replace(".", "/")
        for path in folder.rglob("*.py"):
            sources[prefix + "/" + path.relative_to(folder).as_posix()] = path
    for folder in FLAT_ROOTS:
        for path in folder.glob("*.py"):
            relative = "control/" + path.name
            assert relative not in sources, relative
            sources[relative] = path
    return sorted(sources.items())


def source_path(relative):
    return dict(control_sources())[str(relative).replace("\\", "/")]
