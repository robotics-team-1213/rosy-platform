"""Serialized canonical configuration updates shared by both OS roots."""
from __future__ import annotations

import contextlib
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid
import yaml

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from os_state_io import _json_atomic
from os_state_firstboot import FirstBootState
from os_state_files import (CONFIG_FILES, INITIAL, POINTER_FIELDS, PUBLICATION, initial_changes,
                            load_record, project_files, validate_projection)
from os_state_layout import COMMON, TLS_PENDING, StateError, _guid, _layout, _path, _read


@contextlib.contextmanager
def common_lock(root: Path):
    root = Path(root).absolute()
    try:
        found = _layout(root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StateError(f"OS_STATE_HOLD: {exc}") from exc
    if found is None:
        yield None
        return
    with contextlib.ExitStack() as cleanup:
        try:
            shared = FirstBootState(root, found[0])
            path = _path(root, COMMON + "/state/config.lock")
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            cleanup.callback(os.close, descriptor)
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise ValueError("canonical configuration lock is unsafe")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            shared.validate_storage_state()
        except StateError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StateError(f"OS_STATE_HOLD: {exc}") from exc
        yield shared


class ConfigurationUpdate:
    def __init__(self, root: Path, shared: FirstBootState | None, expected_generation: str | None):
        self.root, self.shared = root, shared
        self.changes = {}
        self.committed = False
        self.pointer = None
        self.values = {}
        if shared is None:
            if expected_generation is not None:
                raise ValueError("legacy configuration has no canonical generation")
            return
        if shared.current.exists():
            self.pointer, manifest, self.values = shared._generation()
            if expected_generation is not None and self.pointer["generation"] != expected_generation:
                raise ValueError("canonical configuration revision changed")
            shared.prepare_existing()
            self.completion = manifest["completion"]
        else:
            if expected_generation is not None:
                raise ValueError("canonical configuration has not been committed")
            initial = shared._pending() if shared.pending.exists() else load_record(
                root, COMMON + "/state/factory.json", {"schema_version", "state_schema", "factory_id"})
            self.factory_id = initial["factory_id"]
            self.values = initial_changes(root, self.factory_id)
            project_files(root, self.values)

    @property
    def card(self) -> Path:
        relative = "run/rosy-provision-boot/rosy-config.yaml" if self.shared is not None else "boot/firmware/rosy-config.yaml"
        return self.root / relative

    def handles(self, path: Path) -> bool:
        if self.shared is None:
            return False
        try:
            return Path(path).absolute().relative_to(self.root).as_posix() in CONFIG_FILES
        except ValueError:
            return False

    def stage(self, relative: str, data: bytes | None, mode: int) -> None:
        if self.shared is None or self.committed:
            raise ValueError("configuration update is not open")
        supported = {**CONFIG_FILES, "etc/rosy/runtime.env": 0o640}
        if relative == "etc/rosy/runtime.env" and (self.pointer is None or data is None):
            raise ValueError("runtime changes require a committed device identity")
        if relative not in supported or type(mode) is not int or mode != supported[relative]:
            raise ValueError("configuration file or mode is unsupported")
        validate_projection(self.root, {relative: data})
        self.changes[relative] = data

    def commit(self, *, generation: str | None = None) -> None:
        if generation is not None:
            _guid(generation)
            if self.pointer is None:
                raise ValueError("explicit generation requires a committed device")
        if self.committed:
            raise ValueError("configuration update already committed")
        if self.shared is None or not self.changes:
            self.committed = True
            return
        values = {**self.values, **self.changes}
        validate_projection(self.root, values)
        if self.pointer is None:
            record = dict(schema_version=1, state_schema=1,
                factory_id=self.factory_id,
                changes={key: value.decode("utf-8") if value is not None else None for key, value in values.items()})
            encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if len(encoded) > 64 * 1024:
                raise ValueError("initial configuration record exceeds reader limit")
            _json_atomic(_path(self.root, INITIAL), record, 0o600)
            project_files(self.root, values)
        else:
            current = load_record(self.root, COMMON + "/state/current.json", POINTER_FIELDS)
            if current != self.pointer:
                raise ValueError("canonical configuration revision changed")
            pointer = self.shared.stage_generation(generation or str(uuid.uuid4()), self.completion, values)
            prior = _read(self.shared.complete, 64 * 1024, self.root.stat().st_uid)
            _json_atomic(_path(self.root, PUBLICATION), dict(schema_version=1, state_schema=1,
                previous=self.pointer, current=pointer, previous_completion_sha256=hashlib.sha256(prior).hexdigest()), 0o600)
            _json_atomic(self.shared.current, pointer, 0o600)
            self.shared.prepare_existing()
            self.pointer = pointer
            from os_state_ready import refresh_ready
            refresh_ready(self.root, self.shared)
        self.committed = True


@contextlib.contextmanager
def configuration_update(root: Path, *, expected_generation: str | None = None):
    root = Path(root).absolute()
    with common_lock(root) as shared:
        if shared is not None and _path(root, TLS_PENDING).exists():
            raise StateError("OS_STATE_HOLD: TLS transaction pending")
        update = ConfigurationUpdate(root, shared, expected_generation)
        yield update
        if update.changes and not update.committed:
            raise ValueError("canonical configuration changes were not committed")


def commit_runtime(root: Path, data: bytes, *, expected: bytes) -> None:
    """Publish a privileged runtime edit without losing a concurrent settings change."""
    with configuration_update(root) as update:
        if update.shared is None or update.pointer is None:
            raise ValueError("runtime publication requires a provisioned A/B device")
        if update.values["etc/rosy/runtime.env"] != expected:
            raise ValueError("canonical runtime changed before publication")
        update.stage("etc/rosy/runtime.env", data, 0o640)
        update.commit()


def main(argv=None, *, root=Path('/')) -> int:
    parser = argparse.ArgumentParser(description='Commit or clear a commissioned operator overlay across A/B OS roots.')
    parser.add_argument('--file', required=True, choices=('ir_calibration.yaml', 'line_observer_overrides.yaml'))
    parser.add_argument('--profile-input', type=Path, help='Referenced NOMINAL camera profile, captured with a line overlay')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input', help='UTF-8 overlay file, or - for standard input')
    source.add_argument('--clear', action='store_true')
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise ValueError('operator overlay publication requires root')
        data = None
        if not args.clear:
            if args.input == '-':
                data = sys.stdin.buffer.read(65537)
            else:
                with Path(args.input).open('rb') as handle:
                    data = handle.read(65537)
            if len(data) > 65536:
                raise ValueError('operator overlay exceeds canonical file limit')
            data.decode('utf-8')
        profile_name = 'etc/rosy/camera_nominal.yaml'
        profile, parameters = None, {}
        document = yaml.safe_load(data) if args.file == 'line_observer_overrides.yaml' and data is not None else None
        if isinstance(document, dict):
            node = document.get('/**/line_observer_node', {})
            parameters = node.get('ros__parameters', {}) if isinstance(node, dict) else {}
        if not isinstance(parameters, dict):
            raise ValueError('invalid line observer parameters')
        nominal = parameters.get('camera_ground_source') == 'NOMINAL'
        if args.profile_input is not None:
            if args.clear or args.file != 'line_observer_overrides.yaml' or not nominal:
                raise ValueError('profile input requires a NOMINAL line overlay')
            if parameters.get('nominal_camera_profile_path') != str(args.profile_input.absolute()):
                raise ValueError('profile input differs from the explicit overlay reference')
            with args.profile_input.open('rb') as handle:
                profile = handle.read(65537)
            if len(profile) > 65536 or not isinstance(yaml.safe_load(profile.decode('utf-8')), dict):
                raise ValueError('camera profile is not a bounded mapping')
            parameters['nominal_camera_profile_path'] = '/' + profile_name
            data = yaml.safe_dump(document, sort_keys=False).encode('utf-8')
        with configuration_update(root) as update:
            if update.shared is None or update.pointer is None:
                raise ValueError('operator overlays require a provisioned A/B device')
            if args.file == 'line_observer_overrides.yaml' and args.clear:
                update.stage(profile_name, None, 0o644)
            elif nominal:
                if profile is not None:
                    update.stage(profile_name, profile, 0o644)
                elif (parameters.get('nominal_camera_profile_path') != '/' + profile_name
                      or update.values.get(profile_name) is None):
                    raise ValueError('NOMINAL overlay requires its persistent profile')
            update.stage('etc/rosy/' + args.file, data, 0o644)
            update.commit()
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        print('OS_OPERATOR_OVERLAY_HOLD', file=sys.stderr)
        return 1
    print('OS_OPERATOR_OVERLAY_COMMITTED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
