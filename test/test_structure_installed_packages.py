"""Build/install moved source packages without importing a robot runtime or opening hardware."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("source,package,modules,entrypoints,config", [
    ("middleware/core/gateway", "core", ["core", "core.drive", "core.system", "core.drive.traffic", "core.system.power",
                                         "core_common.protocol.native", "core_common.protocol.native.operation",
                                         "core_common.protocol.native.receipts", "core_features.navigation"],
     {"core": "core.main:main"}, None),
    ("middleware/core/api", "core_api_web", ["core_api_web"], {}, None),
    ("middleware/devices/pinky/bringup", "bringup", ["bringup"],
     {"bringup": "bringup.bringup:main", "battery_publisher": "bringup.battery_publisher:main",
      "dynamixel_probe": "bringup.dynamixel_probe:main"}, "rosy_params.yaml"),
    ("middleware/devices/omx/adapter", "omx_adapter", ["omx_adapter"],
     {"omx-profile-check": "omx_adapter.cli:main"}, "omx_f_kinematics.yaml"),
])
def test_source_holder_builds_and_installs_the_original_package(
        tmp_path, source, package, modules, entrypoints, config):
    copied = tmp_path / "source"
    shutil.copytree(ROOT / source, copied,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    wheels, installed = tmp_path / "wheels", tmp_path / "installed"
    sources = [copied]
    if package == "core":
        for dependency in ("contracts/foundation", "middleware/core/events", "middleware/core/services"):
            target = tmp_path / 'dependencies' / dependency
            shutil.copytree(ROOT / dependency, target,
                            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            sources.append(target)
        shutil.copytree(ROOT / 'middleware/control/drive/behaviors',
                        tmp_path / 'dependencies/middleware/control/drive/behaviors',
                        ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
    for operation in ("wheel", "install"):
        args = (["wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(wheels), *map(str, sources)]
                if operation == "wheel" else
                ["install", "--no-deps", "--no-index", "--target", str(installed),
                 *map(str, wheels.glob("*.whl"))])
        result = subprocess.run([sys.executable, "-m", "pip", "--disable-pip-version-check", *args],
                                cwd=tmp_path, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
    probe = subprocess.run([sys.executable, "-I", "-c", """
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys
target, package, modules = sys.argv[1:]
sys.path.insert(0, target)
dist = importlib.metadata.distribution(package)
assert Path(dist.locate_file('')).resolve() == Path(target).resolve()
for name in json.loads(modules):
    loaded = importlib.import_module(name)
    assert Path(loaded.__file__).resolve().is_relative_to(Path(target).resolve())
if package == 'core':
    from core_common.protocol.native.operation import NativeOperation
    from core_common.protocol.native_operation import NativeOperation as LegacyNativeOperation
    from core_common.protocol.native.receipts import NativeReceipts
    from core_common.protocol.native_receipts import NativeReceipts as LegacyNativeReceipts
    assert NativeOperation is LegacyNativeOperation
    assert NativeReceipts is LegacyNativeReceipts
print(json.dumps({e.name: e.value for e in dist.entry_points if e.group == 'console_scripts'}))
""", str(installed), package, json.dumps(modules)], cwd=tmp_path,
        capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert json.loads(probe.stdout) == entrypoints
    assert (installed / "share/ament_index/resource_index/packages" / package).is_file()
    assert (installed / "share" / package / "package.xml").is_file()
    if config:
        assert (installed / "share" / package / "config" / config).is_file()
