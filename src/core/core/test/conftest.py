"""테스트가 로봇 한 대를 세우는 방법은 한 곳에만 있어야 한다.

`CoreServices.build` 의 배선은 계속 늘어난다 — 도킹 provider, 세션 종료
리스너, e-stop 리스너가 이번에 붙었다. 파일마다 복사해 두면 그중 하나만
빠뜨렸을 때 테스트는 통과하면서 실제 배선과 어긋난다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pytest
import yaml

# colcon install 없이 pytest 를 돌린다 (Windows/CI) — `src/site/fleet/test/conftest.py`
# 와 같은 방식이다. `control` 이 필요한 이유는 D-126 이 남긴 유일한 시험 이음새 때문이다:
# `test_control_sensor_adapter.py` 가 core 어댑터와 control provider
# (`control.sensor_provider:PROVIDER`) 가 맞물리는 자리를 검사한다. 이것이 없으면
# 그 파일들의 ImportError 가 collection 을 중단시켜 core 스위트 전체가 실행되지 않는다.
# 이 경로는 테스트 전용이다. 생산 코드 경계(core 는 control 을 import 하지 않는다)는
# `test/test_module_separation.py` 가 따로 고정한다.
SRC = Path(__file__).resolve().parents[2]

for _path in (SRC / "core", SRC / "core_common", SRC / "core_events",
              SRC / "core_features", SRC / "core_api_web", SRC.parent / "apps" / "control"):
    _entry = str(_path)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

CONFIG_DIR = Path(__file__).parent.parent / "config"


@pytest.fixture
def core_client(tmp_path):
    """`(TestClient, CoreServices)` 를 만드는 팩토리.

    capability 나 설정을 바꿔 끼우는 것이 이 팩토리를 두는 이유다 — "미지원
    로봇은 501" 같은 계약은 지원 로봇에서는 확인할 수 없다.
    """
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices

    def build(*, capabilities: Optional[dict] = None,
              config_overrides: Optional[dict] = None, dev_auth: bool = True):
        def read(name):
            return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))

        config = read("rosy_default.yaml")
        if dev_auth:
            # D-193 7: the shared dev tokens live only in rosy_dev_auth.yaml,
            # merged like ROSY_DEV_AUTH=1 does; the pairing block stays.
            config["auth"] = {**config["auth"], **read("rosy_dev_auth.yaml")["auth"]}
        robot_dir = robot_config_dir("pinky_pro")
        caps = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
        profile = RobotProfile.load(robot_dir / "profile.yaml")
        if capabilities:
            caps.update(capabilities)
        if config_overrides:
            config.update(config_overrides)
        services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
        return TestClient(create_app(config, services)), services

    return build
