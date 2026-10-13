"""Source holders for the existing absorbed ``control`` import identities."""

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DRIVE_ROOT = (PACKAGE_ROOT / "_source_roots/drive"
              if (PACKAGE_ROOT / "_source_roots/drive").is_dir()
              else PACKAGE_ROOT.parent / "drive")
PACKAGE_DIRS = {
    "control.sensing": PACKAGE_ROOT / "sensors/sensing",
    "control.sensing.perception": PACKAGE_ROOT / "front_camera/perception",
    "control.planning": DRIVE_ROOT / "planning/grid",
    "control.safety": DRIVE_ROOT / "motion_limits/adapter",
    "control.wander": DRIVE_ROOT / "tracking/wander",
}
FLAT_ROOTS = tuple(DRIVE_ROOT / name for name in
                   ("motion_limits", "recovery", "tracking", "calibration"))
RUNTIME_ROOT = DRIVE_ROOT / 'runtime'
CONTROL_ROOTS = (PACKAGE_ROOT / 'nodes', RUNTIME_ROOT, *(PACKAGE_ROOT / name for name in
    ('localization', 'graph_health', 'front_camera/object_observation',
     'sensors/line_observation', 'snapshots')))


def load_source_package(namespace):
    """Source-only facade; installed packages contain the original modules."""
    path = PACKAGE_DIRS[namespace["__name__"]]
    source = path / "__init__.py"
    namespace["__path__"] = [str(path)]
    namespace["__file__"] = str(source)
    exec(compile(source.read_bytes(), str(source), "exec"), namespace)


def extend_policy_path(path):
    if (PACKAGE_ROOT / "package.xml").is_file():
        path.extend(str(folder) for folder in FLAT_ROOTS)
