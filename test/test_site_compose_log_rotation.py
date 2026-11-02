"""Site Compose 로그 회전 계약 — 장기 서비스의 json-file 로그는 경계가 있어야 한다.

기본 스택(compose.yaml)과 미디어 프로젝트(compose.media.yaml)의 모든 장기 서비스는
경계 있는 json-file 로깅(20m × 3)을 쓴다. 오버레이의 기존 서비스는 기본 정의를
상속하고, 오버레이에서 추가한 서비스는 같은 경계를 직접 선언한다.
"""

from pathlib import Path

import yaml

SITE = Path(__file__).resolve().parents[1] / "deploy/site"
BOUNDED = {"driver": "json-file", "options": {"max-size": "20m", "max-file": "3"}}
BASE_SERVICES = ("fleet", "vision", "postgres", "proxy")
OVERLAYS = ("compose.account.yaml", "compose.control-unit.yaml", "compose.control-unit.yaml.example", "compose.omx.yaml",
            "compose.pairing.yaml", "compose.workcell.yaml")


def _services(name):
    return yaml.safe_load((SITE / name).read_text(encoding="utf-8"))["services"]


def test_base_stack_services_have_bounded_json_file_logging():
    services = _services("compose.yaml")
    for name in BASE_SERVICES:
        assert services[name]["logging"] == BOUNDED, f"{name} 로그가 무제한이면 안 된다"


def test_media_project_services_have_bounded_json_file_logging():
    services = _services("compose.media.yaml")
    for name in ("media", "media-gateway"):
        assert services[name]["logging"] == BOUNDED, f"{name} 로그가 무제한이면 안 된다"


def test_overlays_inherit_logging_and_bound_new_services():
    base = _services("compose.yaml")
    for name in OVERLAYS:
        for service, config in _services(name).items():
            if service in base:
                assert "logging" not in config, f"{name}의 {service}는 기본 로깅을 상속한다"
            else:
                assert config["logging"] == BOUNDED, f"{name}의 새 서비스 {service} 로그도 제한한다"
