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
        shutil.copytree(ROOT / 'middleware/drive/behaviors',
                        tmp_path / 'dependencies/middleware/drive/behaviors',
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
    if package == "omx_adapter":
        _check_omx_installed_values(installed, tmp_path)


# Explicit compatibility surface, including private helpers used by old imports.
_OMX_VALUE_FAMILIES = {
    "profile": ("adapter_profile", "_ALIASES _KNOWN_MODELS _DEFAULT_JOINTS "
                "_finite_positive _normalize_model _joints _frame OmxAdapterProfile"),
    "ros_goal_contract": ("ros_goal_contract", "RosGoalEventKind _KINDS _GOAL_BOUND_KINDS "
                          "canonical_ros_goal_id RosGoalEvent"),
    "watchdog_observation": ("watchdog_observation", "_number _count JointIntakeObservation "
                            "intake_observation WatchdogObservation watchdog_observation"),
    "hardware_profile": ("hardware_profile", "_fields _number _vector _range "
                         "validate_profile _UniqueLoader"),
    "kinematics": ("kinematic_types", "ARM_JOINTS IK_OK IK_OUTSIDE_WORKSPACE IK_SINGULAR "
                   "IK_UNREACHABLE IK_JOINT_LIMIT IK_YAW_LIMIT Matrix _finite _triple "
                   "ChainJoint TopDownPose TcpPose IkLimits IkResult"),
}

# These programs run only in isolated children against installed/exported files.
# Canonical imports stay here, so the pre-move baseline collects normally.
_OMX_PROBE_SETUP = """
import importlib
import importlib.abc
import json
from pathlib import Path
import sys

target = Path(sys.argv[1]).resolve()
repository = Path(sys.argv[2]).resolve()
families = json.loads(sys.argv[3])
assert not any(Path(entry).resolve().is_relative_to(repository) for entry in sys.path if entry)
sys.path.insert(0, str(target))

class NoRobotRuntime(importlib.abc.MetaPathFinder):
    canonical_only = False

    def find_spec(self, fullname, path=None, target=None):
        assert fullname.split('.')[0] not in {'serial', 'dynamixel_sdk', 'lerobot', 'rclpy',
                                             'guarded_native'}, fullname
        if self.canonical_only and fullname.startswith('omx_adapter.'):
            # Existing package __init__ bootstraps these legacy modules.
            bootstrap = {'omx_adapter.profile', 'omx_adapter.command_owner',
                         'omx_adapter.final_state', 'omx_adapter.manipulation_plan',
                         'omx_adapter.watchdog_observation'}
            assert (fullname in bootstrap or
                    fullname.startswith('omx_adapter.contracts')), fullname

guard = NoRobotRuntime()
sys.meta_path.insert(0, guard)

def local_module(name):
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(target), name
    return module

def assert_aliases(old, new, names):
    for name in names.split():
        assert getattr(old, name) is getattr(new, name), (old.__name__, name)
"""

_OMX_IDENTITY_AND_GEOMETRY = """
import builtins
import inspect
import pickle
from types import ModuleType

canonical_first = sys.argv[4] == 'canonical-first'
guard.canonical_only = canonical_first
for legacy, (canonical, names) in families.items():
    first = 'omx_adapter.contracts.' + canonical if canonical_first else 'omx_adapter.' + legacy
    local_module(first)
guard.canonical_only = False
for legacy, (canonical, names) in families.items():
    old = local_module('omx_adapter.' + legacy)
    new = local_module('omx_adapter.contracts.' + canonical)
    assert_aliases(old, new, names)
    for name in names.split():
        value = getattr(new, name)
        if inspect.isfunction(value) or inspect.isclass(value):
            assert value.__module__ == new.__name__, name
            old_global = ('c' + old.__name__ + '\\n' + name + '\\n.').encode('ascii')
            assert pickle.loads(old_global) is value, name

kin = local_module('omx_adapter.kinematics')
pose = kin.TopDownPose(0.1, 0.2, 0.3, 0.4)
assert pickle.loads(pickle.dumps(pose)) == pose
asset = target / 'share/omx_adapter/config/omx_f_kinematics.yaml'
assert asset.is_file()
expected_revision = kin.OmxKinematics.load(asset).revision
opened = []
def record_open(path, *args, **kwargs):
    opened.append(Path(path).resolve())
    return builtins.open(path, *args, **kwargs)
kin.open = record_open
kin.DEFAULT_KINEMATICS_PATH = Path.cwd() / 'missing-source-geometry.yaml'
sys.prefix = str(target)
assert kin.OmxKinematics.load().revision == expected_revision
assert opened == [asset]

# Ament fallback still resolves the actual installed share asset.
sys.prefix = str(Path.cwd() / 'empty-prefix')
calls = []
ament = ModuleType('ament_index_python')
packages = ModuleType('ament_index_python.packages')
packages.PackageNotFoundError = type('PackageNotFoundError', (LookupError,), {})
def share_directory(name):
    calls.append(name)
    return str(target / 'share' / name)
packages.get_package_share_directory = share_directory
ament.packages = packages
sys.modules['ament_index_python'] = ament
sys.modules['ament_index_python.packages'] = packages
opened.clear()
assert kin.OmxKinematics.load().revision == expected_revision
assert calls == ['omx_adapter'] and opened == [asset]

# An explicit missing path must not fall back to that available asset.
calls.clear()
try:
    kin.OmxKinematics.load(Path.cwd() / 'explicit-missing.yaml')
except FileNotFoundError:
    pass
else:
    raise AssertionError('explicit missing geometry silently fell back')
assert calls == []
sys.modules['ament_index_python'] = None
sys.modules['ament_index_python.packages'] = None
try:
    kin.OmxKinematics.load()
except FileNotFoundError:
    pass
else:
    raise AssertionError('missing installed geometry silently fell back')
print('installed value identities and geometry ok')
"""

_OMX_CLI = """
from contextlib import redirect_stdout
import importlib.metadata
import io
import runpy

disabled, valid_hardware = sys.argv[4:6]
entry = next(e for e in importlib.metadata.distribution('omx_adapter').entry_points
             if e.group == 'console_scripts' and e.name == 'omx-profile-check')
cli = local_module('omx_adapter.cli')
assert entry.load() is cli.main
for invoke in (lambda: entry.load()([disabled]),
               lambda: runpy.run_module('omx_adapter.cli', run_name='__main__')):
    sys.argv = ['omx-profile-check', disabled]
    output = io.StringIO()
    with redirect_stdout(output):
        try:
            code = invoke()
        except SystemExit as exc:
            code = exc.code
    assert code == 0 and json.loads(output.getvalue()) == {}

hardware = local_module('omx_adapter.hardware_profile')
duplicate = Path.cwd() / 'duplicate-profile.yaml'
duplicate.write_text('profile: hardware\\nprofile: hardware\\n', encoding='utf-8')
for path in (Path(valid_hardware), Path.cwd() / 'missing-profile.yaml', duplicate):
    for invoke in (lambda: hardware.main([str(path)]),
                   lambda: runpy.run_module('omx_adapter.hardware_profile', run_name='__main__')):
        sys.argv = ['omx_adapter.hardware_profile', str(path)]
        output = io.StringIO()
        with redirect_stdout(output):
            try:
                code = invoke()
            except SystemExit as exc:
                code = exc.code
        report = json.loads(output.getvalue())
        assert report['motion_admitted'] is False
        if path == Path(valid_hardware):
            assert code == 0 and report['profile_document_valid'] is True
            assert report['joint_names'] == [f'joint{i}' for i in range(1, 6)]
            assert 'independent_stop' in report['unverified']
        else:
            assert code == 2 and report['profile_document_valid'] is False
            assert report['error']
        if path == duplicate:
            assert 'unique string keys' in report['error']
print('installed CLI entry paths ok')
"""


def _check_omx_installed_values(installed, tmp_path):
    for order in ('canonical-first', 'legacy-first'):
        probe = subprocess.run(
            [sys.executable, '-I', '-c', _OMX_PROBE_SETUP + _OMX_IDENTITY_AND_GEOMETRY,
             str(installed), str(ROOT), json.dumps(_OMX_VALUE_FAMILIES), order],
            cwd=tmp_path, capture_output=True, text=True, timeout=30)
        assert probe.returncode == 0, order + '\n' + probe.stdout + probe.stderr
    disabled = tmp_path / 'omx.disabled.yaml'
    shutil.copy2(ROOT / 'middleware/devices/omx/profile/config/omx.disabled.yaml', disabled)
    # Serialize shared synthetic input in the parent; the child imports installed code only.
    data = json.loads((ROOT / 'middleware/devices/omx/adapter/test/fixtures/'
                      'synthetic_hardware_profile.json').read_text(encoding='utf-8'))
    hardware = tmp_path / 'hardware-profile.json'
    hardware.write_text(json.dumps(data), encoding='utf-8')
    probe = subprocess.run(
        [sys.executable, '-I', '-c', _OMX_PROBE_SETUP + _OMX_CLI,
         str(installed), str(ROOT), json.dumps(_OMX_VALUE_FAMILIES), str(disabled), str(hardware)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, probe.stdout + probe.stderr


def test_omx_updater_selected_files_close_over_value_contracts(tmp_path):
    # Reuse the updater's declared export and smoke; never fill missing dependencies here.
    config = json.loads((ROOT / 'deploy/robot/omx/omx-devices-autoupdate.json.example').read_text())
    stage = tmp_path / 'native-release'
    stage.mkdir()
    source_paths = config['paths']
    for relative in source_paths:
        source, destination = ROOT / relative, stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(source, destination)
    adapter = 'middleware/devices/omx/adapter/omx_adapter'
    selected = {
        legacy: family for legacy, family in _OMX_VALUE_FAMILIES.items()
        if any(Path(f'{adapter}/{legacy}.py').is_relative_to(Path(relative))
               for relative in source_paths)
    }
    script = _OMX_PROBE_SETUP + """
# Only directories under the selected export are made importable.
sys.path[:0] = [str(target / relative) for relative in (
    'deploy/robot/omx', 'contracts/foundation', 'operations/overhead',
    'middleware/devices/omx/adapter')]
exec(sys.argv[4])
checked = []
for legacy, (canonical, names) in families.items():
    old = local_module('omx_adapter.' + legacy)
    new = local_module('omx_adapter.contracts.' + canonical)
    assert_aliases(old, new, names)
    checked.append(legacy)
assert sorted(checked) == sorted(families)
for name in ('hardware_observer', 'register_probe', 'passive_motor_health',
             'workcell_observation_bridge', 'camera_readiness', 'commissioning_view',
             'camera_source', 'omx_autoupdate'):
    assert Path(sys.modules[name].__file__).resolve().is_relative_to(target), name
print(json.dumps({'checked_value_families': sorted(checked)}))
"""
    probe = subprocess.run(
        [sys.executable, '-I', '-c', script, str(stage), str(ROOT),
         json.dumps(selected), config['smoke']], cwd=stage,
        capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert json.loads(probe.stdout.splitlines()[-1]) == {'checked_value_families': sorted(selected)}
