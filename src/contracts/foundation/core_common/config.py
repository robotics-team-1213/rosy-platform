"""core_common.config — YAML 설정 로드/검증 (P1-1, CFG-001/002).

설정 계층:
1. config/rosy_default.yaml (패키지 기본값)
2. ~/.rosy/rosy.yaml (로봇 로컬 오버라이드) — 있으면 병합
3. 환경변수 ROSY_CONFIG (명시적 경로) — 최우선

개발 토큰(D-193 7)은 기본값에 없다. `ROSY_DEV_AUTH=1` 이고 장치 모드
(`ROSY_DEPLOYMENT=device`)가 아닐 때만 config/rosy_dev_auth.yaml 을 기본값
바로 위에 병합한다. 오버라이드의 `auth.tokens` 는 그 목록을 통째로 대신한다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_CONFIG_NAME = "rosy_default.yaml"
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

        share = Path(get_package_share_directory("core")) / "config"
        if (share / DEFAULT_CONFIG_NAME).exists():
            return share / DEFAULT_CONFIG_NAME
    except Exception:
        pass
    # 소스 트리 실행 (colcon install 미사용) 폴백 — 기본 설정 파일은 core 패키지의
    # config/ 에 산다 (설치 시에도 core share 로 들어간다). core_common/config.py 는
    # src/contracts/foundation/ 에서 두 단계 위, src/ 가 기준이다.
    return (Path(__file__).resolve().parents[3] / "runtime" / "gateway" / "config"
            / DEFAULT_CONFIG_NAME)


def dev_auth_enabled() -> bool:
    """개발 토큰을 병합하는가. 장치 모드는 ROSY_DEV_AUTH 를 무시한다(D-193 7)."""
    if os.environ.get("ROSY_DEPLOYMENT", "").strip() == "device":
        return False
    return os.environ.get("ROSY_DEV_AUTH", "").strip() == "1"


def load_config(explicit_path: Optional[str] = None) -> dict[str, Any]:
    """기본값 → 로컬 오버라이드 → 명시적 경로 순으로 병합해 반환한다."""

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
        if not re.fullmatch(r"[a-z][a-z0-9_]*", model):
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
