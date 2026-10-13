"""The absorbed distribution preserves import identity across semantic holders."""

from pathlib import Path, PurePosixPath
import csv
import importlib
import shutil
import subprocess
import sys
import tarfile
import zipfile
import xml.etree.ElementTree as ET


PACKAGE = Path(__file__).resolve().parents[1]
MIDDLEWARE = PACKAGE.parent
SOURCE_MODULES = {
    "localization/loc_assist.py": "control.loc_assist",
    "localization/loc_assist_node.py": "control.loc_assist_node",
    "localization/localization_node.py": "control.localization_node",
    "graph_health/watch.py": "control.watch",
    "graph_health/watch_node.py": "control.watch_node",
    "vision/object_observation/object_detector.py": "control.object_detector",
    "vision/object_observation/object_detector_node.py": "control.object_detector_node",
    "sensors/line_observation/ir_overlay.py": "control.ir_overlay",
    "sensors/line_observation/core_law_input.py": "control.core_law_input",
    "sensors/line_observation/route_context_input.py": "control.route_context_input",
    "sensors/line_observation/route_followers.py": "control.route_followers",
    "sensors/line_observation/line_observer_node.py": "control.line_observer_node",
    "snapshots/capture_trigger.py": "control.capture_trigger",
    "snapshots/capture_trigger_node.py": "control.capture_trigger_node",
    "sensors/sensing/lidar.py": "control.sensing.lidar",
    "vision/perception/lane.py": "control.sensing.perception.lane",
    "vision/perception/learned/road_observation.py": "control.sensing.perception.learned.road_observation",
    "../drive/safety/command_gate.py": "control.control.command_gate",
    "../drive/recovery/recover.py": "control.control.recover",
    "../drive/tracking/path_follow.py": "control.control.path_follow",
    "../drive/calibration/calibration.py": "control.control.calibration",
    "../drive/planning/grid/goals.py": "control.planning.goals",
    "../drive/safety/adapter/gate.py": "control.safety.gate",
    "../drive/tracking/wander/motion.py": "control.wander.motion",
}


def test_judgment_imports_resolve_to_one_canonical_source():
    for relative, module in SOURCE_MODULES.items():
        if module.count('.') != 1:
            continue
        assert not (PACKAGE / 'control' / Path(relative).name).exists()
        if module.endswith('_node'):
            continue
        loaded = importlib.import_module(module)
        assert Path(loaded.__file__).resolve() == (PACKAGE / relative).resolve()
        assert loaded is importlib.import_module(module)


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
    assert any(row["source"] == "middleware/drive/safety/adapter/node.py"
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
        shutil.copytree(MIDDLEWARE / "drive" / relative,
                        source.parent / "drive" / relative)
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
        for relative, module in SOURCE_MODULES.items():
            assert wheel.read(module.replace('.', '/') + '.py') == (PACKAGE / relative).read_bytes()
        for name in ('control_node', 'goal_node', 'wander_node', 'safety_node'):
            assert names.count('control/' + name + '.py') == 1
            assert not (PACKAGE / 'control' / (name + '.py')).exists()
        for group in ("safety", "recovery", "tracking", "calibration"):
            for path in (MIDDLEWARE / "drive" / group).glob("*.py"):
                assert names.count("control/control/" + path.name) == 1
                assert sum(name.startswith("control/control/") and name.endswith("/" + path.name)
                           for name in names) == 1
        stl = "map/map_v2_fleet/260919 MAP FILE.STL"
        archived_stl = [name for name in names if name.endswith("/share/control/" + stl)]
        assert len(archived_stl) == 1
        assert wheel.read(archived_stl[0]) == (PACKAGE / stl).read_bytes()
        assert not any("_source_roots" in name for name in names)
        package_xml = ET.fromstring(wheel.read(next(name for name in names
                                                   if name.endswith("/share/control/package.xml"))))
        assert package_xml.findtext("version") == "0.1.1"
        assert next(d for d in package_xml.findall("exec_depend")
                    if d.text == "core_common").get("version_gte") == "0.0.1"
        wheel.extractall(installed)
    check = (
        "import importlib, importlib.metadata, pathlib, sys; "
        "sys.path[:0] = sys.argv[1:3]; "
        "from control.control.command_gate import CommandPolicy; "
        "from control.sensor_provider import PROVIDER; "
        "policy = PROVIDER.make_policy('layout-test'); "
        "assert type(policy) is CommandPolicy, ('provider identity', type(policy), CommandPolicy); "
        "entries = importlib.metadata.distribution('control').entry_points; "
        "assert any(e.group == 'rosy.sensor_provider' and "
        "e.value == 'control.sensor_provider:PROVIDER' for e in entries), ('provider entry point', entries); "
        "root = pathlib.Path(sys.argv[1]).resolve(); "
        "modules = ['control.sensing.lidar', 'control.sensing.perception.lane', "
        "'control.loc_assist', 'control.watch', 'control.object_detector', "
        "'control.ir_overlay', 'control.core_law_input', 'control.route_context_input', "
        "'control.route_followers', 'control.capture_trigger', "
        "'control.control.recover', 'control.planning.goals', "
        "'control.sensing.perception.learned.road_observation', 'core_common.observation']; "
        "paths = {m: pathlib.Path(importlib.import_module(m).__file__).resolve() for m in modules}; "
        "assert all(path.is_relative_to(root) for path in paths.values()), ('installed source roots', root, paths)"
    )
    foundation = tmp_path / "foundation"
    shutil.copytree(MIDDLEWARE.parent / "contracts/foundation", foundation,
                    ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build", "dist"))
    _run("-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(dist),
         str(foundation), cwd=tmp_path)
    _run("-m", "pip", "install", "--no-deps", "--no-index", "--target", str(installed),
         str(next(dist.glob("core_common-*.whl"))), cwd=tmp_path)
    check += (
        "; import importlib.metadata as metadata; "
        "from packaging.requirements import Requirement; "
        "from packaging.utils import canonicalize_name; "
        "assert metadata.version('control') == '0.1.1', ('control version', metadata.version('control')); "
        "assert metadata.version('core_common') == '0.0.2', ('foundation version', metadata.version('core_common')); "
        "requirements = [Requirement(raw) for raw in metadata.requires('control')]; "
        "expected = Requirement('core_common>=0.0.1'); "
        "assert any(canonicalize_name(r.name) == canonicalize_name(expected.name) "
        "and r.specifier == expected.specifier and not r.extras and r.marker is None "
        "and r.url is None for r in requirements), ('control requirements', requirements)"
    )
    _run("-I", "-c", check, str(installed), str(installed), cwd=tmp_path)
