"""core_common.config — YAML 설정 로드/검증 (P1-1, CFG-001/002).

설정 계층:
1. config/rosy_default.yaml (패키지 기본값)
2. <robot package>/config/core.yaml (robot.model 의 로봇 사실 — D-196 추가 2026-10-01;
   패키지가 있으면 반드시 있어야 한다)
3. ~/.rosy/rosy.yaml (로봇 로컬 오버라이드) — 있으면 병합
4. 환경변수 ROSY_CONFIG (명시적 경로) — 있으면 3 대신 병합, 최우선

개발 토큰(D-193 7)은 기본값에 없다. `ROSY_DEV_AUTH=1` 이고 장치 모드
(`ROSY_DEPLOYMENT=device`)가 아닐 때만 config/rosy_dev_auth.yaml 을 기본값
바로 위에 병합한다. 오버라이드의 `auth.tokens` 는 그 목록을 통째로 대신한다.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from .config_transaction import transaction
from pathlib import Path
from typing import Any, Optional

import yaml

_LOG = logging.getLogger(__name__)

DEFAULT_CONFIG_NAME = "rosy_default.yaml"
ROBOT_CORE_CONFIG_NAME = "core.yaml"
#: A robot package name (robot.model / ROSY_ROBOT), D-196.
ROBOT_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
DEV_AUTH_CONFIG_NAME = "rosy_dev_auth.yaml"
LOCAL_CONFIG_PATH = Path.home() / ".rosy" / "rosy.yaml"
RUNTIME_MODES = frozenset({"core", "motor", "hardware"})
NAVIGATION_BACKENDS = frozenset({"localization", "slam"})
#: `robot.name` in rosy_default.yaml. Seen alone it means "nobody named this robot".
DEFAULT_ROBOT_NAME = "Rosy 01"


class ConfigError(Exception):
    """Local overlay could not be written."""


def overlay_path() -> Path:
    """Where dashboard/API writes persist: ROSY_CONFIG if set, else ~/.rosy/rosy.yaml."""
    env = os.environ.get("ROSY_CONFIG", "").strip()
    return Path(env) if env else LOCAL_CONFIG_PATH


#: D-555: keys the private Fleet link file owns inside `fleet`.
FLEET_LINK_KEYS = ("pairing_token", "hub_url", "discovery")


def fleet_link_path() -> Path:
    """D-555 private Fleet link file (0600, CORE user): ROSY_FLEET_LINK, else ~/.rosy/fleet-link.yaml."""
    env = os.environ.get("ROSY_FLEET_LINK", "").strip()
    return Path(env) if env else Path.home() / ".rosy" / "fleet-link.yaml"


def fleet_link_ca_path() -> Path:
    path = fleet_link_path()
    return path.with_name(path.stem + "-ca.pem")


def fleet_link_layer() -> dict[str, Any] | None:
    """The provisioned `fleet` link block, or None. A file others can read is ignored (D-555)."""
    path = fleet_link_path()
    if not path.is_file():
        return None
    if os.name == "posix" and path.stat().st_mode & 0o077:
        _LOG.warning("%s is readable by group or others; Fleet link ignored", path)
        return None
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    fleet = data.get("fleet") if isinstance(data, dict) else None
    return {key: fleet[key] for key in FLEET_LINK_KEYS if key in fleet} if isinstance(fleet, dict) else None


def merge_fleet_link(fleet: dict[str, Any] | None, link: dict[str, Any] | None) -> dict[str, Any]:
    """`fleet` with its link keys replaced by ``link`` (None = keep the lower layers' link)."""
    merged = dict(fleet or {})
    if link is not None:
        for key in FLEET_LINK_KEYS:
            merged.pop(key, None)
        merged.update(link)
    return merged


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(temporary)  # mkstemp creates 0600
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def write_fleet_link(pairing_token: str, expected_hostname: str, ca_pem: str) -> dict[str, Any]:
    """Write the CA and the 0600 link file; return the link block (D-555). Never logs the token."""
    ca_path = fleet_link_ca_path()
    _write_private(ca_path, ca_pem)
    link = {"pairing_token": pairing_token,
            "discovery": {"expected_hostname": expected_hostname, "ca_file": str(ca_path)}}
    _write_private(fleet_link_path(), yaml.safe_dump({"fleet": link}, sort_keys=False))
    return link


def clear_fleet_link() -> bool:
    """Remove the link file and its CA. True when a link file was there."""
    path = fleet_link_path()
    existed = path.exists()
    path.unlink(missing_ok=True)
    fleet_link_ca_path().unlink(missing_ok=True)
    return existed


def local_overlay() -> dict[str, Any]:
    """The operator's local overlay alone (the layer load_config merges last), {} if absent.

    Lets a consumer tell an operator-set value from the robot package's
    URDF-nominal one (D-397: URDF nominal < accepted calibration record <
    operator overlay)."""
    path = overlay_path()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _find_default_config() -> Path:
    try:
        from ament_index_python.packages import get_package_share_directory

        share = Path(get_package_share_directory("core_common")) / "config"
        if (share / DEFAULT_CONFIG_NAME).exists():
            return share / DEFAULT_CONFIG_NAME
    except Exception:
        pass
    # 소스 트리 실행 (colcon install 미사용) 폴백. 기본 설정은 이 패키지가 소유한다.
    return Path(__file__).resolve().parents[1] / "config" / DEFAULT_CONFIG_NAME


#: D-548: root가 한 로봇에 이 파일을 만들면 그 로봇만 공용 개발 토큰을 연다.
#: 파일이 없으면 D-193 7 그대로 닫힌다.
DEV_MODE_MARKER = Path("/etc/rosy/dev-mode")


def dev_auth_enabled() -> bool:
    """개발 토큰을 병합하는가. 장치 모드는 ROSY_DEV_AUTH 를 무시하고(D-193 7)
    개발 모드 표식 파일만 본다(D-548)."""
    if os.environ.get("ROSY_DEPLOYMENT", "").strip() == "device":
        return DEV_MODE_MARKER.is_file()
    return os.environ.get("ROSY_DEV_AUTH", "").strip() == "1"


def _append_dev_tokens(config: dict[str, Any], dev_layer: dict[str, Any]) -> None:
    """D-548: a device overlay always lists card or paired tokens, and a list replaces the
    one below it, so the marker puts the shared tokens on top. A digest already listed
    (a record stored on an earlier write) is not added twice."""
    auth = config.setdefault("auth", {})
    tokens = auth.get("tokens") or []
    if not isinstance(tokens, list):
        return
    def digest(item: Any) -> Optional[str]:
        if not isinstance(item, dict):
            return None
        if item.get("sha256"):
            return str(item["sha256"]).strip().lower()
        return hashlib.sha256(str(item["token"]).encode("utf-8")).hexdigest() if item.get("token") else None

    listed = {digest(item) for item in tokens}
    auth["tokens"] = tokens + [item for item in (dev_layer.get("auth") or {}).get("tokens") or []
                               if digest(item) is not None and digest(item) not in listed]


def _robot_package_layer(config: dict[str, Any], overlay: Any) -> dict[str, Any]:
    """The robot package's `core.yaml` (D-196): robot facts CORE needs, e.g. its
    LiDAR forward angle. The model is ROSY_ROBOT, else the overlay's
    robot.model, else the default's. A robot package that exists must ship the
    file (ConfigError otherwise: a silently missing layer would point the
    default robot's obstacle stop at the rear). An unknown model or missing package
    adds nothing and logs one warning; the profile loader then refuses it."""
    from core_common.profile import DEFAULT_ROBOT, robot_config_dir

    overlay_robot = overlay.get("robot") if isinstance(overlay, dict) else None
    model = (os.environ.get("ROSY_ROBOT", "").strip()
             or (overlay_robot.get("model") if isinstance(overlay_robot, dict) else None)
             or (config.get("robot") or {}).get("model") or DEFAULT_ROBOT)
    if not ROBOT_NAME_PATTERN.fullmatch(str(model)):
        return {}  # ROSY_ROBOT is rejected below; a bad overlay model fails in the profile loader
    try:
        path = robot_config_dir(str(model)) / ROBOT_CORE_CONFIG_NAME
    except ConfigError as exc:
        _LOG.warning("robot package CORE config layer skipped for model %r: %s", model, exc)
        return {}
    if not path.is_file():
        raise ConfigError(f"robot package {model!r} has no {path}; every robot package must ship "
                          f"{ROBOT_CORE_CONFIG_NAME} (an empty mapping is fine)")
    try:
        with open(path, encoding="utf-8") as f:
            layer = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(layer, dict):
        raise ConfigError(f"{path} must be a mapping")
    for key, value in layer.items():
        # _deep_merge replaces a default section with whatever the layer holds,
        # so an empty `line_follow:` (None) would wipe every default under it.
        if value is None:
            raise ConfigError(f"{path}: top-level key {key!r} is empty (null)")
        if isinstance(config.get(key), dict) and not isinstance(value, dict):
            raise ConfigError(f"{path}: top-level key {key!r} must be a mapping like the default")
    return layer


def load_config(explicit_path: Optional[str] = None) -> dict[str, Any]:
    """기본값 → 로봇 패키지 core.yaml → ~/.rosy/rosy.yaml 또는 ROSY_CONFIG 순으로 병합해 반환한다.

    ROSY_CONFIG 가 있으면 ~/.rosy/rosy.yaml 대신 그것을 읽는다. 로봇 패키지 층의 오류는 ConfigError.
    """

    base_path = Path(explicit_path) if explicit_path else _find_default_config()
    config: dict[str, Any] = {}
    with open(base_path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    device = os.environ.get("ROSY_DEPLOYMENT", "").strip() == "device"
    dev_layer: dict[str, Any] = {}
    if dev_auth_enabled():
        dev_path = base_path.parent / DEV_AUTH_CONFIG_NAME
        if not dev_path.exists():
            dev_path = _find_default_config().parent / DEV_AUTH_CONFIG_NAME
        if dev_path.exists():
            with open(dev_path, encoding="utf-8") as f:
                dev_layer = yaml.safe_load(f) or {}
    if not device:
        config = _deep_merge(config, dev_layer)

    override_path = Path(os.environ.get("ROSY_CONFIG", "")) if os.environ.get("ROSY_CONFIG") else LOCAL_CONFIG_PATH
    overlay: dict[str, Any] = {}
    if override_path.exists():
        with open(override_path, encoding="utf-8") as f:
            overlay = yaml.safe_load(f) or {}
    config = _deep_merge(config, _robot_package_layer(config, overlay))
    config = _deep_merge(config, overlay)
    link = fleet_link_layer()
    if link is not None:
        config["fleet"] = merge_fleet_link(config.get("fleet"), link)
    if device and dev_layer:
        _append_dev_tokens(config, dev_layer)
    overlay_robot = overlay.get("robot") if isinstance(overlay, dict) else None
    overlay_named = isinstance(overlay_robot, dict) and "name" in overlay_robot

    namespace = os.environ.get("ROSY_NAMESPACE", "").strip().strip("/")
    if namespace:
        config.setdefault("robot", {})["frame_prefix"] = f"{namespace}/"

    robot = config.setdefault("robot", {})
    if namespace:
        robot["id"] = namespace
    number_env = os.environ.get("ROSY_ROBOT_NUMBER", "").strip()
    if number_env:
        if not re.fullmatch(r"0|[1-9][0-9]*", number_env):
            raise ValueError(
                f"ROSY_ROBOT_NUMBER must be a decimal integer with no leading zero, got {number_env!r}"
            )
        number = int(number_env)
        expected = f"rosy_{number:02d}"
        if namespace and namespace != expected:
            raise ValueError(
                f"ROSY_ROBOT_NUMBER={number} derives {expected}, not ROSY_NAMESPACE={namespace}"
            )
        robot["number"] = number
        if not namespace:
            robot["id"] = expected

    # Provisioned identity: first boot copies device-identity.json's
    # device_name into /etc/rosy/runtime.env. It is an immutable fact about
    # this card, so it wins over anything a config file says.
    device_name = os.environ.get("ROSY_DEVICE_NAME", "").strip()
    if device_name:
        robot["device_name"] = device_name
    device_uid = os.environ.get("ROSY_DEVICE_UID", "").strip()
    if device_uid:
        robot["device_uid"] = device_uid
    # The package default name ("Rosy 01") is a placeholder, not an identity: a
    # provisioned robot #18 must not introduce itself as robot 01. An operator
    # rename lives in the overlay and is kept as is.
    if not overlay_named and robot.get("name") in (None, "", DEFAULT_ROBOT_NAME):
        if device_name:
            robot["name"] = device_name
        elif "number" in robot:
            robot["name"] = f"Rosy {int(robot['number']):02d}"

    model = os.environ.get("ROSY_ROBOT", "").strip()
    if model:
        if not ROBOT_NAME_PATTERN.fullmatch(model):
            raise ConfigError(f"ROSY_ROBOT must be a robot package name, got {model!r}")
        robot["model"] = model

    mode = os.environ.get("ROSY_RUNTIME_MODE", "").strip()
    if mode:
        if mode not in RUNTIME_MODES:
            raise ValueError(
                f"ROSY_RUNTIME_MODE must be core, motor, or hardware, got {mode!r}"
            )
        config.setdefault("runtime", {})["mode"] = mode
    else:
        config.setdefault("runtime", {}).setdefault("mode", "core")

    backend = os.environ.get("ROSY_NAVIGATION_BACKEND", "").strip()
    if backend:
        if backend not in NAVIGATION_BACKENDS:
            raise ValueError(
                "ROSY_NAVIGATION_BACKEND must be localization or slam, "
                f"got {backend!r}"
            )
        if backend == "slam" and config["runtime"]["mode"] != "hardware":
            raise ValueError("slam navigation backend requires hardware runtime mode")
        config["runtime"]["navigation_backend"] = backend
    else:
        config["runtime"].setdefault("navigation_backend", "localization")

    # The native service sets this independently of editable robot YAML.  A
    # core-only device can publish odometry through read-only I/O; that sample
    # must not make motion, navigation or SLAM executable.
    if os.environ.get("ROSY_DEPLOYMENT", "").strip() == "device":
        config["runtime"]["deployment"] = "device"

    return config


def _patch_local_config_unlocked(patch: dict[str, Any], path: Optional[Path] = None,
                                 replace: tuple[str, ...] = ()) -> Path:
    """Deep-merge `patch` into the local overlay file. Never writes package defaults.

    Only the overlay is updated, so unrelated keys (auth tokens, robot id) stay
    as they were. Used by runtime settings such as SAF-004 manual speed limits.
    ``replace`` names one mapping path whose value the patch replaces whole
    instead of merging, so keys absent from the patch are removed there.
    """
    target = Path(path) if path is not None else overlay_path()
    default = _find_default_config()
    if target.resolve() == default.resolve():
        raise ConfigError("refusing to write package default config")

    existing: dict[str, Any] = {}
    if target.exists():
        loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ConfigError("local overlay is not a mapping")
        existing = loaded

    merged = _deep_merge(existing, patch)
    if replace:
        holder, value = merged, patch
        for key in replace[:-1]:
            holder, value = holder[key], value[key]
        holder[replace[-1]] = value[replace[-1]]
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    tmp = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
        if os.name == 'posix':
            directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return target


def patch_local_config(patch: dict[str, Any], path: Optional[Path] = None,
                       replace: tuple[str, ...] = ()) -> Path:
    """Preserve unrelated overlay keys under the shared process/thread fence."""
    target = Path(path) if path is not None else overlay_path()
    with transaction(target):
        return _patch_local_config_unlocked(patch, target, replace)
