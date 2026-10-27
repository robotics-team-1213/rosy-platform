"""Site Compose 로그 회전 계약 — 장기 서비스의 json-file 로그는 경계가 있어야 한다.

기본 스택(compose.yaml)과 미디어 프로젝트(compose.media.yaml)의 모든 장기 서비스는
경계 있는 json-file 로깅(20m × 3)을 쓴다. 오버레이는 기본 정의를 상속할 뿐 조용히
경계를 덮어쓰지 않는다(덮어쓰려면 이 계약을 같이 고친다).
"""

from pathlib import Path

import yaml

SITE = Path(__file__).resolve().parents[1] / "deploy/site"
BOUNDED = {"driver": "json-file", "options": {"max-size": "20m", "max-file": "3"}}
BASE_SERVICES = ("fleet", "vision", "postgres", "proxy")
OVERLAYS = ("compose.account.yaml", "compose.control-unit.yaml.example", "compose.omx.yaml",
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


def test_overlays_inherit_the_base_logging_instead_of_overriding_it():
    for name in OVERLAYS:
        text = (SITE / name).read_text(encoding="utf-8")
        assert "\n    logging:" not in text, f"{name}은(는) 기본 로깅을 덮어쓰지 않는다"
