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

import logging
import os
import re
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


def local_overlay() -> dict[str, Any]:
    """The operator's local overlay alone (the layer load_config merges last), {} if absent.

    Lets a consumer tell an operator-set value from the robot package's
    URDF-nominal one (D-397: URDF nominal < accepted calibration record <
    operator overlay)."""
    path = Path(os.environ.get("ROSY_CONFIG", "")) if os.environ.get("ROSY_CONFIG") else LOCAL_CONFIG_PATH
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


def dev_auth_enabled() -> bool:
    """개발 토큰을 병합하는가. 장치 모드는 ROSY_DEV_AUTH 를 무시한다(D-193 7)."""
    if os.environ.get("ROSY_DEPLOYMENT", "").strip() == "device":
        return False
    return os.environ.get("ROSY_DEV_AUTH", "").strip() == "1"


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

    if dev_auth_enabled():
        dev_path = base_path.parent / DEV_AUTH_CONFIG_NAME
        if not dev_path.exists():
            dev_path = _find_default_config().parent / DEV_AUTH_CONFIG_NAME
        if dev_path.exists():
            with open(dev_path, encoding="utf-8") as f:
                config = _deep_merge(config, yaml.safe_load(f) or {})

    override_path = Path(os.environ.get("ROSY_CONFIG", "")) if os.environ.get("ROSY_CONFIG") else LOCAL_CONFIG_PATH
    overlay: dict[str, Any] = {}
    if override_path.exists():
        with open(override_path, encoding="utf-8") as f:
            overlay = yaml.safe_load(f) or {}
    config = _deep_merge(config, _robot_package_layer(config, overlay))
    config = _deep_merge(config, overlay)
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


def patch_local_config(patch: dict[str, Any], path: Optional[Path] = None) -> Path:
    """Deep-merge `patch` into the local overlay file. Never writes package defaults.

    Only the overlay is updated, so unrelated keys (auth tokens, robot id) stay
    as they were. Used by runtime settings such as SAF-004 manual speed limits.
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
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(
            yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(tmp, target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return target
