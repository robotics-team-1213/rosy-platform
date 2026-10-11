"""The absorbed distribution preserves import identity across semantic holders."""

from pathlib import Path, PurePosixPath
import csv
import shutil
import subprocess
import sys
import tarfile
import zipfile


PACKAGE = Path(__file__).resolve().parents[1]
MIDDLEWARE = PACKAGE.parent
SOURCE_MODULES = {
    "sensors/sensing/lidar.py": "control.sensing.lidar",
    "vision/perception/lane.py": "control.sensing.perception.lane",
    "../control/drive/safety/command_gate.py": "control.control.command_gate",
    "../control/drive/recovery/recover.py": "control.control.recover",
    "../control/drive/tracking/path_follow.py": "control.control.path_follow",
    "../control/drive/calibration/calibration.py": "control.control.calibration",
    "../control/drive/planning/grid/goals.py": "control.planning.goals",
    "../control/drive/safety/adapter/gate.py": "control.safety.gate",
    "../control/drive/tracking/wander/motion.py": "control.wander.motion",
}


def _run(*args, cwd):
    result = subprocess.run([sys.executable, *args], cwd=cwd,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr


def test_sensor_and_drive_sources_have_distinct_semantic_holders():
    for relative in SOURCE_MODULES:
        assert (PACKAGE / relative).is_file(), relative
    assert not (PACKAGE / "control/sensing/lidar.py").exists()
    assert not (PACKAGE / "control/control/command_gate.py").exists()


def test_ros_source_audit_includes_moved_adapter_once(tmp_path):
    output = tmp_path / "endpoints.csv"
    _run(str(PACKAGE / "tools/audit_ros_names.py"), "--output", str(output), cwd=tmp_path)
    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert any(row["source"] == "middleware/control/drive/safety/adapter/node.py"
               for row in rows)
    keys = [(row["source"], row["line"], row["kind"], row["expression"]) for row in rows]
    assert len(keys) == len(set(keys))


def test_sdist_alone_builds_one_installed_copy_with_provider_identity(tmp_path):
    # Copy only this distribution and its declared Drive sources, not the repo.
    test_sensor_and_drive_sources_have_distinct_semantic_holders()
    source = tmp_path / "source/middleware/perception"
    shutil.copytree(PACKAGE, source, ignore=shutil.ignore_patterns(
        "__pycache__", "*.egg-info", "build", "dist"))
    for relative in ("safety", "recovery", "tracking", "calibration", "planning/grid", "runtime"):
        shutil.copytree(MIDDLEWARE / "control/drive" / relative,
                        source.parent / "control/drive" / relative)
    dist = tmp_path / "dist"
    _run("setup.py", "sdist", "--dist-dir", str(dist), cwd=source)
    with tarfile.open(next(dist.glob("*.tar.gz"))) as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and ".." not in path.parts
            assert not member.issym() and not member.islnk()
        archive.extractall(tmp_path / "unpacked", filter="data")
    unpacked = next((tmp_path / "unpacked").iterdir())
    _run("setup.py", "bdist_wheel", "--dist-dir", str(dist), cwd=unpacked)
    installed = tmp_path / "installed"
    with zipfile.ZipFile(next(dist.glob("*.whl"))) as wheel:
        names = wheel.namelist()
        for module in SOURCE_MODULES.values():
            assert names.count(module.replace(".", "/") + ".py") == 1
        for name in ('control_node', 'goal_node', 'wander_node', 'safety_node'):
            assert names.count('control/' + name + '.py') == 1
            assert not (PACKAGE / 'control' / (name + '.py')).exists()
        for group in ("safety", "recovery", "tracking", "calibration"):
            for path in (MIDDLEWARE / "control/drive" / group).glob("*.py"):
                assert names.count("control/control/" + path.name) == 1
                assert sum(name.startswith("control/control/") and name.endswith("/" + path.name)
                           for name in names) == 1
        stl = "map/map_v2_fleet/260919 MAP FILE.STL"
        archived_stl = [name for name in names if name.endswith("/share/control/" + stl)]
        assert len(archived_stl) == 1
        assert wheel.read(archived_stl[0]) == (PACKAGE / stl).read_bytes()
        assert not any("_source_roots" in name for name in names)
        wheel.extractall(installed)
    check = (
        "import importlib, importlib.metadata, pathlib, sys; "
        "sys.path[:0] = sys.argv[1:3]; "
        "from control.control.command_gate import CommandPolicy; "
        "from control.sensor_provider import PROVIDER; "
        "assert type(PROVIDER.make_policy('layout-test')) is CommandPolicy; "
        "entries = importlib.metadata.distribution('control').entry_points; "
        "assert any(e.group == 'rosy.sensor_provider' and "
        "e.value == 'control.sensor_provider:PROVIDER' for e in entries); "
        "root = pathlib.Path(sys.argv[1]).resolve(); "
        "modules = ['control.sensing.lidar', 'control.sensing.perception.lane', "
        "'control.control.recover', 'control.planning.goals']; "
        "assert all(pathlib.Path(importlib.import_module(m).__file__).resolve()"
        ".is_relative_to(root) for m in modules)"
    )
    foundation = MIDDLEWARE.parent / "contracts/foundation"
    _run("-I", "-c", check, str(installed), str(foundation), cwd=tmp_path)
