"""D-630: current-state projection is installed independently of Fleet."""

import importlib
from pathlib import Path
import shutil
import subprocess
import sys


WORLD = Path(__file__).resolve().parents[1]
REPO = WORLD.parents[1]
PROJECTION = WORLD / "src/rosy/world/state/projections/map_pose.py"


def test_world_projection_and_fleet_consumers_have_one_owner(monkeypatch):
    assert PROJECTION.is_file(), "current-state MapPose implementation belongs to world"
    assert not (REPO / "operations/fleet/fleet/localization/map_pose.py").exists()
    monkeypatch.syspath_prepend(str(WORLD / "src"))
    projection = importlib.import_module("rosy.world.state.projections.map_pose")
    assert projection.MapPoseTracker.__module__ == projection.__name__
    for path in (REPO / "operations/fleet/fleet").rglob("*.py"):
        assert "fleet.localization.map_pose" not in path.read_text(encoding="utf-8"), path


def test_world_wheel_contains_projection_without_fleet(tmp_path):
    assert PROJECTION.is_file(), "the standalone world wheel must ship its projection"
    source = tmp_path / "world"
    shutil.copytree(WORLD, source, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build", "dist"))
    foundation = tmp_path / "foundation"
    shutil.copytree(REPO / "contracts/foundation", foundation,
                    ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build", "dist"))
    wheelhouse, installed = tmp_path / "wheelhouse", tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                    "--wheel-dir", str(wheelhouse), str(source)], check=True, capture_output=True, text=True)
    wheels = list(wheelhouse.glob("rosy_world-*.whl"))
    assert len(wheels) == 1
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                    "--wheel-dir", str(wheelhouse), str(foundation)], check=True, capture_output=True, text=True)
    wheels += list(wheelhouse.glob("core_common-*.whl"))
    assert len(wheels) == 2
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
                    "--target", str(installed), *map(str, wheels)], check=True, capture_output=True, text=True)
    result = subprocess.run([sys.executable, "-I", "-c", """
import pathlib, sys
sys.path.insert(0, sys.argv[1])
import importlib.metadata
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
assert importlib.metadata.version('core_common') == '0.0.2'
requirements = {canonicalize_name(requirement.name): requirement
                for requirement in map(Requirement, importlib.metadata.requires('rosy-world'))}
dependency = requirements['core-common']
assert str(dependency.specifier) == '>=0.0.1'
assert dependency.marker is None and not dependency.extras
from rosy.world.api import ObservationSnapshot
from rosy.world.state.projections import map_pose
from rosy.world.state.projections import physical_transfer
from rosy.world.state.projections import omx_geometry
from rosy.world.state.projections.road_region import road_region_input_errors
from core_common import observation
assert ObservationSnapshot is observation.ObservationSnapshot
assert road_region_input_errors is observation.road_region_input_errors
assert callable(road_region_input_errors)
assert pathlib.Path(map_pose.__file__).is_relative_to(pathlib.Path(sys.argv[1]))
assert map_pose.MapPoseTracker('robot').pose(1800000000.0).state == map_pose.UNKNOWN
assert pathlib.Path(physical_transfer.__file__).is_relative_to(pathlib.Path(sys.argv[1]))
assert physical_transfer.PhysicalPose((1, 2, 3), (0, 0, 0, 1)).position_m == (1., 2., 3.)
assert pathlib.Path(omx_geometry.__file__).is_relative_to(pathlib.Path(sys.argv[1]))
try:
    omx_geometry.load_omx_geometry(b'not the installed model', {})
except ValueError:
    pass
else:
    raise AssertionError('unreviewed model accepted')
assert not any(name == 'fleet' or name.startswith('fleet.') for name in sys.modules)
assert not any(name == 'omx_adapter' or name.startswith('omx_adapter.') for name in sys.modules)
""", str(installed)], check=True, capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0
