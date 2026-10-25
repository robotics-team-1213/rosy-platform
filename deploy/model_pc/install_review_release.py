"""Install or reactivate a versioned Model PC review app without moving review state.

Run as the same user that owns rosy-review-v13.service. See README.md.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import ipaddress
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


SERVICE = "rosy-review-v13.service"
APP = Path("learning/curation/perception/review_app.py")
WEB = Path("learning/curation/perception/review_app_web")
LEGACY_APP = Path("learning/training/perception/dataset/review_app.py")


SPLIT_REQUIRED = (
                  'middleware/perception/nodes/calib_node.py',
                  'middleware/perception/nodes/calibrated_values.py',
                  'middleware/perception/nodes/calibration_atomic.py',
                  'middleware/perception/nodes/calibration_camera.py',
                  'middleware/perception/nodes/calibration_lock.py',
                  'middleware/perception/nodes/calibration_record.py',
                  'middleware/perception/nodes/calibration_relocation.py',
                  'middleware/perception/nodes/calibration_rotation.py',
                  'middleware/perception/nodes/calibration_sequence.py',
                  'middleware/perception/nodes/calibration_snapshot.py',
                  'middleware/perception/nodes/calibration_storage.py',
                  'middleware/perception/nodes/camera_detect_node.py',
                  'middleware/perception/nodes/camera_lock.py',
                  'middleware/perception/nodes/camera_region_range.py',
                  'middleware/perception/nodes/dock_observer_node.py',
                  'middleware/perception/nodes/executor_choice.py',
                  'middleware/drive/runtime/goal_escape.py',
                  'middleware/perception/nodes/ir_adc_node.py',
                  'middleware/perception/nodes/learned_lane_node.py',
                  'middleware/perception/nodes/obstacle_observer_node.py',
                  'middleware/perception/nodes/pilot_recorder_node.py',
                  'middleware/perception/nodes/pilot_recording.py',
                  'middleware/perception/nodes/record_session.py',
                  'middleware/perception/nodes/recording.py',
                  'middleware/perception/nodes/road_observer_node.py',
                  'middleware/perception/nodes/road_state_node.py',
                  'middleware/perception/nodes/sensor_provider.py',
                  'middleware/perception/nodes/startup_calibration_node.py',
                  'middleware/perception/nodes/tf_buffer.py',
                  'middleware/perception/nodes/web_http.py',
                  'middleware/perception/nodes/web_map_control.py',
                  'middleware/perception/nodes/web_node.py',
                  'middleware/perception/nodes/web_render.py',
                  'middleware/perception/nodes/web_state.py',

                  'middleware/perception/localization/loc_assist.py',
                  'middleware/perception/localization/loc_assist_node.py',
                  'middleware/perception/localization/localization_node.py',
                  'middleware/perception/graph_health/watch.py',
                  'middleware/perception/graph_health/watch_node.py',
                  'middleware/perception/front_camera/object_observation/object_detector.py',
                  'middleware/perception/front_camera/object_observation/object_detector_node.py',
                  'middleware/perception/sensors/line_observation/ir_overlay.py',
                  'middleware/perception/sensors/line_observation/line_observer_overrides.py',
                  'middleware/perception/sensors/line_observation/core_law_input.py',
                  'middleware/perception/sensors/line_observation/route_context_input.py',
                  'middleware/perception/sensors/line_observation/route_followers.py',
                  'middleware/perception/sensors/line_observation/line_observer_node.py',
                  'middleware/perception/snapshots/capture_trigger.py',
                  'middleware/perception/snapshots/capture_trigger_node.py',
                  "middleware/perception/package.xml",
                  "middleware/perception/sensors/sensing/__init__.py",
                  "middleware/perception/front_camera/perception/__init__.py",
                  "middleware/drive/motion_limits/command_gate.py",
                  "middleware/drive/recovery/recover.py",
                  "middleware/drive/tracking/path_follow.py",
                  "middleware/drive/calibration/modes.py",
                  "middleware/drive/planning/grid/__init__.py",
                  "middleware/drive/motion_limits/adapter/__init__.py",
                  "middleware/drive/tracking/wander/__init__.py")


def validate_service(service: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*\.service', service):
        raise ValueError('service must be one safe systemd service name')
    return service


def check_source(source: Path, root: Path, state: Path) -> None:
    if (source == root or root in source.parents or source in state.parents
            or state in source.parents or state == root or root in state.parents):
        raise ValueError("source, release root, and review state must be separate")
    for required in (APP, WEB / "index.html", WEB / "pixels.html", Path("shared/web/shared-assets.json")):
        if not (source / required).is_file():
            raise ValueError(f"release source is missing {required}")
    if (source / "middleware/perception/control/_source_layout.py").is_file():
        for required in SPLIT_REQUIRED:
            if not (source / required).is_file():
                raise ValueError(f"release source is missing {required}")
    for directory, dirs, files in os.walk(source):
        for name in dirs + files:
            entry = Path(directory) / name
            if entry.is_symlink():
                raise ValueError(f"release source contains a symlink: {entry}")
            if entry.name == "reviews.sqlite3":
                raise ValueError("release source contains review state")


def digest_tree(source: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(path for path in source.rglob("*") if path.is_file()):
        digest.update(file.relative_to(source).as_posix().encode() + b"\0")
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def unit_contents(current: Path, state: Path, python: Path, host: str, port: int,
                  *, source: Path | None = None) -> str:
    collaboration = state / 'learning-collaboration.json'
    if collaboration.is_file() and not ipaddress.ip_address(host).is_loopback:
        raise ValueError('collaboration requires a loopback listener behind HTTPS')
    if not 1 <= port <= (65535 if collaboration.is_file() else 55535):
        raise ValueError('review port must leave room for its loopback decisions port')
    dataset = current / "learning/curation/perception"
    paths = (
        current / "middleware/perception",
        current / "contracts/foundation",
        current / "tools/perception",
        current / "learning/registry/perception",
        dataset,
        current / "learning/training/perception",
    )
    for value in (current, state, python):
        if any(char.isspace() for char in str(value)):
            raise ValueError("systemd paths must not contain whitespace")
    control = f" --learning-control {state / 'learning-control.json'}" if (state / 'learning-control.json').is_file() else ''
    if (state / 'review-ai.json').is_file():
        control += f" --review-ai-config {state / 'review-ai.json'}"
    control += (f' --collaboration {collaboration}' if collaboration.is_file()
                else f' --decisions-port {port + 10000}')
    if ((state / 'omx-center.json').is_file()
            and '--omx-center-config' in ((source or current) / APP).read_text(encoding='utf-8')):
        control += f" --omx-center-config {state / 'omx-center.json'}"
    links = state / 'workspace-links.json'
    if ((links.exists() or links.is_symlink())
            and '--workspace-links' in ((source or current) / APP).read_text(encoding='utf-8')):
        control += f" --workspace-links {check_workspace_links(links)}"
    return ("[Unit]\nDescription=ROSY v13 drivable review\nAfter=network-online.target\n"
            "Wants=network-online.target\n\n[Service]\nType=simple\n"
            f"WorkingDirectory={dataset}\nEnvironment=PYTHONPATH={':'.join(map(str, paths))}\n"
            f"ExecStart={python} {dataset / 'review_app.py'} --state {state} --port {port} --host {host}{control}\n"
            "Restart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n")


def check_workspace_links(binding: Path) -> Path:
    # The app validates every entry at start; refuse here what would only fail later in check_live.
    if binding.is_symlink() or not binding.is_file():
        raise ValueError('workspace links must be a regular file inside the review state')
    config = json.loads(binding.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or config.get('schema') != 'rosy.learning.workspace-links/1':
        raise ValueError('workspace links file has the wrong schema')
    return binding


def check_collaboration(app: Path, binding: Path, host: str) -> dict:
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError('collaboration requires a loopback listener behind HTTPS')
    config = json.loads(binding.read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('collaboration configuration must be an object')
    if '--collaboration' not in app.read_text(encoding='utf-8'):
        raise ValueError('release does not support the bound collaboration configuration')
    if config.get('account_client_file') and not (app.parent / 'learning_rosy_accounts.py').is_file():
        raise ValueError('release does not support central Account collaboration')
    return config


def run_systemctl(*args: str) -> None:
    subprocess.run(("systemctl", "--user", *args), check=True)


def check_live(host: str, port: int, service: str = SERVICE, collaboration: dict | None = None) -> None:
    validate_service(service)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(15):
        try:
            run_systemctl("is-active", "--quiet", service)
            try:
                with opener.open(f"http://{host}:{port}/api/workspace", timeout=3) as response:
                    if collaboration is not None or not isinstance(json.load(response), dict):
                        raise ValueError("workspace did not enforce expected authentication")
            except urllib.error.HTTPError as exc:
                if collaboration is None or exc.code != 401:
                    raise
                exc.close()
            if collaboration is not None:
                with opener.open(f"http://{host}:{port}/api/accounts/options", timeout=3) as response:
                    options = json.load(response)
                    if (not isinstance(options, dict) or options.get('enabled') is not True
                            or options.get('project_id') != collaboration.get('project_id')
                            or options.get('rosy_account') is not bool(collaboration.get('account_client_file'))):
                        raise ValueError('collaboration options differ from the configured project')
            page = 'accounts' if collaboration is not None else 'pixels'
            with opener.open(f"http://{host}:{port}/{page}", timeout=3) as response:
                if response.status != 200:
                    raise ValueError("review account or pixel page is unavailable")
            return
        except (OSError, ValueError, subprocess.CalledProcessError):
            time.sleep(1)
    raise RuntimeError("review service did not pass authentication, workspace and page checks")


def switch(current: Path, target: Path) -> None:
    candidate = current.with_name(".current-next")
    if candidate.exists() or candidate.is_symlink():
        raise ValueError(f"stale switch link exists: {candidate}")
    candidate.symlink_to(target, target_is_directory=True)
    os.replace(candidate, current)


def check_learning_idle(config: Path) -> None:
    """Preflight only: the operator must keep new jobs quiesced during switching."""
    if not config.exists() and not config.is_symlink():
        return
    try:
        if config.is_symlink() or not config.is_file() or config.stat().st_size > 1024 * 1024:
            raise ValueError('bounded regular learning center configuration required')
        document = json.loads(config.read_bytes())
        if not isinstance(document, dict) or not isinstance(document.get('root'), str):
            raise ValueError('learning center root configuration required')
        root = Path(document['root'])
        if not root.is_absolute() or root.is_symlink() or (root.exists() and not root.is_dir()):
            raise ValueError('absolute owned learning center root required')
        database = root / 'center.sqlite'
        if not database.exists() and not database.is_symlink():
            return
        if database.is_symlink() or not database.is_file():
            raise ValueError('regular learning center database required')
        # mode=ro also prevents accidentally creating a database at a wrong path.
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            db.execute('PRAGMA query_only=ON')
            for raw, in db.execute('SELECT document FROM runs'):
                if not isinstance(raw, str) or len(raw.encode('utf-8')) > 1024 * 1024:
                    raise ValueError('bounded learning run state required')
                run = json.loads(raw)
                if not isinstance(run, dict) or run.get('status') not in (
                        'launching', 'running', 'stopping', 'succeeded', 'failed', 'cancelled', 'interrupted'):
                    raise ValueError('valid learning run state required')
                if run['status'] in ('launching', 'running', 'stopping'):
                    raise ValueError('active learning jobs must finish or be stopped before a release switch')
    except (OSError, sqlite3.Error, json.JSONDecodeError, UnicodeError, RecursionError, TypeError) as exc:
        raise ValueError('learning center state could not be verified') from exc


def install(source: Path | None, release: str, root: Path, state: Path | None,
            python: Path | None, host: str, port: int, unit: Path, service: str = SERVICE) -> Path:
    validate_service(service)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", release) or release in (".", ".."):
        raise ValueError("release must be one safe path component")
    address = ipaddress.IPv4Address(host)
    allowed = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
               "169.254.0.0/16", "100.64.0.0/10")
    if not any(address in ipaddress.ip_network(network) for network in allowed):
        raise ValueError("review host must be a private or Tailscale IPv4 address")
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    root = root.expanduser().resolve()
    target = root / "releases" / release
    current = root / "current"
    if not unit.is_file():
        raise ValueError(f"existing service unit is missing: {unit}")
    if current.exists() and not current.is_symlink():
        raise ValueError("current must be a symlink")
    if current.is_symlink() and not current.exists():
        raise ValueError("current points to a missing release")
    if current.with_name(".current-next").exists() or current.with_name(".current-next").is_symlink():
        raise ValueError("a release switch is already pending")
    old_target = current.resolve() if current.is_symlink() else None
    old_unit = unit.read_bytes()
    for line in old_unit.decode('utf-8').splitlines():
        if line.startswith('ExecStart='):
            bound = re.search(r' --omx-center-config ([^\s]+)', line)
            state_arg = re.search(r' --state ([^\s]+)', line)
            if bound:
                config = Path(bound[1])
                if not config.is_absolute() or not config.is_file():
                    raise ValueError('configured learning center file is missing or invalid')
                check_learning_idle(config)
            elif state_arg:
                check_learning_idle(Path(state_arg[1]) / 'omx-center.json')
    collaboration = None
    if source is not None:
        if state is None or python is None:
            raise ValueError("new releases require --state and --python")
        source = source.expanduser().resolve(strict=True)
        state = state.expanduser().resolve(strict=True)
        check_learning_idle(state / 'omx-center.json')
        # Keep the venv entrypoint: resolving it can silently select system Python.
        python = python.expanduser().absolute()
        if not (state / "reviews.sqlite3").is_file() or not python.is_file():
            raise ValueError("existing review database and Python executable are required")
        check_source(source, root, state)
        if target.exists():
            raise ValueError(f"release already exists: {target}")
        unit_text = unit_contents(current, state, python, host, port, source=source)
        binding = state / 'learning-collaboration.json'
        if b' --collaboration ' in old_unit and not binding.is_file():
            raise ValueError('bound collaboration configuration is missing')
        if binding.is_file():
            collaboration = check_collaboration(source / APP, binding, host)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".staging-{release}-{os.getpid()}")
        shutil.copytree(source, staging)
        source_digest = digest_tree(source)
        if digest_tree(staging) != source_digest:
            raise ValueError("staged release differs from source")
        (staging / "REVIEW_RELEASE.json").write_text(json.dumps({
            "release": release, "source_sha256": source_digest}, indent=2) + "\n", encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = ":".join(str(staging / part) for part in (
            "middleware/perception", "contracts/foundation", "tools/perception",
            "learning/registry/perception", "learning/curation/perception", "learning/training/perception"))
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        subprocess.run((str(python), "-c", "import review_app"), env=env, check=True)
        os.replace(staging, target)
    elif not ((target / APP).is_file() or (target / LEGACY_APP).is_file()):
        raise ValueError(f"existing release is missing: {target}")
    else:
        unit_text = None
        # Retained releases keep their code, digest and receipt bytes. Translate
        # only this managed unit's exact source-holder paths when crossing D-637.
        canonical = str(current / APP.parent)
        legacy = str(current / LEGACY_APP.parent)
        text = old_unit.decode("utf-8")
        to_legacy = not (target / APP).is_file()
        if ((to_legacy and f"WorkingDirectory={canonical}\n" in text)
                or (not to_legacy and f"WorkingDirectory={legacy}\n" in text)):
            pairs = (("learning/curation/perception", "learning/training/perception/dataset"),
                     ("learning/registry/perception", "learning/training/perception/model"),
                     ("learning/training/perception", "learning/training/perception/training"),
                     ("tools/perception", "learning/training/perception"))
            paths = {str(current / (a if to_legacy else b)): str(current / (b if to_legacy else a))
                     for a, b in pairs}
            lines = []
            for line in text.splitlines(keepends=True):
                if line == f"WorkingDirectory={canonical if to_legacy else legacy}\n":
                    line = f"WorkingDirectory={legacy if to_legacy else canonical}\n"
                elif line.startswith("Environment=PYTHONPATH="):
                    tokens = line.removeprefix("Environment=PYTHONPATH=").removesuffix("\n").split(":")
                    line = "Environment=PYTHONPATH=" + ":".join(paths.get(token, token) for token in tokens) + "\n"
                elif line.startswith("ExecStart="):
                    interpreter, space, rest = line.partition(" ")
                    script, separator, arguments = rest.partition(" ")
                    expected = str(current / (APP if to_legacy else LEGACY_APP))
                    if script == expected:
                        script = str(current / (LEGACY_APP if to_legacy else APP))
                        line = interpreter + space + script + separator + arguments
                lines.append(line)
            unit_text = "".join(lines)
        # Retained apps keep their CLI; opt-in controls must survive a roundtrip.
        app = target / (LEGACY_APP if to_legacy else APP)
        lines = []
        for line in (unit_text if unit_text is not None else text).splitlines(keepends=True):
            if line.startswith('ExecStart='):
                line = re.sub(r' --learning-control [^\s]+', '', line)
                line = re.sub(r' --review-ai-config [^\s]+', '', line)
                line = re.sub(r' --omx-center-config [^\s]+', '', line)
                line = re.sub(r' --workspace-links [^\s]+', '', line)
                line = re.sub(r' --decisions-port [^\s]+', '', line)
                cli = app.read_text(encoding='utf-8')
                port_arg = re.search(r' --port ([0-9]+)', line)
                if port_arg and '--decisions-port' in cli:
                    line = line.rstrip('\n') + f' --decisions-port {int(port_arg[1]) + 10000}\n'
                state_arg = re.search(r' --state ([^\s]+)', line)
                bound = re.search(r' --collaboration ([^\s]+)', line)
                binding = Path(bound[1]) if bound else (Path(state_arg[1]) / 'learning-collaboration.json' if state_arg else None)
                if binding and (bound or binding.is_file()):
                    collaboration = check_collaboration(app, binding, host)
                    listener = re.search(r' --host ([^\s]+)', line)
                    if not listener or not ipaddress.ip_address(listener[1]).is_loopback:
                        raise ValueError('collaboration requires a loopback listener behind HTTPS')
                    line = re.sub(r' --decisions-port [^\s]+', '', line)
                    if not bound:
                        line = line.rstrip('\n') + f' --collaboration {binding}\n'
                if state_arg and '--learning-control' in cli:
                    binding = Path(state_arg[1]) / 'learning-control.json'
                    if binding.is_file(): line = line.rstrip('\n') + f' --learning-control {binding}\n'
                if state_arg and '--review-ai-config' in cli:
                    binding = Path(state_arg[1]) / 'review-ai.json'
                    if binding.is_file(): line = line.rstrip('\n') + f' --review-ai-config {binding}\n'
                if state_arg and '--omx-center-config' in cli:
                    binding = Path(state_arg[1]) / 'omx-center.json'
                    if binding.is_file(): line = line.rstrip('\n') + f' --omx-center-config {binding}\n'
                if state_arg and '--workspace-links' in cli:
                    binding = Path(state_arg[1]) / 'workspace-links.json'
                    if binding.exists() or binding.is_symlink():
                        line = line.rstrip('\n') + f' --workspace-links {check_workspace_links(binding)}\n'
            lines.append(line)
        adjusted = ''.join(lines)
        if adjusted != text: unit_text = adjusted
    if old_target == target and unit_text is None:
        return target
    try:
        if unit_text is not None:
            backup = root / (service + ".before-managed")
            if not backup.exists():
                backup.write_bytes(old_unit)
            temporary = unit.with_name(unit.name + ".next")
            temporary.write_text(unit_text, encoding="utf-8")
            os.replace(temporary, unit)
        switch(current, target)
        run_systemctl("daemon-reload")
        run_systemctl("restart", service)
        check_live(host, port, service, collaboration)
    except Exception:
        if old_target is None:
            current.unlink(missing_ok=True)
        else:
            switch(current, old_target)
        unit.write_bytes(old_unit)
        run_systemctl("daemon-reload")
        run_systemctl("restart", service)
        raise
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", help="release name; omit --source to reactivate a prior release")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path, default=Path.home() / "rosy-ml/review-v13-code")
    parser.add_argument("--service", type=validate_service, default=SERVICE)
    args = parser.parse_args()
    unit = Path.home() / ".config/systemd/user" / args.service
    try:
        release = install(args.source, args.release, args.root, args.state, args.python,
                          args.host, args.port, unit, args.service)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"review release failed: {exc}\n")
    print(f"active review release: {release}")


if __name__ == "__main__":
    main()
