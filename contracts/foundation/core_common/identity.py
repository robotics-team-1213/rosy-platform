"""core_common.identity — IDN-001~003 (P1-2). ROS 무의존."""

from __future__ import annotations

import os
import re
import socket
from typing import Any, Optional

SOFTWARE_VERSION = "0.1.0"
ROBOT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def validate_robot_id(robot_id: str) -> str:
    value = (robot_id or "").strip()
    if not ROBOT_ID_PATTERN.fullmatch(value):
        raise ValueError("robot id must be lowercase letters, digits, underscore or hyphen")
    return value


def validate_robot_name(name: str) -> str:
    value = (name or "").strip()
    if not value or len(value) > 64:
        raise ValueError("robot name must be 1 to 64 characters")
    return value


def _primary_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.0)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class RobotIdentity:
    def __init__(self, robot_id: str, robot_name: str, profile_model: str = "unknown",
                 serial: Optional[str] = None, hardware_version: Optional[str] = None,
                 runtime_mode: str = "core", robot_number: Optional[int] = None,
                 device_uid: str = "", device_name: Optional[str] = None) -> None:
        self.robot_id = robot_id
        self.robot_name = robot_name
        self.profile_model = profile_model
        self.serial = serial
        self.hardware_version = hardware_version
        self.runtime_mode = runtime_mode
        self.robot_number = robot_number
        # Fleet hello 신원(API Ref §7.2). device_uid 는 장치 고유 식별자로,
        # 값이 없으면 빈 문자열로 둔다 — 모를 때 지어내면 허브의
        # DUPLICATE_IDENTITY/IDENTITY_DRIFT 방어가 죽는다.
        self.device_uid = device_uid
        self._device_name = device_name

    @property
    def device_name(self) -> str:
        """hello 표시명 — 미지정 시 robot_name 폴백."""
        return self._device_name or self.robot_name

    @property
    def model(self) -> str:
        """hello 필드명으로 노출되는 프로파일 모델."""
        return self.profile_model

    @property
    def hardware_serial(self) -> Optional[str]:
        return self.serial

    @classmethod
    def from_config(cls, config: dict[str, Any], profile_model: str = "unknown") -> "RobotIdentity":
        robot = config.get("robot") or {}
        mode = str((config.get("runtime") or {}).get("mode") or "core")
        number = robot.get("number")
        if number is not None:
            number = int(number)
        return cls(
            robot_id=robot.get("id") or "rosy_01",
            robot_name=robot.get("name") or "Rosy 01",
            profile_model=profile_model,
            serial=robot.get("serial"),
            hardware_version=robot.get("hardware_version"),
            runtime_mode=mode,
            robot_number=number,
            device_uid=str(robot.get("device_uid", "") or ""),
            device_name=robot.get("device_name"),
        )

    def info(self) -> dict[str, Any]:
        """IDN-003 응답 스키마 (API Ref §5.1)."""
        namespace = os.environ.get("ROSY_NAMESPACE", "").strip().strip("/") or self.robot_id
        domain_raw = os.environ.get("ROS_DOMAIN_ID", "").strip()
        if domain_raw:
            domain_id: Optional[int] = int(domain_raw)
        elif self.robot_number is not None:
            domain_id = 40 + self.robot_number
        else:
            domain_id = None
        return {
            "robot_id": self.robot_id,
            "robot_name": self.robot_name,
            "robot_number": self.robot_number,
            "ros_namespace": namespace,
            "ros_domain_id": domain_id,
            "hostname": socket.gethostname(),
            "ip_address": _primary_ip(),
            "hardware_model": self.profile_model,
            "hardware_version": self.hardware_version,
            "serial_number": self.serial,
            "software_version": SOFTWARE_VERSION,
            "ros_version": os.environ.get("ROS_DISTRO", "unknown"),
            "runtime_mode": self.runtime_mode,
            "uptime_seconds": None,
        }
