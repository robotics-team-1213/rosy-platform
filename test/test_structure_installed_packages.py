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
import importlib.abc
import importlib.metadata
import json
from pathlib import Path
import pkgutil
import sys
target, package, modules, repository = sys.argv[1:]
sys.path.insert(0, target)
assert not any(Path(p).resolve().is_relative_to(Path(repository).resolve()) for p in sys.path)
blocked_attempts = []
if package == 'core':
    blocked = {'core_api_web', 'rclpy', 'geometry_msgs', 'nav_msgs', 'nav2_msgs',
               'lifecycle_msgs', 'sensor_msgs', 'std_msgs', 'std_srvs', 'interfaces',
               'tf2_ros', 'slam_toolbox'}

    class NoApiOrRos(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in blocked:
                blocked_attempts.append(fullname)
                raise AssertionError('installed CORE imported forbidden dependency: ' + fullname)

    assert not any(name.split('.')[0] in blocked for name in sys.modules)
    sys.meta_path.insert(0, NoApiOrRos())
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
    import core.system
    # ros_graph is the existing ROS adapter; every other installed owner module is ROS-free.
    for info in pkgutil.walk_packages(core.system.__path__, core.system.__name__ + '.'):
        if info.name == 'core.system.ros_graph':
            continue
        loaded = importlib.import_module(info.name)
        assert Path(loaded.__file__).resolve().is_relative_to(Path(target).resolve())
    # Record attempts too: optional-import exception handlers must not hide a dependency.
    assert not blocked_attempts, blocked_attempts
    assert not any(name.split('.')[0] in blocked for name in sys.modules)
    from datetime import datetime, timedelta, timezone
    import os
    from types import SimpleNamespace
    import core.system.host_files as host_files
    from core.system.host_files import HostFileExchange

    assert Path(host_files.__file__).resolve().is_relative_to(Path(target).resolve())
    owner = HostFileExchange()
    files = Path(target).parent / 'host-file-operations'
    files.mkdir()
    paths = {name: str(files / filename) for name, filename in {
        'result_path': 'hardware.json', 'request_path': 'hw-probe.request',
        'test_request_path': 'hw-test.request', 'test_result_path': 'hw-test.json',
        'confirm_path': 'hw-confirmations.json', 'boot_status_path': 'boot-status.json',
        'status_inputs_path': 'status-inputs.json', 'face_inputs_path': 'face-inputs.json',
    }.items()}
    svc = SimpleNamespace(config={'hardware_probe': paths},
                          state=SimpleNamespace(snapshot=lambda: SimpleNamespace(robot_id='fixture')))
    now = datetime.now(timezone.utc)
    Path(paths['boot_status_path']).write_text(json.dumps({
        'stage': 'CORE_READY', 'failed_unit': None, 'release_id': 'fixture-release'}))
    assert owner.read_boot_status(paths['boot_status_path']) == {
        'stage': 'CORE_READY', 'failed_unit': None, 'release_id': 'fixture-release'}
    assert owner.read_boot_status(str(files / 'absent-boot.json')) is None
    Path(paths['result_path']).write_text(json.dumps({
        'schema': 1, 'boot_id': 'fixture', 'measured_at': now.isoformat(),
        'devices': [{'id': 'buzzer', 'label': 'buzzer', 'bus': 'gpio', 'state': 'ok',
                     'evidence': 'fixture', 'product': True}]}))
    owner.hardware(svc)
    owner.write_status_inputs(svc)
    status = json.loads(Path(paths['status_inputs_path']).read_text())
    assert status['schema'] == 2 and status['robot_id'] == 'fixture'
    assert status['devices'] == [{'id': 'buzzer', 'state': 'ok', 'product': True}]
    paths['status_inputs_path'] = str(files / 'live-config-status.json')
    owner.write_status_inputs(svc)
    assert Path(paths['status_inputs_path']).is_file()

    face_path = Path(paths['face_inputs_path'])
    content = {'schema': 1, 'written_at': now.isoformat(), 'face': 'happy'}
    real_replace, prior_umask = host_files.os.replace, os.umask(0o027)
    modes = []
    fail_replace = [False]

    def replace(source, destination):
        if Path(destination) == face_path:
            modes.append(os.stat(source).st_mode & 0o777)
            if fail_replace[0]:
                raise OSError('replace unavailable')
        return real_replace(source, destination)

    host_files.os.replace = replace
    try:
        owner.write_face_inputs(svc, content)
        assert json.loads(face_path.read_text()) == content
        fail_replace[0] = True
        try:
            owner.write_face_inputs(svc, {**content, 'face': 'sad'})
        except OSError:
            pass
        else:
            raise AssertionError('failed replacement was hidden')
        assert json.loads(face_path.read_text()) == content
        assert not list(files.glob('.face-inputs.*'))
        fail_replace[0] = False
        owner.write_face_inputs(svc, content)
    finally:
        host_files.os.replace = real_replace
        os.umask(prior_umask)
    if os.name == 'posix':
        assert modes == [0o644, 0o644, 0o644]
    assert not list(files.glob('.face-inputs.*'))

    clock = [100.0]
    real_time = host_files.time
    host_files.time = SimpleNamespace(monotonic=lambda: clock[0])
    try:
        owner.refresh_hardware(svc, by='fixture-actor')
        assert json.loads(Path(paths['request_path']).read_text())['by'] == 'fixture-actor'
        owner.test_hardware(svc, device='buzzer', by='fixture-actor')
        request_path = Path(paths['test_request_path'])
        written = request_path.read_bytes()
        request = json.loads(written)
        assert request['action'] == 'buzzer' and request['by'] == 'fixture-actor'
        assert len(request['request_id']) == 16
        try:
            HostFileExchange().identify(svc, color='blue', quiet=True, by='fixture-actor')
        except owner.Error as exc:
            assert exc.code == 'HW_TEST_COOLDOWN'
        else:
            raise AssertionError('a second owner bypassed the process-wide request cooldown')
        assert request_path.read_bytes() == written
        Path(paths['test_result_path']).write_text(json.dumps({
            'schema': 1, 'action': 'buzzer', 'state': 'done', 'detail': 'fixture',
            'request_id': request['request_id'],
            'finished_at': (now - timedelta(seconds=1)).isoformat(timespec='seconds')}))
        owner.confirm_hardware(svc, device='buzzer', observed=True, by='fixture-actor', label='fixture')
        answer = json.loads(Path(paths['confirm_path']).read_text())['devices']['buzzer']
        assert answer['observed'] is True and answer['request_id'] == request['request_id']
        assert answer['by'] == 'fixture-actor' and answer['label'] == 'fixture'
        clock[0] += 10
        owner.identify(svc, color='blue', quiet=True, by='fixture-actor')
        identified = json.loads(request_path.read_text())
        assert identified['action'] == 'identify_blue_quiet'
        owner.identify_result(svc, identified['request_id'])
        Path(paths['test_result_path']).write_text(json.dumps({
            'schema': 1, 'action': 'identify_blue_quiet', 'state': 'done', 'detail': 'fixture',
            'request_id': identified['request_id'], 'finished_at': now.isoformat(timespec='seconds')}))
        owner.identify_result(svc, identified['request_id'])
    finally:
        host_files.time = real_time
    assert not blocked_attempts, blocked_attempts
    assert not any(name.split('.')[0] in blocked for name in sys.modules)
print(json.dumps({e.name: e.value for e in dist.entry_points if e.group == 'console_scripts'}))
""", str(installed), package, json.dumps(modules), str(ROOT)], cwd=tmp_path,
        capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert json.loads(probe.stdout) == entrypoints
    assert (installed / "share/ament_index/resource_index/packages" / package).is_file()
    assert (installed / "share" / package / "package.xml").is_file()
    if config:
        assert (installed / "share" / package / "config" / config).is_file()
