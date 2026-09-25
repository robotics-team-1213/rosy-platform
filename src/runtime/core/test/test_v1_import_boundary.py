"""v1 라우터는 core_features 를 직접 import 하지 않는다 (결합도 평가 2026-09-19 §7-5).

라우터가 features 하위 모듈을 직접 참조하면 features 재조정의 전파 반경이
라우터 전부로 번진다. 도메인 타입은 ``core_api_web.api.deps`` 재수출 면만
통과한다. 텍스트 구조 검사라 ROS 오버레이·fastapi 없이도 돈다.
"""

from __future__ import annotations

import re
from pathlib import Path

V1 = Path(__file__).resolve().parents[2] / "core_api_web" / "core_api_web" / "api" / "v1"

DIRECT_FEATURES = re.compile(r"^\s*(?:from|import)\s+core_features\b", re.MULTILINE)


def test_v1_routers_do_not_import_core_features_directly():
    offenders = []
    for path in sorted(V1.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        match = DIRECT_FEATURES.search(text)
        if match:
            offenders.append(f"{path.name}: {match.group(0).strip()}")
    assert not offenders, (
        "v1 라우터의 도메인 타입은 core_api_web.api.deps 뒤로 ("
        + "; ".join(offenders)
        + ")"
    )


def test_deps_still_owns_the_domain_type_surface():
    deps = V1.parent / "deps.py"
    text = deps.read_text(encoding="utf-8")
    for symbol in (
        "Mode",
        "NavigationError",
        "DockError",
        "LineFollowMode",
        "valid_costmap_scope",
        "worst",
        "SwarmError",
        "Waypoint",
    ):
        assert symbol in text, f"api/deps.py 가 라우터용 타입 {symbol} 을 실어야 한다"
